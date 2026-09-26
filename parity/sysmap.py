"""
parity/sysmap.py
Parse CardDemo JCL + COBOL sources and produce a system map.

Usage:
    python3 -m parity.sysmap          # prints stats, writes bob_outputs/sysmap.json
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent.parent
_JCL_DIR = _ROOT / "vendor" / "carddemo" / "jcl"
_CBL_DIR = _ROOT / "vendor" / "carddemo" / "cbl"
_OUT_DIR = _ROOT / "bob_outputs"

# ---------------------------------------------------------------------------
# JCL parser
# ---------------------------------------------------------------------------

# Known mainframe utility programs that should not be treated as app programs
_UTILITIES = {
    "IEBGENER", "IEBCOPY", "IEFBR14", "IDCAMS", "SORT", "DFSORT",
    "ICEMAN", "IEBPTPCH", "IEHPROGM", "IEBUPDTE", "IEHINITT",
    "IEBCOMPR", "IEHLIST", "IKJEFT01", "IKJEFT1B", "FTP", "BDMPXWRT",
    "SDSF", "DFHCSDUP",
}


def _jcl_join_continuations(text: str) -> list[str]:
    """
    JCL continuation: a line whose operand field ends with a comma and the
    next line starts with '//' followed by at least one space (column 3+).
    Return a list of logical statements (comments and blank cards dropped).
    """
    physical = text.splitlines()
    logical: list[str] = []
    buf = ""
    for raw in physical:
        line = raw.rstrip()
        # Comment or blank cards
        if re.match(r"^//\*", line) or re.match(r"^$", line):
            if buf:
                logical.append(buf)
                buf = ""
            continue
        # Continuation line: starts with '//' then space(s) then non-space
        if buf and re.match(r"^//\s+\S", line):
            buf = buf.rstrip() + " " + line[2:].strip()
            continue
        # New statement
        if buf:
            logical.append(buf)
        buf = line
    if buf:
        logical.append(buf)
    return logical


def parse_jcl(path: Path) -> dict[str, Any]:
    """
    Return:
      {
        "job": "<JOB-NAME>",
        "steps": [
          {
            "step": "<STEP-NAME>",
            "pgm":  "<PROGRAM>",
            "parm": "<PARM-STRING or None>",
            "dds": {"<DD-NAME>": "<DSN or None>", ...},
          }, ...
        ]
      }
    """
    text = path.read_text(errors="replace")
    stmts = _jcl_join_continuations(text)

    job_name: str = ""
    steps: list[dict] = []
    current_step: dict | None = None

    for stmt in stmts:
        # JOB statement:  //JOBNAME  JOB ...
        m = re.match(r"^//(\w+)\s+JOB\b", stmt, re.IGNORECASE)
        if m:
            job_name = m.group(1)
            continue

        # EXEC PGM= statement:  //STEPNAME  EXEC  PGM=pgmname[,PARM='...']
        m = re.match(r"^//(\w+)\s+EXEC\s+PGM=(\w+)(.*)", stmt, re.IGNORECASE)
        if m:
            step_name = m.group(1)
            pgm = m.group(2).upper()
            rest = m.group(3)
            parm_m = re.search(r"PARM=(?:'([^']*)'|(\S+))", rest, re.IGNORECASE)
            parm = None
            if parm_m:
                parm = parm_m.group(1) if parm_m.group(1) is not None else parm_m.group(2)
            current_step = {"step": step_name, "pgm": pgm, "parm": parm, "dds": {}}
            steps.append(current_step)
            continue

        # DD statement:  //DDNAME  DD  ...,DSN=<dsn>,...
        m = re.match(r"^//(\w+)\s+DD\b(.*)", stmt, re.IGNORECASE)
        if m and current_step is not None:
            dd_name = m.group(1).upper()
            rest = m.group(2)
            dsn_m = re.search(r"DSN=([^,\s]+)", rest, re.IGNORECASE)
            dsn = dsn_m.group(1).strip("'") if dsn_m else None
            current_step["dds"][dd_name] = dsn

    return {"job": job_name, "steps": steps}


# ---------------------------------------------------------------------------
# COBOL parser
# ---------------------------------------------------------------------------

def _cbl_content_lines(text: str) -> list[tuple[int, str]]:
    """
    Yield (line_number, content) for non-comment lines.
    COBOL fixed format: col 7 (index 6) == '*' or '/' means comment.
    Lines shorter than 7 chars are treated as blank/non-content.
    """
    result = []
    for i, raw in enumerate(text.splitlines(), 1):
        if len(raw) > 6 and raw[6] in ("*", "/"):
            continue
        result.append((i, raw))
    return result


def parse_cbl(path: Path) -> dict[str, Any]:
    """
    Return:
      {
        "program_id": "<NAME>",
        "copies": ["<COPYBOOK>", ...],
        "assigns": {"<file-name>": "<dd-name>", ...},
        "open_modes": {"<file-name>": "INPUT|OUTPUT|I-O|EXTEND", ...},
        "line_count": <int>,
        "kind": "online"|"batch",
      }
    """
    text = path.read_text(errors="replace")
    total_lines = len(text.splitlines())
    content = _cbl_content_lines(text)
    joined = " ".join(line for _, line in content)
    # Normalise runs of whitespace for easier regex
    joined_norm = re.sub(r"\s+", " ", joined)

    # PROGRAM-ID
    pid_m = re.search(r"\bPROGRAM-ID\s*\.\s*(\w+)", joined_norm, re.IGNORECASE)
    program_id = pid_m.group(1).upper() if pid_m else path.stem.upper()

    # COPY names
    copies = [m.upper() for m in re.findall(r"\bCOPY\s+(\w+)", joined_norm, re.IGNORECASE)]

    # SELECT <logical-file> ASSIGN TO [EXTERNAL] <dd-name>
    assigns: dict[str, str] = {}
    for m in re.finditer(
        r"\bSELECT\s+(\S+)\s+ASSIGN\s+TO\s+(?:EXTERNAL\s+)?(\S+)",
        joined_norm,
        re.IGNORECASE,
    ):
        file_name = m.group(1).upper().rstrip(".")
        dd_name = m.group(2).upper().rstrip(".")
        assigns[file_name] = dd_name

    # OPEN mode for each logical file
    # Pattern: OPEN INPUT file1 file2 ... (until next keyword / period)
    open_modes: dict[str, str] = {}
    for m in re.finditer(
        r"\bOPEN\s+(INPUT|OUTPUT|I-O|EXTEND)\s+((?:(?!\bOPEN\b|\bCLOSE\b|\bREAD\b|\bWRITE\b|\bREWRITE\b|\bPERFORM\b|\bIF\b|\bMOVE\b|\bDISPLAY\b)[^\.\n])+)",
        joined_norm,
        re.IGNORECASE,
    ):
        mode = m.group(1).upper()
        names_part = m.group(2)
        # Extract identifiers (words that look like file logical names)
        for name_m in re.finditer(r"\b([A-Z][A-Z0-9-]+)\b", names_part, re.IGNORECASE):
            candidate = name_m.group(1).upper()
            # Only record if it's actually assigned (present in assigns dict)
            if candidate in assigns:
                open_modes[candidate] = mode

    # online if EXEC CICS appears in non-comment source
    is_online = bool(re.search(r"\bEXEC\s+CICS\b", joined_norm, re.IGNORECASE))

    return {
        "program_id": program_id,
        "copies": copies,
        "assigns": assigns,
        "open_modes": open_modes,
        "line_count": total_lines,
        "kind": "online" if is_online else "batch",
    }


# ---------------------------------------------------------------------------
# Build map
# ---------------------------------------------------------------------------

# Node id helpers so job names never collide with program names
def _job_id(name: str) -> str:
    return f"job:{name}"


def _pgm_id(name: str) -> str:
    return f"pgm:{name}"


def build_map() -> dict[str, Any]:
    """
    Parse all JCL and COBOL sources and return:
      {
        "stats": {
          "programs": <int>,
          "batch": <int>,
          "online": <int>,
          "jobs": <int>,
          "datasets": <int>,
          "edges": <int>,
        },
        "nodes": [{"id": ..., "type": ..., ...}, ...],
        "edges": [{"from": ..., "to": ..., "rel": ..., ...}, ...],
      }
    """
    # -----------------------------------------------------------------------
    # 1. Parse all COBOL programs
    # -----------------------------------------------------------------------
    cbl_programs: dict[str, dict] = {}  # program_id -> parsed info

    for cbl_file in sorted(_CBL_DIR.iterdir()):
        if cbl_file.suffix.upper() != ".CBL":
            continue
        info = parse_cbl(cbl_file)
        pid = info["program_id"]
        cbl_programs[pid] = info

    known_pgm_ids = set(cbl_programs.keys())

    # -----------------------------------------------------------------------
    # 2. Parse all JCL jobs
    # -----------------------------------------------------------------------
    jcl_jobs: list[dict] = []

    for jcl_file in sorted(_JCL_DIR.iterdir()):
        if jcl_file.suffix.upper() != ".JCL":
            continue
        info = parse_jcl(jcl_file)
        if not info["job"]:
            continue
        # Skip jobs whose steps only run utilities (no known app program)
        app_steps = [
            s for s in info["steps"]
            if s["pgm"] in known_pgm_ids
        ]
        if not app_steps:
            continue
        jcl_jobs.append(info)

    # -----------------------------------------------------------------------
    # 3. Build nodes
    # -----------------------------------------------------------------------
    nodes: list[dict] = []
    node_ids: set[str] = set()

    def _add_node(node: dict) -> None:
        if node["id"] not in node_ids:
            nodes.append(node)
            node_ids.add(node["id"])

    # Job nodes — use "job:<NAME>" to avoid collision with same-named programs
    for job in jcl_jobs:
        _add_node({"id": _job_id(job["job"]), "type": "job", "name": job["job"]})

    # Program nodes — use "pgm:<NAME>"
    for pid, info in cbl_programs.items():
        _add_node({
            "id": _pgm_id(pid),
            "type": info["kind"],
            "name": pid,
            "line_count": info["line_count"],
            "copies": info["copies"],
        })

    # -----------------------------------------------------------------------
    # 4. Build edges
    # -----------------------------------------------------------------------
    edges: list[dict] = []

    _SYSDD = {"STEPLIB", "SYSPRINT", "SYSOUT", "SYSUDUMP", "SYSIN", "SYSABEND", "CEEDUMP"}

    for job in jcl_jobs:
        job_node_id = _job_id(job["job"])
        for step in job["steps"]:
            pgm_name = step["pgm"]
            if pgm_name not in known_pgm_ids:
                continue

            pgm_node_id = _pgm_id(pgm_name)

            # job -> program (runs)
            edge: dict[str, Any] = {
                "from": job_node_id,
                "to": pgm_node_id,
                "rel": "runs",
                "step": step["step"],
            }
            if step["parm"] is not None:
                edge["parm"] = step["parm"]
            edges.append(edge)

            prog_info = cbl_programs[pgm_name]
            # Map DD name -> DSN for this step
            step_dd_dsn: dict[str, str] = {
                dd: dsn for dd, dsn in step["dds"].items()
                if dd not in _SYSDD and dsn
            }

            # For each SELECT/ASSIGN in the program, resolve DD -> DSN
            for file_name, dd_name in prog_info["assigns"].items():
                dd_upper = dd_name.upper()
                dsn = step_dd_dsn.get(dd_upper)
                if not dsn:
                    continue

                mode = prog_info["open_modes"].get(file_name, "INPUT")

                # Ensure dataset node exists
                _add_node({"id": dsn, "type": "dataset", "dsn": dsn})

                if mode == "INPUT":
                    edges.append({
                        "from": dsn,
                        "to": pgm_node_id,
                        "rel": "read",
                        "dd": dd_upper,
                    })
                elif mode == "OUTPUT":
                    edges.append({
                        "from": pgm_node_id,
                        "to": dsn,
                        "rel": "write",
                        "dd": dd_upper,
                    })
                elif mode in ("I-O", "EXTEND"):
                    edges.append({
                        "from": pgm_node_id,
                        "to": dsn,
                        "rel": "update",
                        "dd": dd_upper,
                    })

    # -----------------------------------------------------------------------
    # 5. Stats
    # -----------------------------------------------------------------------
    program_nodes = [n for n in nodes if n["type"] in ("batch", "online")]
    dataset_nodes = [n for n in nodes if n["type"] == "dataset"]
    job_nodes = [n for n in nodes if n["type"] == "job"]

    stats = {
        "programs": len(program_nodes),
        "batch": sum(1 for n in program_nodes if n["type"] == "batch"),
        "online": sum(1 for n in program_nodes if n["type"] == "online"),
        "jobs": len(job_nodes),
        "datasets": len(dataset_nodes),
        "edges": len(edges),
    }

    return {"stats": stats, "nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    result = build_map()
    stats = result["stats"]
    print("=== sysmap stats ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _OUT_DIR / "sysmap.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
