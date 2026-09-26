"""
tests/test_copybook.py
======================
Round-trip decode→encode test against vendor/carddemo/data/acctdata.txt.

For every line in acctdata.txt (CRLF stripped, padded to 300):
  1. decode(line, CVACT01Y_layout) → dict
  2. encode(dict, CVACT01Y_layout) → str
  3. assert encoded == original (padded to 300)
"""

from __future__ import annotations

import pathlib
import pytest

from parity.copybook import decode, encode, get_layout

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ACCTDATA = REPO_ROOT / "vendor" / "carddemo" / "data" / "acctdata.txt"
RECORD_LEN = 300


def _load_acctdata() -> list[str]:
    """
    Read acctdata.txt, strip CR (handle CRLF), pad each line to RECORD_LEN.
    Returns one entry per non-empty line.
    """
    records: list[str] = []
    with open(ACCTDATA, encoding="latin-1", newline="") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")  # strip CR/LF
            if not line:
                continue
            # Pad to full record length (trailing spaces stripped by unloader)
            records.append(line.ljust(RECORD_LEN))
    return records


# ---------------------------------------------------------------------------
# Parametrised test
# ---------------------------------------------------------------------------

_LAYOUT = get_layout("CVACT01Y")
_RECORDS = _load_acctdata()


@pytest.mark.parametrize("record", _RECORDS, ids=lambda r: r[:11].strip())
def test_roundtrip(record: str) -> None:
    """decode then encode must reproduce the original 300-byte record exactly."""
    fields = decode(record, _LAYOUT)
    result = encode(fields, _LAYOUT)
    assert len(result) == RECORD_LEN, (
        f"encode returned {len(result)} chars, expected {RECORD_LEN}"
    )
    assert result == record, (
        f"\noriginal: {record!r}\nencoded:  {result!r}"
    )
