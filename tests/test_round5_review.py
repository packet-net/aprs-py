"""Round 5, after the independent review (vectors R26): the rules the vectors cannot pin because a rule
check always comes first, and a regression test for each defect the review found.

Each test here must fail when the clause it names is removed (the mutation proofs are in the commit
that added them).
"""

from __future__ import annotations

import copy
import pickle
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest

import pdn_aprs as aprs
from pdn_aprs import EncodeError, RefusalCode
from pdn_aprs import _readback as rb
from pdn_aprs import encode as enc
from pdn_aprs._decode import Ctx
from pdn_aprs._neutral import from_neutral, to_neutral
from pdn_aprs.diagnostics import DiagnosticCode, Severity

POSITION = {"type": "position", "latitude": 51.5, "longitude": -0.5, "symbol": "/>"}
POSITION_INFO = b"!5130.00N/00030.00W>"
STATUS = {"type": "status", "text": "hi"}
MIC_E = {"type": "mic-e", "mic_e_message": "off-duty", "latitude": 51.5, "longitude": -0.5, "symbol": "/>"}


def _mismatch(neutral: dict[str, Any], info: bytes, destination: str = "APZ001") -> str | None:
    data = from_neutral(neutral)
    return rb.mismatch(data, to_neutral(data), info, destination)


def _code(call: Callable[[], object]) -> RefusalCode:
    with pytest.raises(EncodeError) as caught:
        call()
    return caught.value.code


def _inject(monkeypatch: pytest.MonkeyPatch, severity: Severity, code: DiagnosticCode) -> None:
    """Make the read-back's decode raise one more diagnostic, as a decoder that saw something would."""
    real = rb.decode_info
    diagnostic = aprs.Diagnostic(severity, code)

    def wrapped(info: bytes, destination: str, ctx: Ctx) -> Any:
        data = real(info, destination, ctx)
        ctx.diags.append(diagnostic)
        return data

    monkeypatch.setattr(rb, "decode_info", wrapped)


# ---------------------------------------------------------------- 9: the read-back's diagnostics


@pytest.mark.parametrize("severity", [Severity.WARNING, Severity.ERROR])
def test_a_read_back_that_sees_only_a_warning_or_an_error_refuses(
    monkeypatch: pytest.MonkeyPatch, severity: Severity
) -> None:
    """Fields and info all agree; the one thing wrong is a warning (or an error) in the decode."""
    assert _mismatch(POSITION, POSITION_INFO) is None
    _inject(monkeypatch, severity, DiagnosticCode.CONTROL_CHARACTER_IN_TEXT)
    assert _mismatch(POSITION, POSITION_INFO) is not None
    assert _code(lambda: enc.encode_info(from_neutral(POSITION))) is RefusalCode.DOES_NOT_READ_BACK


def test_an_info_no_form_lists_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    _inject(monkeypatch, Severity.INFO, DiagnosticCode.NOT_APRS)
    assert _mismatch(POSITION, POSITION_INFO) is not None
    assert _code(lambda: enc.encode_info(from_neutral(POSITION))) is RefusalCode.DOES_NOT_READ_BACK


@pytest.mark.parametrize(
    ("neutral", "code"),
    [
        (POSITION, DiagnosticCode.OBSOLETE_FORMAT),
        (STATUS, DiagnosticCode.OBSOLETE_FORMAT),
        (POSITION, DiagnosticCode.MIC_E_MISSING_DEVICE_TYPE),
        (STATUS, DiagnosticCode.INVALID_QUERY),
        (POSITION, DiagnosticCode.INVALID_TELEMETRY_METADATA),
    ],
)
def test_an_info_listed_for_one_form_is_not_accepted_on_another(
    monkeypatch: pytest.MonkeyPatch, neutral: dict[str, Any], code: DiagnosticCode
) -> None:
    info = enc.encode_info(from_neutral(neutral))
    assert _mismatch(neutral, info) is None
    _inject(monkeypatch, Severity.INFO, code)
    assert _mismatch(neutral, info) is not None


@pytest.mark.parametrize(
    ("neutral", "code"),
    [
        ({"type": "raw-weather", "format": "peet-bros-hash", "data": "abc"}, DiagnosticCode.OBSOLETE_FORMAT),
        ({"type": "maidenhead-beacon", "locator": "IO91SX", "comment": ""}, DiagnosticCode.OBSOLETE_FORMAT),
        (
            {"type": "weather", "timestamp": "10090556", "weather": {"temperature_f": 70}},
            DiagnosticCode.OBSOLETE_FORMAT,
        ),
        (
            MIC_E | {"comment": "hello"},
            DiagnosticCode.MIC_E_MISSING_DEVICE_TYPE,
        ),
        ({"type": "message", "addressee": "N0CALL", "text": "?FOO", "message_id": "1"}, DiagnosticCode.INVALID_QUERY),
        (
            {"type": "message", "addressee": "N0CALL", "text": "PARM.a,b,c,d,e,f,g,h,i,j,k,l,m,n"},
            DiagnosticCode.INVALID_TELEMETRY_METADATA,
        ),
    ],
)
def test_an_info_listed_for_a_form_is_accepted_there(neutral: dict[str, Any], code: DiagnosticCode) -> None:
    data = from_neutral(neutral)
    written = enc._write(data)
    ctx = Ctx(aprs.ParseOptions.lenient())
    rb.decode_info(written.info, written.destination, ctx)
    assert [d.code for d in ctx.diags if d.severity is Severity.INFO] == [code]
    assert rb.mismatch(data, to_neutral(data), written.info, written.destination) is None


def test_a_decode_with_a_field_the_data_does_not_give_refuses() -> None:
    assert _mismatch(STATUS, b">hi^A5") is not None
    assert "was not given" in str(_mismatch(STATUS, b">hi^A5"))
    assert "was not given" in str(_mismatch(POSITION, POSITION_INFO + b"088/036"))


def test_a_field_given_that_is_not_in_the_decode_refuses() -> None:
    beam = {"heading_code": "A", "power_code": "5"}
    assert _mismatch(STATUS | {"beam": beam}, b">hi^A5") is None
    reason = _mismatch(STATUS | {"beam": beam}, b">hi")
    assert reason is not None
    assert "is not read back" in reason


def test_a_mic_e_speed_is_the_only_thing_a_decode_may_add_and_only_when_it_is_0() -> None:
    neutral = {
        "type": "mic-e",
        "mic_e_message": "off-duty",
        "latitude": 51.5,
        "longitude": -0.5,
        "symbol": "/>",
        "type_code": "`",
    }
    ten = enc.encode_info(from_neutral(neutral | {"speed_knots": 10}))
    zero = enc.encode_info(from_neutral(neutral))
    destination = enc.mic_e_destination(from_neutral(neutral))
    assert _mismatch(neutral, zero, destination) is None
    assert _mismatch(neutral, ten, destination) is not None
    assert _mismatch(neutral | {"speed_knots": 10}, ten, destination) is None


