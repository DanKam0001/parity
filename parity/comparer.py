"""
parity/comparer.py
==================
Field-by-field comparison of COBOL vs Java outputs for one parity run.

Public API
----------
    compare(cobol_out_dir, java_out_dir) -> CompareResult

CompareResult fields
--------------------
    passed          bool  – True iff every record matches on every field
    acctfile        FileResult
    transact        FileResult
    report_dict()   -> dict  – JSON-serialisable summary

FileResult fields
-----------------
    cobol_count     int   – records seen on the COBOL side
    java_count      int   – records seen on the Java side
    matched         int   – records whose every field agreed
    mismatched      int   – records with ≥1 field disagreement
    missing         int   – keys in COBOL output absent from Java output
    extra           int   – keys in Java output absent from COBOL output
    field_diffs     list[FieldDiff]   – top offending fields (≤ all)

FieldDiff
---------
    field_name      str
    mismatch_count  int
    examples        list[Example]   – up to 3

Example
-------
    key             str   – record key (ACCT-ID or TRAN-ID)
    cobol_value     str   – decoded value as string
    java_value      str   – decoded value as string
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from parity.copybook import decode, get_layout

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCTFILE_RECLEN  = 300      # pad COBOL lines to this (unloader strips trailing spaces)
TRANSACT_RECLEN  = 350      # binary concatenated, no newlines
TS_PATTERN       = re.compile(
    r"^\d{4}-\d{2}-\d{2}-\d{2}\.\d{2}\.\d{2}\.\d{2}0000$"
)
TS_FIELDS        = {"TRAN-ORIG-TS", "TRAN-PROC-TS"}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Example:
    key: str
    cobol_value: str
    java_value: str

    def to_dict(self) -> dict:
        return {"key": self.key, "cobol_value": self.cobol_value, "java_value": self.java_value}


@dataclass
class FieldDiff:
    field_name: str
    mismatch_count: int = 0
    examples: list[Example] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "field_name": self.field_name,
            "mismatch_count": self.mismatch_count,
            "examples": [e.to_dict() for e in self.examples],
        }


@dataclass
class FileResult:
    name: str
    cobol_count: int = 0
    java_count: int = 0
    matched: int = 0
    mismatched: int = 0
    missing: int = 0
    extra: int = 0
    field_diffs: list[FieldDiff] = field(default_factory=list)

    @property
    def equal(self) -> bool:
        return (
            self.cobol_count == self.java_count
            and self.mismatched == 0
            and self.missing == 0
            and self.extra == 0
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "cobol_count": self.cobol_count,
            "java_count": self.java_count,
            "matched": self.matched,
            "mismatched": self.mismatched,
            "missing": self.missing,
            "extra": self.extra,
            "equal": self.equal,
            "field_diffs": [fd.to_dict() for fd in self.field_diffs],
        }


@dataclass
class CompareResult:
    acctfile: FileResult
    transact: FileResult

    @property
    def passed(self) -> bool:
        return self.acctfile.equal and self.transact.equal

    def report_dict(self) -> dict:
        return {
            "passed": self.passed,
            "acctfile": self.acctfile.to_dict(),
            "transact": self.transact.to_dict(),
        }

    def verdict_line(self) -> str:
        af = self.acctfile
        tr = self.transact
        status = "EQUIVALENT" if self.passed else "DIFFERENCES FOUND"
        return (
            f"ACCTFILE {af.matched}/{af.cobol_count} · "
            f"TRANSACT {tr.matched}/{tr.cobol_count} · {status}"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_acctfile(path: Path) -> dict[str, dict[str, Any]]:
    """
    Read ACCTFILE.txt (one 300-byte padded record per line, LF-terminated).
    Returns {acct_id_str: decoded_fields}.
    The COBOL unloader strips trailing spaces, so lines may be short; pad to 300.
    """
    layout = get_layout("CVACT01Y")
    records: dict[str, dict[str, Any]] = {}
    with open(path, encoding="latin-1", newline="") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            line = line.ljust(ACCTFILE_RECLEN)
            fields = decode(line, layout)
            key = str(fields["ACCT-ID"]).strip()
            records[key] = fields
    return records


def _load_transact(path: Path) -> dict[str, dict[str, Any]]:
    """
    Read TRANSACT.dat (binary, 350-byte records, no newlines).
    Returns {tran_id_str: decoded_fields}.
    """
    layout = get_layout("CVTRA05Y")
    records: dict[str, dict[str, Any]] = {}
    data = path.read_bytes()
    n = len(data) // TRANSACT_RECLEN
    for i in range(n):
        chunk = data[i * TRANSACT_RECLEN : (i + 1) * TRANSACT_RECLEN]
        rec_str = chunk.decode("latin-1")
        fields = decode(rec_str, layout)
        key = fields["TRAN-ID"].strip()
        records[key] = fields
    return records


def _value_str(v: Any) -> str:
    """Normalise a decoded field value to a plain string for comparison."""
    return str(v)


def _compare_records(
    name: str,
    cobol_recs: dict[str, dict[str, Any]],
    java_recs:  dict[str, dict[str, Any]],
) -> FileResult:
    """
    Compare two dicts of decoded records field by field.
    Returns a FileResult.
    """
    result = FileResult(name=name)
    result.cobol_count = len(cobol_recs)
    result.java_count  = len(java_recs)

    cobol_keys = set(cobol_recs)
    java_keys  = set(java_recs)

    missing_keys = cobol_keys - java_keys
    extra_keys   = java_keys  - cobol_keys
    common_keys  = cobol_keys & java_keys

    result.missing = len(missing_keys)
    result.extra   = len(extra_keys)

    # Per-field diff tracking: field_name → {"count": int, "examples": list}
    field_tracker: dict[str, dict] = {}

    for key in sorted(common_keys):
        cf = cobol_recs[key]
        jf = java_recs[key]

        record_ok = True

        for fname in cf:
            cv = _value_str(cf[fname])
            jv = _value_str(jf.get(fname, ""))

            if fname in TS_FIELDS:
                # Format-check only; literal value is never compared
                c_ok = bool(TS_PATTERN.match(cv))
                j_ok = bool(TS_PATTERN.match(jv))
                if not c_ok or not j_ok:
                    # Bad format is a mismatch
                    bad_val = cv if not c_ok else jv
                    side    = "COBOL" if not c_ok else "Java"
                    _track_diff(
                        field_tracker, fname, key,
                        cobol_value=f"[FORMAT-CHECK:{cv}]" if not c_ok else f"[FORMAT-OK:{cv}]",
                        java_value =f"[FORMAT-CHECK:{jv}]" if not j_ok else f"[FORMAT-OK:{jv}]",
                    )
                    record_ok = False
                # If both formats are valid, this field is "matched" (not listed as diff)
            else:
                if cv != jv:
                    _track_diff(field_tracker, fname, key, cv, jv)
                    record_ok = False

        if record_ok:
            result.matched += 1
        else:
            result.mismatched += 1

    # Build FieldDiff list, sorted by mismatch_count descending
    diffs: list[FieldDiff] = []
    for fname, info in field_tracker.items():
        fd = FieldDiff(
            field_name=fname,
            mismatch_count=info["count"],
            examples=info["examples"][:3],
        )
        diffs.append(fd)
    diffs.sort(key=lambda d: d.mismatch_count, reverse=True)
    result.field_diffs = diffs

    return result


def _track_diff(
    tracker: dict,
    fname: str,
    key: str,
    cobol_value: str,
    java_value: str,
) -> None:
    if fname not in tracker:
        tracker[fname] = {"count": 0, "examples": []}
    tracker[fname]["count"] += 1
    if len(tracker[fname]["examples"]) < 3:
        tracker[fname]["examples"].append(
            Example(key=key, cobol_value=cobol_value, java_value=java_value)
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compare(cobol_out_dir: str | Path, java_out_dir: str | Path) -> CompareResult:
    """
    Compare the COBOL and Java outputs of one parity run.

    Parameters
    ----------
    cobol_out_dir:
        Directory containing COBOL outputs:
          - ACCTFILE.txt  (unloaded, variable-length lines padded to 300)
          - TRANSACT.dat  (binary, 350-byte records)
    java_out_dir:
        Directory containing Java outputs (same file names, same formats).

    Returns
    -------
    CompareResult with per-file statistics and field-level diffs.
    """
    cobol_out = Path(cobol_out_dir)
    java_out  = Path(java_out_dir)

    # ── ACCTFILE ────────────────────────────────────────────────────────────
    cobol_acct = _load_acctfile(cobol_out / "ACCTFILE.txt")
    java_acct  = _load_acctfile(java_out  / "ACCTFILE.txt")
    acct_result = _compare_records("ACCTFILE", cobol_acct, java_acct)

    # ── TRANSACT ────────────────────────────────────────────────────────────
    cobol_tran = _load_transact(cobol_out / "TRANSACT.dat")
    java_tran  = _load_transact(java_out  / "TRANSACT.dat")
    tran_result = _compare_records("TRANSACT", cobol_tran, java_tran)

    return CompareResult(acctfile=acct_result, transact=tran_result)
