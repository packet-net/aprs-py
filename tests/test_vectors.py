"""The conformance vectors: every check the vectors' README defines, for every case.

There is one parametrised test per check, with the case id as the test id. A check listed in
``known_differences.json`` is skipped with its reason.
"""

from __future__ import annotations

from typing import Any

import pytest
from conformance import CHECKS, VECTORS, checks_for, load_cases, load_known_differences

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
    """Turning off only the one tolerance a case used gives the ``strict`` result."""
    _run("tolerance", case)


@pytest.mark.parametrize("case", _params("reencode"))
def test_reencode(case: dict[str, Any]) -> None:
    """Encoding the lenient data again: identical bytes, equivalent bytes, or a refusal."""
    _run("reencode", case)


@pytest.mark.parametrize("case", _params("encode"))
def test_encode(case: dict[str, Any]) -> None:
    """Encode cases: the information field (and Mic-E destination) written, or a refusal."""
    _run("encode", case)