def test_no_other_read_back_speed_of_0_is_allowed() -> None:
    # a speed of 0 is the Mic-E form's own; in a position report a speed left out is not 0
    given = POSITION | {"course_degrees": 88}
    assert _mismatch(given, POSITION_INFO + b"088/000") is not None
    assert _mismatch(given | {"speed_knots": 0}, POSITION_INFO + b"088/000") is None


def test_the_third_party_inner_warnings_and_errors_are_compared_as_a_multiset() -> None:
    line = b"N0CALL>APRS:}G4ABC>APZ001:>a\x01b"
    held = aprs.decode_tnc2(line)
    assert isinstance(held.data, aprs.ThirdParty)
    inner = held.data.packet
    warnings = [d for d in inner.diagnostics if d.severity is Severity.WARNING]
    assert len(warnings) == 1
    data = held.data
    assert enc.encode_info(data) == line.split(b":", 1)[1]

    def with_diagnostics(diagnostics: tuple[aprs.Diagnostic, ...]) -> aprs.ThirdParty:
        return aprs.ThirdParty(replace(inner, diagnostics=diagnostics))

    # the same warning twice is not the one the bytes read back with; none is not either
    twice = with_diagnostics((*inner.diagnostics, *warnings))
    assert _code(lambda: enc.encode_info(twice)) is RefusalCode.DOES_NOT_READ_BACK
    none = with_diagnostics(())
    assert _code(lambda: enc.encode_info(none)) is RefusalCode.DOES_NOT_READ_BACK
    other = with_diagnostics((aprs.Diagnostic(Severity.WARNING, DiagnosticCode.NON_UTF8_TEXT),))
    assert _code(lambda: enc.encode_info(other)) is RefusalCode.DOES_NOT_READ_BACK
    # infos, given or decoded, are not compared
    info = aprs.Diagnostic(Severity.INFO, DiagnosticCode.OBSOLETE_FORMAT)
    assert enc.encode_info(with_diagnostics((*inner.diagnostics, info))) == enc.encode_info(data)


def test_neutral_inner_data_given_a_warning_its_bytes_do_not_carry_has_no_form() -> None:
    inner = {"source": "N0CALL", "destination": "APRS", "data": STATUS}
    clean = {"type": "third-party", "packet": inner}
    assert enc.encode_info(from_neutral(clean)) == b"}N0CALL>APRS:>hi"
    for diagnostic in ("warning:control-character-in-text", "error:invalid-mic-e-information"):
        given = {"type": "third-party", "packet": {**inner, "diagnostics": [diagnostic]}}
        assert _code(lambda given=given: enc.encode_info(from_neutral(given))) is RefusalCode.VALUE_HAS_NO_FORM
    # the same two deep, and ahead of the fallback codes
    deep = {"type": "third-party", "packet": {**inner, "data": {"type": "third-party", "packet": inner}}}
    deep["packet"]["data"]["packet"] = {**inner, "diagnostics": ["warning:control-character-in-text"]}
    assert _code(lambda: enc.encode_info(from_neutral(deep))) is RefusalCode.VALUE_HAS_NO_FORM
    # an info is not compared
    assert enc.encode_info(from_neutral({"type": "third-party", "packet": {**inner, "diagnostics": ["info:not-aprs"]}}))


def test_a_header_written_with_a_diagnostic_the_packet_does_not_carry_is_refused() -> None:
    held = aprs.Packet("N0CALL", "", (), b">hi", aprs.StatusReport(text="hi"))
    assert _code(held.to_tnc2) is RefusalCode.INVALID_ADDRESS
    assert _code(lambda: held.header) is RefusalCode.INVALID_ADDRESS
    # the same destination, decoded: the defect is the packet's own data and is written as received
    decoded = aprs.decode_tnc2(b"N0CALL>:>hi")
    assert decoded.diagnostics
    assert decoded.to_tnc2() == b"N0CALL>:>hi"
    assert _code(replace(decoded, diagnostics=()).to_tnc2) is RefusalCode.INVALID_ADDRESS


# ---------------------------------------------------------------- the review's defects


@pytest.mark.parametrize("source", ["a b", "S;C", "PY2SP_R-R"])
def test_d1_an_inner_header_written_on_its_own_is_read_back_by_the_outer_rules(source: str) -> None:
    held = aprs.decode_tnc2(f"N0CALL>APRS:}}{source}>APRS,A*,B:>hi".encode())
    assert isinstance(held.data, aprs.ThirdParty)
    inner = held.data.packet
    for write in (inner.to_tnc2, lambda: inner.header, inner.to_ax25, inner.to_kiss):
        assert _code(write) is RefusalCode.INVALID_ADDRESS
    assert str(inner).startswith(f"{source}>APRS,A*,B:")
    # written inside third-party data it is still read back by the third-party rules
    assert enc.encode_info(held.data).startswith(f"}}{source}>".encode())


def test_d1_an_inner_q_construct_is_determined_by_the_path_and_not_compared() -> None:
    held = aprs.decode_tnc2(b"N0CALL>APRS:}G4ABC>APRS,qAR,X:>hi")
    assert isinstance(held.data, aprs.ThirdParty)
    inner = held.data.packet
    assert inner.q_construct is None
    assert inner.to_tnc2() == b"G4ABC>APRS,qAR,X:>hi"
    assert aprs.decode_tnc2(inner.to_tnc2()).q_construct == aprs.QConstruct("qAR", "X")
    assert _code(inner.to_ax25) is RefusalCode.AX25_CANNOT_CARRY


def test_d1_an_inner_packet_with_an_empty_information_field_is_written_as_received() -> None:
    held = aprs.decode_tnc2(b"N0CALL>APRS:}G4ABC>APRS:")
    assert isinstance(held.data, aprs.ThirdParty)
    assert held.data.packet.to_tnc2() == b"G4ABC>APRS:"
    assert enc.encode_info(held.data) == b"}G4ABC>APRS:"


def test_d2_a_slash_a_beside_the_mic_e_bytes_holds_the_value_exactly() -> None:
    report = from_neutral(MIC_E)
    assert isinstance(report, aprs.MicEReport)
    inexact = replace(report, altitude_feet=100.3, altitude_in_comment=True)
    info = enc.encode_info(inexact)
    assert b"/A=" not in info
    assert info.endswith(b"}")
    again = aprs.decode_tnc2(b"N0CALL>" + enc.mic_e_destination(inexact).encode() + b":" + info).data
    assert isinstance(again, aprs.MicEReport)
    assert again.altitude_feet == pytest.approx(100.1, abs=3.3)
    exact = replace(report, altitude_feet=100.0, altitude_in_comment=True)
    assert b"/A=000100" in enc.encode_info(exact)
    # the comparison itself holds a /A= to the value exactly
    data = replace(report, altitude_feet=100.3)
    assert rb.mismatch(data, to_neutral(data), b"`v:\x1cl \x1c>/", enc.mic_e_destination(data)) is not None


