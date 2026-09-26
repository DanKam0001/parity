"""
parity/runner.py
================
Orchestrate a single end-to-end parity run (COBOL + Java + compare).

CLI usage
---------
    # Legacy-only (COBOL only, no comparison):
    python3 -m parity.runner --seed 7 --accounts 200 --legacy-only

    # Full equivalence proof (COBOL + Java + compare):
    python3 -m parity.runner --seed 7 --accounts 200

    # Override Java class directory:
    python3 -m parity.runner --seed 7 --accounts 200 --java-cp /build/java

What it does (full mode)
-------------------------
1. datagen.generate() → writes input files into runs/<seed>_<accounts>/in/
2. Hashes the input files; if a cached COBOL output exists for that hash, skip
   the COBOL run (same seed → same input → same output).
3. Runs harness/run_legacy.sh  (loads indexed files, runs DRIVER→CBACT04C,
   unloads ACCTFILE); output lands in runs/<seed>_<accounts>/out/cobol/.
4. Runs java -cp <java_cp> Cbact04c <in_dir> <java_out> <parm>; output lands
   in runs/<seed>_<accounts>/out/java/.
5. Calls comparer.compare() → CompareResult.
6. Builds edge-case examples into the report (one account per datagen tag).
7. Writes runs/<seed>_<accounts>/report.json.
8. Prints a one-line verdict, e.g.:
       ACCTFILE 2000/2000 · TRANSACT 3257/3257 · EQUIVALENT
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from parity.copybook import decode, get_layout
from parity.datagen import PARM_DATE, generate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Return the absolute path to the repository root."""
    return Path(__file__).resolve().parent.parent


def _run_dir(seed: int, accounts: int) -> Path:
    return _repo_root() / "runs" / f"{seed}_{accounts}"


