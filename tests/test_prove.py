"""
tests/test_prove.py
===================
Integration tests for the equivalence proof.

Test 1 – real Java gives equal=True on seed 7 / 200 accounts.
Test 2 – a patched copy of Cbact04c.java (RoundingMode.DOWN → HALF_UP),
          compiled into a temp dir, gives equal=False with TRAN-AMT among the
          differing fields.

These tests require a working build environment:
  - bash, the COBOL harness and binaries on PATH / COB_LIBRARY_PATH
  - java and javac on PATH
  - The compiled Cbact04c class reachable at /build/java (default java_cp)

The tests are marked ``integration`` and are skipped when the executables
are not present.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Skip guard — skip the whole module if the environment isn't available
# ---------------------------------------------------------------------------

def _have_java() -> bool:
    return shutil.which("java") is not None


def _have_javac() -> bool:
    return shutil.which("javac") is not None


def _have_bash() -> bool:
    return shutil.which("bash") is not None


def _cobol_binaries_present() -> bool:
    """Return True if the COBOL harness executables are on PATH."""
    return (
        shutil.which("DRIVER") is not None
        or shutil.which("LOADER_ACCTFILE") is not None
    )


_NEEDS_FULL_ENV = pytest.mark.skipif(
    not (_have_bash() and _cobol_binaries_present() and _have_java() and _have_javac()),
    reason="Integration environment not available (needs bash + COBOL harness + java + javac)",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT   = Path(__file__).resolve().parent.parent
JAVA_SRC    = REPO_ROOT / "bob_outputs" / "Cbact04c.java"
DEFAULT_CP  = "/build/java"

SEED     = 7
ACCOUNTS = 200

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _java_cp() -> str:
    """Return the Java classpath to use for the unmodified run."""
    return DEFAULT_CP


def _compile_java(src: Path, out_dir: Path) -> Path:
    """
    Compile *src* with javac -encoding UTF-8 into *out_dir*.
    Raises subprocess.CalledProcessError on failure.
    Returns *out_dir*.
    """
    result = subprocess.run(
        ["javac", "-encoding", "UTF-8", "-d", str(out_dir), str(src)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"javac failed:\n{result.stdout}\n{result.stderr}"
        )
    return out_dir


def _patch_rounding(src: Path, dst: Path) -> None:
    """
    Copy *src* to *dst*, replacing every occurrence of
    RoundingMode.DOWN  with  RoundingMode.HALF_UP.
    """
    text = src.read_text(encoding="utf-8")
    patched = text.replace("RoundingMode.DOWN", "RoundingMode.HALF_UP")
    if patched == text:
        raise ValueError("No RoundingMode.DOWN found in source — patch target missing")
    dst.write_text(patched, encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1 – real Java → EQUIVALENT
# ---------------------------------------------------------------------------

@_NEEDS_FULL_ENV
def test_real_java_equivalent() -> None:
    """
    Seed 7, 200 accounts: the real compiled Cbact04c gives equal=True on
    every field of both output files.
    """
    from parity.runner import run_parity

    result = run_parity(seed=SEED, accounts=ACCOUNTS, java_cp=_java_cp())

    assert result["passed"] is True, (
        f"Expected EQUIVALENT but got differences.\n"
        f"Verdict: {result['verdict']}\n"
        f"Report: {result['report_path']}"
    )

    cr = result["compare_result"]
    assert cr.acctfile.mismatched == 0, (
        f"ACCTFILE mismatched records: {cr.acctfile.mismatched}"
    )
    assert cr.transact.mismatched == 0, (
        f"TRANSACT mismatched records: {cr.transact.mismatched}"
    )
    assert cr.acctfile.missing == 0
    assert cr.acctfile.extra   == 0
    assert cr.transact.missing == 0
    assert cr.transact.extra   == 0


# ---------------------------------------------------------------------------
# Test 2 – patched Java (HALF_UP) → DIFFERENCES FOUND, TRAN-AMT in diffs
# ---------------------------------------------------------------------------

@_NEEDS_FULL_ENV
def test_patched_rounding_detected() -> None:
    """
    A copy of Cbact04c.java with RoundingMode.DOWN replaced by HALF_UP,
    compiled fresh, gives equal=False with TRAN-AMT among the differing fields.
    """
    from parity.runner import run_parity, run_legacy, run_java, _run_dir
    from parity.datagen import generate
    from parity.comparer import compare

    run_root = _run_dir(SEED, ACCOUNTS)
    in_dir   = run_root / "in"

    # Ensure COBOL outputs exist (reuse cache if available)
    legacy = run_legacy(seed=SEED, accounts=ACCOUNTS)
    if legacy["rc"] != 0:
        pytest.fail(
            f"Legacy COBOL run failed (rc={legacy['rc']}). "
            "This is a harness problem, not a test failure."
        )
    cobol_out = legacy["out_dir"]

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)

        # Write and compile the patched source
        patched_src = tmpdir / "Cbact04c.java"
        _patch_rounding(JAVA_SRC, patched_src)
        patched_cp = tmpdir / "classes"
        patched_cp.mkdir()
        _compile_java(patched_src, patched_cp)

        # Run patched Java
        java_out = tmpdir / "java_out"
        java_result = run_java(
            in_dir=in_dir,
            java_out_dir=java_out,
            java_cp=str(patched_cp),
        )
        # Java process returning non-zero is not a harness error for this test —
        # it might still have produced output we can compare.

        # Compare COBOL output vs patched Java output
        cr = compare(cobol_out_dir=cobol_out, java_out_dir=java_out)

        assert cr.passed is False, (
            "Expected DIFFERENCES FOUND with patched rounding but got EQUIVALENT"
        )

        # TRAN-AMT must appear in the transaction field diffs
        tran_diff_fields = {fd.field_name for fd in cr.transact.field_diffs}
        assert "TRAN-AMT" in tran_diff_fields, (
            f"Expected TRAN-AMT in differing fields, got: {sorted(tran_diff_fields)}"
        )
