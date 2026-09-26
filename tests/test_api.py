"""
tests/test_api.py
=================
FastAPI TestClient tests for the Parity backend.

Tests
-----
  - GET /api/map        → has stats, nodes, edges
  - GET /api/rules      → all rules are verified
  - GET /api/source     → has a link for 1300-COMPUTE-INTEREST
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ui.app import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# /api/map
# ---------------------------------------------------------------------------


def test_map_structure():
    """GET /api/map returns a dict with stats, nodes, and edges."""
    resp = client.get("/api/map")
    assert resp.status_code == 200
    data = resp.json()

    assert "stats" in data, "response must have 'stats'"
    assert "nodes" in data, "response must have 'nodes'"
    assert "edges" in data, "response must have 'edges'"

    stats = data["stats"]
    for key in ("programs", "batch", "online", "jobs", "datasets", "edges"):
        assert key in stats, f"stats must have '{key}'"

    # Basic sanity: there should be at least one program and one job
    assert stats["programs"] >= 1, "expected at least one program"
    assert stats["jobs"] >= 1, "expected at least one JCL job"

    # Nodes and edges must be lists
    assert isinstance(data["nodes"], list)
    assert isinstance(data["edges"], list)


# ---------------------------------------------------------------------------
# /api/rules
# ---------------------------------------------------------------------------


def test_rules_all_verified():
    """GET /api/rules → every rule has verified=True."""
    resp = client.get("/api/rules")
    assert resp.status_code == 200
    data = resp.json()

    assert "rules" in data, "response must have 'rules'"
    rules = data["rules"]
    assert len(rules) > 0, "expected at least one rule"

    unverified = [r["id"] for r in rules if not r.get("verified")]
    assert unverified == [], (
        f"Rules with unverifiable line ranges: {unverified}. "
        "Each rule's 'lines' field must reference lines that exist in CBACT04C.cbl."
    )


def test_rules_have_code():
    """Every rule includes a non-empty 'code' list."""
    resp = client.get("/api/rules")
    rules = resp.json()["rules"]
    for rule in rules:
        assert isinstance(rule["code"], list), f"rule {rule['id']} has no 'code' list"
        assert len(rule["code"]) > 0, (
            f"rule {rule['id']} has an empty 'code' list (lines={rule.get('lines')})"
        )


# ---------------------------------------------------------------------------
# /api/source
# ---------------------------------------------------------------------------


def test_source_structure():
    """GET /api/source returns cobol lines, java lines, and links."""
    resp = client.get("/api/source")
    assert resp.status_code == 200
    data = resp.json()

    assert "cobol" in data and isinstance(data["cobol"], list)
    assert "java"  in data and isinstance(data["java"],  list)
    assert "links" in data and isinstance(data["links"], list)

    # CBACT04C.cbl is ~653 lines; cobol list should be at least 600
    assert len(data["cobol"]) >= 600, "expected COBOL source to have ≥600 lines"
    # Cbact04c.java is several hundred lines
    assert len(data["java"])  >= 100, "expected Java source to have ≥100 lines"


def test_source_has_1300_link():
    """GET /api/source includes a link whose paragraphs include 1300-COMPUTE-INTEREST."""
    resp = client.get("/api/source")
    links = resp.json()["links"]

    matching = [
        lnk for lnk in links
        if "1300-COMPUTE-INTEREST" in lnk.get("paragraphs", [])
    ]
    assert len(matching) >= 1, (
        "Expected at least one link with paragraph '1300-COMPUTE-INTEREST'. "
        f"Links found: {[l['method'] for l in links]}"
    )

    lnk = matching[0]
    assert lnk["java_start"] >= 1
    assert lnk["java_end"]   >= lnk["java_start"]
    assert len(lnk["cobol_ranges"]) >= 1, (
        "Link for 1300-COMPUTE-INTEREST must have at least one cobol_range"
    )
    start, end = lnk["cobol_ranges"][0]
    assert start >= 1
    assert end >= start