def test_s3_a_display_conversion_is_total_and_not_a_writer() -> None:
    odd = [
        aprs.Packet("N0 CALL", "APZ001", (), b">hi", aprs.StatusReport(text="hi")),
        aprs.Packet("N0CALL", "", (), b">hi\r\nx", aprs.StatusReport(text="hi")),
        aprs.Packet(
            "N0CALL", "APZ001", (aprs.PathEntry("A"), aprs.PathEntry("B", True)), b">h\xff", aprs.StatusReport("")
        ),
        aprs.Packet("\u00e9", "APZ001", (), b"\xff", aprs.StatusReport(text="")),
    ]
    for packet in odd:
        assert isinstance(str(packet), str)
        assert isinstance(repr(packet), str)
    assert str(odd[0]) == "N0 CALL>APZ001:>hi"
    assert str(odd[2]).startswith("N0CALL>APZ001,A,B*:")
    # the writers are the ones that refuse
    assert _code(odd[0].to_tnc2) is RefusalCode.INVALID_ADDRESS
    assert "display" in (aprs.Packet.__str__.__doc__ or "")


def test_s4_a_builders_altitude_is_the_plain_float_it_was_given() -> None:
    packet = aprs.Station("N0CALL").mic_e(51.5, -0.5, aprs.Symbol.CAR, altitude_feet=1000)
    data = packet.data
    assert isinstance(data, aprs.MicEReport)
    assert type(data.altitude_feet) in (int, float)
    assert data.altitude_feet == 1000
    assert type(pickle.loads(pickle.dumps(data)).altitude_feet) is type(data.altitude_feet)
    assert type(copy.deepcopy(data).altitude_feet) is type(data.altitude_feet)
    assert type(replace(data, comment="x").altitude_feet) is type(data.altitude_feet)
    # the builder writes the Mic-E bytes first; neutral data holding the same value is a whole number of
    # feet that the bytes do not hold exactly, so it goes in a /A= (the Encoding rule)
    assert packet.info.endswith(b"}")
    assert b"/A=001000" in enc.encode_info(replace(data, altitude_feet=1000.0))
    # in metres, too
    metres = aprs.Station("N0CALL").mic_e(51.5, -0.5, aprs.Symbol.CAR, altitude_m=300)
    assert metres.info.endswith(b"}")
    assert type(metres.data.altitude_feet) is float  # type: ignore[attr-defined]


def test_s4_the_encoder_has_no_class_that_marks_an_altitude() -> None:
    assert not hasattr(enc, "BuilderAltitude")
    import inspect

    assert "mic_e_first" not in inspect.signature(aprs.build_packet).parameters
    assert "mic_e_first" not in inspect.signature(aprs.encode_info).parameters


def _frame(info: bytes) -> bytes:
    """A frame from N0CALL to APZ001 carrying ``info``, for the data a program would hold for it."""
    from pdn_aprs.packet import _ax25_address

    return _ax25_address("APZ001", command=True) + _ax25_address("N0CALL", last=True) + b"\x03\xf0" + info


def test_s5_a_line_ends_at_a_cr_or_lf_inside_the_information_field() -> None:
    for info in (b">a\rb", b">a\nb", b"\n>x", b">a\r\nb"):
        held = aprs.Packet("N0CALL", "APZ001", (), info, aprs.decode_ax25(_frame(info)).data)
        assert _code(held.to_tnc2) is RefusalCode.TNC2_CANNOT_CARRY
        assert held.to_ax25().endswith(info)
        assert held.to_kiss()
    for info in (b">ab\n", b">ab\r\n", b">ab\r"):
        held = aprs.Packet("N0CALL", "APZ001", (), info, aprs.decode_ax25(_frame(info)).data)
        assert held.to_tnc2() == b"N0CALL>APZ001:" + info


def test_s5_a_built_user_defined_packet_with_a_line_break_is_written_as_held_by_a_frame_only() -> None:
    data = aprs.UserDefined("A", "x", "a\nX>Y:>evil")
    assert enc.encode_info(data) == b"{Axa\nX>Y:>evil"
    packet = aprs.build_packet("N0CALL", data)
    assert packet.info == b"{Axa\nX>Y:>evil"
    assert _code(packet.to_tnc2) is RefusalCode.TNC2_CANNOT_CARRY
    assert packet.to_ax25().endswith(packet.info)


@pytest.mark.parametrize("entry", ["WIDE1-1**", "**", "*", "WIDE*1", "*WIDE1-1", "WIDE1-1*x", "A**B"])
def test_s6_anything_but_one_trailing_star_is_an_invalid_address(entry: str) -> None:
    status = aprs.StatusReport(text="hi")
    assert _code(lambda: aprs.build_packet("N0CALL", status, path=[entry])) is RefusalCode.INVALID_ADDRESS
    assert _code(lambda: aprs.Station("N0CALL", path=[entry]).status("hi")) is RefusalCode.INVALID_ADDRESS
    assert _code(lambda: aprs.build_packet("N0CALL", status, path=[aprs.PathEntry(entry)])) is (
        RefusalCode.INVALID_ADDRESS
    )


def test_s6_exactly_one_trailing_star_marks_a_used_entry() -> None:
    packet = aprs.build_packet("N0CALL", aprs.StatusReport(text="hi"), path=["WIDE1-1*", "WIDE2-1"])
    assert packet.path == (aprs.PathEntry("WIDE1-1", True), aprs.PathEntry("WIDE2-1", False))


# ---------------------------------------------------------------- the refusal order of a header


def test_a_header_fault_of_any_form_comes_before_every_data_fault_and_the_size() -> None:
    bad_data = aprs.ObjectReport(
        name="TOOLONGNAME", latitude=1, longitude=2, symbol=aprs.Symbol.CAR, timestamp=aprs.Timestamp.dhm(27, 9, 23)
    )
    big = aprs.StatusReport(text="x" * 300)
    for data in (bad_data, big):
        assert _code(lambda data=data: aprs.build_packet("N0CALL", data, path=["A", "B*"])) is RefusalCode.INVALID_PATH
        assert _code(lambda data=data: aprs.build_packet("N0 CALL", data, path=["A", "B*"])) is (
            RefusalCode.INVALID_ADDRESS
        )
        assert _code(lambda data=data: aprs.build_packet("N0CALL", data, destination="A B")) is (
            RefusalCode.INVALID_ADDRESS
        )
    assert _code(lambda: aprs.build_packet("N0CALL", bad_data)) is RefusalCode.INVALID_NAME
    assert _code(lambda: aprs.build_packet("N0CALL", big)) is RefusalCode.INFORMATION_FIELD_TOO_LONG


