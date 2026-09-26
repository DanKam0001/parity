"""
ui/app.py
=========
FastAPI backend for the Parity web UI.

Endpoints
---------
  GET  /api/map        -> parity.sysmap.build_map()
  GET  /api/rules      -> bob_outputs/rules_CBACT04C.json (+ verified + code)
  GET  /api/source     -> cobol lines, java lines, method→paragraph links
  GET  /api/report     -> runs/<seed>_<accounts>/report.json (run if missing)
  POST /api/prove      -> run full proof (max 1 at a time)
  GET  /api/mutants    -> bob_outputs/mutants.json
  GET  /api/confirm    -> bob_outputs/confirm.json

Static files (index.html etc.) are served from ui/static/ at /.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT       = Path(__file__).resolve().parent.parent
_BOB        = _ROOT / "bob_outputs"
_COBOL_SRC  = _ROOT / "vendor" / "carddemo" / "cbl" / "CBACT04C.cbl"
_JAVA_SRC   = _BOB / "Cbact04c.java"
_RULES_JSON = _BOB / "rules_CBACT04C.json"
_MUTANTS    = _BOB / "mutants.json"
_CONFIRM    = _BOB / "confirm.json"
_STATIC     = Path(__file__).resolve().parent / "static"

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Parity")

# Serve static files at /  (must be mounted last so API routes take priority)
# We mount at the end of the module so route decorators are registered first.

# ---------------------------------------------------------------------------
# Concurrency guard for /api/prove
# ---------------------------------------------------------------------------

_prove_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cobol_content_cols(line: str) -> str:
    """Return columns 7–72 (1-based) of a COBOL fixed-format line (0-padded)."""
    # COBOL fixed format: col 1-6 sequence, col 7 indicator, cols 8-72 content
    # We want cols 7-72 inclusive (0-based indices 6..71).
    padded = line.rstrip("\r\n").ljust(72)
    return padded[6:72]


def _load_cobol_lines() -> list[str]:
    """Read CBACT04C.cbl and return columns 7-72 of each line."""
    lines = _COBOL_SRC.read_text(encoding="latin-1").splitlines()
    return [_cobol_content_cols(ln) for ln in lines]


def _load_java_lines() -> list[str]:
    """Read Cbact04c.java and return all lines (no column restriction)."""
    return _JAVA_SRC.read_text(encoding="utf-8").splitlines()


def _cobol_paragraphs() -> dict[str, tuple[int, int]]:
    """
    Return {paragraph_name: (start_line, end_line)} (1-based, inclusive).

    A paragraph header is a line whose content in cols 8-72 starts with an
    identifier followed by a period on the same line, with nothing else on the
    line except optional whitespace.  The paragraph runs to the line before
    the next header (or EOF).
    """
    raw_lines = _COBOL_SRC.read_text(encoding="latin-1").splitlines()
    # Pattern: col 7 is space (not indicator), col 8+ starts a word ending with '.'
    # In 0-based terms: index 6 == ' ', index 7+ has NAME.
    header_re = re.compile(r"^ {7}([A-Z0-9][A-Z0-9-]+)\.\s*$", re.IGNORECASE)

    headers: list[tuple[int, str]] = []  # (1-based line number, name)
    for i, raw in enumerate(raw_lines, 1):
        m = header_re.match(raw.rstrip())
        if m:
            headers.append((i, m.group(1).upper()))

    result: dict[str, tuple[int, int]] = {}
    for idx, (lineno, name) in enumerate(headers):
        end = headers[idx + 1][0] - 1 if idx + 1 < len(headers) else len(raw_lines)
        result[name] = (lineno, end)
    return result


def _java_method_links(cobol_paras: dict[str, tuple[int, int]]) -> list[dict]:
    """
    Parse Cbact04c.java and return one link per method with a Javadoc comment.

    Each link:
        {
          "method": <java method name>,
          "java_start": <1-based line>,
          "java_end":   <1-based line>,
          "paragraphs": ["1300-COMPUTE-INTEREST", ...],
          "cobol_ranges": [[start, end], ...],
        }

    Paragraphs are extracted from the Javadoc: any word matching
    [0-9]{4}-[A-Z][A-Z0-9-]+ is treated as a paragraph reference.
    """
    java_lines = _load_java_lines()
    total = len(java_lines)
    links: list[dict] = []

    # Javadoc paragraph references
    para_re = re.compile(r"\b(\d{4}-[A-Z][A-Z0-9-]+)\b")
    # Method signature (public/private/protected, static or not)
    method_sig_re = re.compile(
        r"^\s+(?:public|private|protected)\s+(?:static\s+)?(?:\S+\s+)(\w+)\s*\("
    )

    i = 0
    while i < total:
        line = java_lines[i]
        # Look for start of Javadoc block
        stripped = line.strip()
        if stripped == "/**":
            doc_start = i
            doc_lines: list[str] = []
            i += 1
            while i < total and java_lines[i].strip() != "*/":
                doc_lines.append(java_lines[i])
                i += 1
            # i now points at the closing */
            i += 1  # move past */

            # Collect all paragraph references from the doc block
            doc_text = " ".join(doc_lines)
            found_paras = para_re.findall(doc_text)
            if not found_paras:
                continue

            # Skip blank lines between javadoc and method
            while i < total and java_lines[i].strip() == "":
                i += 1

            if i >= total:
                continue

            # Next non-blank line should be the method signature
            m = method_sig_re.match(java_lines[i])
            if not m:
                continue

            method_name = m.group(1)
            method_start = i + 1  # 1-based

            # Find end of method: matching closing brace
            depth = 0
            method_end = method_start
            j = i
            while j < total:
                for ch in java_lines[j]:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                if depth == 0 and j > i:
                    method_end = j + 1  # 1-based
                    break
                j += 1

            # Build cobol_ranges from found paragraphs
            cobol_ranges: list[list[int]] = []
            for pname in found_paras:
                pname_upper = pname.upper()
                if pname_upper in cobol_paras:
                    s, e = cobol_paras[pname_upper]
                    cobol_ranges.append([s, e])

            links.append({
                "method": method_name,
                "java_start": method_start,
                "java_end": method_end,
                "paragraphs": found_paras,
                "cobol_ranges": cobol_ranges,
            })
        else:
            i += 1

    return links


def _verify_rule(rule: dict, cobol_lines: list[str]) -> dict:
    """
    Add "verified" and "code" fields to a rule dict.

    verified: True if rule["lines"] = [start, end] and both exist in cobol_lines.
    code: list of column-7-72 strings for that line range (1-based).
    """
    lines_field = rule.get("lines")
    total = len(cobol_lines)
    if (
        isinstance(lines_field, list)
        and len(lines_field) == 2
        and all(isinstance(x, int) for x in lines_field)
    ):
        start, end = lines_field
        verified = 1 <= start <= total and 1 <= end <= total
        # Clamp to valid range for code extraction
        s = max(1, start)
        e = min(total, end)
        code = cobol_lines[s - 1 : e]  # already cols 7-72
    else:
        verified = False
        code = []
    return {**rule, "verified": verified, "code": code}


def _run_dir(seed: int, accounts: int) -> Path:
    return _ROOT / "runs" / f"{seed}_{accounts}"


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@app.get("/api/map")
def get_map() -> Any:
    """Return the system map produced by parity.sysmap.build_map()."""
    from parity.sysmap import build_map
    return build_map()


@app.get("/api/rules")
def get_rules() -> Any:
    """
    Return rules_CBACT04C.json with each rule enriched with:
      "verified": bool  – whether the cited line range exists in CBACT04C.cbl
      "code": [str]     – the cited lines, columns 7-72
    """
    raw = json.loads(_RULES_JSON.read_text(encoding="utf-8"))
    cobol_lines = _load_cobol_lines()
    enriched_rules = [_verify_rule(r, cobol_lines) for r in raw.get("rules", [])]
    return {**raw, "rules": enriched_rules}


@app.get("/api/source")
def get_source() -> Any:
    """
    Return:
      {
        "cobol": [lines of CBACT04C.cbl, columns 7-72],
        "java":  [lines of Cbact04c.java],
        "links": [
          {
            "method":       <java method name>,
            "java_start":   <1-based line number>,
            "java_end":     <1-based line number>,
            "paragraphs":   ["1300-COMPUTE-INTEREST", ...],
            "cobol_ranges": [[start, end], ...],
          },
          ...
        ]
      }

    Paragraphs come from each Java method's Javadoc.
    A COBOL paragraph runs from its header line to the line before the next header.
    """
    cobol_paras = _cobol_paragraphs()
    return {
        "cobol": _load_cobol_lines(),
        "java":  _load_java_lines(),
        "links": _java_method_links(cobol_paras),
    }


@app.get("/api/report")
def get_report(
    seed: int = Query(default=7),
    accounts: int = Query(default=2000),
) -> Any:
    """
    Return runs/<seed>_<accounts>/report.json.
    If the report does not exist, run the full proof first.
    """
    report_path = _run_dir(seed, accounts) / "report.json"
    if not report_path.exists():
        # Run proof on demand (blocking)
        _do_prove(seed, accounts)
    if not report_path.exists():
        raise HTTPException(status_code=500, detail="Proof run did not produce report.json")
    return json.loads(report_path.read_text(encoding="utf-8"))


@app.post("/api/prove")
def post_prove(
    seed: int = Query(default=7),
    accounts: int = Query(default=2000),
) -> Any:
    """
    Run the full equivalence proof.
    Returns 429 if a proof is already running.
    Accounts are clamped to [1, 5000].
    """
    accounts = max(1, min(5000, accounts))

    if not _prove_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="A proof is already running")
    try:
        return _do_prove(seed, accounts)
    finally:
        _prove_lock.release()


def _do_prove(seed: int, accounts: int) -> dict:
    """Run parity.runner.run_parity and return a summary dict."""
    from parity.runner import run_parity

    result = run_parity(seed=seed, accounts=accounts)
    return {
        "passed":      result["passed"],
        "verdict":     result["verdict"],
        "report_path": str(result["report_path"]),
        "cobol_rc":    result["cobol_rc"],
        "java_rc":     result["java_rc"],
    }


@app.get("/api/mutants")
def get_mutants() -> Any:
    """Return bob_outputs/mutants.json."""
    return json.loads(_MUTANTS.read_text(encoding="utf-8"))


@app.get("/api/confirm")
def get_confirm() -> Any:
    """Return bob_outputs/confirm.json."""
    return json.loads(_CONFIRM.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Static files  (mounted last so /api/* routes are not shadowed)
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")
