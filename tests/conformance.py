"""Loading and checking the conformance vectors (the ``vectors/`` submodule).

Each case is checked as the vectors' README describes: the lenient decoding, the strict one,
the single-tolerance check, the re-encoding (byte for byte against ``canonical_info`` where a case
gives it), and for encode cases the encoding. Checks listed in ``known_differences.json`` are
skipped with their reasons.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdn_aprs import (
    DiagnosticCode,
    EncodeError,
    HeaderError,
    MicEReport,
    Packet,
    ParseOptions,
    decode_ax25,
    decode_tnc2,
)
from pdn_aprs.encode import encode_info, mic_e_destination
from pdn_aprs.neutral import NeutralFormError, from_neutral, header_to_neutral, to_neutral

ROOT = Path(__file__).resolve().parent.parent
VECTORS = ROOT / "vectors"
KNOWN_DIFFERENCES = Path(__file__).resolve().parent / "known_differences.json"

TOLERABLE = frozenset(
    c["id"]
    for c in (
        json.loads((VECTORS / "codes.json").read_text(encoding="utf-8"))["codes"]
        if (VECTORS / "codes.json").exists()
        else []
    )
    if c["tolerable"]
)


def load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted((VECTORS / "cases").glob("*.json")):
        cases.extend(json.loads(path.read_text(encoding="utf-8"))["cases"])
    return cases


def load_known_differences() -> dict[str, str]:
    if not KNOWN_DIFFERENCES.exists():
        return {}
    data = json.loads(KNOWN_DIFFERENCES.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


# ---------------------------------------------------------------- comparing


def _number_equal(a: float, b: float) -> bool:
    scale = max(abs(a), abs(b))
    return abs(a - b) <= 1e-9 * (scale if scale >= 1 else 1)


def differences(expected: Any, actual: Any, path: str = "") -> list[str]:
    """Where two neutral values differ, by the vectors' comparison rules."""
    out: list[str] = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in expected.keys() | actual.keys():
            p = f"{path}.{key}"
            if key not in actual:
                out.append(f"{p}: missing (expected {expected[key]!r})")
            elif key not in expected:
                out.append(f"{p}: unexpected {actual[key]!r}")
            elif key == "diagnostics":
                out.extend(diagnostic_differences(expected[key], actual[key], p))
            else:
                out.extend(differences(expected[key], actual[key], p))
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            out.append(f"{path}: expected {expected!r}, got {actual!r}")
        else:
            for i, (e, a) in enumerate(zip(expected, actual, strict=False)):
                out.extend(differences(e, a, f"{path}[{i}]"))
    elif isinstance(expected, bool) or isinstance(actual, bool):
        if expected is not actual:
            out.append(f"{path}: expected {expected!r}, got {actual!r}")
    elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if not _number_equal(expected, actual):
            out.append(f"{path}: expected {expected!r}, got {actual!r}")
    elif expected != actual:
        out.append(f"{path}: expected {expected!r}, got {actual!r}")
    return out


def diagnostic_differences(expected: list[str] | None, actual: list[str] | None, path: str) -> list[str]:
    e, a = Counter(expected or []), Counter(actual or [])
    out = [f"{path}: missing {d}" for d in sorted((e - a).elements())]
    out += [f"{path}: unexpected {d}" for d in sorted((a - e).elements())]
    return out


# ---------------------------------------------------------------- decoding a case


@dataclass
class Outcome:
    packet: Packet | None = None
    header_error: list[str] | None = None


def raw_info(case: dict[str, Any]) -> tuple[bytes, str, str]:
    """The information field a decode case carries, and its source and destination."""
    inp = case["input"]
    if "tnc2" in inp or "tnc2_hex" in inp:
        line = inp["tnc2"].encode("utf-8") if "tnc2" in inp else bytes.fromhex(inp["tnc2_hex"])
        header, _, info = line.partition(b":")
        source, _, rest = header.decode("latin-1").partition(">")
        return info, source, rest.split(",")[0]
    if "ax25_hex" in inp:
        packet = decode_ax25(bytes.fromhex(inp["ax25_hex"]))
        return packet.info, packet.source, packet.destination
    info = inp["info"].encode("utf-8") if "info" in inp else bytes.fromhex(inp["info_hex"])
    return info, inp.get("source", "N0CALL"), inp.get("destination", "APZ001")