def test_more_than_eight_path_entries_is_a_frame_fault_not_a_header_fault() -> None:
    packet = aprs.build_packet("N0CALL", aprs.StatusReport(text="hi"), path=["A"] * 9)
    assert packet.to_tnc2().startswith(b"N0CALL>APZ001,A,A,A,A,A,A,A,A,A:")
    assert _code(packet.to_ax25) is RefusalCode.AX25_CANNOT_CARRY


def test_an_empty_destination_is_ax25_cannot_carry_from_a_frame_and_carried_by_a_line() -> None:
    held = aprs.decode_tnc2(b"N0CALL>:>x")
    assert held.to_tnc2() == b"N0CALL>:>x"
    assert _code(held.to_ax25) is RefusalCode.AX25_CANNOT_CARRY
    assert _code(held.to_kiss) is RefusalCode.AX25_CANNOT_CARRY


# ---------------------------------------------------------------- whole units and codes are never rounded


@pytest.mark.parametrize(
    "extra",
    [
        {"phg": {"power": 4.4, "height": 1, "gain": 3, "directivity": 2}},
        {"phg": {"power": 4, "height": 2.5, "gain": 3, "directivity": 2}},
        {"phg": {"power": 4, "height": 1, "gain": 3.5, "directivity": 2}},
        {"phg": {"power": 4, "height": 1, "gain": 3, "directivity": 2.5}},
        {"phg": {"power": 4, "height": 1, "gain": 3, "directivity": 2, "beacons_per_hour": 2.5}},
        {"dfs": {"strength": 4.5, "height": 1, "gain": 3, "directivity": 2}},
        {"dfs": {"strength": 4, "height": 1.5, "gain": 3, "directivity": 2}},
        {"area": {"shape": "open-circle", "color": "blue", "lat_offset": 3.5, "lon_offset": 3}},
        {"area": {"shape": "open-circle", "color": "blue", "lat_offset": 3, "lon_offset": 3.5}},
        {"telemetry": {"sequence": 10.5, "analog": [1, 2]}},
        {"telemetry": {"sequence": 10, "analog": [1.5, 2]}},
        {"telemetry": {"sequence": 10, "analog": [1, 2], "digital": 3.5}},
        {"frequency": {"mhz": 146.52, "tone": "tone", "tone_value": 100.5}},
        {"frequency": {"mhz": 146.52, "range": 25.5}},
        {"symbol": "/\\", "df_bearing": {"bearing_degrees": 100.5, "number": 1, "range": 2, "quality": 3}},
        {"symbol": "/\\", "df_bearing": {"bearing_degrees": 100, "number": 1.5, "range": 2, "quality": 3}},
        {"symbol": "/\\", "df_bearing": {"bearing_degrees": 100, "number": 1, "range": 2.5, "quality": 3}},
        {"symbol": "/\\", "df_bearing": {"bearing_degrees": 100, "number": 1, "range": 2, "quality": 3.5}},
        {
            "symbol": "\\@",
            "storm": {
                "type": "hurricane",
                "sustained_wind_knots": 100.5,
                "gust_knots": 120,
                "central_pressure_mbar": 950,
                "hurricane_radius_nm": 40,
                "tropical_storm_radius_nm": 80,
            },
        },
        {
            "symbol": "\\@",
            "storm": {
                "type": "hurricane",
                "sustained_wind_knots": 100,
                "gust_knots": 120,
                "central_pressure_mbar": 950,
                "hurricane_radius_nm": 40,
                "tropical_storm_radius_nm": 80,
                "whole_gale_radius_nm": 150.5,
            },
        },
    ],
    ids=lambda extra: next(iter(extra)) + str(hash(str(extra)) % 1000),
)
def test_a_non_integer_in_a_whole_unit_or_code_field_is_out_of_range_never_rounded(extra: dict[str, Any]) -> None:
    neutral = {**POSITION, **extra}
    assert _code(lambda: enc.encode_info(from_neutral(neutral))) is RefusalCode.VALUE_OUT_OF_RANGE
    # at every depth
    inner = {"source": "N0CALL", "destination": "APRS", "data": neutral}
    wrapped = {
        "type": "third-party",
        "packet": {"source": "N0CALL", "destination": "APRS", "data": {"type": "third-party", "packet": inner}},
    }
    assert _code(lambda: enc.encode_info(from_neutral(wrapped))) is RefusalCode.VALUE_OUT_OF_RANGE


def test_a_whole_number_given_as_a_float_is_that_whole_number() -> None:
    phg = {"power": 4.0, "height": 1.0, "gain": 3.0, "directivity": 2.0, "beacons_per_hour": 2.0}
    assert enc.encode_info(from_neutral({**POSITION, "phg": phg})) == POSITION_INFO + b"PHG41322/"
    area = {"shape": "open-circle", "color": "blue", "lat_offset": 3.0, "lon_offset": 4.0}
    assert enc.encode_info(from_neutral({**POSITION, "symbol": "\\l", "area": area}))


def test_an_agrelo_quality_and_a_mic_e_ssid_are_codes_too() -> None:
    assert _code(lambda: enc.encode_info(aprs.AgreloDf(bearing_degrees=90, quality=2.5))) is (
        RefusalCode.VALUE_OUT_OF_RANGE
    )
    assert enc.encode_info(aprs.AgreloDf(bearing_degrees=90.4, quality=2.0)) == b"%090/2"
    report = from_neutral(MIC_E)
    assert isinstance(report, aprs.MicEReport)
    assert _code(lambda: enc.encode_info(replace(report, destination_ssid=1.5))) is RefusalCode.VALUE_OUT_OF_RANGE  # type: ignore[arg-type]


def test_a_number_that_is_a_step_field_is_still_rounded() -> None:
    neutral = {**POSITION, "course_degrees": 2.5, "speed_knots": 10.4}
    assert enc.encode_info(from_neutral(neutral)) == POSITION_INFO + b"003/010"


# ---------------------------------------------------------------- every depth, never a crash


def _depth(data: aprs.AprsData, levels: int) -> aprs.AprsData:
    for _ in range(levels):
        data = aprs.ThirdParty(aprs.Packet("N0CALL", "APRS", (), b"", data))
    return data


NAN = float("nan")
INF = float("inf")


