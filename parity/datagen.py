"""
parity/datagen.py
=================
Generate self-consistent test data for CBACT04C parity runs.

Output files (written into *out_dir*)
--------------------------------------
  ACCTFILE.txt   – ACCOUNT-RECORD (300 bytes/line, LF, CVACT01Y layout)
  XREFFILE.txt   – CARD-XREF-RECORD (50 bytes/line, LF, CVACT03Y layout)
  TCATBALF.txt   – TRAN-CAT-BAL-RECORD (50 bytes/line, LF, CVTRA01Y layout)
  DISCGRP.txt    – DIS-GROUP-RECORD (50 bytes/line, LF, CVTRA02Y layout)
  PARM           – literal text "2022071800" (no newline)

All numeric DISPLAY fields use trailing overpunched signs.
Records are sorted by primary key (ascending) within each file.
LF line endings (not CRLF), per the harness requirement.

Returned tag set per account
-----------------------------
  negative   – ACCT-CURR-BAL is negative
  cent       – ACCT-CURR-BAL is ±0.01
  fallback   – group is PLATINUM (not in DISCGRP → DEFAULT fallback)
  zero_rate  – group is ZEROAPR (all rates 0 %)
  huge       – ACCT-CURR-BAL near ±9,999,999,999.99
  last       – the last account (always A000000000, 3 balance rows)
"""

from __future__ import annotations

import os
import random
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

from parity.copybook import encode, get_layout

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PARM_DATE = "2022071800"

# DISCGRP type/category keys present in the vendor file – used for
# both the DISCGRP rows we copy and the TCATBALF rows we generate.
# Each entry is (type_cd: str(2), cat_cd: int(4))
_DISCGRP_KEYS = [
    ("01", 1), ("01", 2), ("01", 3), ("01", 4),
    ("02", 1), ("02", 2), ("02", 3),
    ("03", 1), ("03", 2), ("03", 3),
    ("04", 1), ("04", 2), ("04", 3),
    ("05", 1),
    ("06", 1), ("06", 2),
    ("07", 1),
]

# Rate groups present in vendor/carddemo/data/discgrp.txt
# (rates taken verbatim from that file – see below)
_VENDOR_RATES: dict[tuple[str, str, int], Decimal] = {
    # A000000000
    ("A000000000", "01", 1): Decimal("15.00"),
    ("A000000000", "01", 2): Decimal("25.00"),
    ("A000000000", "01", 3): Decimal("25.00"),
    ("A000000000", "01", 4): Decimal("25.00"),
    ("A000000000", "02", 1): Decimal("0.00"),
    ("A000000000", "02", 2): Decimal("0.00"),
    ("A000000000", "02", 3): Decimal("0.00"),
    ("A000000000", "03", 1): Decimal("0.00"),
    ("A000000000", "03", 2): Decimal("0.00"),
    ("A000000000", "03", 3): Decimal("0.00"),
    ("A000000000", "04", 1): Decimal("15.00"),
    ("A000000000", "04", 2): Decimal("15.00"),
    ("A000000000", "04", 3): Decimal("15.00"),
    ("A000000000", "05", 1): Decimal("15.00"),
    ("A000000000", "06", 1): Decimal("15.00"),
    ("A000000000", "06", 2): Decimal("15.00"),
    ("A000000000", "07", 1): Decimal("0.00"),   # vendor has 0 for 07/0001
    # DEFAULT
    ("DEFAULT   ", "01", 1): Decimal("15.00"),
    ("DEFAULT   ", "01", 2): Decimal("25.00"),
    ("DEFAULT   ", "01", 3): Decimal("25.00"),
    ("DEFAULT   ", "01", 4): Decimal("25.00"),
    ("DEFAULT   ", "02", 1): Decimal("0.00"),
    ("DEFAULT   ", "02", 2): Decimal("0.00"),
    ("DEFAULT   ", "02", 3): Decimal("0.00"),
    ("DEFAULT   ", "03", 1): Decimal("0.00"),
    ("DEFAULT   ", "03", 2): Decimal("0.00"),
    ("DEFAULT   ", "03", 3): Decimal("0.00"),
    ("DEFAULT   ", "04", 1): Decimal("15.00"),
    ("DEFAULT   ", "04", 2): Decimal("15.00"),
    ("DEFAULT   ", "04", 3): Decimal("15.00"),
    ("DEFAULT   ", "05", 1): Decimal("15.00"),
    ("DEFAULT   ", "06", 1): Decimal("15.00"),
    ("DEFAULT   ", "06", 2): Decimal("15.00"),
    ("DEFAULT   ", "07", 1): Decimal("0.00"),
    # ZEROAPR
    ("ZEROAPR   ", "01", 1): Decimal("0.00"),
    ("ZEROAPR   ", "01", 2): Decimal("0.00"),
    ("ZEROAPR   ", "01", 3): Decimal("0.00"),
    ("ZEROAPR   ", "01", 4): Decimal("0.00"),
    ("ZEROAPR   ", "02", 1): Decimal("0.00"),
    ("ZEROAPR   ", "02", 2): Decimal("0.00"),
    ("ZEROAPR   ", "02", 3): Decimal("0.00"),
    ("ZEROAPR   ", "03", 1): Decimal("0.00"),
    ("ZEROAPR   ", "03", 2): Decimal("0.00"),
    ("ZEROAPR   ", "03", 3): Decimal("0.00"),
    ("ZEROAPR   ", "04", 1): Decimal("0.00"),
    ("ZEROAPR   ", "04", 2): Decimal("0.00"),
    ("ZEROAPR   ", "04", 3): Decimal("0.00"),
    ("ZEROAPR   ", "05", 1): Decimal("0.00"),
    ("ZEROAPR   ", "06", 1): Decimal("0.00"),
    ("ZEROAPR   ", "06", 2): Decimal("0.00"),
    ("ZEROAPR   ", "07", 1): Decimal("0.00"),
}