def decode_case(case: dict[str, Any], options: ParseOptions) -> Outcome:
    inp = case["input"]
    try:
        if "tnc2" in inp:
            return Outcome(decode_tnc2(inp["tnc2"].encode("utf-8"), options))
        if "tnc2_hex" in inp:
            return Outcome(decode_tnc2(bytes.fromhex(inp["tnc2_hex"]), options))
        if "ax25_hex" in inp:
            return Outcome(decode_ax25(bytes.fromhex(inp["ax25_hex"]), options))
        info = inp["info"].encode("utf-8") if "info" in inp else bytes.fromhex(inp["info_hex"])
        header = inp.get("source", "N0CALL") + ">" + inp.get("destination", "APZ001")
        if inp.get("path"):
            header += "," + ",".join(inp["path"])
        return Outcome(decode_tnc2(header.encode("ascii") + b":" + info, options))
    except HeaderError as e:
        return Outcome(header_error=[str(d) for d in e.diagnostics])


def check_result(outcome: Outcome, expect: dict[str, Any], *, device: bool = True) -> list[str]:
    """How a decoding differs from an expectation of the ``expect`` form."""
    if "header_error" in expect:
        if outcome.header_error is None:
            assert outcome.packet is not None
            return [f"expected a header error, decoded {to_neutral(outcome.packet.data)!r}"]
        return diagnostic_differences(expect["header_error"], outcome.header_error, "header_error")
    if outcome.packet is None:
        return [f"unexpected header error {outcome.header_error!r}"]
    packet = outcome.packet
    out = differences(expect["data"], to_neutral(packet.data), "data")
    out += diagnostic_differences(expect.get("diagnostics"), [str(d) for d in packet.diagnostics], "diagnostics")
    if "header" in expect:
        out += differences(expect["header"], header_to_neutral(packet), "header")
    if not device:
        return out
    # a case without "device" says nothing about device identification (vectors README)
    if "device" in expect:
        found = packet.device
        got = {"vendor": found.vendor, "model": found.model} if found else None
        want = expect["device"]
        if got is None or any(got.get(k) != v for k, v in want.items()):
            out.append(f"device: expected {want!r}, got {got!r}")
    return out


def check_rejected(outcome: Outcome, code: str, header: bool) -> list[str]:
    want = f"error:{code}"
    if header:
        if outcome.header_error is None:
            return ["expected the header to be rejected"]
        return [] if want in outcome.header_error else [f"header error {outcome.header_error!r} lacks {want}"]
    if outcome.packet is None:
        return [f"unexpected header error {outcome.header_error!r}"]
    data = to_neutral(outcome.packet.data)
    diagnostics = [str(d) for d in outcome.packet.diagnostics]
    out = []
    if data != {"type": "unrecognized", "reason": "malformed"}:
        out.append(f"expected unrecognized/malformed, got {data!r}")
    if want not in diagnostics:
        out.append(f"diagnostics {diagnostics!r} lack {want}")
    return out


def check_strict_expectation(outcome: Outcome, case: dict[str, Any]) -> list[str]:
    strict = case.get("strict", "same")
    if strict == "same":
        return check_result(outcome, case["expect"])
    if "rejected_by" in strict:
        return check_rejected(outcome, strict["rejected_by"], strict.get("header", False))
    expect = dict(case["expect"])
    expect["data"] = strict["data"]
    expect["diagnostics"] = strict.get("diagnostics", [])
    expect.pop("device", None)
    return check_result(outcome, expect, device=False)


def single_tolerance(case: dict[str, Any]) -> str | None:
    """The one tolerable code a case's lenient decoding used, if exactly one."""
    codes = {
        d.partition(":")[2]
        for d in case["expect"].get("diagnostics", [])
        if d.startswith("warning:") and d.partition(":")[2] in TOLERABLE
    }
    return next(iter(codes)) if len(codes) == 1 else None