@pytest.mark.parametrize("levels", [0, 1, 2, 4])
@pytest.mark.parametrize(
    ("data", "code"),
    [
        (aprs.PositionReport(latitude=NAN, longitude=0, symbol=aprs.Symbol.CAR), RefusalCode.NOT_A_NUMBER),
        (aprs.PositionReport(latitude=0, longitude=INF, symbol=aprs.Symbol.CAR), RefusalCode.NOT_A_NUMBER),
        (
            aprs.PositionReport(latitude=0, longitude=0, symbol=aprs.Symbol.CAR, course_degrees=NAN, speed_knots=1),
            RefusalCode.NOT_A_NUMBER,
        ),
        (
            aprs.PositionReport(latitude=0, longitude=0, symbol=aprs.Symbol.CAR, phg=aprs.Phg(NAN, 1, 3, 2)),
            RefusalCode.NOT_A_NUMBER,
        ),
        (
            aprs.PositionReport(latitude=0, longitude=0, symbol=aprs.Symbol.CAR, course_degrees=400, speed_knots=1),
            RefusalCode.VALUE_OUT_OF_RANGE,
        ),
        (
            aprs.PositionReport(latitude=0, longitude=0, symbol=aprs.Symbol.CAR, phg=aprs.Phg(10, 1, 3, 2)),
            RefusalCode.VALUE_OUT_OF_RANGE,
        ),
        (aprs.PositionReport(latitude=1e308, longitude=0, symbol=aprs.Symbol.CAR), RefusalCode.VALUE_OUT_OF_RANGE),
        (aprs.AgreloDf(bearing_degrees=NAN, quality=1), RefusalCode.NOT_A_NUMBER),
        (aprs.AgreloDf(bearing_degrees=90, quality=NAN), RefusalCode.NOT_A_NUMBER),
        (aprs.AgreloDf(bearing_degrees=900, quality=1), RefusalCode.VALUE_OUT_OF_RANGE),
        (aprs.TelemetryReport("1", (1, 2, 3, 4, NAN), "00000000"), RefusalCode.NOT_A_NUMBER),
    ],
)
def test_every_rule_check_applies_to_inner_data_at_every_depth(
    data: aprs.AprsData, code: RefusalCode, levels: int
) -> None:
    assert _code(lambda: enc.encode_info(_depth(data, levels))) is code


# ---------------------------------------------------------------- empty and absent


def test_null_and_false_in_neutral_data_are_absent() -> None:
    plain = enc.encode_info(from_neutral(POSITION))
    nulls = {**POSITION, "comment": None, "messaging": False, "compressed": False, "phg": None, "timestamp": None}
    assert enc.encode_info(from_neutral(nulls)) == plain
    inner = {"source": "N0CALL", "destination": "APRS", "path": None, "data": {**STATUS, "timestamp": False}}
    assert enc.encode_info(from_neutral({"type": "third-party", "packet": inner})) == b"}N0CALL>APRS:>hi"
    assert enc.encode_info(from_neutral({"type": "message", "addressee": "N0CALL", "text": "hi", "message_id": None}))
    # a null among a list's items is a value
    telemetry = {"type": "telemetry", "sequence": "1", "analog": [1, None, 3, 4, 5], "bits": "00000000"}
    assert b",," in enc.encode_info(from_neutral(telemetry))


@pytest.mark.parametrize("kind", ["ack", "reject"])
def test_an_ack_or_reject_id_absent_or_empty_is_invalid_message_id(kind: str) -> None:
    key = "acked_id" if kind == "ack" else "rejected_id"
    for given in ({}, {key: ""}, {key: None}):
        neutral = {"type": kind, "addressee": "N0CALL", **given}
        assert _code(lambda neutral=neutral: enc.encode_info(from_neutral(neutral))) is RefusalCode.INVALID_MESSAGE_ID


def test_a_builders_empty_values() -> None:
    station = aprs.Station("N0CALL")
    assert _code(lambda: station.ack("N0CALL", "")) is RefusalCode.INVALID_MESSAGE_ID
    assert _code(lambda: station.message("N0CALL", "hi", message_id="")) is RefusalCode.INVALID_MESSAGE_ID
    assert _code(lambda: aprs.Station("N0CALL", destination="").status("hi")) is RefusalCode.INVALID_ADDRESS
    assert station.position(51.5, -0.5, aprs.Symbol.CAR, comment="").info == enc.encode_info(
        aprs.PositionReport(latitude=51.5, longitude=-0.5, symbol=aprs.Symbol.CAR)
    )


# ---------------------------------------------------------------- the comparison, strengthened


def test_a_dao_position_is_compared_in_its_own_steps() -> None:
    neutral = {**POSITION, "latitude": 51.5, "dao": {"datum": "W", "precision": "base91"}}
    data = from_neutral(neutral)
    info = enc.encode_info(data)
    assert rb.mismatch(data, to_neutral(data), info, "APZ001") is None
    shifted = info.replace(b"!w", b"!x", 1) if b"!w" in info else info[:-2] + bytes([info[-2] + 1]) + info[-1:]
    assert shifted != info
    assert rb.mismatch(data, to_neutral(data), shifted, "APZ001") is not None


def test_the_compression_type_given_is_exactly_the_type_read_back() -> None:
    base = {**POSITION, "compressed": True, "course_degrees": 88, "speed_knots": 36}
    typed = base | {"compression": {"fix": "current", "source": "other", "origin": "pico"}}
    data = from_neutral(typed)
    info = enc.encode_info(data)
    assert rb.mismatch(data, to_neutral(data), info, "APZ001") is None
    default_type = enc.encode_info(from_neutral(base))
    # a type given must be the type the bytes carry, not the default the form would add
    assert info[-1] != default_type[-1]
    assert rb.mismatch(data, to_neutral(data), info[:-1] + default_type[-1:], "APZ001") is not None
    # and a default left out is the one the decode carries, not any
    data = from_neutral(base)
    assert rb.mismatch(data, to_neutral(data), info, "APZ001") is not None


def test_a_mic_e_altitude_is_compared_in_whole_metres_and_a_slash_a_exactly() -> None:
    data = from_neutral({**MIC_E, "altitude_feet": 100.5})
    info = enc.encode_info(data)
    destination = enc.mic_e_destination(data)
    assert rb.mismatch(data, to_neutral(data), info, destination) is None
    assert b"/A=" not in info
    bumped = info[:-2] + bytes([info[-2] + 1]) + info[-1:]
    assert rb.mismatch(data, to_neutral(data), bumped, destination) is not None
    # a /A= beside neutral data that gives another value
    held = from_neutral({**MIC_E, "altitude_feet": 100})
    text = enc.encode_info(held)
    assert rb.mismatch(held, to_neutral(held), text, enc.mic_e_destination(held)) is None
    assert rb.mismatch(held, to_neutral(held), text.replace(b"000100", b"000101"), enc.mic_e_destination(held))


def test_a_position_one_step_away_in_any_form_is_refused() -> None:
    assert _mismatch(POSITION | {"ambiguity": 2}, b"!5130.  N/00030.  W>") is None
    assert _mismatch(POSITION | {"ambiguity": 2}, b"!5130.50N/00030.00W>") is not None
    assert _mismatch(POSITION | {"latitude": 51.50004}, POSITION_INFO) is None
    assert _mismatch(POSITION | {"latitude": 51.50009}, POSITION_INFO) is not None


