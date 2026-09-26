#!/usr/bin/env bash
# harness/run_legacy.sh <io_dir>
#
# Orchestrates one COBOL parity run:
#   1. Load <io_dir>/in/{TCATBALF,XREFFILE,ACCTFILE,DISCGRP}.txt
#      into temporary BDB indexed files.
#   2. Run DRIVER → CBACT04C with the PARM from <io_dir>/in/PARM.
#   3. Unload the updated ACCTFILE to <io_dir>/out/ACCTFILE.txt.
#   4. Write <io_dir>/out/SYSOUT.txt (combined stdout/stderr) and
#      <io_dir>/out/RC (return code as a plain integer).
#
# Environment expected:
#   PATH must include /build (where cobc placed the executables).
#   COB_LIBRARY_PATH must include /build (for dynamic .so lookup).
#
# Usage:
#   harness/run_legacy.sh /runs/run-001
set -euo pipefail

IO_DIR="${1:?Usage: run_legacy.sh <io_dir>}"
IN_DIR="${IO_DIR}/in"
OUT_DIR="${IO_DIR}/out"

# ---------- sanity checks -------------------------------------------
for f in TCATBALF XREFFILE ACCTFILE DISCGRP; do
    [[ -f "${IN_DIR}/${f}.txt" ]] || {
        echo "ERROR: missing ${IN_DIR}/${f}.txt" >&2; exit 1
    }
done
[[ -f "${IN_DIR}/PARM" ]] || {
    echo "ERROR: missing ${IN_DIR}/PARM" >&2; exit 1
}

mkdir -p "${OUT_DIR}"

# ---------- temp directory for indexed files ------------------------
TMPDIR_IDX="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_IDX}"' EXIT

# ---------- step 1: load text files into BDB indexed files ----------

# TCATBALF – primary key bytes 1-17
export DD_TCATIN="${IN_DIR}/TCATBALF.txt"
export DD_TCATBALF="${TMPDIR_IDX}/TCATBALF"
LOADER_TCATBALF

# XREFFILE – primary key bytes 1-16, alternate key bytes 26-36
export DD_XREFIN="${IN_DIR}/XREFFILE.txt"
export DD_XREFFILE="${TMPDIR_IDX}/XREFFILE"
LOADER_XREFFILE

# ACCTFILE – primary key bytes 1-11
export DD_ACCTIN="${IN_DIR}/ACCTFILE.txt"
export DD_ACCTFILE="${TMPDIR_IDX}/ACCTFILE"
LOADER_ACCTFILE

# DISCGRP – primary key bytes 1-16
export DD_DISCIN="${IN_DIR}/DISCGRP.txt"
export DD_DISCGRP="${TMPDIR_IDX}/DISCGRP"
LOADER_DISCGRP

# ---------- step 2: run DRIVER → CBACT04C ---------------------------
PARM="$(cat "${IN_DIR}/PARM")"

export COBOL_PROGRAM="CBACT04C"
export COBOL_PARM="${PARM}"
export DD_TRANSACT="${OUT_DIR}/TRANSACT.dat"

# DD vars for indexed files already set above (ACCTFILE is I-O).
SYSOUT_FILE="${OUT_DIR}/SYSOUT.txt"
RC=0
DRIVER >"${SYSOUT_FILE}" 2>&1 || RC=$?

echo "${RC}" >"${OUT_DIR}/RC"

# ---------- step 3: unload updated ACCTFILE -------------------------
export DD_ACCTOUT="${OUT_DIR}/ACCTFILE.txt"
# DD_ACCTFILE is still set to the temp indexed file.
UNLOADER_ACCTFILE >>"${SYSOUT_FILE}" 2>&1

echo "run_legacy.sh: done (RC=${RC})"
exit "${RC}"
