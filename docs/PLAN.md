# Parity — Repository Layout and Module Plan

Demo target: `vendor/carddemo/cbl/CBACT04C.cbl` (monthly interest batch).  
Goal: prove a COBOL-to-Java migration is correct by running both programs on
identical generated inputs and comparing every output field.

---

## Directory tree

```
Parity/
├── .gitattributes                   # *.sh text eol=lf
├── docs/
│   ├── FACTS.md                     # verified facts (this repo)
│   └── PLAN.md                      # this file
│
├── Dockerfile                       # debian:bookworm-slim, all tools (repo root)
│
├── harness/                         # COBOL glue programs
│   ├── DRIVER.cbl                   # plays JCL: reads env vars, calls CBACT04C
│   ├── CEE3ABD.cbl                  # off-mainframe stub for abend service
│   ├── LOADER_TCATBALF.cbl          # line-seq text → TCATBALF indexed
│   ├── LOADER_XREFFILE.cbl          # line-seq text → XREFFILE indexed (+ alt key)
│   ├── LOADER_ACCTFILE.cbl          # line-seq text → ACCTFILE indexed
│   ├── LOADER_DISCGRP.cbl           # line-seq text → DISCGRP indexed
│   └── UNLOADER_ACCTFILE.cbl        # ACCTFILE indexed → text (post-run)
│
├── parity/                          # Python package (pip-installable)
│   ├── __init__.py
│   ├── copybook.py                  # copybook PIC decoder / encoder
│   ├── datagen.py                   # test-data generator (non-zero balances)
│   ├── runner.py                    # orchestrates one parity run end-to-end
│   ├── comparer.py                  # field-by-field diff of COBOL vs Java output
│   ├── mutation.py                  # planted-bug (mutation) runner
│   └── sysmap.py                    # JCL + COBOL system-map parser
│
├── bob_outputs/                     # Java rewrite of CBACT04C (added at task B5)
│   └── Cbact04c.java                # single class, compiled at image build time
│
└── ui/
    ├── app.py                       # FastAPI application
    ├── static/
    │   ├── index.html               # vanilla JS single-page UI
    │   └── main.js
    └── requirements.txt
```

---

## Module descriptions

### `Dockerfile` (repo root)

Builds the single container image:

1. Install `gnucobol3`, `openjdk-17-jdk-headless`, `python3`, `python3-venv`.
2. Copy and compile all harness COBOL programs (`cobc -x` for executables,
   `cobc -m -fsign=EBCDIC` for `CBACT04C.cbl` and `CEE3ABD.cbl`).
3. Install the `parity` Python package and FastAPI dependencies.
4. `CMD` launches the FastAPI server.

The `javac bob_outputs/Cbact04c.java` step is added to the Dockerfile only once
`bob_outputs/Cbact04c.java` exists (task B5). Until then the image builds without it.

---

### `harness/DRIVER.cbl`

Compiled as a standalone executable (`cobc -x`).  
Reads `COBOL_PROGRAM` and `COBOL_PARM` from the environment, builds the
`EXTERNAL-PARMS` linkage block (2-byte `PARM-LENGTH` S9(4) COMP + 10-byte text),
then `CALL`s the named module.  
File DD paths are pre-set by the caller via `DD_<name>` environment variables.

---

### `harness/CEE3ABD.cbl`

Compiled as a loadable module (`cobc -m`).  
Accepts `ABCODE` and `TIMING`, DISPLAYs the code, then `STOP RUN RETURNING 16`.

---

### `harness/LOADER_*.cbl` and `harness/UNLOADER_ACCTFILE.cbl`

One loader per indexed input file.  Each:
- Opens a line-sequential input text file (path from a DD env var).
- Reads records one at a time and WRITEs into the target indexed file.
- Records must already be in ascending primary-key order.

`UNLOADER_ACCTFILE.cbl` reads the indexed `ACCTFILE` sequentially and writes
fixed-width text lines for the comparer.

---

### `parity/copybook.py`

Parses the five copybooks used by CBACT04C and provides:

- `decode(record_bytes, layout)` → `dict` of field name → Python value  
  (handles `PIC 9`, `PIC X`, `PIC S9V99`, overpunched trailing signs).
- `encode(fields, layout)` → `bytes` (for data generation).

No external COBOL-parsing library; the relevant layouts are small enough to
describe as Python data structures derived directly from the copybooks.

---

### `parity/datagen.py`

Generates a self-consistent set of test data files with non-zero balances:

- Produces `ACCTFILE`, `XREFFILE`, `TCATBALF`, `DISCGRP` records covering:
  - Multiple accounts with varying group IDs.
  - At least one account whose group is missing in `DISCGRP` (triggers DEFAULT fallback).
  - At least one account that will be the "last" record (exercises the known skip bug).
- Writes all four text files (CRLF-terminated, fixed-width, overpunched signs where
  required) ready for the loaders.

---

### `parity/runner.py`

Orchestrates a single end-to-end parity run:

1. Call `datagen` (or accept pre-existing data files).
2. Run the four COBOL loaders to build indexed files.
3. Run `DRIVER` → `CBACT04C` (COBOL path); set `DD_*` and `COBOL_*` env vars;
   capture stdout/stderr and return code.
