"""The public API beyond what the conformance vectors check: the builder, AX.25 and KISS, parse
options, symbols, devices, timestamps and the encoder's refusals."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import packet_aprs as aprs
from packet_aprs import (
    DiagnosticCode,
    EncodeError,
    HeaderError,
    MicEMessage,
    ParseOptions,
    Severity,
    Station,
    Symbol,
    Timestamp,
    TimestampKind,
)
from packet_aprs.neutral import from_neutral, to_neutral


def _round_trip(packet: aprs.Packet) -> aprs.Packet:
    """Decode a built packet again: it must read back as the same data, without defects."""
    again = aprs.decode(packet.to_tnc2())
    assert not [d for d in again.diagnostics if d.severity is not Severity.INFO], again.diagnostics
    assert _close(to_neutral(again.data), to_neutral(packet.data)), (to_neutral(again.data), to_neutral(packet.data))
    return again


def _close(a: object, b: object) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, float) or isinstance(b, float):
        # the built data may carry more precision than the format: within its resolution
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) < 0.01
    return a == b


STATION = Station("M0LTE-9", via="WIDE1-1,WIDE2-1", symbol=Symbol.CAR, messaging=True)


@pytest.mark.parametrize(
    "packet",
    [
        STATION.position(51.45, -0.98, course=88, speed=36, altitude=120, comment="Mobile"),
        STATION.position(-33.8688, 151.2093, timestamp=Timestamp.dhm(1, 2, 3), comment="Sydney"),
        STATION.position(51.45, -0.98, compressed=True, course=88, speed=0),
        STATION.position(51.4512, -0.9812, frequency=145.5, tone=77, offset_khz=-600, comment="QRV"),
        STATION.position(51.45, -0.98, ambiguity=2),
        STATION.position(51.45, -0.98, comment=" starts with a space"),
        STATION.position(51.45, -0.98, comment="088/036 looks like course and speed"),
        STATION.object("LEADER", 49.0583, -72.0292, timestamp=Timestamp.dhm(9, 23, 45), course=88, speed=36),
        STATION.object("LEADER", 49.0583, -72.0292, timestamp=Timestamp.dhm(9, 23, 45), killed=True),
        STATION.item("AID #2", 49.0583, -72.0292, Symbol.AID_STATION),
        STATION.mic_e(51.4575, -0.9811, speed=12, course=94, comment="Hello"),
        STATION.mic_e(-33.8688, 151.2093, message=MicEMessage.EMERGENCY, speed=0),
        STATION.mic_e(42.3, -71.3, speed=153, course=200, altitude=5787.401574803149),
        STATION.weather(49.05, -72.03, wind_direction=220, wind_speed=4, gust=5, temperature=-7, humidity=100),
        STATION.weather(wind_direction=220, wind_speed=4, gust=5, temperature=77, timestamp=Timestamp.mdhm(1, 2, 3, 4)),
        STATION.message("G4ABC", "Hello", message_id="1"),
        STATION.message("G4ABC", "Hi", message_id="01", reply_ack=""),
        STATION.ack("G4ABC", "1"),
        STATION.reject("G4ABC", "1"),
        STATION.bulletin("1", "Net tonight at eight"),
        STATION.bulletin("4", "Snow", group="WX"),
        STATION.status("On the air"),
        STATION.status(locator="IO91SX", symbol=Symbol.GRID_SQUARE),
        STATION.telemetry(5, [199, 0, 255, 73, 123], "01101001"),
        STATION.telemetry("MIC", [1.5, None, 3, 4, 5]),
        STATION.telemetry_names(["Battery", "Temp"]),
        STATION.telemetry_units(["V", "degC"]),
        STATION.telemetry_coefficients([0, 5.2, 0, 0, 0.53, -32]),
        STATION.telemetry_bits("10110000", "Balloon"),
    ],
)
def test_built_packets_read_back(packet: aprs.Packet) -> None:
    _round_trip(packet)


def test_station_needs_a_symbol() -> None:
    with pytest.raises(ValueError, match="symbol"):
        Station("M0LTE").position(51.0, 0.0)


def test_station_path_forms() -> None:
    assert Station("M0LTE", via="WIDE1-1, WIDE2-1").path == ("WIDE1-1", "WIDE2-1")
    assert Station("M0LTE", via=["WIDE1-1"]).path == ("WIDE1-1",)


def test_timestamp_from_datetime() -> None:
    moment = datetime(2026, 9, 26, 14, 5, 9, tzinfo=timezone.utc)
    packet = STATION.position(51.0, 0.0, timestamp=moment)
    assert isinstance(packet.data, aprs.PositionReport)
    assert packet.data.timestamp == Timestamp("261405z")


def test_mic_e_destination_is_computed() -> None:
    packet = STATION.mic_e(
        33.42733333333334, -112.129, Symbol.JEEP, message=MicEMessage.RETURNING, speed=20, course=251
    )
    assert packet.destination == "S32UVT"


# ---------------------------------------------------------------- AX.25 and KISS


def test_ax25_round_trip() -> None:
    packet = STATION.position(51.45, -0.98, comment="Mobile")
    again = aprs.decode_ax25(packet.to_ax25())
    assert str(again) == str(packet)


def test_kiss_round_trip_with_escapes() -> None:
    data = aprs.UserDefined("{", "x", "\xc0\xdb\x00")
    packet = aprs.build_packet("M0LTE", data)
    frame = packet.to_kiss()
    assert frame.startswith(b"\xc0\x00")
    assert frame.endswith(b"\xc0")
    assert b"\xc0" not in frame[1:-1]
    again = aprs.decode_kiss(frame)
    assert again.data == data


def test_ax25_needs_ax25_addresses() -> None:
    packet = aprs.decode("M0LTE>APZ001,TCPIP*,qAC,T2TEST:>hi")
    with pytest.raises(EncodeError, match=r"AX\.25"):
        packet.to_ax25()


def test_kiss_rejects_non_data_frames() -> None:
    with pytest.raises(HeaderError):
        aprs.decode_kiss(b"\xc0\x01\x00\xc0")


# ---------------------------------------------------------------- decoding


def test_decode_str_and_bytes_agree() -> None:
    line = "N0CALL>APZ001:>73 de M0LTE °"
    assert aprs.decode(line).data == aprs.decode(line.encode("utf-8")).data


def test_header_error_carries_diagnostics() -> None:
    with pytest.raises(HeaderError) as info:
        aprs.decode("no header at all")
    assert [str(d) for d in info.value.diagnostics] == ["error:invalid-header"]


def test_non_utf8_text_is_latin1_with_a_warning() -> None:
    packet = aprs.decode(b"N0CALL>APZ001:>DX: 67\xf8 22:18")
    assert isinstance(packet.data, aprs.StatusReport)
    assert packet.data.text == "DX: 67ø 22:18"
    assert [str(d) for d in packet.diagnostics] == ["warning:non-utf8-text"]


def test_warnings_and_errors() -> None:
    packet = aprs.decode("N0CALL>APZ001:!4903.50n/07201.75W-")
    assert [d.code for d in packet.warnings] == [DiagnosticCode.LOWERCASE_HEMISPHERE]
    assert packet.errors == ()


# ---------------------------------------------------------------- options


def test_parse_options() -> None:
    lenient = ParseOptions.lenient()
    assert lenient.tolerates(DiagnosticCode.NON_UTF8_TEXT)
    assert not ParseOptions.strict().tolerates(DiagnosticCode.NON_UTF8_TEXT)
    assert ParseOptions.strict().is_strict
    only = ParseOptions.strict().tolerating(DiagnosticCode.NON_UTF8_TEXT)
    assert only.tolerated == frozenset({DiagnosticCode.NON_UTF8_TEXT})
    assert not lenient.without(DiagnosticCode.NON_UTF8_TEXT).tolerates(DiagnosticCode.NON_UTF8_TEXT)
    with pytest.raises(ValueError, match="not tolerable"):
        ParseOptions(frozenset({DiagnosticCode.INVALID_HEADER}))


def test_every_tolerable_code_is_known() -> None:
    assert len([c for c in DiagnosticCode if c.tolerable]) == 32
    assert len(DiagnosticCode) == 64
    assert aprs.Diagnostic.parse("warning:non-utf8-text").code is DiagnosticCode.NON_UTF8_TEXT


# ---------------------------------------------------------------- symbols, devices, timestamps


def test_symbols() -> None:
    assert Symbol("/", ">") == Symbol.CAR
    assert Symbol.from_name("Car") is Symbol.CAR
    assert Symbol.parse("3>").base == Symbol.OVERLAY_VEHICLE
    assert Symbol.parse("3>").overlay == "3"
    assert Symbol.parse("3>").name == "OVERLAY_VEHICLE"
    with pytest.raises(ValueError, match="alternate"):
        Symbol.CAR.with_overlay("3")
    with pytest.raises(ValueError, match="overlay"):
        Symbol.OVERLAY_VEHICLE.with_overlay("x")
    with pytest.raises(ValueError, match="no symbol"):
        Symbol.from_name("teapot")
    assert not Symbol("x", "-").is_valid


def test_devices() -> None:
    device = aprs.decode("N0CALL>APDW18:>hi").device
    assert device is not None
    assert (device.vendor, device.model) == ("WB2OSZ", "DireWolf")
    assert aprs.decode("N0CALL>APZZZZ:>hi").device is not None
    assert aprs.decode("N0CALL>QQQQQQ:>hi").device is None


def test_timestamps() -> None:
    assert Timestamp("092345z").kind is TimestampKind.DHM_ZULU
    assert Timestamp("092345/").kind is TimestampKind.DHM_LOCAL
    hms = Timestamp("234517h")
    assert (hms.hour, hms.minute, hms.second) == (23, 45, 17)
    mdhm = Timestamp("10090556")
    assert (mdhm.month, mdhm.day, mdhm.hour, mdhm.minute) == (10, 9, 5, 56)
    assert Timestamp("092345z").is_valid
    assert not Timestamp("204140z").is_valid
    assert not Timestamp("ABCDEFz").is_valid


# ---------------------------------------------------------------- encoder refusals


@pytest.mark.parametrize(
    "data",
    [
        aprs.Message("N0CALL", "a{b"),
        aprs.Message("TOOLONGCALL", "x"),
        aprs.Message("N0CALL", "x", message_id="toolong"),
        aprs.Ack("N0CALL", ""),
        aprs.StatusReport("x", Timestamp("010203h")),
        aprs.TelemetryReport("001", (1, 2, 3, 4), "00000000"),
        aprs.TelemetryBits("N0CALL", "11111111", "x" * 24),
        aprs.PositionReport(latitude=91, longitude=0, symbol=Symbol.HOUSE),
        aprs.PositionReport(latitude=0, longitude=0, symbol=Symbol.HOUSE, comment="a\rb"),
        aprs.ObjectReport(latitude=0, longitude=0, symbol=Symbol.HOUSE, name="X"),
        aprs.ItemReport(latitude=0, longitude=0, symbol=Symbol.HOUSE, name="AB"),
        aprs.MicEReport(latitude=0, longitude=0, symbol=Symbol.CAR, mic_e_message=MicEMessage.UNKNOWN),
        aprs.Unrecognized(aprs.UnrecognizedReason.MALFORMED),
    ],
)
def test_encoder_refuses(data: aprs.AprsData) -> None:
    with pytest.raises(EncodeError):
        aprs.encode_info(data)


def test_neutral_round_trip() -> None:
    packet = aprs.decode("N1JCM-9>TRQP7T,WA1PLE-4*:`c'wl|+>/`\"4-}_%")
    assert from_neutral(to_neutral(packet.data)) == packet.data
