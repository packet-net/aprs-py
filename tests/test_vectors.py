"""The conformance vectors: every check the vectors' README defines, for every case.

There is one parametrised test per check, with the case id as the test id. A check listed in
``known_differences.json`` is skipped with its reason.
"""

from __future__ import annotations

from typing import Any

import pytest
from conformance import (
    CHECKS,
    VECTORS,
    checks_for,
    lenient_single_tolerance,
    load_cases,
    load_known_differences,
)

if not (VECTORS / "cases").is_dir():
    pytest.skip("the vectors submodule is not checked out (git submodule update --init)", allow_module_level=True)

CASES = load_cases()
KNOWN = load_known_differences()


def _params(check: str) -> list[Any]:
    params = []
    for case in CASES:
        if check not in checks_for(case):
            continue
        key = f"{case['id']}::{check}"
        marks = [pytest.mark.skip(reason=KNOWN[key])] if key in KNOWN else []
        params.append(pytest.param(case, id=case["id"], marks=marks))
    return params


def _run(check: str, case: dict[str, Any]) -> None:
    problems = CHECKS[check](case)
    if problems:
        pytest.fail(f"{case['id']} ({check}): " + "; ".join(problems), pytrace=False)


@pytest.mark.parametrize("case", _params("lenient"))
def test_lenient(case: dict[str, Any]) -> None:
    """Decoding leniently (the default) gives the expected data, diagnostics and header."""
    _run("lenient", case)


@pytest.mark.parametrize("case", _params("strict"))
def test_strict(case: dict[str, Any]) -> None:
    """Decoding strictly gives the ``strict`` result: the same, a rejection, or other data."""
    _run("strict", case)


@pytest.mark.parametrize("case", _params("tolerance"))
def test_tolerance(case: dict[str, Any]) -> None:
    """Turning off only the one tolerance a case used gives the ``strict`` result (or, where strict
    is rejected by another code, a reading that warns of that code)."""
    _run("tolerance", case)


def test_tolerance_check_runs_on_every_case_with_one_tolerance() -> None:
    """No case is skipped: the check runs on every case whose lenient diagnostics name exactly one tolerable code."""
    candidates = [c for c in CASES if "encode" not in c["input"] and "build" not in c["input"]]
    named = [c for c in candidates if lenient_single_tolerance(c) is not None]
    ran = [c for c in named if "tolerance" in checks_for(c)]
    print(f"tolerance check runs on {len(ran)} of {len(named)} cases")
    assert named
    assert len(ran) == len(named)
    skipped_known = [c["id"] for c in ran if f"{c['id']}::tolerance" in KNOWN]
    assert not skipped_known


@pytest.mark.parametrize("case", _params("reencode"))
def test_reencode(case: dict[str, Any]) -> None:
    """Encoding the lenient data again: identical bytes, the canonical bytes (for ``equivalent``,
    once they read back as the same data, and for ``rounded``), or a refusal."""
    _run("reencode", case)


@pytest.mark.parametrize("case", _params("encode"))
def test_encode(case: dict[str, Any]) -> None:
    """Encode cases: the information field (and Mic-E destination) written, or a refusal."""
    _run("encode", case)


@pytest.mark.parametrize("case", _params("build"))
def test_build(case: dict[str, Any]) -> None:
    """Build cases: the builder gives the TNC2 line, or the refusal, the case names."""
    _run("build", case)


@pytest.mark.parametrize("case", _params("pass_through"))
def test_pass_through(case: dict[str, Any]) -> None:
    """Pass-through cases: the lenient packet written back as a TNC2 line and an AX.25 frame, or the refusal."""
    _run("pass_through", case)


@pytest.mark.parametrize("case", _params("pass_through_inner"))
def test_pass_through_inner(case: dict[str, Any]) -> None:
    """The inner packet of a third-party packet written on its own, or the refusal, as the case says."""
    _run("pass_through_inner", case)
