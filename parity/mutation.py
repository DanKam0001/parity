"""
parity/mutation.py
==================
Mutation-testing harness for the Cbact04c Java rewrite.

CLI usage
---------
    python3 -m parity.mutation

What it does
------------
For each of 6 defined mutants:
  1. Apply ONE exact find/replace edit to a temp copy of bob_outputs/Cbact04c.java.
  2. Compile the mutant with javac into a private temp dir.
  3. Run the proof on seed=7, 2000 accounts, using the cached COBOL output.
  4. Record: caught (bool), differing fields (count + one example).

Writes:
  bob_outputs/mutants.json   – per-mutant results
  bob_outputs/confirm.json   – real rewrite re-proved on seeds 11, 23, 42

Prints a summary line like:
  6/6 mutants caught · 3/3 seeds equivalent
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo / path helpers
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _java_source() -> Path:
    return _repo_root() / "bob_outputs" / "Cbact04c.java"


def _bob_outputs() -> Path:
    return _repo_root() / "bob_outputs"


# ---------------------------------------------------------------------------
# Mutant definitions
# ---------------------------------------------------------------------------

@dataclass
class Mutant:
    id: str
    description: str
    search: str    # exact string to find in the Java source
    replace: str   # exact string to replace it with


MUTANTS: list[Mutant] = [
    # 1. helpful-fix: post the last account after the loop, fixing the faithful
    #    last-account bug — makes Java diverge from COBOL on the final account.
    Mutant(
        id="helpful-fix",
        description=(
            "Post the last account's interest and reset its cycle totals after "
            "the loop (fixes the faithful last-account bug, breaking parity)"
        ),
        search="        tranOut.close();",
        replace=(
            "        if (!wsFirstTime && accountRecord != null) {\n"
            "            perform1050UpdateAccount(accountRecord, acctByKey,\n"
            "                    wsLastAcctNum, wsTotalInt);\n"
            "        }\n"
            "        tranOut.close();"
        ),
    ),

    # 2. rounding: HALF_UP instead of truncation (DOWN).
    Mutant(
        id="rounding",
        description=(
            "Use RoundingMode.HALF_UP instead of RoundingMode.DOWN when "
            "computing monthly interest (should be truncation)"
        ),
        search=(
            "        return catBal.multiply(intRate)\n"
            "                     .divide(BigDecimal.valueOf(1200), 2, RoundingMode.DOWN);"
        ),
        replace=(
            "        return catBal.multiply(intRate)\n"
            "                     .divide(BigDecimal.valueOf(1200), 2, RoundingMode.HALF_UP);"
        ),
    ),

    # 3. floats: double arithmetic then convert, losing decimal precision.
    Mutant(
        id="floats",
        description=(
            "Compute monthly interest with double arithmetic then convert to "
            "BigDecimal (introduces floating-point rounding errors)"
        ),
        search=(
            "        return catBal.multiply(intRate)\n"
            "                     .divide(BigDecimal.valueOf(1200), 2, RoundingMode.DOWN);"
        ),
        replace=(
            "        double _d = catBal.doubleValue() * intRate.doubleValue() / 1200.0;\n"
            "        return BigDecimal.valueOf(_d).setScale(2, RoundingMode.DOWN);"
        ),
    ),

    # 4. fallback: wrong fallback group name.
    Mutant(
        id="fallback",
        description=(
            "Fall back to group ZEROAPR instead of DEFAULT when disclosure "
            "group record is missing"
        ),
        search='            String defaultKey = buildDiscKey("DEFAULT   ", typeCd, catCd);',
        replace='            String defaultKey = buildDiscKey("ZEROAPR   ", typeCd, catCd);',
    ),

    # 5. cycle-reset: omit the credit-total reset in 1050-UPDATE-ACCOUNT.
    Mutant(
        id="cycle-reset",
        description=(
            "Forget to reset ACCT-CURR-CYC-CREDIT in 1050-UPDATE-ACCOUNT "
            "(cycle credit total is not zeroed)"
        ),
        search=(
            "        setAcctCurrCycCredit(accountRecord, BigDecimal.ZERO);\n"
            "        setAcctCurrCycDebit(accountRecord, BigDecimal.ZERO);"
        ),
        replace="        setAcctCurrCycDebit(accountRecord, BigDecimal.ZERO);",
    ),

    # 6. numbering: pass suffix before incrementing so first TX ID ends in 000000.
    Mutant(
        id="numbering",
        description=(
            "Number transactions from 0 instead of 1 (pass suffix before "
            "incrementing so first transaction ID suffix is 000000)"
        ),
        search=(
            "                        wsTranidSuffix++;\n"
            "                        perform1300bWriteTx(tranOut, parmDate, wsTranidSuffix,\n"
            "                                wsMonthlyInt, accountRecord, cardXrefRecord);"
        ),
        replace=(
            "                        perform1300bWriteTx(tranOut, parmDate, wsTranidSuffix,\n"
            "                                wsMonthlyInt, accountRecord, cardXrefRecord);\n"
            "                        wsTranidSuffix++;"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Compile a mutated Java source into a temp directory
# ---------------------------------------------------------------------------

def _compile_mutant(java_source: str, tmp_dir: Path) -> tuple[bool, str]:
    """
    Write java_source to tmp_dir/Cbact04c.java and compile it.
    Returns (success, error_output).
    """
    src_path = tmp_dir / "Cbact04c.java"
    src_path.write_text(java_source, encoding="utf-8")

    result = subprocess.run(
        ["javac", "-encoding", "UTF-8", str(src_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, result.stderr
    return True, ""


# ---------------------------------------------------------------------------
# Run proof for one mutant (or the real rewrite)
# ---------------------------------------------------------------------------

def _run_proof(
    seed: int,
    accounts: int,
    java_cp: str,
    out_label: str = "java",
) -> dict:
    """
    Run a full parity proof with the given java_cp.
    Returns a dict with 'passed', 'acctfile', 'transact', 'verdict'.
    """
    from parity.comparer import compare, CompareResult
    from parity.runner import run_legacy, run_java, _run_dir

    run_root = _run_dir(seed, accounts)
    in_dir = run_root / "in"

    # Generate inputs (idempotent for same seed/accounts)
    from parity.datagen import generate
    generate(accounts=accounts, seed=seed, out_dir=in_dir)

    # Run COBOL (cached if already done)
    legacy = run_legacy(seed=seed, accounts=accounts)
    if legacy["rc"] != 0:
        raise RuntimeError(
            f"Legacy COBOL run failed rc={legacy['rc']}\n{legacy['stderr']}"
        )
    cobol_out = legacy["out_dir"]

    # Run Java (mutant or real)
    java_out = run_root / "out" / out_label
    java_result = run_java(in_dir=in_dir, java_out_dir=java_out, java_cp=java_cp)

    if java_result["rc"] != 0:
        # Java failed (e.g. abend) — treat as caught (not equivalent)
        return {
            "passed": False,
            "java_rc": java_result["rc"],
            "java_stderr": java_result["stderr"],
            "acctfile": None,
            "transact": None,
            "verdict": "JAVA ABENDED",
        }

    cr: CompareResult = compare(cobol_out_dir=cobol_out, java_out_dir=java_out)

    # Collect field diffs summary
    def _file_summary(fr) -> dict:
        if fr is None:
            return {}
        diffs = []
        for fd in fr.field_diffs:
            ex = fd.examples[0] if fd.examples else None
            diffs.append({
                "field": fd.field_name,
                "mismatch_count": fd.mismatch_count,
                "example": {
                    "key": ex.key,
                    "cobol_value": ex.cobol_value,
                    "java_value": ex.java_value,
                } if ex else None,
            })
        return {
            "cobol_count": fr.cobol_count,
            "java_count": fr.java_count,
            "matched": fr.matched,
            "mismatched": fr.mismatched,
            "missing": fr.missing,
            "extra": fr.extra,
            "field_diffs": diffs,
        }

    return {
        "passed": cr.passed,
        "java_rc": java_result["rc"],
        "acctfile": _file_summary(cr.acctfile),
        "transact": _file_summary(cr.transact),
        "verdict": cr.verdict_line(),
    }


# ---------------------------------------------------------------------------
# Per-mutant result
# ---------------------------------------------------------------------------

def _run_mutant(mutant: Mutant, seed: int, accounts: int) -> dict:
    """Apply the mutant, compile, run proof, return result dict."""
    original = _java_source().read_text(encoding="utf-8")

    if mutant.search not in original:
        return {
            "id": mutant.id,
            "description": mutant.description,
            "edit": {"search": mutant.search, "replace": mutant.replace},
            "compile_ok": False,
            "compile_error": "SEARCH STRING NOT FOUND IN SOURCE",
            "caught": False,
            "fields": [],
        }

    mutated = original.replace(mutant.search, mutant.replace, 1)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        compile_ok, compile_err = _compile_mutant(mutated, tmp_dir)

        if not compile_ok:
            return {
                "id": mutant.id,
                "description": mutant.description,
                "edit": {"search": mutant.search, "replace": mutant.replace},
                "compile_ok": False,
                "compile_error": compile_err,
                "caught": False,
                "fields": [],
            }

        java_cp = str(tmp_dir)
        proof = _run_proof(
            seed=seed, accounts=accounts, java_cp=java_cp,
            out_label=f"java_mutant_{mutant.id}",
        )

    caught = not proof["passed"]

    # Collect field-diff summary (at most one example per differing field)
    fields: list[dict] = []
    for file_key in ("acctfile", "transact"):
        file_result = proof.get(file_key) or {}
        for diff in file_result.get("field_diffs", []):
            fields.append({
                "file": file_key,
                "field": diff["field"],
                "mismatch_count": diff["mismatch_count"],
                "example": diff.get("example"),
            })

    return {
        "id": mutant.id,
        "description": mutant.description,
        "edit": {"search": mutant.search, "replace": mutant.replace},
        "compile_ok": True,
        "compile_error": "",
        "caught": caught,
        "verdict": proof.get("verdict", ""),
        "fields": fields,
    }


# ---------------------------------------------------------------------------
# Confirm real rewrite on multiple seeds
# ---------------------------------------------------------------------------

def _run_confirm(seeds: list[int], accounts: int, java_cp: str) -> list[dict]:
    """Re-prove the real rewrite on each seed. Returns list of result dicts."""
    results = []
    for seed in seeds:
        print(f"  confirm seed={seed} accounts={accounts} ...", flush=True)
        proof = _run_proof(
            seed=seed, accounts=accounts, java_cp=java_cp,
            out_label="java",
        )
        results.append({
            "seed": seed,
            "accounts": accounts,
            "passed": proof["passed"],
            "verdict": proof.get("verdict", ""),
        })
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python3 -m parity.mutation",
        description="Mutation-test the Cbact04c Java rewrite.",
    )
    parser.add_argument(
        "--seed", type=int, default=7,
        help="Seed for mutation tests (default: 7)"
    )
    parser.add_argument(
        "--accounts", type=int, default=2000,
        help="Number of accounts for mutation tests (default: 2000)"
    )
    parser.add_argument(
        "--java-cp", default="/build/java",
        help="Java classpath for the REAL Cbact04c (default: /build/java)"
    )
    parser.add_argument(
        "--confirm-seeds", default="11,23,42",
        help="Comma-separated seeds for confirmation runs (default: 11,23,42)"
    )
    args = parser.parse_args(argv)

    confirm_seeds = [int(s) for s in args.confirm_seeds.split(",")]

    bob_out = _bob_outputs()
    bob_out.mkdir(parents=True, exist_ok=True)

    # ── Run all mutants ──────────────────────────────────────────────────────
    mutant_results: list[dict] = []
    caught_count = 0

    for i, mutant in enumerate(MUTANTS, 1):
        print(f"[{i}/{len(MUTANTS)}] mutant={mutant.id} ...", flush=True)
        result = _run_mutant(mutant, seed=args.seed, accounts=args.accounts)
        mutant_results.append(result)

        caught_count += int(result["caught"])

        status = "CAUGHT" if result["caught"] else ("COMPILE_FAIL" if not result["compile_ok"] else "MISSED")
        verdict = result.get("verdict", result.get("compile_error", ""))
        print(f"         → {status}  {verdict}")
        if result["fields"]:
            f0 = result["fields"][0]
            ex = f0.get("example") or {}
            print(
                f"           first diff: {f0['file']}.{f0['field']} "
                f"count={f0['mismatch_count']} "
                f"key={ex.get('key','')} "
                f"cobol={ex.get('cobol_value','')} "
                f"java={ex.get('java_value','')}"
            )

    # Write mutants.json
    mutants_path = bob_out / "mutants.json"
    with open(mutants_path, "w", encoding="utf-8") as fh:
        json.dump(mutant_results, fh, indent=2)
    print(f"\nWrote {mutants_path}")

    # ── Confirm real rewrite ─────────────────────────────────────────────────
    print(f"\nConfirming real rewrite on seeds {confirm_seeds} ...", flush=True)
    confirm_results = _run_confirm(
        seeds=confirm_seeds,
        accounts=args.accounts,
        java_cp=args.java_cp,
    )
    passed_confirm = sum(1 for r in confirm_results if r["passed"])

    confirm_path = bob_out / "confirm.json"
    with open(confirm_path, "w", encoding="utf-8") as fh:
        json.dump(confirm_results, fh, indent=2)
    print(f"Wrote {confirm_path}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print(
        f"\n{caught_count}/{len(MUTANTS)} mutants caught · "
        f"{passed_confirm}/{len(confirm_seeds)} seeds equivalent"
    )

    if caught_count < len(MUTANTS) or passed_confirm < len(confirm_seeds):
        sys.exit(1)


if __name__ == "__main__":
    main()