4. Run `UNLOADER_ACCTFILE` to export the COBOL-updated account file.
5. Run Java: `java -cp <classdir> Cbact04c <in_dir> <out_dir> <parm>`
   where `<in_dir>` contains `TCATBALF.txt`, `XREFFILE.txt`, `ACCTFILE.txt`,
   `DISCGRP.txt` (the same text files the loaders consumed), and `<out_dir>`
   receives `ACCTFILE.txt` and `TRANSACT.dat`; capture stdout/stderr and return code.
6. Return raw outputs and file paths to the caller.

COBOL runs in a per-run temp directory. Java uses plain file arguments — no `DD_*`
env vars.

---

### `parity/comparer.py`

Field-by-field comparison of the two programs' outputs:

**`TRANSACT` records** — keyed by `TRAN-ID` (16 chars, same value from both sides
since `PARM-DATE` and the counter are deterministic): compare **every field** of
every record. Exception: `TRAN-ORIG-TS` and `TRAN-PROC-TS` are format-validated
only (`YYYY-MM-DD-HH.MM.SS.hh0000`, 26 chars) — their literal values are not compared.

**`ACCTFILE` records** — keyed by `ACCT-ID`: compare **every field** of every record
decoded with the `CVACT01Y` layout (300 bytes). This includes `ACCT-CURR-BAL`,
`ACCT-CURR-CYC-CREDIT`, `ACCT-CURR-CYC-DEBIT`, and all other fields.

**stdout** — not compared (informational only).

Returns a structured diff report (list of `FieldMismatch` objects with record key,
field name, COBOL value, Java value) and a boolean `passed`.

---

### `parity/mutation.py`

Planted-bug runner for demo purposes:

- Accepts a list of `Mutation` descriptors (e.g., change `/1200` to `/1000` in
  interest formula; remove DEFAULT fallback; add ROUNDED).
- For each mutation: patches the Java source in a temp copy, recompiles, runs the
  full parity check, and records whether the comparer correctly detected the
  divergence.
- Returns a report showing which mutations were caught and which were missed.

---

### `parity/sysmap.py`

Lightweight parser for JCL and COBOL source:

- Reads a JCL file and extracts: job steps, PGM names, DD-name → DSN mappings,
  and PARM values.
- Reads a COBOL source file and extracts: program ID, SELECT/ASSIGN pairs,
  copybook COPY statements, paragraph names.
- Produces a system-map JSON document suitable for display in the web UI's
  "System Map" tab.

---

### `bob_outputs/Cbact04c.java`

A single Java class that reproduces the exact behaviour of `CBACT04C.cbl`,
including:

- The last-account skip bug.
- Truncating interest (no rounding).
- DEFAULT group fallback.
- Empty fee method.
- Timestamp format matching (wall clock, not fixed value).

Takes three positional arguments at runtime:
```
java -cp <classdir> Cbact04c <in_dir> <out_dir> <parm>
```
- `<in_dir>`: directory containing `TCATBALF.txt`, `XREFFILE.txt`, `ACCTFILE.txt`,
  `DISCGRP.txt` (plain text, same format produced by `datagen.py`).
- `<out_dir>`: directory where `ACCTFILE.txt` and `TRANSACT.dat` are written.
- `<parm>`: the 10-character PARM string (e.g. `2022071800`).

Does **not** use `DD_*` env vars. Compiled at image build time with `javac`.

---

### `ui/app.py`

FastAPI application with four endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/run` | POST | Triggers a parity run; returns run ID. |
| `/run/{id}` | GET | Returns status, diff report, and stdout for a completed run. |
| `/sysmap` | GET | Returns the parsed system-map JSON. |
| `/mutations` | POST | Triggers the mutation runner; returns per-mutation results. |

Runs are executed in a thread pool (max 1 concurrent, queued otherwise) to avoid
file-path collisions.

---

### `ui/static/index.html` + `main.js`

Vanilla JS single-page UI with three tabs:

1. **Run** — "Generate data & run parity" button; shows pass/fail badge and field
   diff table side-by-side (COBOL value | Java value | status).
2. **Mutations** — table of planted bugs with caught/missed status.
3. **System Map** — rendered view of the JCL/COBOL map (programs, files, DD names).

No build step; no external JS dependencies beyond the browser's fetch API.

---

## Build / compile order (inside Dockerfile)

```
1. cobc -m -fsign=EBCDIC -I vendor/carddemo/cpy  harness/CEE3ABD.cbl
2. cobc -m -fsign=EBCDIC -I vendor/carddemo/cpy  vendor/carddemo/cbl/CBACT04C.cbl
3. cobc -x  harness/DRIVER.cbl
4. cobc -x  harness/LOADER_TCATBALF.cbl
5. cobc -x  harness/LOADER_XREFFILE.cbl
6. cobc -x  harness/LOADER_ACCTFILE.cbl
7. cobc -x  harness/LOADER_DISCGRP.cbl
8. cobc -x  harness/UNLOADER_ACCTFILE.cbl
# Step 9 is added only once bob_outputs/Cbact04c.java exists (task B5):
9. javac -d bob_outputs/classes  bob_outputs/Cbact04c.java
```

All COBOL object files (`.so` / `.dylib`) land on `COB_LIBRARY_PATH` so the
driver's dynamic CALL can find them at runtime.
