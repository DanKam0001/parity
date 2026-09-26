# Parity — Verified Facts about CBACT04C and the Sandbox

These facts were extracted directly from source files in this repo and are the
authoritative reference for all implementation work.

---

## 1. Sandbox

- Base image: `debian:bookworm-slim`.
- APT packages required: `gnucobol3` (GnuCOBOL 3.1.2, built with BDB for indexed
  file support), `openjdk-17-jdk-headless`, `python3`, `python3-venv`.
- Everything runs inside **one container**: the FastAPI web app, the COBOL
  executable, and the Java rewrite all share a single filesystem. There is no
  Docker-in-Docker.

---

## 2. Compiling CBACT04C (original, unmodified)

```
cobc -m -fsign=EBCDIC -I vendor/carddemo/cpy CBACT04C.cbl
```

- `-m` (module, not `-x` executable) is required because the program has
  `PROCEDURE DIVISION USING EXTERNAL-PARMS` — it is a CALLable module, not a
  self-contained main program.
- `-fsign=EBCDIC` preserves the overpunched sign convention used in the data files.
- `-I vendor/carddemo/cpy` makes all five copybooks findable.

---

## 3. Driver COBOL program (plays the role of JCL)

A small driver program (`DRIVER.cbl`) is compiled as an executable (`cobc -x`).
It:

1. Reads the program name from env var `COBOL_PROGRAM` and the PARM string from
   `COBOL_PARM`.
2. Builds the `EXTERNAL-PARMS` linkage block in working storage:
   - `PARM-LENGTH  PIC S9(04) COMP` — set to the byte length of the PARM string.
   - `PARM-DATE    PIC X(10)` — the PARM text itself (padded or truncated to 10).
3. `CALL`s the compiled CBACT04C module, passing `EXTERNAL-PARMS` by reference.

PARM value from `vendor/carddemo/jcl/INTCALC.jcl` line 22:
```
PARM='2022071800'
```
So `PARM-LENGTH = 10` and `PARM-DATE = '2022071800'`.

---

## 4. CEE3ABD stub

`CEE3ABD` (IBM Language Environment abend service) does not exist off-mainframe.
A stub module (`CEE3ABD.cbl`) compiled with `cobc -m` satisfies the CALL:

```cobol
PROCEDURE DIVISION USING ABCODE, TIMING.
    DISPLAY 'CEE3ABD called, abend code: ' ABCODE
    STOP RUN RETURNING 16.
```

---

## 5. DD-name to file-path mapping

The driver sets environment variables of the form `DD_<name>=<path>`. GnuCOBOL
resolves `ASSIGN TO <name>` by checking `DD_<name>` at runtime.

| DD name    | Org       | Record length | Key position (1-based) | Access mode        | Mode opened |
|------------|-----------|---------------|-------------------------|--------------------|-------------|
| `TCATBALF` | INDEXED   | 50            | bytes 1–17 (`FD-TRAN-CAT-KEY`: 11+2+4) | SEQUENTIAL | INPUT |
| `XREFFILE` | INDEXED   | 50            | primary: bytes 1–16 (`FD-XREF-CARD-NUM`); alternate: bytes 26–36 (`FD-XREF-ACCT-ID`, 9(11)) | RANDOM (by alternate key) | INPUT |
| `ACCTFILE` | INDEXED   | 300           | bytes 1–11 (`FD-ACCT-ID`, 9(11)) | RANDOM | I-O (REWRITE) |
| `DISCGRP`  | INDEXED   | 50            | bytes 1–16 (`FD-DISCGRP-KEY`: 10+2+4) | RANDOM | INPUT |
| `TRANSACT` | SEQUENTIAL | 350           | n/a | SEQUENTIAL | OUTPUT (fixed, no newlines) |

---

## 6. Indexed-file loader and unloader programs

Because GnuCOBOL's BDB indexed files are binary, plain text data must be loaded
before the run and unloaded after:

- **Loaders** (one per indexed input file): small COBOL programs (`cobc -x`) that
  read a line-sequential text file and WRITE each record into an indexed file.
  Records must be fed in ascending primary-key order (BDB requirement for sequential
  loading).
- **Unloader** (for `ACCTFILE` only): reads the indexed file sequentially and
  writes one text line per record, so the Java comparer can inspect the updated
  balances.

---

## 7. Source data files and encoding

Files in `vendor/carddemo/data/*.txt`:

- Line endings: **CRLF**.
- Fields: fixed-width; numeric DISPLAY fields use a **trailing overpunched sign**:
  - `{ABCDEFGHI` = positive digits `0–9` (zone nibble `C`).
  - `}JKLMNOPQR` = negative digits `0–9` (zone nibble `D`).
- `cardxref.txt` records are **36 characters** wide; the indexed file (`XREFFILE`)
  requires 50-byte records — pad with 14 spaces on load.
- **`acctdata.txt` contains real, non-zero balances** (e.g. `00000001940{` = +194.00).
  It is `tcatbal.txt` whose `TRAN-CAT-BAL` fields are all zero (every record ends
  `0000000000{`). Meaningful parity tests require generated test data with non-zero
  `TRAN-CAT-BAL` values.

---

## 8. Copybook summary

| Copybook   | Record name          | File / use             | Length |
|------------|----------------------|------------------------|--------|
| `CVTRA01Y` | `TRAN-CAT-BAL-RECORD`| `TCATBALF` input       | 50     |
| `CVACT01Y` | `ACCOUNT-RECORD`     | `ACCTFILE` I-O         | 300    |
| `CVACT03Y` | `CARD-XREF-RECORD`   | `XREFFILE` input       | 50     |
| `CVTRA02Y` | `DIS-GROUP-RECORD`   | `DISCGRP` input        | 50     |
| `CVTRA05Y` | `TRAN-RECORD`        | `TRANSACT` output      | 350    |

---

## 9. Program behaviour (CBACT04C logic)

### Interest calculation
```
WS-MONTHLY-INT = (TRAN-CAT-BAL * DIS-INT-RATE) / 1200
```
- Computed with `COMPUTE` — **no `ROUNDED`** clause — so the result is truncated
  (not rounded) to 2 decimal places.
- `DIS-INT-RATE` is `PIC S9(04)V99` (e.g., 18.00 = annual 18%).

### Missing rate group (DEFAULT fallback)
- `1200-GET-INTEREST-RATE` reads `DISCGRP` by the account's group + type + category.
- File status `23` (record not found) is treated as non-fatal; the program moves
  `'DEFAULT'` into `FD-DIS-ACCT-GROUP-ID` and retries via `1200-A-GET-DEFAULT-INT-RATE`.

### Empty fee stub
- `1400-COMPUTE-FEES` contains only `EXIT` — it is a no-op placeholder.

### Last-account bug (known off-by-one)
- The main loop is `PERFORM UNTIL END-OF-FILE = 'Y'` with an inner `IF END-OF-FILE = 'N'`.
- When EOF is reached, the outer `ELSE` branch calls `1050-UPDATE-ACCOUNT`, but by
  then `END-OF-FILE` is already `'Y'`, so the `UNTIL` condition is met and the
  `PERFORM` terminates **before** the `ELSE` body executes.
- **Effect**: the very last account read never has its interest posted (no REWRITE).
  This is a faithfully replicated bug — the Java rewrite must reproduce it.

### Timestamps
- `TRAN-ORIG-TS` and `TRAN-PROC-TS` are both set from `FUNCTION CURRENT-DATE` at
  write time; they reflect the real clock.
- During comparison: **validate the format only** — do **not** compare the literal
  value.
- Format: `YYYY-MM-DD-HH.MM.SS.hh0000` (26 characters), where `hh` is 2-digit
  hundredths and the trailing `0000` is always literal.
  Example: `2026-09-24-14.19.24.750000`.

### Transaction ID construction
```cobol
STRING PARM-DATE, WS-TRANID-SUFFIX DELIMITED BY SIZE INTO TRAN-ID
```
`PARM-DATE = '2022071800'` (10 chars) + `WS-TRANID-SUFFIX` zero-filled 6-digit
counter → 16-char `TRAN-ID`.

---

## 10. Java rewrite compilation

- Java source lives in `bob_outputs/`.
- Compiled at **Docker image build time** with `javac`.
- **Never** use `java File.java` (source-launch) at run time.
- Measured on 0.1 CPU: source-launch ≈ 11.7 s; precompiled ≈ 1.5 s.

---

## 11. Windows / cross-platform traps

- All `.sh` files **must** use LF line endings.
  Add to `.gitattributes`:
  ```
  *.sh text eol=lf
  ```
- All Python file I/O must specify `encoding="utf-8"` explicitly.