# ---------------------------------------------------------------- checks


def check_lenient(case: dict[str, Any]) -> list[str]:
    return check_result(decode_case(case, ParseOptions.lenient()), case["expect"])


def check_strict(case: dict[str, Any]) -> list[str]:
    return check_strict_expectation(decode_case(case, ParseOptions.strict()), case)


def check_tolerance(case: dict[str, Any]) -> list[str]:
    code = single_tolerance(case)
    assert code is not None
    options = ParseOptions.lenient().without(DiagnosticCode(code))
    return check_strict_expectation(decode_case(case, options), case)


def check_reencode(case: dict[str, Any]) -> list[str]:
    outcome = decode_case(case, ParseOptions.lenient())
    assert outcome.packet is not None
    data = outcome.packet.data
    info, source, destination = raw_info(case)
    try:
        written = encode_info(data)
        new_destination = mic_e_destination(data) if isinstance(data, MicEReport) else destination
    except EncodeError as e:
        if case["reencode"] == "refused":
            return []
        return [f"refused: {e}"]
    if case["reencode"] == "refused":
        return [f"expected the encoder to refuse, it wrote {written!r}"]
    if case["reencode"] == "identical":
        out = []
        want = info.rstrip(b"\r\n")
        if written != want:
            out.append(f"wrote {written!r}, expected {want!r}")
        if isinstance(data, MicEReport) and new_destination != destination:
            out.append(f"wrote destination {new_destination!r}, expected {destination!r}")
        return out
    canonical = case["canonical_info"].encode("utf-8") if "canonical_info" in case else None
    if case["reencode"] == "rounded":
        # a value the format holds only in steps is rounded, so the data read back differs from
        # the original by that rounding: only the bytes are compared
        assert canonical is not None, "a rounded case gives canonical_info"
        return [] if written == canonical else [f"wrote {written!r}, expected {canonical!r}"]
    again = decode_tnc2(f"{source}>{new_destination}".encode("ascii") + b":" + written)
    out = differences(to_neutral(data), to_neutral(again.data), "reencoded")
    bad = [str(d) for d in again.diagnostics if d.severity.value != "info"]
    if bad:
        out.append(f"wrote {written!r}, which decodes with {bad}")
    elif out:
        out.insert(0, f"wrote {written!r}")
    elif canonical is not None and written != canonical:
        # the bytes the Encoding rule leads to are binding, not only data that reads back the same
        out.append(f"wrote {written!r}, expected {canonical!r}")
    return out


def check_encode(case: dict[str, Any]) -> list[str]:
    expect = case["expect"]
    try:
        data = from_neutral(case["input"]["encode"])
    except NeutralFormError as e:
        # the data model cannot even hold this (an ack with its own message ID, say)
        return [] if expect.get("refused") else [f"cannot represent: {e}"]
    try:
        written = encode_info(data)
        destination = mic_e_destination(data) if isinstance(data, MicEReport) else None
    except EncodeError as e:
        if expect.get("refused"):
            return []
        return [f"refused: {e}"]
    if expect.get("refused"):
        return [f"expected the encoder to refuse, it wrote {written!r}"]
    out = []
    if written != expect["info"].encode("utf-8"):
        out.append(f"wrote {written!r}, expected {expect['info'].encode('utf-8')!r}")
    if "destination" in expect and destination != expect["destination"]:
        out.append(f"destination {destination!r}, expected {expect['destination']!r}")
    return out


CHECKS = {
    "lenient": check_lenient,
    "strict": check_strict,
    "tolerance": check_tolerance,
    "reencode": check_reencode,
    "encode": check_encode,
}


def checks_for(case: dict[str, Any]) -> list[str]:
    if "encode" in case["input"]:
        return ["encode"]
    names = ["lenient", "strict"]
    if single_tolerance(case) is not None:
        names.append("tolerance")
    if "reencode" in case:
        names.append("reencode")
    return names