# Group IDs (padded to 10 chars as stored in ACCT-GROUP-ID / DIS-ACCT-GROUP-ID)
_GROUP_A    = "A000000000"
_GROUP_ZERO = "ZEROAPR   "
_GROUP_PLAT = "PLATINUM  "   # not in DISCGRP → triggers DEFAULT fallback
_GROUP_BLANK= "          "   # blank → also triggers DEFAULT fallback


class AccountTag(NamedTuple):
    acct_id: int
    tags: frozenset[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _overpunch_sign(digit_str: str, negative: bool) -> str:
    """Replace the last character of *digit_str* with the overpunched sign."""
    pos = "{ABCDEFGHI"
    neg = "}JKLMNOPQR"
    last = int(digit_str[-1])
    ch = neg[last] if negative else pos[last]
    return digit_str[:-1] + ch


def _fmt_signed(value: Decimal, int_digits: int, frac_digits: int) -> str:
    """
    Format *value* as a DISPLAY signed field with overpunched trailing sign.
    int_digits + frac_digits = total display length.
    """
    negative = value < 0
    abs_val = abs(value)
    total = int_digits + frac_digits
    if frac_digits:
        s = f"{abs_val:.{frac_digits}f}".replace(".", "")
    else:
        s = str(int(abs_val))
    s = s.zfill(total)[-total:]  # left-truncate on overflow
    return _overpunch_sign(s, negative)


def _fmt_unsigned(value: int | str, width: int) -> str:
    """Format an unsigned integer into a zero-padded field of *width* chars."""
    return str(int(value)).zfill(width)[-width:]


# ---------------------------------------------------------------------------
# Record formatters (hand-rolled for speed and clarity)
# ---------------------------------------------------------------------------

def _acct_record(
    acct_id: int,
    group: str,
    curr_bal: Decimal,
    cyc_credit: Decimal,
    cyc_debit: Decimal,
    credit_limit: Decimal = Decimal("20000.00"),
    cash_limit: Decimal = Decimal("10000.00"),
) -> str:
    """Return a 300-char ACCOUNT-RECORD string."""
    r = (
        _fmt_unsigned(acct_id, 11)          # ACCT-ID
        + "Y"                               # ACCT-ACTIVE-STATUS
        + _fmt_signed(curr_bal, 10, 2)      # ACCT-CURR-BAL      S9(10)V99
        + _fmt_signed(credit_limit, 10, 2)  # ACCT-CREDIT-LIMIT  S9(10)V99
        + _fmt_signed(cash_limit, 10, 2)    # ACCT-CASH-CREDIT-LIMIT S9(10)V99
        + "2014-01-01"                      # ACCT-OPEN-DATE
        + "2030-01-01"                      # ACCT-EXPIRAION-DATE
        + "2030-01-01"                      # ACCT-REISSUE-DATE
        + _fmt_signed(cyc_credit, 10, 2)    # ACCT-CURR-CYC-CREDIT
        + _fmt_signed(cyc_debit, 10, 2)     # ACCT-CURR-CYC-DEBIT
        + " " * 10                          # ACCT-ADDR-ZIP
        + group[:10].ljust(10)             # ACCT-GROUP-ID
    )
    # FILLER PIC X(178)
    r += " " * 178
    assert len(r) == 300, f"ACCT record length {len(r)} != 300"
    return r


def _xref_record(card_num: str, cust_id: int, acct_id: int) -> str:
    """Return a 50-char CARD-XREF-RECORD string."""
    r = (
        card_num[:16].ljust(16)          # XREF-CARD-NUM  X(16)
        + _fmt_unsigned(cust_id, 9)      # XREF-CUST-ID   9(09)
        + _fmt_unsigned(acct_id, 11)     # XREF-ACCT-ID   9(11)
        + " " * 14                       # FILLER         X(14)
    )
    assert len(r) == 50, f"XREF record length {len(r)} != 50"
    return r


def _tcatbal_record(
    acct_id: int, type_cd: str, cat_cd: int, balance: Decimal
) -> str:
    """Return a 50-char TRAN-CAT-BAL-RECORD string."""
    r = (
        _fmt_unsigned(acct_id, 11)          # TRANCAT-ACCT-ID   9(11)
        + type_cd[:2].ljust(2)              # TRANCAT-TYPE-CD   X(02)
        + _fmt_unsigned(cat_cd, 4)          # TRANCAT-CD        9(04)
        + _fmt_signed(balance, 9, 2)        # TRAN-CAT-BAL      S9(09)V99
        + " " * 22                          # FILLER            X(22)
    )
    assert len(r) == 50, f"TCATBAL record length {len(r)} != 50"
    return r


def _discgrp_record(
    group: str, type_cd: str, cat_cd: int, rate: Decimal
) -> str:
    """Return a 50-char DIS-GROUP-RECORD string."""
    r = (
        group[:10].ljust(10)             # DIS-ACCT-GROUP-ID  X(10)
        + type_cd[:2].ljust(2)           # DIS-TRAN-TYPE-CD   X(02)
        + _fmt_unsigned(cat_cd, 4)       # DIS-TRAN-CAT-CD    9(04)
        + _fmt_signed(rate, 4, 2)        # DIS-INT-RATE       S9(04)V99
        + " " * 28                       # FILLER             X(28)
    )
    assert len(r) == 50, f"DISCGRP record length {len(r)} != 50"
    return r


# ---------------------------------------------------------------------------
# DISCGRP file builder
# ---------------------------------------------------------------------------

def _build_discgrp_lines() -> list[str]:
    """Return sorted DISCGRP lines for A000000000, DEFAULT, ZEROAPR."""
    lines: list[str] = []
    for (grp, typ, cat), rate in sorted(_VENDOR_RATES.items()):
        lines.append(_discgrp_record(grp, typ, cat, rate))
    # Sort by primary key: bytes 0-15 = group(10) + type(2) + cat(4)
    lines.sort()
    return lines


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate(accounts: int, seed: int, out_dir: str | os.PathLike) -> list[AccountTag]:
    """
    Generate test-data files for *accounts* accounts.

    Parameters
    ----------
    accounts : int
        Number of accounts to generate (must be ≥ 1).
    seed : int
        RNG seed for reproducibility.
    out_dir : path-like
        Directory into which files are written (created if necessary).

    Returns
    -------
    list of :class:`AccountTag`
        One entry per account, in account-ID order, with a frozenset of
        tag strings.
    """
    rng = random.Random(seed)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    acct_lines: list[str] = []
    xref_lines: list[str] = []
    tcatbal_lines: list[str] = []
    tags: list[AccountTag] = []

    for idx in range(accounts):
        acct_id = idx + 1              # 1-based, zero-padded to 11
        cust_id = acct_id              # 1:1 for simplicity
        card_num = f"{acct_id:016d}"   # 16-digit card number

        account_tags: set[str] = set()
        is_last = (idx == accounts - 1)

        # ── choose group ───────────────────────────────────────────────────
        if is_last:
            group = _GROUP_A
            account_tags.add("last")
        elif acct_id % 97 == 0:
            # Near-max balance every ~97th account
            group = _GROUP_A
        elif acct_id % 13 == 0:
            group = _GROUP_ZERO
            account_tags.add("zero_rate")
        elif acct_id % 17 == 0:
            group = _GROUP_PLAT
            account_tags.add("fallback")
        elif acct_id % 23 == 0:
            group = _GROUP_BLANK
            account_tags.add("fallback")
        else:
            group = _GROUP_A

        # ── choose ACCT-CURR-BAL ──────────────────────────────────────────
        if is_last:
            curr_bal = Decimal("1234.56")
        elif acct_id % 97 == 0:
            # Near max: +/-9,999,999,999.99
            sign = -1 if rng.random() < 0.5 else 1
            curr_bal = Decimal("9999999999.99") * sign
            account_tags.add("huge")
        elif acct_id % 11 == 0:
            curr_bal = Decimal("0.01")
            account_tags.add("cent")
        elif acct_id % 7 == 0:
            curr_bal = -Decimal(str(rng.randint(1, 99999999))) / 100
            account_tags.add("negative")
        elif acct_id % 5 == 0:
            curr_bal = -Decimal("0.01")
            account_tags.add("negative")
            account_tags.add("cent")
        else:
            curr_bal = Decimal(str(rng.randint(1, 99999999))) / 100

        # ── choose balance rows (TCATBALF) ────────────────────────────────
        if is_last:
            n_bal_rows = 3
        else:
            n_bal_rows = rng.randint(1, 5)

        chosen_keys = rng.sample(_DISCGRP_KEYS, min(n_bal_rows, len(_DISCGRP_KEYS)))

        for type_cd, cat_cd in chosen_keys:
            # Balance values: mix of negatives, zero, normal, edge cases
            r = rng.random()
            if r < 0.10:
                bal = -Decimal(str(rng.randint(1, 99999999))) / 100
            elif r < 0.15:
                bal = Decimal("0.00")
            elif r < 0.18:
                bal = Decimal("0.01")
            elif r < 0.20:
                bal = Decimal("999999999.99")  # near max S9(9)V99
            else:
                bal = Decimal(str(rng.randint(1, 9999999))) / 100

            tcatbal_lines.append(
                _tcatbal_record(acct_id, type_cd, cat_cd, bal)
            )

        # ── choose ACCT-CURR-CYC-CREDIT and ACCT-CURR-CYC-DEBIT ──────────
        cyc_credit = Decimal(rng.randint(1, 300000)) / 100
        cyc_debit  = Decimal(rng.randint(1, 300000)) / 100

        # ── emit account / xref records ───────────────────────────────────
        acct_lines.append(_acct_record(acct_id, group, curr_bal, cyc_credit, cyc_debit))
        xref_lines.append(_xref_record(card_num, cust_id, acct_id))
        tags.append(AccountTag(acct_id=acct_id, tags=frozenset(account_tags)))

    # ── sort every file by primary key ────────────────────────────────────
    acct_lines.sort()                     # key = ACCT-ID bytes 0-10
    xref_lines.sort()                     # key = XREF-CARD-NUM bytes 0-15
    tcatbal_lines.sort()                  # key = TRANCAT-ACCT-ID+TYPE+CD bytes 0-16
    discgrp_lines = _build_discgrp_lines()

    # ── write files (LF line endings) ─────────────────────────────────────
    def _write(name: str, lines: list[str]) -> None:
        p = out_path / name
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            for line in lines:
                fh.write(line + "\n")

    _write("ACCTFILE.txt", acct_lines)
    _write("XREFFILE.txt", xref_lines)
    _write("TCATBALF.txt", tcatbal_lines)
    _write("DISCGRP.txt", discgrp_lines)

    # PARM file – no newline
    (out_path / "PARM").write_text(PARM_DATE, encoding="utf-8")

    return tags
