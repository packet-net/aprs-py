"""The public API beyond what the conformance vectors check: the builder, AX.25 and KISS, parse
options, symbols, devices, timestamps and the encoder's refusals."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import pdn_aprs as aprs
from pdn_aprs import (
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
    ToneType,
    VoiceFrequency,
)
from pdn_aprs._neutral import NeutralFormError, from_neutral, to_neutral


def _round_trip(packet: aprs.Packet) -> aprs.Packet:
    """Decode a built packet again: it must read back as the same data, without defects."""
    again = aprs.decode_tnc2(packet.to_tnc2())
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


STATION = Station("M0LTE-9", path="WIDE1-1,WIDE2-1", symbol=Symbol.CAR, messaging=True)


@pytest.mark.parametrize(
    "packet",
    [
        STATION.position(51.45, -0.98, course_degrees=88, speed_knots=36, altitude_feet=120, comment="Mobile"),
        STATION.position(-33.8688, 151.2093, timestamp=Timestamp.dhm(1, 2, 3), comment="Sydney"),
        STATION.position(51.45, -0.98, compressed=True, course_degrees=88, speed_knots=0),
        STATION.position(
            51.4512,
            -0.9812,
            frequency=VoiceFrequency(145.5, tone=ToneType.TONE, tone_value=77, offset_khz=-600),
            comment="QRV",
        ),
        STATION.position(51.45, -0.98, ambiguity=2),
        STATION.position(51.45, -0.98, comment=" starts with a space"),
        STATION.position(51.45, -0.98, comment="088/036 looks like course and speed"),
        STATION.object(
            "LEADER", 49.0583, -72.0292, timestamp=Timestamp.dhm(9, 23, 45), course_degrees=88, speed_knots=36
        ),
        STATION.object("LEADER", 49.0583, -72.0292, timestamp=Timestamp.dhm(9, 23, 45), killed=True),
        STATION.item("AID #2", 49.0583, -72.0292, Symbol.AID_STATION),
        STATION.mic_e(51.4575, -0.9811, speed_knots=12, course_degrees=94, comment="Hello"),
        STATION.mic_e(-33.8688, 151.2093, mic_e_message=MicEMessage.EMERGENCY, speed_knots=0),
        STATION.mic_e(42.3, -71.3, speed_knots=153, course_degrees=200, altitude_m=1764),
        STATION.weather(
            49.05,
            -72.03,
            wind_direction_degrees=220,
            wind_speed_mph=4,
            wind_gust_mph=5,
            temperature_f=-7,
            humidity_percent=100,
        ),
        STATION.weather(
            wind_direction_degrees=220,
            wind_speed_mph=4,
            wind_gust_mph=5,
            temperature_f=77,
            timestamp=Timestamp.mdhm(1, 2, 3, 4),
        ),
        STATION.message("G4ABC", "Hello", message_id="1"),
        STATION.message("G4ABC", "Hi", message_id="01", reply_ack=""),
        STATION.ack("G4ABC", "1"),
        STATION.reject("G4ABC", "1"),
        STATION.bulletin("1", "Net tonight at eight"),
        STATION.bulletin("4", "Snow", group="WX"),
        STATION.status("On the air"),
        STATION.status(locator="IO91SX", symbol=Symbol.GRID_SQUARE),
        STATION.telemetry(5, [199, 0, 255, 73, 123], "01101001"),
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


def test_station_metric_units() -> None:
    packet = STATION.position(51.45, -0.98, course_degrees=88, speed_kmh=100, altitude_m=30.48)
    assert packet.info.endswith(b">088/054/A=000100")
    assert STATION.mic_e(51.45, -0.98, speed_kmh=18.52).data == STATION.mic_e(51.45, -0.98, speed_knots=10).data
    weather = STATION.weather(49.05, -72.03, temperature_c=25, rain_1h_mm=25.4)
    assert b"t077r100" in weather.info
    with pytest.raises(ValueError, match="both units"):
        STATION.position(51.45, -0.98, speed_knots=10, speed_kmh=18.52)


def test_station_mic_e_altitude_in_metres_or_feet() -> None:
    # B2: metres go in the Mic-E altitude bytes, rounded to the metre; feet in a /A=
    in_metres = STATION.mic_e(51.45, -0.98, altitude_m=100.4)
    assert in_metres.info.endswith(b'"4{}')
    assert isinstance(in_metres.data, aprs.MicEReport)
    for feet, written in ((0, b"/A=000000"), (1250, b"/A=001250"), (-12.5, b"/A=-00013")):
        assert STATION.mic_e(51.45, -0.98, altitude_feet=feet).info.endswith(written)


@pytest.mark.parametrize("course", [0, 0.3])
def test_station_course_0_is_unknown(course: float) -> None:
    # B1: a builder's course of 0 is the spec's unknown; north is 360
    assert STATION.position(51.45, -0.98, course_degrees=course, speed_knots=5).info.endswith(b">000/005")
    mic_e = STATION.mic_e(51.45, -0.98, course_degrees=course, speed_knots=5)
    assert isinstance(mic_e.data, aprs.MicEReport)
    assert mic_e.data.course_degrees is None
    assert aprs.decode_tnc2(mic_e.to_tnc2()).data == mic_e.data
    with pytest.raises(EncodeError):
        STATION.position(51.45, -0.98, course_degrees=course, speed_knots=5, compressed=True)


def test_station_telemetry_sequence_over_999_is_refused() -> None:
    # B6: refused, not wrapped
    assert STATION.telemetry(999, [1, 2, 3, 4, 5]).info.startswith(b"T#999,")
    with pytest.raises(EncodeError, match="0-999"):
        STATION.telemetry(1000, [1, 2, 3, 4, 5])
    with pytest.raises(EncodeError):
        STATION.telemetry(-1, [1, 2, 3, 4, 5])


def test_mic_e_altitude_in_comment_is_set_by_the_decoder() -> None:
    # D8: data says how its altitude is written, so a copy encodes to the same bytes
    in_feet = STATION.mic_e(51.45, -0.98, altitude_feet=100.5, comment="x")
    decoded = aprs.decode_tnc2(str(in_feet)).data
    assert isinstance(decoded, aprs.MicEReport)
    assert decoded.altitude_in_comment
    assert aprs.encode_info(decoded) == in_feet.info
    in_metres = aprs.decode_tnc2(str(STATION.mic_e(51.45, -0.98, altitude_m=100, comment="x"))).data
    assert isinstance(in_metres, aprs.MicEReport)
    assert not in_metres.altitude_in_comment


def test_one_voice_frequency_keyword() -> None:
    # D4: MHz or a whole VoiceFrequency, rounded to the field's step, never a bare tone
    assert STATION.position(51.45, -0.98, frequency=145.5).info.endswith(b"145.500MHz")
    assert STATION.position(51.45, -0.98, frequency=145.5004).info.endswith(b"145.500MHz")
    with pytest.raises(TypeError):
        STATION.position(51.45, -0.98, frequency=145.5, tone=77)  # type: ignore[call-arg]


def test_public_surface_after_cleanup() -> None:
    assert aprs.DEFAULT_DESTINATION == "APZ001"
    assert aprs.MESSAGE_TEXT_LIMIT == 67
    assert aprs.DATABASE_VERSION
    assert not hasattr(aprs, "decode")
    assert not hasattr(aprs, "Fix")
    assert not hasattr(aprs, "NmeaSource")
    assert aprs.Phg(3, 3, 3, 3, None).gain_db == 3
    assert aprs.PathEntry("WIDE1-1", True).address == "WIDE1-1"
    assert issubclass(NeutralFormError, aprs.AprsError)
    with pytest.raises(ImportError):
        __import__("pdn_aprs.neutral")


def test_bulletin_id_and_telemetry_sequence_checks() -> None:
    with pytest.raises(EncodeError):
        STATION.bulletin("12", "x")
    with pytest.raises(EncodeError):
        STATION.bulletin("", "x")
    assert aprs.decode_tnc2(str(STATION.bulletin("1", "x"))).data.id == "1"  # type: ignore[attr-defined]
    for bad in ("5", True, 1.0):
        with pytest.raises(TypeError):
            STATION.telemetry(bad, [1, 2, 3, 4, 5])  # type: ignore[arg-type]


def test_altitude_in_comment_follows_the_lifted_slash_a() -> None:
    # Mic-E altitude bytes and a /A= together: the /A= is what is read, so it is what is written
    both = aprs.decode_tnc2('N0CALL>S32UVT:`(_fn"Oj/]"4{}/A=000101x').data
    assert isinstance(both, aprs.MicEReport)
    assert both.altitude_feet == 101
    assert both.altitude_in_comment
    assert aprs.encode_info(both).endswith(b"/A=000101x")


def test_station_path_forms() -> None:
    assert Station("M0LTE", path="WIDE1-1, WIDE2-1").path == ("WIDE1-1", "WIDE2-1")
    assert Station("M0LTE", path=["WIDE1-1"]).path == ("WIDE1-1",)


def test_timestamp_from_datetime() -> None:
    moment = datetime(2026, 9, 26, 14, 5, 9, tzinfo=timezone.utc)
    packet = STATION.position(51.0, 0.0, timestamp=moment)
    assert isinstance(packet.data, aprs.PositionReport)
    assert packet.data.timestamp == Timestamp("261405z")


def test_mic_e_destination_is_computed() -> None:
    packet = STATION.mic_e(
        33.42733333333334,
        -112.129,
        Symbol.JEEP,
        mic_e_message=MicEMessage.RETURNING,
        speed_knots=20,
        course_degrees=251,
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
    packet = aprs.decode_tnc2("M0LTE>APZ001,TCPIP*,qAC,T2TEST:>hi")
    with pytest.raises(EncodeError, match=r"AX\.25"):
        packet.to_ax25()


def test_kiss_rejects_non_data_frames() -> None:
    with pytest.raises(HeaderError):
        aprs.decode_kiss(b"\xc0\x01\x00\xc0")


# ---------------------------------------------------------------- decoding


def test_decode_str_and_bytes_agree() -> None:
    line = "N0CALL>APZ001:>73 de M0LTE °"
    assert aprs.decode_tnc2(line).data == aprs.decode_tnc2(line.encode("utf-8")).data


def test_header_error_carries_diagnostics() -> None:
    with pytest.raises(HeaderError) as info:
        aprs.decode_tnc2("no header at all")
    assert [str(d) for d in info.value.diagnostics] == ["error:invalid-header"]


def test_non_utf8_text_is_latin1_with_a_warning() -> None:
    packet = aprs.decode_tnc2(b"N0CALL>APZ001:>DX: 67\xf8 22:18")
    assert isinstance(packet.data, aprs.StatusReport)
    assert packet.data.text == "DX: 67ø 22:18"
    assert [str(d) for d in packet.diagnostics] == ["warning:non-utf8-text"]


def test_warnings_and_errors() -> None:
    packet = aprs.decode_tnc2("N0CALL>APZ001:!4903.50n/07201.75W-")
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
    device = aprs.decode_tnc2("N0CALL>APDW18:>hi").device
    assert device is not None
    assert (device.vendor, device.model) == ("WB2OSZ", "DireWolf")
    assert aprs.decode_tnc2("N0CALL>APZZZZ:>hi").device is not None
    assert aprs.decode_tnc2("N0CALL>QQQQQQ:>hi").device is None


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
        # each of these would read back as different data
        aprs.PositionReport(
            latitude=0, longitude=0, symbol=Symbol.HOUSE, dao=aprs.Dao("3", aprs.DaoPrecision.THOUSANDTHS)
        ),
        aprs.PositionReport(
            latitude=0,
            longitude=0,
            symbol=Symbol("5", "l"),
            area=aprs.AreaObject(aprs.AreaShape.OPEN_ELLIPSE, aprs.AreaColor.BLACK, 1, 1),
        ),
        aprs.PositionReport(
            latitude=0, longitude=0, symbol=Symbol.HOUSE, telemetry=aprs.CommentTelemetry(0, (0, 0, 0, 0, 0), 256)
        ),
        aprs.PositionReport(latitude=0, longitude=0, symbol=Symbol("\\", "m"), signpost="\xff"),
        aprs.StatusReport("x", beam=aprs.Beam("B", "0")),
        aprs.Bulletin("BLNe", "x"),
        aprs.Capabilities((("MSG_CNT", "4\x1c3"),)),
        aprs.Capabilities((("MSG_CNT", " 43"),)),
        aprs.Query("APRS", aprs.Footprint(100.02, -117.15, 200)),
        aprs.AgreloDf(361, 0),
        aprs.TelemetryCoefficients("N0CALL", (0, float("inf"), 0)),
        aprs.NmeaSentence("GPGLL,2554.459,N,08020.187,W,154027.281,A", comment="/no checksum"),
        aprs.NmeaSentence("GPGLL,2554.459,N,08020.187,W,154027.281,A", latitude=1.0, longitude=1.0),
        aprs.TelemetryCoefficients("BLN1", (0, 1, 0)),
        aprs.TelemetryNames("NWS-WARN", ("Temp",)),
        aprs.DirectedQuery("BLN1", "APRSP"),
        # a line break at the end of a packet is a tolerated defect, not data
        aprs.UserDefined("Q", "1", "data\r"),
    ],
)
def test_encoder_refuses(data: aprs.AprsData) -> None:
    with pytest.raises(EncodeError):
        aprs.encode_info(data)


def test_nmea_comment_after_checksum() -> None:
    line = "N0CALL>APT311:$GPRMC,204717,A,3242.4549,N,08527.2835,W,000,340,090207,,*0C/Home Station by TinyTrack"
    packet = aprs.decode_tnc2(line)
    assert isinstance(packet.data, aprs.NmeaSentence)
    assert packet.data.sentence.endswith(",*0C")
    assert packet.data.comment == "/Home Station by TinyTrack"
    assert aprs.encode_info(packet.data) == packet.info
    assert from_neutral(to_neutral(packet.data)) == packet.data


@pytest.mark.parametrize(
    ("snow", "text"),
    [(0.32, "s.32"), (0.05, "s.05"), (1.5, "s1.5"), (12, "s012"), (0.3, "s.30"), (0.5, "s.50"), (2, "s002")],
)
def test_snowfall_is_written_exactly(snow: float, text: str) -> None:
    info = aprs.encode_info(aprs.PositionlessWeather(Timestamp("10090556"), aprs.Weather(snow_24h_in=snow)))
    assert info.endswith(text.encode())
    assert aprs.decode_tnc2(b"N0CALL>APZ001:" + info).data == aprs.PositionlessWeather(
        Timestamp("10090556"), aprs.Weather(snow_24h_in=snow)
    )


@pytest.mark.parametrize("snow", [999.5, 1000, -1])
def test_snowfall_that_rounds_past_three_digits_is_refused(snow: float) -> None:
    with pytest.raises(EncodeError):
        aprs.encode_info(aprs.PositionlessWeather(Timestamp("10090556"), aprs.Weather(snow_24h_in=snow)))


@pytest.mark.parametrize(
    ("snow", "text"),
    [(12.5, b"s013"), (0.325, b"s.33"), (0.995, b"s001"), (9.96, b"s010"), (9.94, b"s9.9"), (0.001, b"s000")],
)
def test_snowfall_is_rounded_into_its_three_forms(snow: float, text: bytes) -> None:
    # F3: hundredths if under 1, else tenths if under 10, else whole; a whole result in three digits
    info = aprs.encode_info(aprs.PositionlessWeather(Timestamp("10090556"), aprs.Weather(snow_24h_in=snow)))
    assert info.endswith(text)


@pytest.mark.parametrize(
    ("latitude", "longitude", "info"),
    [
        (34.02, -117.15, b"?APRS? 34.02,-117.15,0200"),
        (-34.02, 117.15, b"?APRS?-34.02, 117.15,0200"),
    ],
)
def test_footprint_space_only_before_a_positive_value(latitude: float, longitude: float, info: bytes) -> None:
    query = aprs.Query("APRS", aprs.Footprint(latitude, longitude, 200))
    assert aprs.encode_info(query) == info
    assert aprs.decode_tnc2(b"N0CALL>APZ001:" + info).data == query
    assert isinstance(aprs.decode_tnc2("N0CALL>APZ001:?APRS? 34.02,- 17.15,0200").data, aprs.Unrecognized)


@pytest.mark.parametrize(
    "info", ["?APRS? 34.0,-117.15,0200", "?APRS? 34.360,-.1715,0200", "?APRS? 10.02,117.15,0200", "?APRS?-34,0,0200"]
)
def test_footprint_numbers_as_sent(info: str) -> None:
    # a footprint number is one as a telemetry value is, so it keeps its text as sent
    assert aprs.encode_info(aprs.decode_tnc2("N0CALL>APZ001:" + info).data) == info.encode()


@pytest.mark.parametrize(
    ("info", "written"),
    [
        # a DAO's digits on a compressed position agree with the position reported
        ('!L5<&{T"Pt#  GLoRa APRS Digi Godowa|(X#d*_!s%R!', '!L5<&{T"Pt# sTLoRa APRS Digi Godowa|(X#d*_!sCp!'),
        # the frequency first, then the altitude, then the free text after a space
        ("!4903.50N/07201.75Wj006/058/A=000889146.520MHz Dayton Bound", None),
        ("!4903.50N/07201.75Wj006/058/146.520MHz/A=000889 Dayton Bound", "="),
        (")I91 3N!4903.50N\\07201.75Wm/A=000100146.520MHz T100 x{55}", None),
        (")I91 3N!4903.50N\\07201.75Wm146.520MHz T100{55}/A=000100 x", "="),
        # a PHGR ends in its /, and the frequency follows it straight on
        (
            "@252109z4342.57NI00752.70W#145.225MHz PHG33403/Digi-Igate",
            "@252109z4342.57NI00752.70W#PHG33403/145.225MHz Digi-Igate",
        ),
        ("!4903.50N/07201.75W#PHG3340/145.225MHz Digi", "="),
        # a late range goes into the cs bytes, rounded to the nearest step
        ("!/5L!!<*e7>  G RNG0025hello", "!/5L!!<*e7>{BChello"),
    ],
)
def test_encoder_writes_the_canonical_bytes(info: str, written: str | None) -> None:
    got = aprs.encode_info(aprs.decode_tnc2("N0CALL>APZ001:" + info).data).decode("utf-8")
    if written is None:
        assert got != info
        # what it wrote is canonical: it writes it again byte for byte
        assert aprs.encode_info(aprs.decode_tnc2("N0CALL>APZ001:" + got).data).decode("utf-8") == got
    else:
        assert got == (info if written == "=" else written)


def test_mic_e_phgr_then_frequency_has_one_slash() -> None:
    packet = aprs.decode_tnc2('N0CALL>S32UVT:`(_fn"Oj/`PHG72604/146.520MHz')
    assert isinstance(packet.data, aprs.MicEReport)
    assert packet.data.phg is not None
    assert packet.data.frequency is not None
    assert aprs.encode_info(packet.data) == packet.info


def test_rounding_is_half_away_from_zero() -> None:
    # the rules round to the nearest step, halves away from zero; Python's round() takes halves
    # to the even number
    weather = aprs.Weather(rain_1h_in=0.125, temperature_f=-2.5)
    info = aprs.encode_info(aprs.PositionlessWeather(Timestamp("10090556"), weather))
    assert b"t-03r013" in info


def test_rounding_takes_halves_within_the_tolerance() -> None:
    # F2: halves are judged on the binary value, measured in steps, and one within 1e-6 of a half
    # is the half and goes away from zero. 1.275 inches is just below the half in binary;
    # 25.548583333333333 degrees is 1532.9149999999... minutes, the half 32.915; 0.9764166666666666
    # degrees is 58.584999999999996 minutes; 986.9499999999999 mbar is 9869.5 tenths
    weather = aprs.Weather(rain_24h_in=1.275, rain_midnight_in=8.415, pressure_mbar=986.9499999999999)
    assert b"p128P842b09870" in aprs.encode_info(aprs.PositionlessWeather(Timestamp("10090556"), weather))
    position = aprs.PositionReport(latitude=-58.73025, longitude=-25.548583333333333, symbol=Symbol("/", "k"))
    assert aprs.encode_info(position) == b"!5843.82S/02532.92Wk"
    near = aprs.PositionReport(latitude=0.9764166666666666, longitude=-0.9764166666666666, symbol=Symbol("/", "-"))
    assert aprs.encode_info(near) == b"!0058.59N/00058.59W-"
    # outside the tolerance the nearer step wins
    assert aprs.encode_info(
        aprs.PositionReport(latitude=1.2 / 60 + 0.00499 / 60, longitude=0, symbol=Symbol("/", "-"))
    ).startswith(b"!0001.20N")
    assert aprs.encode_info(
        aprs.PositionReport(
            latitude=0, longitude=0, symbol=Symbol("/", ">"), comment="", frequency=VoiceFrequency(146.5205)
        )
    ).endswith(b"146.521MHz")


def test_ambiguity_writes_the_box_the_value_is_in() -> None:
    # 3.596 minutes is in the box 3.5 to 3.6 (centre 3.55); rounding it to 3.60 first would put it
    # in the next box
    position = aprs.PositionReport(
        latitude=49 + 3.596 / 60, longitude=-(72 + 1.75 / 60), symbol=Symbol("/", "-"), ambiguity=1
    )
    assert aprs.encode_info(position) == b"!4903.5 N/07201.7 W-"
    # Mic-E longitude digits under ambiguity are ignored, and written as the centre reported
    for ambiguity, written in ((1, 5), (2, 50)):
        mic_e = aprs.MicEReport(
            mic_e_message=MicEMessage.OFF_DUTY,
            latitude=36.0,
            longitude=136 + 0.056 / 60,
            symbol=Symbol("/", "v"),
            ambiguity=ambiguity,
            course_degrees=90,
            speed_knots=0,
        )
        info = aprs.encode_info(mic_e)
        assert info[3] - 28 == written
        assert aprs.decode_tnc2(
            b"N0CALL>" + aprs.mic_e_destination(mic_e).encode() + b":" + info
        ).data.longitude == pytest.approx(136 + (0.055 if ambiguity == 1 else 0.5) / 60)


def test_mic_e_speed_190_to_199_knots_is_a_slash() -> None:
    # APRS12c ch. 10 gives / and DEL for 190-199 knots; DEL is a control character (ruling E5)
    info = aprs.encode_info(
        aprs.MicEReport(
            latitude=33.0,
            longitude=-112.0,
            symbol=Symbol("/", ">"),
            mic_e_message=MicEMessage.OFF_DUTY,
            speed_knots=195,
        )
    )
    assert info[4:5] == b"/"


def test_mic_e_comment_after_rev0_telemetry_starting_0x1d_is_text() -> None:
    # after Rev 0 telemetry a comment starting with 0x1D is text, written straight on (ruling E6)
    line = b"N0CALL>SUSPU4:`c'wl|+>/\x1dABCD/\x1dABCDEhello"
    packet = aprs.decode_tnc2(line)
    assert aprs.encode_info(packet.data) == packet.info


@pytest.mark.parametrize(
    ("course", "c"),
    [(358, "!"), (360, "!"), (2, '"'), (6, "#")],
)
def test_compressed_course_rounds_and_360_is_north(course: float, c: str) -> None:
    # a course or wind direction is rounded to the nearest 4 degrees, halves away from zero, and
    # one that rounds to 360 is c = 0 (ruling E9)
    data = aprs.PositionReport(
        latitude=49.5,
        longitude=-72.75,
        symbol=Symbol("/", ">"),
        compressed=True,
        course_degrees=course,
        speed_knots=10,
        compression=aprs.CompressionType(),
    )
    assert aprs.encode_info(data)[11:12] == c.encode()
    wind = aprs.PositionReport(
        latitude=49.5,
        longitude=-72.75,
        symbol=Symbol("/", "_"),
        compressed=True,
        weather=aprs.Weather(wind_direction_degrees=course, wind_speed_mph=10),
        compression=aprs.CompressionType(),
    )
    assert aprs.encode_info(wind)[11:12] == c.encode()


def test_compressed_speed_byte_of_90_is_written() -> None:
    # APRS12c ch. 9 limits only the course byte to !-z; s = { (90) is a speed (ruling E10)
    packet = aprs.decode_tnc2("N0CALL>APZ001:=/5L!!<*e7>{?!")
    assert aprs.encode_info(packet.data) == packet.info


@pytest.mark.parametrize(
    "info",
    [
        # no / before text that reads back as itself without one (ruling E7)
        "!/5L!!<*e7> sT.../...g...",
        "=4903.50N/07201.75W-444.900MHz \x00173",
    ],
)
def test_delimiter_only_where_needed(info: str) -> None:
    packet = aprs.decode_tnc2("N0CALL>APZ001:" + info)
    assert aprs.encode_info(packet.data) == packet.info


def test_mic_e_type_code_then_locator_needs_no_slash() -> None:
    packet = aprs.decode_tnc2(b"N0CALL>SUSPU4:`c'wl|+>/]wO91SX/G")
    assert aprs.encode_info(packet.data) == packet.info


def test_late_altitude_and_phg_in_mic_e_are_written_not_refused() -> None:
    # a clean form exists, so the encoder writes it (ruling E12)
    line = "JA1YKX-1>SUSPU4:'C=?l <1C>#S]PH}#S]PHG33302/W1,KNn-N YOKOHAMA 1200bps="
    packet = aprs.decode_tnc2(line.encode("latin-1"))
    info = aprs.encode_info(packet.data)
    again = aprs.decode_tnc2(b"JA1YKX-1>SUSPU4:" + info)
    assert to_neutral(again.data) == to_neutral(packet.data)


def test_no_size_limit() -> None:
    # refused means the Encoding rule declines the data, never that a buffer is full (ruling E11)
    text = "\u00e9" * 2000
    info = aprs.encode_info(aprs.StatusReport(text))
    assert len(info) == 4001


def test_compressed_weather_altitude_off_the_cs_steps_is_rounded() -> None:
    # F14: the GGA cs bytes hold an altitude in steps, and a weather report has no comment for a
    # /A=, so the altitude is the nearest cs step
    data = aprs.PositionReport(
        latitude=50.7,
        longitude=10.4,
        symbol=Symbol("/", "_"),
        compressed=True,
        altitude_feet=837.29,
        weather=aprs.Weather(),
        compression=aprs.CompressionType(source=aprs.CompressionSource.GGA),
    )
    info = aprs.encode_info(data)
    assert b"/A=" not in info
    back = aprs.decode_tnc2(b"N0CALL>APZ001:" + info).data
    assert isinstance(back, aprs.PositionReport)
    assert back.altitude_feet is not None
    assert abs(back.altitude_feet - 837.29) < 1


def test_device_wildcard_n_is_a_digit() -> None:
    # aprs-deviceid's n matches a digit: APWnnn is WinAPRS, APDnnn aprsd
    assert aprs.decode_tnc2("N0CALL>APW290:>hi").device is not None
    assert aprs.decode_tnc2("N0CALL>APD225:>hi").device is not None
    assert (
        aprs.decode_tnc2("N0CALL>APWXYZ:>hi").device is None
        or aprs.decode_tnc2("N0CALL>APWXYZ:>hi").device.model != "WinAPRS"
    )


def test_station_locator_is_upper_case() -> None:
    packet = STATION.status(locator="io91sx", symbol=Symbol("/", "-"))
    assert packet.info == b">IO91SX/-"


def test_directed_query_targets() -> None:
    def written(query_type: str) -> bytes:
        return aprs.encode_info(aprs.DirectedQuery("KH2Z", query_type, "N0QBF"))

    assert written("APRSH") == b":KH2Z     :?APRSHN0QBF    "
    assert written("APRSD") == b":KH2Z     :?APRSDN0QBF"
    assert written("FOO") == b":KH2Z     :?FOO N0QBF"


def test_third_party_inner_packet_has_no_q_construct() -> None:
    # a q-construct is only read in the outer header (vectors README, "Addresses and path")
    packet = aprs.decode_tnc2("N0CALL>APZ001:}N1CALL>APZ001,WIDE2-1,qAR,N2CALL:>hello")
    assert isinstance(packet.data, aprs.ThirdParty)
    inner = packet.data.packet
    assert [str(p) for p in inner.path] == ["WIDE2-1", "qAR", "N2CALL"]
    assert inner.q_construct is None
    again = from_neutral(to_neutral(packet.data))
    assert isinstance(again, aprs.ThirdParty)
    assert again.packet.q_construct is None
    assert aprs.decode_tnc2("N1CALL>APZ001,WIDE2-1,qAR,N2CALL:>hello").q_construct == aprs.QConstruct("qAR", "N2CALL")


def test_neutral_form_leaves_empty_text_and_addresses_out() -> None:
    assert from_neutral({"type": "bulletin", "addressee": "BLN1"}) == aprs.Bulletin("BLN1", "")
    third = from_neutral({"type": "third-party", "packet": {"source": "N0CALL", "data": {"type": "status"}}})
    assert isinstance(third, aprs.ThirdParty)
    assert third.packet.destination == ""


def test_neutral_round_trip() -> None:
    packet = aprs.decode_tnc2("N1JCM-9>TRQP7T,WA1PLE-4*:`c'wl|+>/`\"4-}_%")
    assert from_neutral(to_neutral(packet.data)) == packet.data


def test_device_lookup_is_case_sensitive() -> None:
    # A1: the database lists tocalls in upper case, and a destination is a callsign
    assert aprs.decode_tnc2("N0CALL>APN102:>hi").device is not None
    assert aprs.decode_tnc2("N0CALL>APNl02:>hi").device is None
    assert aprs.decode_tnc2("N0CALL>apn102:>hi").device is None


@pytest.mark.parametrize(
    ("course", "written"), [(360.4, b">360/010"), (360.25, b">360/010"), (-0.3, b">000/010"), (0.3, b">000/010")]
)
def test_course_is_rounded_before_it_is_checked(course: float, written: bytes) -> None:
    # F2 then F1: 360.4 is 360; -0.3 is 0, written 000 uncompressed
    data = aprs.PositionReport(latitude=0, longitude=0, symbol=Symbol("/", ">"), course_degrees=course, speed_knots=10)
    assert aprs.encode_info(data).endswith(written)


@pytest.mark.parametrize("course", [0, -0.3, 0.4])
def test_course_0_is_refused_where_it_reads_back_otherwise(course: float) -> None:
    # F1: Mic-E 0 reads back as no course, a compressed c of 0 as 360
    mic_e = aprs.MicEReport(
        mic_e_message=MicEMessage.OFF_DUTY,
        latitude=33.4,
        longitude=-112.1,
        symbol=Symbol("/", "j"),
        course_degrees=course,
        speed_knots=20,
    )
    with pytest.raises(EncodeError):
        aprs.encode_info(mic_e)
    compressed = aprs.PositionReport(
        latitude=49.5,
        longitude=-72.75,
        symbol=Symbol("/", ">"),
        compressed=True,
        compression=aprs.CompressionType(),
        course_degrees=course,
        speed_knots=36,
    )
    with pytest.raises(EncodeError):
        aprs.encode_info(compressed)


@pytest.mark.parametrize(("direction", "written"), [(360.25, b"_360/004"), (360.4, b"_360/004"), (-0.3, b"_000/004")])
def test_wind_direction_is_rounded_before_it_is_checked(direction: float, written: bytes) -> None:
    weather = aprs.Weather(wind_direction_degrees=direction, wind_speed_mph=4, wind_gust_mph=5, temperature_f=77)
    data = aprs.PositionReport(latitude=0, longitude=0, symbol=Symbol("/", "_"), weather=weather)
    assert written in aprs.encode_info(data)


def test_numbers_given_as_data_are_plain_decimals() -> None:
    # F11: no exponent, no +, no trailing .0
    data = aprs.TelemetryCoefficients(addressee="N0CALL", coefficients=(0.53, 190.0, 1e61, -94.0))
    assert aprs.encode_info(data) == b":N0CALL   :EQNS.0.53,190,1" + b"0" * 61 + b",-94"


def test_footprint_radius_is_rounded_and_0_takes_the_space() -> None:
    # F2 rounds the radius to whole miles; F15: a coordinate of 0 takes the leading space
    footprint = aprs.Footprint(latitude=0, longitude=-117.15, radius_miles=199.5)
    assert aprs.encode_info(aprs.Query("APRS", footprint=footprint)) == b"?APRS? 0,-117.15,0200"


def test_mic_e_with_an_empty_first_channel_is_refused() -> None:
    # F12: T#MIC,,033 reads back otherwise
    data = aprs.TelemetryReport(sequence="MIC", analog=(None, 33, None, None, None), bits="00000000")
    with pytest.raises(EncodeError, match="MIC"):
        aprs.encode_info(data)


@pytest.mark.parametrize(
    ("extra", "status"),
    [
        ({"telemetry": aprs.CommentTelemetry(sequence=25, analog=(470, 625))}, b"`IO91/G|!:&0'p|"),
        ({"dao": aprs.Dao("W", aprs.DaoPrecision.BASE91)}, b"`IO91/G!w"),
    ],
)
def test_mic_e_locator_then_telemetry_or_dao(extra: dict[str, object], status: bytes) -> None:
    # F16: telemetry and a DAO are lifted before the locator is read, so nothing is missing
    data = aprs.MicEReport(
        mic_e_message=MicEMessage.OFF_DUTY,
        latitude=33.42733333333334,
        longitude=-112.129,
        symbol=Symbol("/", "j"),
        course_degrees=251,
        speed_knots=20,
        type_code="`",
        locator="IO91",
        **extra,
    )
    info = aprs.encode_info(data)
    assert status in info
    back = aprs.decode_tnc2(b"N0CALL>" + aprs.mic_e_destination(data).encode() + b":" + info)
    assert not back.diagnostics


def test_locator_text_after_a_mic_e_phg_is_comment() -> None:
    # F17: a locator is read only at the start of the status text
    back = aprs.decode_tnc2('N0CALL>S32UVT:`(_fn"Oj/]PHG3330IO91SX/G')
    assert isinstance(back.data, aprs.MicEReport)
    assert back.data.locator is None
    assert back.data.comment == "IO91SX/G"


@pytest.mark.parametrize("comment", ["{5}", "{}", "}:LoRa iGate"])
def test_mic_e_comment_that_would_join_an_altitude_gets_a_space(comment: str) -> None:
    # E12: after /A=000101, {5} would read as the Mic-E altitude 1{5}; a space holds it apart
    packet = STATION.mic_e(33.46, -2.69, altitude_feet=100.5, comment=comment)
    assert packet.info.endswith(b"/A=000101 " + comment.encode())
    back = aprs.decode_tnc2(packet.to_tnc2())
    assert not back.diagnostics
    assert isinstance(back.data, aprs.MicEReport)
    assert back.data.comment == comment


@pytest.mark.parametrize(("knots", "refused"), [(-0.03, False), (-0.3, True), (-1, True)])
def test_compressed_speed_steps_beyond_the_byte(knots: float, refused: bool) -> None:
    # G3: the nearest step 1.08^s - 1 for any whole s; refused when s is outside the byte
    data = aprs.PositionReport(
        latitude=49.5,
        longitude=-72.75,
        symbol=Symbol("/", ">"),
        compressed=True,
        compression=aprs.CompressionType(),
        course_degrees=88,
        speed_knots=knots,
    )
    if refused:
        with pytest.raises(EncodeError):
            aprs.encode_info(data)
    else:
        assert aprs.encode_info(data)[12:13] == b"!"


@pytest.mark.parametrize(("miles", "refused"), [(1.95, False), (1.9, True), (0, True)])
def test_compressed_range_steps_beyond_the_byte(miles: float, refused: bool) -> None:
    # G3: 1.95 miles is nearest the 2-mile step (s = 0); 1.9 is nearest s = -1
    data = aprs.PositionReport(
        latitude=49.5,
        longitude=-72.75,
        symbol=Symbol("/", ">"),
        compressed=True,
        compression=aprs.CompressionType(),
        range_miles=miles,
    )
    if refused:
        with pytest.raises(EncodeError):
            aprs.encode_info(data)
    else:
        assert aprs.encode_info(data)[11:13] == b"{!"


def test_ambiguity_cut_takes_the_tolerance() -> None:
    # G2: 80.49 degrees is 29.40 minutes in the text's meaning, box 29.4x, though its binary
    # value is a hair below
    data = aprs.PositionReport(latitude=80.49, longitude=0, symbol=Symbol("/", "-"), ambiguity=1)
    assert aprs.encode_info(data).startswith(b"!8029.4 N")


def test_compressed_cs_values_without_a_compression_type_get_the_default() -> None:
    # the default type byte C goes with cs values the data gives no type for
    data = aprs.PositionReport(
        latitude=49.05833333333333,
        longitude=-72.02916666666667,
        symbol=Symbol("/", ">"),
        compressed=True,
        range_miles=2,
    )
    assert aprs.encode_info(data) == b"!/5`=k<;>x>{!C"
    late = aprs.decode_tnc2("N0CALL>APZ001:!/5L!!<*e7>  G RNG0025hello").data
    assert aprs.encode_info(late) == b"!/5L!!<*e7>{BChello"


def test_area_offsets_are_digits() -> None:
    # Tyy/Cxx takes digits: 7 0/310 is comment text, not an area
    packet = aprs.decode_tnc2("N0CALL>APZ001:;SEARCH 1 *092345z4903.50N\\07201.75Wl7 0/310 0/310")
    assert isinstance(packet.data, aprs.ObjectReport)
    assert packet.data.area is None
    assert packet.data.comment == "7 0/310 0/310"
    assert aprs.encode_info(packet.data) == packet.info


@pytest.mark.parametrize("ssid", ["00", "0", "07"])
def test_ax25_refuses_an_ssid_it_cannot_carry_as_sent(ssid: str) -> None:
    # -00 would come back from the frame as no SSID
    packet = aprs.decode_tnc2(f"N0CALL>APZ001:}}WB4APR-{ssid}>APRS,TCPIP,G9RXG*:>hi")
    assert isinstance(packet.data, aprs.ThirdParty)
    with pytest.raises(EncodeError, match="leading zero"):
        packet.data.packet.to_ax25()


def test_unknown_snowfall_after_a_compressed_gga_position_counts_as_present() -> None:
    packet = aprs.decode_tnc2(
        "KA7HOS-10>APDW16,qAR,KA7HOS-10:=Aid_15oum_wuxs   *111111z3714.14N/11338.11W+`STG Marathon Aid Station 15"
    )
    assert isinstance(packet.data, aprs.PositionReport)
    assert packet.data.comment == "*111111z3714.14N/11338.11W+`STG Marathon Aid Station 15"
    assert packet.data.weather is not None
    assert packet.data.weather.snow_24h_in is None


def test_strict_mic_e_with_no_later_altitude_reads_as_lenient() -> None:
    # lifting the telemetry leaves RWJ}, which is text: nothing to decline, so no rejection
    line = '`j.po_Tk/`"=K3RW|)>%v|J}146.520MHz 146.970(127.3)_6'
    lenient = aprs.decode_tnc2(b"N0CALL>S32UVT:" + line.encode())
    strict = aprs.decode_tnc2(b"N0CALL>S32UVT:" + line.encode(), aprs.ParseOptions.strict())
    assert isinstance(strict.data, aprs.MicEReport)
    assert strict.data == lenient.data


def test_storm_data_with_a_space_in_a_field_is_text() -> None:
    line = ";BRENDA   *092345z4903.50N\\07202.75W@088/036/HC/150^200/0980> 90&030%040"
    packet = aprs.decode_tnc2(b"N0CALL>APZ001:" + line.encode())
    assert isinstance(packet.data, aprs.ObjectReport)
    assert packet.data.storm is None
    assert packet.data.comment == "HC/150^200/0980> 90&030%040"


def test_ax25_refuses_a_dash_with_no_ssid() -> None:
    packet = aprs.decode_tnc2("N0CALL>APZ001:}N0CALL>APZ,WIDE1-*,WIDE2-1*:>x")
    assert isinstance(packet.data, aprs.ThirdParty)
    with pytest.raises(EncodeError, match="dash"):
        packet.data.packet.to_ax25()


def test_strict_mic_e_rejects_only_an_altitude_joined_across_a_lifted_place() -> None:
    # "3z} was in the bytes already: kept; II!} forms across the place of the DAO lifted: rejected
    kept = aprs.decode_tnc2('N0CALL>PURWS8:`l(tmz#<X|!wII!}3/"3z}</"3z}', aprs.ParseOptions.strict())
    assert isinstance(kept.data, aprs.MicEReport)
    assert kept.data.dao is not None
    joined = aprs.decode_tnc2(
        "N0CALL>U5TVQS:`0)1839h0654.57S/10742fl!X>/'\";X|!wII!!wII!}3", aprs.ParseOptions.strict()
    )
    assert isinstance(joined.data, aprs.Unrecognized)


def test_object_and_item_take_the_position_options() -> None:
    st = Station("N0CALL", symbol=Symbol.CAR)
    phg = aprs.Phg(2, 3, 4, 0)
    obj = st.object("OBJ", 51.5, -1.0, course_degrees=90, speed_kmh=37.04, altitude_m=100, ambiguity=1)
    assert obj.data.ambiguity == 1
    assert obj.data.speed_knots == pytest.approx(20)
    assert st.object("OBJ", 51.5, -1.0, phg=phg).data.phg == phg
    item = st.item(
        "ITEM",
        51.5,
        -1.0,
        compressed=True,
        course_degrees=88,
        speed_knots=36,
        frequency=VoiceFrequency(146.52, tone=ToneType.TONE, tone_value=100),
    )
    assert item.data.compressed
    assert item.data.frequency.mhz == 146.52
    assert st.item("ITEM", 51.5, -1.0, dao=True, range_miles=20).data.dao is not None
    with pytest.raises(ValueError, match="once"):
        st.item("ITEM", 51.5, -1.0, speed_knots=1, speed_kmh=2)


def test_mic_e_takes_frequency_ambiguity_dao_and_telemetry() -> None:
    st = Station("N0CALL", symbol=Symbol.CAR)
    got = _round_trip(st.mic_e(51.5, -1.0, ambiguity=2, frequency=145.5)).data
    assert got.ambiguity == 2
    assert got.frequency.mhz == 145.5
    got = _round_trip(st.mic_e(51.5, -1.0, dao=True, telemetry=aprs.CommentTelemetry(1, (2, 3)))).data
    assert got.dao is not None
    assert got.telemetry.analog == (2, 3)


def test_weather_takes_any_symbol_and_status_a_beam() -> None:
    st = Station("N0CALL")
    wx = st.weather(51.5, -1.0, symbol=Symbol.parse("\\_"), temperature_f=60)
    assert wx.to_tnc2().decode().endswith("W_.../...g...t060")
    assert st.status("hi", beam=aprs.Beam("B", "7")).to_tnc2().decode().endswith(">hi^B7")


def test_dao_with_ambiguity_is_refused_by_item_and_mic_e() -> None:
    st = Station("N0CALL", symbol=Symbol.CAR)
    with pytest.raises(EncodeError, match="ambiguous"):
        st.item("ITEM", 51.5, -1.0, ambiguity=1, dao=True)
    with pytest.raises(EncodeError, match="ambiguous"):
        st.mic_e(51.5, -1.0, ambiguity=1, dao=True)


def test_mic_e_speed_in_both_units_is_refused() -> None:
    st = Station("N0CALL", symbol=Symbol.CAR)
    with pytest.raises(ValueError, match="once"):
        st.mic_e(51.5, -1.0, speed_knots=5, speed_kmh=10)


def test_positionless_weather_refuses_a_symbol() -> None:
    with pytest.raises(ValueError, match="no symbol"):
        Station("N0CALL").weather(symbol=Symbol.parse("\\_"), temperature_f=60)


def test_ambiguous_object_and_compressed_item_bytes() -> None:
    st = Station("N0CALL", symbol=Symbol.CAR)
    obj = st.object("OBJ", 51.5, -1.0, timestamp=Timestamp.dhm(9, 23, 45), ambiguity=2)
    assert obj.to_tnc2() == b"N0CALL>APZ001:;OBJ      *092345z5130.  N/00100.  W>"
    item = st.item("ITEM", 51.5, -1.0, compressed=True, course_degrees=88, speed_knots=36)
    assert item.to_tnc2() == b"N0CALL>APZ001:)ITEM!/4K!!N7!!>7PC"


# ---------------------------------------------------------------- refusal codes (1.0.1)


def _code(fn: object) -> str:
    with pytest.raises(EncodeError) as info:
        fn()  # type: ignore[operator]
    return info.value.code.value


def _pos(**kw: object) -> aprs.PositionReport:
    return aprs.PositionReport(latitude=49.0, longitude=-72.0, symbol=Symbol.HOUSE, **kw)  # type: ignore[arg-type]


def test_refusal_codes_cover_the_shared_list() -> None:
    import json
    from pathlib import Path

    from pdn_aprs import RefusalCode

    ids = [
        r["id"] for r in json.loads((Path(__file__).parent.parent / "vectors" / "codes.json").read_text())["refusals"]
    ]
    assert [c.value for c in RefusalCode] == ids


def test_encode_error_without_a_code_is_the_fallback() -> None:
    assert EncodeError("x").code is aprs.RefusalCode.DOES_NOT_READ_BACK


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        (lambda: aprs.encode_info(aprs.Message("N0CALL", "x" * 68)), "too-long"),
        (lambda: aprs.encode_info(aprs.Message("N0CALL", "a{b")), "invalid-character"),
        (lambda: aprs.encode_info(aprs.Message("", "hi")), "invalid-addressee"),
        (lambda: aprs.encode_info(aprs.Message("N0CALL", "hi", message_id="123456")), "invalid-message-id"),
        (
            lambda: aprs.encode_info(aprs.PositionReport(latitude=91, longitude=0, symbol=Symbol.HOUSE)),
            "value-out-of-range",
        ),
        (
            lambda: aprs.encode_info(aprs.PositionReport(latitude=float("nan"), longitude=0, symbol=Symbol.HOUSE)),
            "not-a-number",
        ),
        (lambda: aprs.encode_info(_pos(compressed=True, ambiguity=1)), "field-not-allowed"),
        (lambda: aprs.encode_info(_pos(comment="/A=001234")), "text-reads-as-field"),
        (
            lambda: aprs.encode_info(aprs.ObjectReport(name="", latitude=0, longitude=0, symbol=Symbol.HOUSE)),
            "invalid-name",
        ),
        (lambda: aprs.encode_info(aprs.Unrecognized(aprs.UnrecognizedReason.EMPTY)), "not-encodable"),
        (lambda: aprs.build_packet("bad call", _pos()), "invalid-address"),
        (lambda: aprs.build_packet("N0CALL", _pos(), path=["A"] * 9), "ax25-cannot-carry"),
        (lambda: aprs.encode_info(aprs.Message("BLN1", "hi")), "invalid-addressee"),
        (lambda: aprs.encode_info(aprs.Message("N0CALL", "hi", reply_ack="1")), "missing-field"),
        (lambda: aprs.encode_info(aprs.Capabilities((("bad token",),))), "malformed"),
        (lambda: aprs.encode_info(aprs.TelemetryBits("N0CALL", "10101010", "x" * 24)), "too-long"),
        (lambda: aprs.encode_info(aprs.TelemetryCoefficients("N0CALL", (float("nan"),))), "not-a-number"),
        (
            lambda: aprs.encode_info(
                aprs.PositionReport(latitude=float("inf"), longitude=0, symbol=Symbol.HOUSE, comment="a\nb")
            ),
            "not-a-number",
        ),
        (
            lambda: aprs.encode_info(aprs.PositionReport(latitude=1, longitude=1, symbol=Symbol("/", "_"))),
            "symbol-mismatch",
        ),
        (
            lambda: aprs.encode_info(
                aprs.PositionReport(latitude=1, longitude=1, symbol=Symbol("/", "_"), comment="a\nb")
            ),
            "invalid-character",
        ),
        (lambda: Station("N0CALL").telemetry(1000, [1, 2, 3, 4, 5], "00000000"), "value-out-of-range"),
        (
            lambda: Station("N0CALL").weather(temperature_f=1, temperature_c=1, symbol=Symbol.WEATHER_STATION),
            "value-given-twice",
        ),
    ],
)
def test_refusal_code(make: object, expected: str) -> None:
    assert _code(make) == expected


def test_to_ax25_refuses_with_ax25_cannot_carry() -> None:
    packet = aprs.build_packet("N0CALLX", _pos())
    assert _code(packet.to_ax25) == "ax25-cannot-carry"


def test_a_huge_finite_latitude_is_out_of_range_not_a_number() -> None:
    for make in (
        lambda: aprs.encode_info(aprs.PositionReport(latitude=1e308, longitude=0, symbol=Symbol.HOUSE)),
        lambda: aprs.encode_info(
            aprs.PositionReport(latitude=1e308, longitude=0, symbol=Symbol.HOUSE, compressed=True)
        ),
    ):
        assert _code(make) == "value-out-of-range"


def test_mic_e_legacy_telemetry_ending_in_cr_is_an_invalid_character() -> None:
    report = aprs.MicEReport(
        mic_e_message=MicEMessage.RETURNING,
        latitude=33.42733333333334,
        longitude=-112.129,
        symbol=Symbol("/", "j"),
        course_degrees=299,
        speed_knots=1,
        legacy_telemetry=(47, 79, 128, 208, 13),
    )
    assert _code(lambda: aprs.encode_info(report)) == "invalid-character"


def test_mic_e_status_text_that_reads_back_changed_is_text_reads_as_field() -> None:
    packet = aprs.decode_tnc2(b'LA7DHA-8>U9UR55,LD1OE*,WIDE2-1,qAS,LB1HG-10:`&>]l#MPY/>"3}')
    assert _code(lambda: aprs.encode_info(packet.data)) == "text-reads-as-field"


def test_station_reuse_keeps_no_quantity_between_calls() -> None:
    """Each call stands alone: a quantity in the other unit on an earlier call never counts,
    and value-given-twice is only for one call with both units."""
    st = aprs.Station("N0CALL", symbol=aprs.Symbol.CAR)
    first = str(st.position(10.0, 20.0, speed_knots=10, course_degrees=90))
    kmh = str(st.position(10.0, 20.0, speed_kmh=20, course_degrees=90))
    last = str(st.position(10.0, 20.0, speed_knots=5, course_degrees=90))
    assert "090/010" in first
    assert "090/011" in kmh
    assert "090/005" in last
    with pytest.raises(aprs.EncodeError) as err:
        st.position(10.0, 20.0, speed_knots=10, speed_kmh=20)
    assert err.value.code is aprs.RefusalCode.VALUE_GIVEN_TWICE
    assert "090/005" in str(st.position(10.0, 20.0, speed_knots=5, course_degrees=90))


def test_a_refused_builder_call_leaks_nothing_into_the_next() -> None:
    st = aprs.Station("N0CALL", symbol=aprs.Symbol.CAR)
    with pytest.raises(aprs.EncodeError) as err:
        st.weather(temperature_c=10, temperature_f=50, symbol=aprs.Symbol.CAR)
    assert err.value.code is aprs.RefusalCode.SYMBOL_MISMATCH
    assert str(st.message("N0CALL-1", "hi")).endswith(":N0CALL-1 :hi")


def test_a_caller_built_third_party_chain_ten_thousand_deep_is_refused_without_recursion() -> None:
    from pdn_aprs import Packet, StatusReport, ThirdParty
    from pdn_aprs._neutral import to_neutral

    data: aprs.AprsData = StatusReport("hi")
    for _ in range(10_000):
        data = ThirdParty(Packet("A", "B", (), b"", data))
    with pytest.raises(aprs.EncodeError) as err:
        aprs.encode_info(data)
    assert err.value.code is aprs.RefusalCode.INVALID_THIRD_PARTY_HEADER
    with pytest.raises(aprs.EncodeError):
        aprs.build_packet("N0CALL", data)
    neutral = to_neutral(data)
    assert neutral["type"] == "third-party"
    assert neutral["packet"]["data"]["type"] == "third-party"


def test_from_neutral_refuses_a_chain_ten_thousand_deep_without_recursion() -> None:
    from pdn_aprs._neutral import from_neutral

    data: dict[str, object] = {"type": "status", "text": "hi"}
    for _ in range(10_000):
        data = {"type": "third-party", "packet": {"source": "A", "destination": "B", "data": data}}
    with pytest.raises(aprs.EncodeError) as err:
        from_neutral(data)
    assert err.value.code is aprs.RefusalCode.INVALID_THIRD_PARTY_HEADER


def test_the_header_is_judged_first_and_an_invalid_source_is_refused() -> None:
    st = aprs.Station("BAD!!", symbol=aprs.Symbol.CAR)
    for build in (
        lambda: st.position(10.0, 10.0),
        lambda: st.position(10.0, 10.0, course_degrees=999),
        lambda: st.mic_e(10.0, 10.0, course_degrees=999),
    ):
        with pytest.raises(aprs.EncodeError) as err:
            build()
        assert err.value.code is aprs.RefusalCode.INVALID_ADDRESS


def test_a_quantity_in_two_units_is_ranked_with_each_value_checked() -> None:
    st = aprs.Station("N0CALL", symbol=aprs.Symbol.CAR)

    def code(build: object) -> aprs.RefusalCode:
        with pytest.raises(aprs.EncodeError) as err:
            build()  # type: ignore[operator]
        return err.value.code

    twice = aprs.RefusalCode.VALUE_GIVEN_TWICE
    out = aprs.RefusalCode.VALUE_OUT_OF_RANGE
    assert code(lambda: st.position(10.0, 10.0, speed_knots=5, speed_kmh=9)) is twice
    assert code(lambda: st.position(10.0, 10.0, speed_knots=799.5, speed_kmh=-1)) is out
    assert code(lambda: st.position(10.0, 10.0, altitude_feet=5, altitude_m=304800)) is out
    assert code(lambda: st.weather(10.0, 10.0, temperature_f=50, temperature_c=10, humidity_percent=0)) is (
        aprs.RefusalCode.VALUE_HAS_NO_FORM
    )
    assert code(lambda: st.weather(10.0, 10.0, rain_1h_in=1, rain_1h_mm=1000, pressure_mbar=99999)) is out


def test_a_name_or_timestamp_fault_comes_before_not_a_number() -> None:
    nan = float("nan")
    weather = aprs.Weather(wind_direction_degrees=nan, wind_speed_mph=1, wind_gust_mph=2, temperature_f=3)
    stamp = aprs.Timestamp("092460z")
    with pytest.raises(aprs.EncodeError) as err:
        aprs.encode_info(aprs.PositionlessWeather(stamp, weather))
    assert err.value.code is aprs.RefusalCode.INVALID_TIMESTAMP
    with pytest.raises(aprs.EncodeError) as err:
        aprs.encode_info(aprs.ObjectReport(name="TOOLONGNAME1", latitude=1, longitude=nan, symbol=aprs.Symbol.CAR))
    assert err.value.code is aprs.RefusalCode.INVALID_NAME
    with pytest.raises(aprs.EncodeError) as err:
        aprs.encode_info(
            aprs.ObjectReport(
                name="OK", timestamp=aprs.Timestamp("111111z"), latitude=1, longitude=nan, symbol=aprs.Symbol.CAR
            )
        )
    assert err.value.code is aprs.RefusalCode.NOT_A_NUMBER


def test_non_finite_builder_input_is_refused_never_raised() -> None:
    inf = float("inf")
    st = aprs.Station("N0CALL", symbol=aprs.Symbol.CAR)
    nan_code = aprs.RefusalCode.NOT_A_NUMBER
    for build in (
        lambda: st.mic_e(10.0, 10.0, course_degrees=-inf),
        lambda: st.mic_e(10.0, 10.0, altitude_m=inf),
        lambda: st.mic_e(10.0, 10.0, ambiguity=inf),  # type: ignore[arg-type]
        lambda: st.telemetry(float("nan"), [1, 2, 3, 4, 5]),  # type: ignore[arg-type]
    ):
        with pytest.raises(aprs.EncodeError) as err:
            build()
        assert err.value.code is nan_code