# ---------------------------------------------------------------- a voice offset is never rounded


@pytest.mark.parametrize(
    ("offset", "outcome"),
    [
        (600, b"146.520MHz +060"),
        (-600, b"146.520MHz -060"),
        (0, b"146.520MHz +000"),
        (605, RefusalCode.VALUE_HAS_NO_FORM),
        (-61, RefusalCode.VALUE_HAS_NO_FORM),
        (600.4, RefusalCode.VALUE_OUT_OF_RANGE),
        (600.5, RefusalCode.VALUE_OUT_OF_RANGE),
        (10000, RefusalCode.VALUE_OUT_OF_RANGE),
        (605.5, RefusalCode.VALUE_OUT_OF_RANGE),
    ],
)
def test_a_voice_offset_is_written_as_tens_of_khz_and_never_rounded(offset: float, outcome: object) -> None:
    neutral = POSITION | {"frequency": {"mhz": 146.52, "offset_khz": offset}}
    if isinstance(outcome, RefusalCode):
        assert _code(lambda: enc.encode_info(from_neutral(neutral))) is outcome
    else:
        assert enc.encode_info(from_neutral(neutral)).endswith(outcome)  # type: ignore[arg-type]


# ---------------------------------------------------------------- R27: telemetry is the last valid block


def _comment_of(text: str) -> aprs.PositionReport:
    packet = aprs.decode_tnc2("N0CALL>APZ001:!5130.00N/00030.00W>" + text)
    assert isinstance(packet.data, aprs.PositionReport)
    return packet.data


def test_r27_the_telemetry_is_the_last_valid_block_and_bars_around_text_are_text() -> None:
    live = _comment_of("|!a!'!#|| IGate PCBUnit 2 LoRa |144.190| BW10.4 SF8 CR5")
    assert live.telemetry is not None
    assert live.dao is None
    assert live.comment == "| IGate PCBUnit 2 LoRa |144.190| BW10.4 SF8 CR5"
    two = _comment_of('x|!!!!|y|!"!#|z')
    assert two.telemetry is not None
    assert two.comment == "x|!!!!|yz"
    for text in ("x||y", "x|a b|", "x|!!!|", "x|!!!!!|"):
        data = _comment_of(text)
        assert data.telemetry is None
        assert data.comment == text
    assert _comment_of("x||!!!!|").telemetry is not None
    assert _comment_of("x|y z|!!!!|").comment == "x|y z"
    assert _comment_of("x|!!!!|y z|").comment == "xy z|"


def test_r27_a_dao_after_the_block_is_read_outside_it() -> None:
    data = _comment_of("x|!!!!|!W12!|a b|")
    assert data.telemetry == aprs.CommentTelemetry(0, (0,))
    assert data.dao is not None
    assert data.comment == "x|a b|"
    # the pairs slide, so a block-shaped run holding a DAO-shaped one is the last block
    assert _comment_of("x|!!!!|!W12!y|a b|").dao is None


def test_r27_data_without_telemetry_whose_comment_holds_a_block_is_text_reads_as_field() -> None:
    report = aprs.PositionReport(latitude=51.5, longitude=-0.5, symbol=aprs.Symbol.CAR, comment="x|!!!!|y|a b|")
    assert _code(lambda: enc.encode_info(report)) is RefusalCode.TEXT_READS_AS_FIELD
    # with telemetry the comment's block is text and the telemetry the last block
    with_telemetry = replace(report, telemetry=aprs.CommentTelemetry(1, (2,)))
    info = enc.encode_info(with_telemetry)
    again = aprs.decode_tnc2(b"N0CALL>APZ001:" + info).data
    assert isinstance(again, aprs.PositionReport)
    assert again.telemetry == with_telemetry.telemetry
    assert again.comment == report.comment


def test_r27_many_bars_are_read_in_linear_time() -> None:
    import time

    def took(n: int) -> float:
        line = ("N0CALL>APZ001:!5130.00N/00030.00W>" + "|a" * n).encode()
        best = 1e9
        for _ in range(5):
            t = time.perf_counter()
            aprs.decode_tnc2(line)
            best = min(best, time.perf_counter() - t)
        return best

    small, large = took(20_000), took(80_000)
    assert large < max(small, 0.02) * 12


# ---------------------------------------------------------------- R28 and the second review


def test_r28_an_ambiguity_of_0_is_no_ambiguity() -> None:
    plain = enc.encode_info(from_neutral(POSITION))
    assert enc.encode_info(from_neutral(POSITION | {"ambiguity": 0})) == plain
    assert enc.encode_info(from_neutral(POSITION | {"ambiguity": 0.0})) == plain
    station = aprs.Station("N0CALL", symbol=aprs.Symbol.CAR)
    assert station.position(51.5, -0.5, ambiguity=0).info == station.position(51.5, -0.5).info
    assert station.mic_e(51.5, -0.5, ambiguity=0).info == station.mic_e(51.5, -0.5).info


def test_r28_a_trailing_run_of_line_breaks_is_one_warning_and_a_pass_through_carries_it() -> None:
    held = aprs.decode_tnc2(b"N0CALL>APZ001:>hi\r\n\r\n")
    assert [str(d) for d in held.diagnostics] == ["warning:trailing-line-break"]
    assert held.data == aprs.StatusReport(text="hi")
    assert held.to_tnc2() == b"N0CALL>APZ001:>hi\r\n\r\n"
    assert aprs.decode_tnc2(b"N0CALL>APZ001:>h\ri\r\n").to_tnc2 is not None
    inside = aprs.Packet("N0CALL", "APZ001", (), b">h\ri\r\n", aprs.StatusReport(text="h\ri"))
    assert _code(inside.to_tnc2) is RefusalCode.TNC2_CANNOT_CARRY


def test_r28_test_and_user_defined_data_with_a_line_break_inside_are_written_as_an_information_field() -> None:
    for data, info in ((aprs.TestData("a\rb"), b",a\rb"), (aprs.UserDefined("A", "x", "a\nb"), b"{Axa\nb")):
        assert enc.encode_info(data) == info
        assert _code(lambda data=data: aprs.build_packet("N0CALL", data).to_tnc2()) is RefusalCode.TNC2_CANNOT_CARRY
        assert aprs.build_packet("N0CALL", data).to_ax25().endswith(info)
    for data in (aprs.TestData("ab\n"), aprs.UserDefined("A", "x", "ab\r")):
        assert _code(lambda data=data: enc.encode_info(data)) is RefusalCode.INVALID_CHARACTER


