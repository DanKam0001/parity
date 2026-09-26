"""
parity/copybook.py
==================
Parse COBOL copybook 01 records into field layouts, then decode/encode
fixed-width DISPLAY records.

Supported PIC types
-------------------
  PIC 9(n)        – unsigned decimal, n digits
  PIC X(n)        – alphanumeric, n chars
  PIC S9(n)V99    – signed decimal, n integer + 2 fractional digits,
                    trailing overpunched sign
  PIC S9(n)Vmm    – generalised form of the above

Overpunched trailing sign (EBCDIC / COBOL DISPLAY)
---------------------------------------------------
  Positive last digit  0-9  →  { A B C D E F G H I
  Negative last digit  0-9  →  } J K L M N O P Q R
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

# ---------------------------------------------------------------------------
# Overpunch tables
# ---------------------------------------------------------------------------
_POS_OVERPUNCH = "{ABCDEFGHI"   # index 0-9 → positive last digit
_NEG_OVERPUNCH = "}JKLMNOPQR"   # index 0-9 → negative last digit

# Reverse maps: overpunch char → (digit, sign)
_OVERPUNCH_TO_DIGIT: dict[str, tuple[str, int]] = {}
for _d, _ch in enumerate(_POS_OVERPUNCH):
    _OVERPUNCH_TO_DIGIT[_ch] = (str(_d), +1)
for _d, _ch in enumerate(_NEG_OVERPUNCH):
    _OVERPUNCH_TO_DIGIT[_ch] = (str(_d), -1)


# ---------------------------------------------------------------------------
# Field descriptor
# ---------------------------------------------------------------------------
class Field:
    """One elementary field in a copybook layout."""

    __slots__ = ("name", "offset", "length", "pic_type", "signed",
                 "decimal_scale", "total_digits")

    def __init__(
        self,
        name: str,
        offset: int,
        length: int,       # display length in bytes
        pic_type: str,     # 'X' or '9'
        signed: bool,
        decimal_scale: int,  # digits after implicit decimal point
        total_digits: int,   # total digit count (integer + fractional)
    ) -> None:
        self.name = name
        self.offset = offset
        self.length = length
        self.pic_type = pic_type
        self.signed = signed
        self.decimal_scale = decimal_scale
        self.total_digits = total_digits

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"Field({self.name!r}, off={self.offset}, len={self.length}, "
            f"type={self.pic_type!r}, signed={self.signed}, "
            f"scale={self.decimal_scale})"
        )


# ---------------------------------------------------------------------------
# Copybook parser
# ---------------------------------------------------------------------------
_PIC_RE = re.compile(
    r"""
    PIC\s+
    (?P<sign>S)?                      # optional sign
    9\((?P<int_digits>\d+)\)          # 9(n)  integer digits
    (?:V9\((?P<frac_parens>\d+)\)     # V9(m) fractional (parens form)
    |  V(?P<frac_9s>9+))?             # V99   fractional (repeated-9 form)
    """,
    re.VERBOSE | re.IGNORECASE,
)

_PIC_X_RE = re.compile(
    r"PIC\s+X\((?P<n>\d+)\)",
    re.IGNORECASE,
)

_PIC_X1_RE = re.compile(
    r"PIC\s+X(?!\()",        # PIC X  (no parens → single char)
    re.IGNORECASE,
)

_PIC_9_PLAIN_RE = re.compile(
    r"PIC\s+9\((?P<n>\d+)\)(?!\s*V)",
    re.IGNORECASE,
)

_LEVEL_RE = re.compile(
    r"^\s*(?P<level>\d{2})\s+(?P<name>\S+)\s+",
    re.MULTILINE,
)


def parse_copybook(source: str) -> list[Field]:
    """
    Parse the 01-level record from *source* (raw copybook text).

    Returns a list of :class:`Field` objects for every leaf (elementary)
    field, in declaration order, with byte offsets from the start of the
    record.  FILLER fields and 88-level conditions are skipped.
    REDEFINES clauses cause the entire line to be skipped so the first
    occurrence wins (matching typical COBOL REDEFINES semantics for
    sequential records).
    """
    fields: list[Field] = []
    offset = 0

    for line in source.splitlines():
        # Skip comment / blank lines
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue

        m_level = _LEVEL_RE.match(line)
        if not m_level:
            continue

        level = int(m_level.group("level"))
        name = m_level.group("name").rstrip(".")

        # Skip group levels (01, 05, 10 … without PIC), 88-levels, FILLER,
        # and REDEFINES
        if level == 88:
            continue
        if "REDEFINES" in line.upper():
            continue
        if "PIC" not in line.upper():
            # group level – no data storage
            continue
        if name.upper() == "FILLER" or name.upper().startswith("FILLER"):
            # Include FILLER as a space-padded X field so encode() reproduces it
            length = _pic_length(line)
            if length > 0:
                fields.append(
                    Field(
                        name=f"FILLER@{offset}",
                        offset=offset,
                        length=length,
                        pic_type="X",
                        signed=False,
                        decimal_scale=0,
                        total_digits=0,
                    )
                )
                offset += length
            continue

        length, pic_type, signed, scale, total_digits = _parse_pic(line)
        if length == 0:
            continue

        fields.append(
            Field(
                name=name,
                offset=offset,
                length=length,
                pic_type=pic_type,
                signed=signed,
                decimal_scale=scale,
                total_digits=total_digits,
            )
        )
        offset += length

    return fields


def _pic_length(line: str) -> int:
    """Return display length of a PIC clause (including FILLER)."""
    length, *_ = _parse_pic(line)
    return length


def _parse_pic(line: str) -> tuple[int, str, bool, int, int]:
    """
    Return (length, pic_type, signed, decimal_scale, total_digits).
    """
    upper = line.upper()

    # --- S9(n)V... forms ---
    m = _PIC_RE.search(upper)
    if m:
        signed = bool(m.group("sign"))
        int_digits = int(m.group("int_digits"))
        if m.group("frac_parens"):
            frac_digits = int(m.group("frac_parens"))
        elif m.group("frac_9s"):
            frac_digits = len(m.group("frac_9s"))
        else:
            frac_digits = 0
        total = int_digits + frac_digits
        return total, "9", signed, frac_digits, total

    # --- plain 9(n) ---
    m = _PIC_9_PLAIN_RE.search(upper)
    if m:
        n = int(m.group("n"))
        return n, "9", False, 0, n

    # --- X(n) ---
    m = _PIC_X_RE.search(upper)
    if m:
        n = int(m.group("n"))
        return n, "X", False, 0, 0

    # --- X (single char) ---
    if _PIC_X1_RE.search(upper):
        return 1, "X", False, 0, 0

    return 0, "?", False, 0, 0


# ---------------------------------------------------------------------------
# Pre-built layouts (derived from the five copybooks)
# ---------------------------------------------------------------------------

def _load(path: str) -> list[Field]:
    """Load and parse a copybook file."""
    import pathlib
    text = pathlib.Path(path).read_text(encoding="utf-8")
    return parse_copybook(text)


def _cpy_path(name: str) -> str:
    """Resolve a copybook name to its path relative to the repo root."""
    import pathlib
    base = pathlib.Path(__file__).parent.parent / "vendor" / "carddemo" / "cpy"
    # try exact name, then with .cpy extension
    for candidate in (name, name + ".cpy"):
        p = base / candidate
        if p.exists():
            return str(p)
    raise FileNotFoundError(f"Copybook not found: {name}")


def get_layout(name: str) -> list[Field]:
    """
    Return the parsed field list for a copybook name, e.g. ``'CVACT01Y'``.
    Results are cached after the first call.
    """
    if name not in _LAYOUT_CACHE:
        _LAYOUT_CACHE[name] = _load(_cpy_path(name))
    return _LAYOUT_CACHE[name]


_LAYOUT_CACHE: dict[str, list[Field]] = {}

# Convenience names matching the five copybooks used by CBACT04C
CVTRA01Y = property(lambda _: get_layout("CVTRA01Y"))
CVACT01Y = property(lambda _: get_layout("CVACT01Y"))
CVACT03Y = property(lambda _: get_layout("CVACT03Y"))
CVTRA02Y = property(lambda _: get_layout("CVTRA02Y"))
CVTRA05Y = property(lambda _: get_layout("CVTRA05Y"))


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------

def decode(record: str | bytes, layout: list[Field]) -> dict[str, Any]:
    """
    Decode a fixed-width DISPLAY record according to *layout*.

    Parameters
    ----------
    record:
        The raw record as a ``str`` or ``bytes`` (ASCII / latin-1 safe).
        Lines read from acctdata.txt have had CR stripped; they may be
        shorter than the full record length (trailing spaces omitted by the
        unloader).  The decoder pads on the right with spaces as needed.
    layout:
        List of :class:`Field` objects, e.g. from :func:`get_layout`.

    Returns
    -------
    dict mapping field name → Python value:
      - ``str`` for PIC X fields
      - ``Decimal`` for numeric fields (preserves scale)
    """
    if isinstance(record, bytes):
        record = record.decode("latin-1")

    result: dict[str, Any] = {}

    for fld in layout:
        end = fld.offset + fld.length
        # Pad short records with spaces (trailing-space stripping by unloader)
        if len(record) < end:
            chunk = record[fld.offset:].ljust(fld.length)
        else:
            chunk = record[fld.offset:end]

        if fld.pic_type == "X":
            result[fld.name] = chunk
        else:
            # Numeric DISPLAY
            if fld.signed:
                value = _decode_signed(chunk, fld.decimal_scale)
            else:
                value = _decode_unsigned(chunk, fld.decimal_scale)
            result[fld.name] = value

    return result


def _decode_unsigned(chunk: str, scale: int) -> Decimal:
    digits = chunk  # plain digits, no overpunch
    if scale == 0:
        return Decimal(digits)
    integer_part = digits[:-scale] or "0"
    frac_part = digits[-scale:]
    return Decimal(f"{integer_part}.{frac_part}")


def _decode_signed(chunk: str, scale: int) -> Decimal:
    """Decode a DISPLAY signed field with trailing overpunched sign."""
    last = chunk[-1]
    rest = chunk[:-1]

    if last in _OVERPUNCH_TO_DIGIT:
        last_digit, sign = _OVERPUNCH_TO_DIGIT[last]
    elif last.isdigit():
        # Unsigned source written without overpunch (positive)
        last_digit, sign = last, +1
    else:
        # Unexpected; treat as positive zero
        last_digit, sign = "0", +1

    digits = rest + last_digit

    if scale == 0:
        value = Decimal(digits)
    else:
        integer_part = digits[:-scale] or "0"
        frac_part = digits[-scale:]
        value = Decimal(f"{integer_part}.{frac_part}")

    if sign == -1:
        value = -value

    return value


# ---------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------

def encode(fields: dict[str, Any], layout: list[Field]) -> str:
    """
    Encode a dict of field values back into a fixed-width DISPLAY string.

    Rules
    -----
    * Numeric values are truncated (never rounded) to fit ``total_digits``
      and ``decimal_scale``, matching COBOL MOVE semantics.
    * PIC X fields are left-justified and space-padded (or right-truncated).
    * Signed numeric fields use a trailing overpunched sign character.
    * The returned string has exactly ``sum(f.length for f in layout)`` chars.
    """
    parts: list[str] = []

    for fld in layout:
        raw = fields.get(fld.name, None)

        if fld.pic_type == "X":
            if raw is None:
                raw = ""
            s = str(raw)
            # Left-justify, space-pad or right-truncate
            parts.append(s[:fld.length].ljust(fld.length))
        else:
            # Numeric
            parts.append(_encode_numeric(raw, fld))

    return "".join(parts)


def _encode_numeric(value: Any, fld: Field) -> str:
    """Encode a numeric value into a DISPLAY field."""
    if value is None:
        value = Decimal(0)

    d = Decimal(str(value))
    negative = d < 0
    d = abs(d)

    # Truncate to decimal_scale (COBOL MOVE truncates, never rounds)
    if fld.decimal_scale > 0:
        # Shift right by scale, truncate to integer, shift back
        factor = Decimal(10) ** fld.decimal_scale
        d = (d * factor).to_integral_value(rounding="ROUND_FLOOR") / factor
    else:
        d = d.to_integral_value(rounding="ROUND_FLOOR")

    # Convert to a string of exactly total_digits digits (integer + frac)
    if fld.decimal_scale > 0:
        # Format with fixed decimal places, then remove the decimal point
        fmt = f"{{:.{fld.decimal_scale}f}}"
        s = fmt.format(d).replace(".", "")
    else:
        s = str(int(d))

    # Right-justify in total_digits, truncate on the left if overflow
    s = s.zfill(fld.total_digits)[-fld.total_digits :]   # left-truncate overflow

    if fld.signed:
        # Replace last character with overpunch
        last_digit = int(s[-1])
        if negative:
            overpunch = _NEG_OVERPUNCH[last_digit]
        else:
            overpunch = _POS_OVERPUNCH[last_digit]
        s = s[:-1] + overpunch

    return s
