"""
parity/runner.py
================
Orchestrate a single COBOL-only ("legacy") parity run.

CLI usage
---------
    python3 -m parity.runner --seed 7 --accounts 2000 --legacy-only

What it does
------------
1. Calls datagen.generate() → writes input files into  runs/<seed>_<accounts>/in/
2. Calls harness/run_legacy.sh  (which loads indexed files, runs DRIVER→CBACT04C,
   and unloads ACCTFILE).
3. Prints:
     RC=<return code>
     ACCTFILE lines=<number>
     TRANSACT records=<file_size_bytes / 350>
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from parity.datagen import generate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Return the absolute path to the repository root."""
    return Path(__file__).resolve().parent.parent


def _run_dir(seed: int, accounts: int) -> Path:
    return _repo_root() / "runs" / f"{seed}_{accounts}"


# ---------------------------------------------------------------------------
# Core run logic
# ---------------------------------------------------------------------------

def run_legacy(seed: int, accounts: int) -> dict:
    """
    Generate inputs and run the legacy COBOL path.

    Returns a dict with keys:
        rc          – int return code from run_legacy.sh
        acctfile_lines – int number of lines in the unloaded ACCTFILE
        transact_records – int number of TRANSACT records (bytes / 350)
        stdout      – str combined stdout of the shell script
        stderr      – str combined stderr of the shell script
    """
    run_root = _run_dir(seed, accounts)
    in_dir = run_root / "in"

    # Step 1 – generate input data
    generate(accounts=accounts, seed=seed, out_dir=in_dir)

    # Step 2 – call the shell harness
    script = _repo_root() / "harness" / "run_legacy.sh"

    result = subprocess.run(
        ["bash", str(script), str(run_root)],
        capture_output=True,
        text=True,
    )

    rc = result.returncode
    stdout = result.stdout
    stderr = result.stderr

    # Step 3 – count outputs
    out_dir = run_root / "out"
    acctfile_out = out_dir / "ACCTFILE.txt"
    transact_out = out_dir / "TRANSACT.dat"

    acctfile_lines = 0
    if acctfile_out.exists():
        with open(acctfile_out, encoding="utf-8") as fh:
            acctfile_lines = sum(1 for _ in fh)

    transact_records = 0
    if transact_out.exists():
        transact_records = transact_out.stat().st_size // 350

    return {
        "rc": rc,
        "acctfile_lines": acctfile_lines,
        "transact_records": transact_records,
        "stdout": stdout,
        "stderr": stderr,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python3 -m parity.runner",
        description="Generate inputs, run legacy COBOL, print summary.",
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
        help="Run legacy COBOL only (Java path not yet implemented).",
    )
    args = parser.parse_args(argv)

    if not args.legacy_only:
        parser.error("Only --legacy-only is currently supported.")

    result = run_legacy(seed=args.seed, accounts=args.accounts)

    print(f"RC={result['rc']}")
    print(f"ACCTFILE lines={result['acctfile_lines']}")
    print(f"TRANSACT records={result['transact_records']}")

    if result["stdout"]:
        print("--- stdout ---")
        print(result["stdout"], end="")
    if result["stderr"]:
        print("--- stderr ---", file=sys.stderr)
        print(result["stderr"], end="", file=sys.stderr)


if __name__ == "__main__":
    main()