def test_r28_an_out_of_order_inner_path_two_levels_down_is_an_invalid_third_party_header() -> None:
    bad = (aprs.PathEntry("A"), aprs.PathEntry("B", True))
    status = aprs.StatusReport(text="hi")
    one = aprs.ThirdParty(aprs.Packet("N0CALL", "APRS", bad, b"", status))
    two = aprs.ThirdParty(aprs.Packet("N0CALL", "APRS", (), b"", one))
    three = aprs.ThirdParty(aprs.Packet("N0CALL", "APRS", (), b"", two))
    for data in (one, two, three):
        assert _code(lambda data=data: enc.encode_info(data)) is RefusalCode.INVALID_THIRD_PARTY_HEADER


def test_r28_a_corridor_on_an_area_that_is_not_a_line_is_field_not_allowed() -> None:
    area = {"shape": "open-circle", "color": "blue", "lat_offset": 1, "lon_offset": 2, "corridor_width_miles": 3}
    neutral = POSITION | {"symbol": "\\l", "area": area}
    assert _code(lambda: enc.encode_info(from_neutral(neutral))) is RefusalCode.FIELD_NOT_ALLOWED
    line = neutral | {"area": area | {"shape": "line-down-right"}}
    assert b"{3}" in enc.encode_info(from_neutral(line))


def test_n1_an_infinity_in_an_nmea_field_or_an_inner_packet_is_never_written() -> None:
    sentence = "GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    for field in ("latitude", "longitude", "altitude_m"):
        data = aprs.NmeaSentence(sentence=sentence, has_checksum=True, **{field: float("inf")})
        assert _code(lambda data=data: aprs.build_packet("N0CALL", data).to_tnc2()) is RefusalCode.NOT_A_NUMBER
    held = aprs.decode_tnc2(b"N0CALL>APRS:}X>APRS:!5130.00N/00030.00W>088/036")
    assert isinstance(held.data, aprs.ThirdParty)
    inner = held.data.packet
    assert isinstance(inner.data, aprs.PositionReport)
    for kw in ({"latitude": float("inf")}, {"course_degrees": float("-inf")}):
        data = aprs.ThirdParty(replace(inner, data=replace(inner.data, **kw)))
        assert _code(lambda data=data: enc.encode_info(data)) is RefusalCode.NOT_A_NUMBER
    bad = aprs.CommentTelemetry(float("inf"), (1,))  # type: ignore[arg-type]
    report = aprs.PositionReport(latitude=51.5, longitude=-0.5, symbol=aprs.Symbol.CAR, telemetry=bad)
    telemetry = aprs.ThirdParty(aprs.Packet("X", "APRS", (), b"", report))
    assert _code(lambda: enc.encode_info(telemetry)) is RefusalCode.NOT_A_NUMBER


def test_n2_a_whole_number_given_as_a_float_is_that_number_in_legacy_mic_e_telemetry() -> None:
    report = from_neutral(MIC_E)
    assert isinstance(report, aprs.MicEReport)
    assert enc.encode_info(replace(report, legacy_telemetry=(1.0, 1, 2, 3, 4))) == enc.encode_info(
        replace(report, legacy_telemetry=(1, 1, 2, 3, 4))
    )
    assert _code(lambda: enc.encode_info(replace(report, legacy_telemetry=(0.5, 1, 2, 3, 4)))) is (
        RefusalCode.VALUE_OUT_OF_RANGE
    )


def test_n3_repr_and_str_are_total_and_show_what_changes_the_bytes() -> None:
    data: aprs.AprsData = aprs.StatusReport(text="x")
    for _ in range(3000):
        data = aprs.ThirdParty(aprs.Packet("N0CALL", "APRS", (), b"", data))
    assert "..." in repr(data)
    assert isinstance(repr(aprs.Packet("N0CALL", "APRS", (), b"", data)), str)
    assert isinstance(str(aprs.Packet("N0CALL", "APRS", (), b"", data)), str)
    report = from_neutral(MIC_E)
    assert "altitude_in_comment=True" in repr(replace(report, altitude_in_comment=True))  # type: ignore[type-var]


def test_n6_a_kiss_port_is_a_whole_number_and_an_empty_path_entry_is_refused_by_the_station_too() -> None:
    packet = aprs.Station("N0CALL").status("hi")
    for port in (1.5, True, "1", None, -1, 16):
        with pytest.raises(ValueError):  # noqa: PT011
            packet.to_kiss(port)  # type: ignore[arg-type]
    assert packet.to_kiss(3)
    assert _code(lambda: aprs.Station("N0CALL", path="A,,B").status("hi")) is RefusalCode.INVALID_ADDRESS
    assert _code(lambda: aprs.build_packet("N0CALL", aprs.StatusReport("hi"), path=["A", "", "B"])) is (
        RefusalCode.INVALID_ADDRESS
    )
    assert aprs.Station("N0CALL", path="").status("hi").path == ()


# ---------------------------------------------------------------- reading under the header written

MIC_E_SHAPED = b'`(_fn"Oj/'


def _raw(destination: str) -> aprs.Packet:
    """Undecoded bytes shaped like Mic-E, held with the error they were decoded with, under a destination."""
    held = aprs.decode_tnc2(b"N0CALL>APZ001:" + MIC_E_SHAPED)
    assert isinstance(held.data, aprs.Unrecognized)
    return replace(held, destination=destination)


def test_raw_bytes_shaped_like_mic_e_are_refused_under_a_destination_that_makes_them_mic_e() -> None:
    plain, mic_e = _raw("APZ001"), _raw("S32U6T")
    assert plain.to_tnc2() == b'N0CALL>APZ001:`(_fn"Oj/'
    assert plain.to_ax25()
    for write in (mic_e.to_tnc2, mic_e.to_ax25, mic_e.to_kiss, lambda: mic_e.header):
        assert _code(write) is RefusalCode.NOT_ENCODABLE
    # as a third-party inner packet, written under its own header and on its own
    assert enc.encode_info(aprs.ThirdParty(plain)) == b'}N0CALL>APZ001:`(_fn"Oj/'
    assert _code(lambda: enc.encode_info(aprs.ThirdParty(mic_e))) is RefusalCode.NOT_ENCODABLE
    assert _code(lambda: enc.encode_info(_depth(aprs.ThirdParty(mic_e), 1))) is RefusalCode.NOT_ENCODABLE


def test_a_held_packet_re_addressed_in_either_direction_is_read_under_the_new_header() -> None:
    held = aprs.decode_tnc2(b'N0CALL>APZ001:`(_fn"Oj/')
    assert _code(replace(held, destination="S32U6T").to_tnc2) is RefusalCode.NOT_ENCODABLE
    assert replace(held, destination="APRS").to_tnc2() == b'N0CALL>APRS:`(_fn"Oj/'
    report = aprs.decode_tnc2(b'N0CALL>S32U6T:`(_fn"Oj/')
    assert isinstance(report.data, aprs.MicEReport)
    assert _code(replace(report, destination="APZ001").to_ax25) is RefusalCode.NOT_ENCODABLE
    assert report.to_tnc2() == b'N0CALL>S32U6T:`(_fn"Oj/'