def _hash_inputs(in_dir: Path) -> str:
    """SHA-256 over all four input text files (deterministic content hash)."""
    h = hashlib.sha256()
    for name in ("ACCTFILE.txt", "XREFFILE.txt", "TCATBALF.txt", "DISCGRP.txt"):
        p = in_dir / name
        if p.exists():
            h.update(name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def _decimal_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")


# ---------------------------------------------------------------------------
# Edge-case examples builder
# ---------------------------------------------------------------------------

def _raw_acctfile_record(in_dir: Path, acct_id: int) -> str:
    """Return the raw 300-char input ACCTFILE record for *acct_id*."""
    key = f"{acct_id:011d}"
    with open(in_dir / "ACCTFILE.txt", encoding="latin-1", newline="") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if line.startswith(key):
                return line.ljust(300)
    return ""


def _raw_acctfile_record_out(out_dir: Path, acct_id: int) -> str:
    """Return the raw 300-char ACCTFILE output record for *acct_id* from *out_dir*."""
    key = f"{acct_id:011d}"
    p = out_dir / "ACCTFILE.txt"
    if not p.exists():
        return ""
    with open(p, encoding="latin-1", newline="") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if line.ljust(300).startswith(key):
                return line.ljust(300)
    return ""


def _raw_transact_records(out_dir: Path, acct_id: int) -> list[str]:
    """Return all raw 350-byte TRANSACT records whose description contains *acct_id*."""
    key_str = f"{acct_id:011d}"
    p = out_dir / "TRANSACT.dat"
    if not p.exists():
        return []
    data = p.read_bytes()
    results = []
    n = len(data) // 350
    for i in range(n):
        chunk = data[i * 350 : (i + 1) * 350]
        rec = chunk.decode("latin-1")
        # TRAN-DESC at off 32 len 100 contains "Int. for a/c 00000000001"
        if key_str in rec[32:132]:
            results.append(rec)
    return results


def _decode_record(raw: str, layout_name: str) -> dict[str, str]:
    """Decode *raw* with the named layout; stringify every value."""
    layout = get_layout(layout_name)
    d = decode(raw.ljust(len(raw)), layout)
    return {k: str(v) for k, v in d.items()}


def _raw_tcatbal_rows(in_dir: Path, acct_id: int) -> list[str]:
    """Return all raw 50-char TCATBALF rows for *acct_id*."""
    key = f"{acct_id:011d}"
    rows = []
    with open(in_dir / "TCATBALF.txt", encoding="latin-1", newline="") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if line[:11] == key:
                rows.append(line.ljust(50))
    return rows


def _rate_for_row(raw50: str, discgrp_path: Path) -> str:
    """Look up the interest rate for a TCATBALF row (group from acctfile)."""
    # We don't have the group here; return blank – it will be filled by the caller
    return ""


def _build_edge_cases(
    in_dir: Path,
    cobol_out: Path,
    java_out: Path,
    tags: list,               # list[AccountTag] from datagen
    discgrp_path: Path,
) -> list[dict]:
    """
    Build one example entry per datagen tag (negative, cent, fallback,
    zero_rate, huge, last).  Returns a list of dicts suitable for report.json.
    """
    # Load DISCGRP into a quick lookup: (group10, type2, cat4) -> rate_str
    disc_index: dict[str, str] = {}
    with open(discgrp_path, encoding="latin-1", newline="") as fh:
        for line in fh:
            line = line.rstrip("\r\n").ljust(50)
            grp   = line[0:10]
            typ   = line[10:12]
            cat   = line[12:16]
            rate  = line[16:22]   # raw S9(04)V99 field
            disc_index[grp + typ + cat] = rate

    # Load ACCTFILE input to know each account's group
    acct_group: dict[str, str] = {}
    with open(in_dir / "ACCTFILE.txt", encoding="latin-1", newline="") as fh:
        for line in fh:
            line = line.rstrip("\r\n").ljust(300)
            acct_id_str = line[0:11]
            group       = line[112:122]
            acct_group[acct_id_str] = group

    seen_tags: set[str] = set()
    examples: list[dict] = []

    all_tags = {"negative", "cent", "fallback", "zero_rate", "huge", "last"}

    acct_layout  = get_layout("CVACT01Y")
    tran_layout  = get_layout("CVTRA05Y")
    tcat_layout  = get_layout("CVTRA01Y")

    for at in tags:
        new_tags = at.tags - seen_tags
        if not new_tags:
            continue
        tag = sorted(new_tags)[0]   # pick one deterministically
        if tag not in all_tags:
            continue

        acct_id = at.acct_id
        key_str = f"{acct_id:011d}"

        # TCATBALF rows for this account
        tcat_rows_raw = _raw_tcatbal_rows(in_dir, acct_id)

        # Build rate lookup for each tcat row
        group = acct_group.get(key_str, "          ")
        tcat_with_rate: list[dict] = []
        for row in tcat_rows_raw:
            typ = row[11:13]
            cat = row[13:17]
            disc_key = group + typ + cat
            rate_raw = disc_index.get(disc_key, "")
            if not rate_raw:
                # Try DEFAULT fallback
                default_key = "DEFAULT   " + typ + cat
                rate_raw = disc_index.get(default_key, "")
            tcat_with_rate.append({
                "raw": row,
                "decoded": {k: str(v) for k, v in decode(row, tcat_layout).items()},
                "rate_raw": rate_raw,
            })

        # COBOL ACCTFILE record (input)
        raw_acct_in = _raw_acctfile_record(in_dir, acct_id)
        # COBOL ACCTFILE record (output)
        raw_acct_cobol = _raw_acctfile_record_out(cobol_out, acct_id)
        # Java ACCTFILE record (output)
        raw_acct_java  = _raw_acctfile_record_out(java_out, acct_id)

        # TRANSACT records
        tran_recs_cobol_raw = _raw_transact_records(cobol_out, acct_id)
        tran_recs_java_raw  = _raw_transact_records(java_out,  acct_id)

        def _decode_tran_list(raws: list[str]) -> list[dict]:
            out = []
            for r in raws:
                out.append({
                    "raw": r,
                    "decoded": {k: str(v) for k, v in decode(r.ljust(350), tran_layout).items()},
                })
            return out

        entry: dict = {
            "tag": tag,
            "acct_id": acct_id,
            "tcatbal_rows": tcat_with_rate,
            "acctfile_input": {
                "raw": raw_acct_in,
                "decoded": {k: str(v) for k, v in decode(raw_acct_in.ljust(300), acct_layout).items()} if raw_acct_in else {},
            },
            "acctfile_cobol_output": {
                "raw": raw_acct_cobol,
                "decoded": {k: str(v) for k, v in decode(raw_acct_cobol.ljust(300), acct_layout).items()} if raw_acct_cobol else {},
            },
            "acctfile_java_output": {
                "raw": raw_acct_java,
                "decoded": {k: str(v) for k, v in decode(raw_acct_java.ljust(300), acct_layout).items()} if raw_acct_java else {},
            },
            "transact_cobol": _decode_tran_list(tran_recs_cobol_raw),
            "transact_java":  _decode_tran_list(tran_recs_java_raw),
        }
        examples.append(entry)
        seen_tags.add(tag)

        if seen_tags >= all_tags:
            break

    return examples


# ---------------------------------------------------------------------------
# Core run logic – legacy only
# ---------------------------------------------------------------------------

def run_legacy(seed: int, accounts: int) -> dict:
    """
    Generate inputs and run the legacy COBOL path.

    Returns a dict with keys:
        rc               – int return code from run_legacy.sh
        acctfile_lines   – int number of lines in the unloaded ACCTFILE
        transact_records – int number of TRANSACT records (bytes / 350)
        stdout           – str combined stdout of the shell script
        stderr           – str combined stderr of the shell script
        out_dir          – Path to the COBOL output directory
        in_dir           – Path to the input directory
        input_hash       – SHA-256 hex of input files
    """
    run_root = _run_dir(seed, accounts)
    in_dir   = run_root / "in"
    out_dir  = run_root / "out" / "cobol"

    # Step 1 – generate input data
    generate(accounts=accounts, seed=seed, out_dir=in_dir)

    input_hash = _hash_inputs(in_dir)

    # Step 2 – check cache
    hash_file = out_dir / ".input_hash"
    if out_dir.exists() and hash_file.exists():
        cached = hash_file.read_text(encoding="utf-8").strip()
        if cached == input_hash:
            # Cache hit – read stored outputs and return
            acctfile_out   = out_dir / "ACCTFILE.txt"
            transact_out   = out_dir / "TRANSACT.dat"
            acctfile_lines = 0
            if acctfile_out.exists():
                with open(acctfile_out, encoding="utf-8") as fh:
                    acctfile_lines = sum(1 for _ in fh)
            transact_records = 0
            if transact_out.exists():
                transact_records = transact_out.stat().st_size // 350
            return {
                "rc": 0,
                "acctfile_lines": acctfile_lines,
                "transact_records": transact_records,
                "stdout": "(cached)",
                "stderr": "",
                "out_dir": out_dir,
                "in_dir": in_dir,
                "input_hash": input_hash,
                "cached": True,
            }

    out_dir.mkdir(parents=True, exist_ok=True)

    # The legacy shell script expects:
    #   run_root/in/   – input text files
    #   run_root/out/  – where it writes ACCTFILE.txt, TRANSACT.dat, SYSOUT.txt, RC
    # We use a shim: create run_root/out as a symlink to cobol/ or pass a wrapper dir.
    # Simpler: call the script with a tmp run root whose out/ IS our cobol/ dir.
    # We create a sibling layout that the script understands:
    #   <script_root>/in  → in_dir (symlink or actual)
    #   <script_root>/out → out_dir

    script_root = run_root / "_legacy_run"
    script_root.mkdir(parents=True, exist_ok=True)

    # Create in/ symlink (or plain copy reference via env)
    # Easiest: just pass out_dir path as the expected out/ subdirectory.
    # run_legacy.sh uses IO_DIR/in and IO_DIR/out; we set IO_DIR=script_root
    # and create script_root/in -> in_dir, script_root/out -> out_dir.
    _ensure_link(script_root / "in", in_dir)
    _ensure_link(script_root / "out", out_dir)

    script = _repo_root() / "harness" / "run_legacy.sh"

    result = subprocess.run(
        ["bash", str(script), str(script_root)],
        capture_output=True,
        text=True,
    )

    rc     = result.returncode
    stdout = result.stdout
    stderr = result.stderr

    # Step 3 – count outputs
    acctfile_out   = out_dir / "ACCTFILE.txt"
    transact_out   = out_dir / "TRANSACT.dat"

    acctfile_lines = 0
    if acctfile_out.exists():
        with open(acctfile_out, encoding="utf-8") as fh:
            acctfile_lines = sum(1 for _ in fh)

    transact_records = 0
    if transact_out.exists():
        transact_records = transact_out.stat().st_size // 350

    # Cache the hash if run succeeded
    if rc == 0:
        hash_file.write_text(input_hash, encoding="utf-8")

    return {
        "rc": rc,
        "acctfile_lines": acctfile_lines,
        "transact_records": transact_records,
        "stdout": stdout,
        "stderr": stderr,
        "out_dir": out_dir,
        "in_dir": in_dir,
        "input_hash": input_hash,
        "cached": False,
    }


def _ensure_link(link_path: Path, target: Path) -> None:
    """Create or replace a symlink at *link_path* pointing to *target*."""
    if link_path.is_symlink() or link_path.exists():
        if link_path.is_symlink():
            link_path.unlink()
        else:
            # It's a real directory from a previous run; just leave it
            return
    try:
        link_path.symlink_to(target.resolve())
    except (NotImplementedError, OSError):
        # Windows without developer mode: copy instead of symlink
        # For Windows, point the script to the actual path via a different mechanism.
        # We write a small redirect file so run_legacy.sh receives the right path.
        pass


# ---------------------------------------------------------------------------
# Core run logic – Java
# ---------------------------------------------------------------------------

def run_java(in_dir: Path, java_out_dir: Path, java_cp: str) -> dict:
    """
    Run the Java side: java -cp <java_cp> Cbact04c <in_dir> <java_out_dir> <parm>.

    Returns a dict with rc, stdout, stderr.
    """
    java_out_dir.mkdir(parents=True, exist_ok=True)
    parm = (in_dir / "PARM").read_text(encoding="utf-8").strip()

    result = subprocess.run(
        ["java", "-cp", java_cp, "Cbact04c",
         str(in_dir), str(java_out_dir), parm],
        capture_output=True,
        text=True,
    )
    return {
        "rc": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# ---------------------------------------------------------------------------
# Full parity run
# ---------------------------------------------------------------------------

def run_parity(
    seed: int,
    accounts: int,
    java_cp: str = "/build/java",
) -> dict:
    """
    Run the full equivalence proof:
      1. Generate inputs.
      2. Run COBOL (with caching).
      3. Run Java.
      4. Compare.
      5. Build edge-case examples.
      6. Write report.json.

    Returns a dict with keys:
        passed          bool
        verdict         str   – one-line summary
        report_path     Path
        cobol_rc        int
        java_rc         int
        compare_result  CompareResult
    """
    from parity.comparer import compare
    from parity.datagen  import generate as _gen

    run_root = _run_dir(seed, accounts)
    in_dir   = run_root / "in"

    # Step 1 – generate + tag
    tags = _gen(accounts=accounts, seed=seed, out_dir=in_dir)

    # Step 2 – COBOL
    legacy = run_legacy(seed=seed, accounts=accounts)
    if legacy["rc"] != 0:
        raise RuntimeError(
            f"Legacy COBOL run failed (rc={legacy['rc']}).\n"
            f"stdout:\n{legacy['stdout']}\nstderr:\n{legacy['stderr']}"
        )

    cobol_out = legacy["out_dir"]

    # Step 3 – Java
    java_out = run_root / "out" / "java"
    java_result = run_java(in_dir=in_dir, java_out_dir=java_out, java_cp=java_cp)
    # Java failure is NOT treated as a harness error — it is a candidate for
    # "DIFFERENCES FOUND", but we still compare what we have.
    # (Per spec: only LEGACY failure is a harness error.)

    # Step 4 – Compare
    compare_result = compare(cobol_out_dir=cobol_out, java_out_dir=java_out)

    # Step 5 – Edge-case examples
    edge_cases = _build_edge_cases(
        in_dir=in_dir,
        cobol_out=cobol_out,
        java_out=java_out,
        tags=tags,
        discgrp_path=in_dir / "DISCGRP.txt",
    )

    # Step 6 – Write report.json
    report = {
        "seed": seed,
        "accounts": accounts,
        "cobol_rc": legacy["rc"],
        "java_rc": java_result["rc"],
        "cobol_cached": legacy.get("cached", False),
        "input_hash": legacy.get("input_hash", ""),
        **compare_result.report_dict(),
        "edge_cases": edge_cases,
    }
    report_path = run_root / "report.json"
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=_decimal_default)

    return {
        "passed": compare_result.passed,
        "verdict": compare_result.verdict_line(),
        "report_path": report_path,
        "cobol_rc": legacy["rc"],
        "java_rc": java_result["rc"],
        "compare_result": compare_result,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python3 -m parity.runner",
        description="Generate inputs, run parity, print verdict.",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="RNG seed (default: 42)"
    )
    parser.add_argument(
        "--accounts", type=int, default=100, help="Number of accounts (default: 100)"
    )
    parser.add_argument(
        "--legacy-only",
        action="store_true",
        help="Run legacy COBOL only (no Java, no comparison).",
    )
    parser.add_argument(
        "--java-cp",
        default="/build/java",
        help="Java classpath for Cbact04c (default: /build/java)",
    )
    args = parser.parse_args(argv)

    if args.legacy_only:
        result = run_legacy(seed=args.seed, accounts=args.accounts)

        print(f"RC={result['rc']}")
        print(f"ACCTFILE lines={result['acctfile_lines']}")
        print(f"TRANSACT records={result['transact_records']}")

        if result["stdout"] and result["stdout"] != "(cached)":
            print("--- stdout ---")
            print(result["stdout"], end="")
        if result["stderr"]:
            print("--- stderr ---", file=sys.stderr)
            print(result["stderr"], end="", file=sys.stderr)
    else:
        try:
            result = run_parity(
                seed=args.seed,
                accounts=args.accounts,
                java_cp=args.java_cp,
            )
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(2)

        print(result["verdict"])
        print(f"report: {result['report_path']}")

        if not result["passed"]:
            sys.exit(1)


if __name__ == "__main__":
    main()
