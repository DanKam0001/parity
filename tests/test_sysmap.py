"""
tests/test_sysmap.py
Assertions against the parsed CardDemo system map.
"""

import pytest
from parity.sysmap import build_map


@pytest.fixture(scope="module")
def sysmap():
    return build_map()


@pytest.fixture(scope="module")
def nodes_by_id(sysmap):
    return {n["id"]: n for n in sysmap["nodes"]}


@pytest.fixture(scope="module")
def edges(sysmap):
    return sysmap["edges"]


# ---------------------------------------------------------------------------
# Program counts
# ---------------------------------------------------------------------------

def test_total_programs(sysmap):
    assert sysmap["stats"]["programs"] == 31


def test_batch_programs(sysmap):
    assert sysmap["stats"]["batch"] == 14


def test_online_programs(sysmap):
    assert sysmap["stats"]["online"] == 17


# ---------------------------------------------------------------------------
# INTCALC job -> CBACT04C
# ---------------------------------------------------------------------------

def test_intcalc_runs_cbact04c(edges):
    run_edges = [
        e for e in edges
        if e["rel"] == "runs"
        and e["from"] == "job:INTCALC"
        and e["to"] == "pgm:CBACT04C"
    ]
    assert len(run_edges) == 1, "Expected exactly one 'runs' edge from INTCALC to CBACT04C"


def test_intcalc_cbact04c_parm(edges):
    run_edge = next(
        e for e in edges
        if e["rel"] == "runs"
        and e["from"] == "job:INTCALC"
        and e["to"] == "pgm:CBACT04C"
    )
    assert run_edge.get("parm") == "2022071800"


# ---------------------------------------------------------------------------
# CBACT04C dataset relationships
# ---------------------------------------------------------------------------

def _cbact04c_read_edges(edges):
    return [e for e in edges if e["rel"] == "read" and e["to"] == "pgm:CBACT04C"]


def _cbact04c_update_edges(edges):
    return [e for e in edges if e["rel"] == "update" and e["from"] == "pgm:CBACT04C"]


def _cbact04c_write_edges(edges):
    return [e for e in edges if e["rel"] == "write" and e["from"] == "pgm:CBACT04C"]


def test_cbact04c_reads_3_datasets(edges):
    reads = _cbact04c_read_edges(edges)
    assert len(reads) == 3, f"Expected 3 read edges for CBACT04C, got {len(reads)}: {reads}"


def test_cbact04c_updates_account_file(edges):
    updates = _cbact04c_update_edges(edges)
    assert len(updates) == 1, f"Expected 1 update edge for CBACT04C, got {len(updates)}: {updates}"
    # The updated dataset should be the account VSAM
    dsn = updates[0]["to"]
    assert "ACCT" in dsn.upper(), (
        f"Expected account-related DSN but got: {dsn}"
    )


def test_cbact04c_writes_transaction_file(edges):
    writes = _cbact04c_write_edges(edges)
    assert len(writes) == 1, f"Expected 1 write edge for CBACT04C, got {len(writes)}: {writes}"
    dsn = writes[0]["to"]
    assert "TRAN" in dsn.upper() or "SYSTRAN" in dsn.upper(), (
        f"Expected transaction-related DSN but got: {dsn}"
    )


# ---------------------------------------------------------------------------
# Node type sanity checks
# ---------------------------------------------------------------------------

def test_cbact04c_is_batch(nodes_by_id):
    assert nodes_by_id["pgm:CBACT04C"]["type"] == "batch"


def test_online_programs_have_cics(nodes_by_id):
    """Every program marked 'online' should exist as a node of type online."""
    online_nodes = [n for n in nodes_by_id.values() if n["type"] == "online"]
    assert len(online_nodes) == 17


def test_intcalc_is_job_node(nodes_by_id):
    assert nodes_by_id["job:INTCALC"]["type"] == "job"