def test_inner_mic_e_data_is_written_under_the_destination_it_computes_and_no_other() -> None:
    report = from_neutral(MIC_E)
    assert isinstance(report, aprs.MicEReport)
    computed = enc.mic_e_destination(report)
    written = enc.encode_info(aprs.ThirdParty(aprs.Packet("N0CALL", computed, (), b"", report)))
    assert written.startswith(f"}}N0CALL>{computed}:".encode())
    assert _code(lambda: enc.encode_info(aprs.ThirdParty(aprs.Packet("N0CALL", "APRS", (), b"", report)))) is (
        RefusalCode.NOT_ENCODABLE
    )


def test_a_held_mic_e_report_re_addressed_to_another_mic_e_destination_is_not_encodable() -> None:
    held = aprs.decode_tnc2(b'N0CALL>S32U6T:`(_fn"Oj/')
    assert isinstance(held.data, aprs.MicEReport)
    assert held.to_tnc2() == b'N0CALL>S32U6T:`(_fn"Oj/'
    for destination in ("S32U7T", "S32U6T-3", "S32V6T", "S32U6U", "T32U6T"):
        again = replace(held, destination=destination)
        for write in (again.to_tnc2, again.to_ax25, again.to_kiss):
            assert _code(write) is RefusalCode.NOT_ENCODABLE, destination


def test_a_builder_mic_e_packet_with_a_latitude_between_steps_and_no_ssid_is_written_under_its_destination() -> None:
    packet = aprs.Station("N0CALL", symbol=aprs.Symbol.CAR).mic_e(
        51.45751234, -0.98114, speed_knots=12, course_degrees=94
    )
    assert packet.to_tnc2()
    assert packet.to_ax25()
    assert "-" not in packet.destination
    report = packet.data
    assert isinstance(report, aprs.MicEReport)
    assert replace(packet, data=replace(report, destination_ssid=0)).to_tnc2() == packet.to_tnc2()
    with_ssid = aprs.Station("N0CALL", symbol=aprs.Symbol.CAR).mic_e(51.4575, -0.9811)
    assert isinstance(with_ssid.data, aprs.MicEReport)
    assert _code(replace(with_ssid, destination=with_ssid.destination + "-3").to_tnc2) is RefusalCode.NOT_ENCODABLE


# ---------------------------------------------------------------- the differential run's findings


def test_a_non_finite_number_in_a_field_the_report_has_no_place_for_is_not_a_number() -> None:
    weather = {"wind_direction_degrees": 220, "wind_speed_mph": 4, "temperature_f": 77}
    base = {"type": "position", "latitude": -62.7, "longitude": 109.9, "symbol": "/_", "weather": weather}
    nan, inf = float("nan"), float("inf")
    for extra in (
        {"altitude_feet": nan, "comment": "\n"},
        {"telemetry": {"sequence": 8281, "analog": [nan]}},
        {"telemetry": {"sequence": 1, "analog": [inf]}},
        {"frequency": {"mhz": inf}},
    ):
        assert _code(lambda extra=extra: enc.encode_info(from_neutral(base | extra))) is RefusalCode.NOT_A_NUMBER
    # a code that comes first in the order still wins
    named = base | {"altitude_feet": nan}
    assert _code(lambda: enc.encode_info(from_neutral(named | {"timestamp": "bad"}))) is RefusalCode.INVALID_TIMESTAMP


def test_inner_mic_e_with_a_nan_longitude_is_not_a_number_and_a_mismatch_comes_after_the_rules() -> None:
    inner = {
        "type": "mic-e",
        "mic_e_message": "returning",
        "latitude": 33.42733333333334,
        "longitude": float("nan"),
        "symbol": "/j",
        "course_degrees": 88,
        "speed_knots": 36,
    }
    wrapped = {"type": "third-party", "packet": {"source": "N0CALL", "destination": "S32U6T", "data": inner}}
    assert _code(lambda: enc.encode_info(from_neutral(wrapped))) is RefusalCode.NOT_A_NUMBER
    # a mismatch found by the read-back loses to an inner header fault and to a data rule
    finite = inner | {"longitude": -12.129, "latitude": -90.0}
    bad_path = {"source": "N0CALL", "destination": "S32U6T", "data": finite, "path": ["TC+IP*"]}
    assert _code(lambda: enc.encode_info(from_neutral({"type": "third-party", "packet": bad_path}))) is (
        RefusalCode.INVALID_THIRD_PARTY_HEADER
    )
    wrong = {"source": "N0CALL", "destination": "APRS", "data": inner | {"longitude": -12.129, "course_degrees": 400}}
    assert _code(lambda: enc.encode_info(from_neutral({"type": "third-party", "packet": wrong}))) is (
        RefusalCode.VALUE_OUT_OF_RANGE
    )


# ---------------------------------------------------------------- a defect of one entry is listed once for each


def _codes(packet: aprs.Packet) -> list[str]:
    return [str(d) for d in packet.diagnostics]


def test_a_defect_of_one_path_entry_is_listed_once_for_each_and_a_judgement_of_the_whole_once() -> None:
    assert _codes(aprs.decode_tnc2(b"N0CALL>APZ001,,A,,B:>x")).count("warning:empty-path-entry") == 2
    assert _codes(aprs.decode_tnc2(b"N0CALL>APZ001,A,:>x")).count("warning:empty-path-entry") == 1
    held = aprs.decode_tnc2(b"N0CALL>APRS:}X>Y,,A,,B:>x")
    assert isinstance(held.data, aprs.ThirdParty)
    assert _codes(held.data.packet).count("warning:empty-path-entry") == 2
    # several used markers are one judgement of the path
    assert _codes(aprs.decode_tnc2(b"N0CALL>APZ001,A*,B*,C*:>x")).count("warning:multiple-used-markers") == 1

    # and in a frame, one for each empty address
    def address(name: str, *, last: bool = False) -> bytes:
        return bytes(ord(c) << 1 for c in name.ljust(6)) + bytes([0x60 | (1 if last else 0)])

    frame = (
        address("APZ001") + address("N0CALL") + address("") + address("WIDE1") + address("", last=True) + b"\x03\xf0>x"
    )
    assert _codes(aprs.decode_ax25(frame)).count("warning:empty-path-entry") == 2
    # strict stops at the first defect it rejects by
    with pytest.raises(aprs.HeaderError) as caught:
        aprs.decode_tnc2(b"N0CALL>APZ001,,A,,B:>x", aprs.ParseOptions.strict())
    assert len(caught.value.diagnostics) == 1
