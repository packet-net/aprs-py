"""Regression tests for the 2026-11 review fixes."""

from __future__ import annotations

import collections
import dataclasses
import decimal
import fractions
import re
import time

import pytest

import pdn_aprs as aprs
from pdn_aprs import EncodeError, HeaderError, RefusalCode, Station, Symbol, encode_info
from pdn_aprs import _decode as dec
from pdn_aprs import encode as enc

ST = Station("M0LTE-9", symbol=aprs.Symbol.CAR)


def _telemetry(value: float) -> str:
    return ST.telemetry(1, [value, 0, 0, 0, 0], "00000000").info.decode()


def test_telemetry_whole_numbers_are_shortest_decimal() -> None:
    assert _telemetry(1e23) == "T#001,1" + "0" * 23 + ",000,000,000,000,00000000"
    assert _telemetry(1e200) == "T#001,1" + "0" * 200 + ",000,000,000,000,00000000"
    with pytest.raises(EncodeError) as too_long:
        _telemetry(1e308)  # 309 digits: the information field would be over 256 bytes
    assert too_long.value.code is RefusalCode.INFORMATION_FIELD_TOO_LONG
    assert _telemetry(1000.0) == "T#001,1000,000,000,000,000,00000000"
    assert _telemetry(-1e23).startswith("T#001,-1" + "0" * 23 + ",")
    assert _telemetry(5.0) == "T#001,005,000,000,000,000,00000000"
    assert _telemetry(10**25) == "T#001,1" + "0" * 25 + ",000,000,000,000,00000000"


def test_decode_tnc2_str_with_surrogateescape() -> None:
    raw = b"M0LTE>APRS:>caf\xe9 status"
    line = raw.decode("utf-8", "surrogateescape")
    packet = aprs.decode_tnc2(line)
    assert packet.info == b">caf\xe9 status"
    assert packet.info == aprs.decode_tnc2(raw).info


def test_decode_tnc2_other_lone_surrogates_do_not_raise_oddly() -> None:
    packet = aprs.decode_tnc2("M0LTE>APRS:>x\ud800y\udd00z")
    assert packet.info == ">x�y�z".encode()
    with pytest.raises(HeaderError):
        aprs.decode_tnc2("M0\ud800>APRS:>x")
    with pytest.raises(HeaderError):
        aprs.decode_tnc2("M0\udc80>APRS:>x")


def _code(fn: object) -> RefusalCode:
    with pytest.raises(EncodeError) as info:
        fn()  # type: ignore[operator]
    return info.value.code


def test_builder_refusals_are_encode_errors() -> None:
    assert _code(lambda: ST.position(51.45, -0.98, ambiguity=1.0 + 1e-9)) is RefusalCode.VALUE_OUT_OF_RANGE
    assert _code(lambda: ST.position(51.45, -0.98, ambiguity=decimal.Decimal("NaN"))) is RefusalCode.NOT_A_NUMBER
    assert _code(lambda: ST.position(51.45, -0.98, frequency=10**400)) is RefusalCode.VALUE_OUT_OF_RANGE
    assert _code(lambda: ST.position(51.45, -0.98, course_degrees=10**400)) is RefusalCode.VALUE_OUT_OF_RANGE
    assert _code(lambda: ST.position(decimal.Decimal("NaN"), -0.98)) is RefusalCode.NOT_A_NUMBER
    assert _code(lambda: ST.position(51.45, -0.98, course_degrees=float("inf"))) is RefusalCode.NOT_A_NUMBER
    assert _code(lambda: ST.position(51.45, -0.98, comment="\ud800")) is RefusalCode.TEXT_READS_AS_FIELD
    assert _code(lambda: ST.message("G4ABC", "a\udfffb")) is RefusalCode.TEXT_READS_AS_FIELD
    assert _code(lambda: ST.status("\ud800")) is RefusalCode.TEXT_READS_AS_FIELD
    # an earlier code in the Refusal reasons order still wins over the surrogate
    assert _code(lambda: ST.position(51.45, -0.98, comment="\ud800\n")) is RefusalCode.INVALID_CHARACTER


def test_whole_float_ambiguity_is_that_level() -> None:
    assert ST.position(51.45, -0.98, ambiguity=1.0).info == ST.position(51.45, -0.98, ambiguity=1).info


def test_decimal_is_a_real_number() -> None:
    d = decimal.Decimal
    assert ST.position(d("51.45"), d("-0.98")).info == ST.position(51.45, -0.98).info
    assert ST.position(d("51.45"), -0.98).info == ST.position(fractions.Fraction(5145, 100), -0.98).info
    assert (
        ST.position(51.45, -0.98, course_degrees=d("51"), speed_knots=d("12")).info
        == ST.position(51.45, -0.98, course_degrees=51, speed_knots=12).info
    )
    assert ST.mic_e(d("51.45"), d("-0.98")).info == ST.mic_e(51.45, -0.98).info
    assert ST.telemetry(1, [d("51.45"), 1, 2, 3, 4]).info == ST.telemetry(1, [51.45, 1, 2, 3, 4]).info
    assert ST.telemetry_coefficients([d("51.45"), 1, 0]).info == ST.telemetry_coefficients([51.45, 1, 0]).info
    assert ST.weather(51.45, -0.98, temperature_f=d("51")).info == ST.weather(51.45, -0.98, temperature_f=51).info


def test_encode_info_only_raises_encode_error_on_bad_data() -> None:
    bad = aprs.PositionReport(latitude=51.45, longitude=-0.98, symbol=aprs.Symbol.CAR, ambiguity=1.5)  # type: ignore[arg-type]
    with pytest.raises(EncodeError):
        aprs.encode_info(bad)


def test_top_level_exports() -> None:
    assert callable(aprs.identify_tocall)
    assert callable(aprs.identify_mic_e)


# ---- linear patterns

LONG = "1" * 100_000


def _fast(line: str) -> None:
    t0 = time.perf_counter()
    aprs.decode_tnc2(line)
    assert time.perf_counter() - t0 < 2.0


@pytest.mark.parametrize(
    "line",
    [
        f"N0CALL>APZ001:T#001,{LONG}x,2,3,4,5,00000000",
        f"N0CALL>APZ001::N0CALL   :EQNS.{LONG}x,1,0",
        f"N0CALL>APZ001::N0CALL   :EQNS.1,{LONG}e,0",
        f"N0CALL>APZ001:?APRS? {LONG}x,1,0050",
        f"N0CALL>APZ001:?APRS? -{LONG}x,1,0050",
        f"N0CALL>APZ001:$GPGGA,123456,{LONG}x,N,00100.00,W,1,05,1.0,10,M,0,M,,*00",
    ],
)
def test_long_digit_runs_decode_quickly(line: str) -> None:
    _fast(line)


def test_encoder_patterns_are_linear_too() -> None:
    for pattern in (enc._TELEMETRY_VALUE, enc._COEFFICIENT, enc._FOOTPRINT_VALUE):
        t0 = time.perf_counter()
        assert pattern.match(LONG + "x") is None
        assert time.perf_counter() - t0 < 1.0


OLD = r"-?(?:[0-9]+\.?[0-9]*|\.[0-9]+)\Z"
SAMPLES = [
    "", "-", ".", "-.", "1", "1.", "1.5", ".5", "-.5", "-1.", "00", "0.", "1..", "1.2.3", "1e5", "x1", "1x", "--1",
    "+1", "1 ", " 1", "12345", "-12.", "-.", "5.5e", "\u0661",
]  # fmt: skip


@pytest.mark.parametrize("text", SAMPLES)
def test_accepted_language_is_unchanged(text: str) -> None:
    old = re.compile(OLD)
    assert bool(dec._TELEMETRY_NUMBER.match(text)) == bool(old.match(text))
    assert bool(dec._DECIMAL.match(text)) == bool(old.match(text))
    assert bool(enc._TELEMETRY_VALUE.match(text)) == bool(old.match(text))
    old_coeff = re.compile(r" *(-?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?) *\Z")
    assert bool(dec._COEFF.match(text)) == bool(old_coeff.match(text))
    old_fp = re.compile(r"(?: ?(?:[0-9]+\.?[0-9]*|\.[0-9]+)|-(?:[0-9]+\.?[0-9]*|\.[0-9]+))\Z")
    assert bool(enc._FOOTPRINT_VALUE.match(text)) == bool(old_fp.match(text))


_NT = collections.namedtuple("_NT", "a b c d e")
Decimal = decimal.Decimal
Fraction = fractions.Fraction
_POS = aprs.decode_tnc2("M0LTE>APRS:!5127.00N/00058.80W>088/036/A=001234hello").data
_ST = Station("M0LTE-9", symbol=Symbol.CAR)


def test_namedtuples_pass_to_the_builders() -> None:
    assert _ST.telemetry(1, _NT(1, 2, 3, 4, 5), "00000000").info.startswith(b"T#001,001,002,003,004,005,")
    assert _ST.telemetry_names(_NT("a", "b", "c", "d", "e")).info.startswith(b":")
    assert _ST.telemetry_coefficients(_NT(0, 1, 0, 0, 1)).info.startswith(b":")


def test_huge_fraction_and_signalling_nan_are_refused_not_leaked() -> None:
    with pytest.raises(EncodeError) as e:
        _ST.position(Fraction(10**400, 3), -0.98)
    assert e.value.code is RefusalCode.VALUE_OUT_OF_RANGE
    with pytest.raises(EncodeError) as e:
        encode_info(dataclasses.replace(_POS, latitude=Fraction(10**400, 3)))
    assert e.value.code is RefusalCode.VALUE_OUT_OF_RANGE
    with pytest.raises(EncodeError) as e:
        _ST.position(Decimal("sNaN"), -0.98)
    assert e.value.code is RefusalCode.NOT_A_NUMBER


def test_huge_finite_decimal_is_out_of_range_but_nan_is_not_a_number() -> None:
    with pytest.raises(EncodeError) as e:
        _ST.position(Decimal("1e1000"), -0.98)
    assert e.value.code is RefusalCode.VALUE_OUT_OF_RANGE
    with pytest.raises(EncodeError) as e:
        _ST.position(Decimal("NaN"), -0.98)
    assert e.value.code is RefusalCode.NOT_A_NUMBER


def test_whole_telemetry_values_past_two_to_the_53_are_the_shortest_decimal_of_the_double() -> None:
    big = 10**25 + 1
    info = _ST.telemetry(1, (Fraction(big), Decimal(big), 2, 3, 4), "00000000").info
    # past 2**53 a number is the shortest decimal of the same double (vectors 4e558d5)
    shortest = f"1{'0' * 25}"
    assert info.startswith(f"T#001,{shortest},{shortest},002,003,004,".encode())


def test_telemetry_sequence_type_error_names_the_type() -> None:
    with pytest.raises(TypeError, match="not Decimal"):
        _ST.telemetry(Decimal(1), (1, 2, 3, 4, 5))  # type: ignore[arg-type]


def test_run_2_non_finite_value_with_no_place_is_not_a_number_and_gga_altitude() -> None:
    from pdn_aprs._neutral import from_neutral

    weather = {"wind_gust_mph": 0, "temperature_f": 50}
    inner = {
        "type": "position",
        "timestamp": "092345z",
        "latitude": 49.0,
        "longitude": -72.0,
        "symbol": "/_",
        "weather": weather,
        "altitude_feet": float("nan"),
    }
    third = {"type": "third-party", "packet": {"source": "A", "destination": "B", "data": inner}}
    with pytest.raises(EncodeError) as e:
        encode_info(from_neutral(third))
    assert e.value.code is RefusalCode.NOT_A_NUMBER
    gga = {
        "type": "object",
        "name": "147.345",
        "latitude": 20.4,
        "longitude": 10.0,
        "symbol": "N0",
        "compressed": True,
        "compression": {"fix": "old", "source": "gga", "origin": "digipeater-conversion"},
        "altitude_feet": float("-inf"),
        "timestamp": "020226h",
    }
    with pytest.raises(EncodeError) as e:
        encode_info(from_neutral(gga))
    assert e.value.code is RefusalCode.NOT_A_NUMBER


def test_run_2_agrelo_bearing_is_rounded_then_checked() -> None:
    agrelo = aprs.AgreloDf
    assert encode_info(agrelo(12.5, 5)) == b"%013/5"  # type: ignore[arg-type]
    assert encode_info(agrelo(12.49, 5)) == b"%012/5"  # type: ignore[arg-type]
    with pytest.raises(EncodeError) as e:
        encode_info(agrelo(360.5, 5))  # type: ignore[arg-type]
    assert e.value.code is RefusalCode.VALUE_OUT_OF_RANGE


def test_run_2_two_units_beat_the_size() -> None:
    with pytest.raises(EncodeError) as e:
        _ST.position(49.0, -72.0, symbol=Symbol.CAR, altitude_feet=100, altitude_m=30.48, comment="x" * 236)
    assert e.value.code is RefusalCode.VALUE_GIVEN_TWICE


def _refusal(call: object) -> str:
    with pytest.raises(EncodeError) as e:
        call()  # type: ignore[operator]
    return e.value.code.value


def test_run_4_a_held_packet_is_written_as_it_stands() -> None:
    # a decoded packet's TNC2, AX.25 and KISS forms are not an encoder: no size check
    packet = aprs.decode_tnc2(b"N0CALL>APZ001:>" + b"x" * 300)
    assert len(packet.info) == 301
    assert packet.to_tnc2().endswith(b"x" * 300)
    assert packet.to_ax25().endswith(b"x" * 300)
    assert packet.to_kiss().endswith(b"x" * 300 + b"\xc0")
    assert _refusal(lambda: encode_info(packet.data)) == "information-field-too-long"


def test_run_4_storm_fields_are_digits() -> None:
    head = ";BRENDA   *100045z4905.50N/07201.75W@101/047"
    full = head + "/HC/104^123/0980>065&020%040"
    assert aprs.decode_tnc2("N0CALL>APZ001:" + full).data.storm.whole_gale_radius_nm == 40  # type: ignore[attr-defined]
    dotted = aprs.decode_tnc2("N0CALL>APZ001:" + head + "/HC/...^123/0980>065&020%040").data
    assert dotted.storm is None  # type: ignore[attr-defined]
    assert dotted.comment == "HC/...^123/0980>065&020%040"  # type: ignore[attr-defined]
    ends = aprs.decode_tnc2("N0CALL>APZ001:" + head + "/HC/104^123/0980>065&020%4.410").data
    assert ends.storm.whole_gale_radius_nm is None  # type: ignore[attr-defined]
    assert ends.comment == "%4.410"  # type: ignore[attr-defined]
    missing = aprs.ObjectReport(
        name="BRENDA",
        timestamp=aprs.Timestamp("100045z"),
        latitude=49.0,
        longitude=-72.0,
        symbol=aprs.Symbol("/", "@"),
        storm=aprs.Storm(aprs.StormType.HURRICANE, sustained_wind_knots=104),
    )
    assert _refusal(lambda: encode_info(missing)) == "missing-field"


def test_run_4_a_telemetry_sequence_of_mic_and_more_is_malformed() -> None:
    mic1 = aprs.TelemetryReport("MIC1", (1, 2, 3, 4, 5), "00000000")
    assert _refusal(lambda: encode_info(mic1)) == "malformed"
    assert _refusal(lambda: encode_info(dataclasses.replace(mic1, comment="x" * 240))) == "malformed"


def test_run_4_a_run_on_value_ends_at_a_trailing_dao_or_telemetry() -> None:
    dao = aprs.decode_tnc2("N0CALL>APZ001:!4903.50N/07201.75W_220/004g005t2147483647!W12!").data
    assert dao.weather.temperature_f is None  # type: ignore[attr-defined]
    assert dao.dao is not None  # type: ignore[attr-defined]


def test_run_4_review_timestamp_false_is_no_timestamp() -> None:
    assert ST.position(51.0, -1.0, timestamp=False).info == ST.position(51.0, -1.0).info
    with pytest.raises(TypeError):
        ST.position(51.0, -1.0, timestamp=True)  # type: ignore[arg-type]


def test_run_4_review_a_finite_value_too_big_for_its_unit_is_out_of_range() -> None:
    assert _refusal(lambda: ST.mic_e(51.0, -1.0, altitude_m=1e308)) == "value-out-of-range"
    assert _refusal(lambda: ST.mic_e(51.0, -1.0, altitude_feet=1e308)) == "value-out-of-range"
    assert _refusal(lambda: ST.mic_e(51.0, -1.0, speed_kmh=1e308)) == "value-out-of-range"
    assert _refusal(lambda: ST.position(51.0, -1.0, altitude_m=1e308)) == "value-out-of-range"
    assert _refusal(lambda: ST.weather(51.0, -1.0, temperature_c=1e308)) == "value-out-of-range"
    assert _refusal(lambda: ST.mic_e(51.0, -1.0, altitude_m=float("inf"))) == "not-a-number"


_WX = "N0CALL>APZ001:!4903.50N/07201.75W_220/004g005"


@pytest.mark.parametrize(
    ("tail", "comment", "temperature"),
    [
        ("t2147483647|!!!!|7k", "7k", None),
        ("t247483647!W12!12!", "12!", None),
        ("t072r12345!W12!r001", "r001", 72),
        ("t072|!!!!|r000", "r000", 72),
    ],
)
def test_run_5_a_run_on_value_ends_at_a_lifted_element_anywhere(
    tail: str, comment: str, temperature: int | None
) -> None:
    result = aprs.decode_tnc2(_WX + tail)
    assert result.data.comment == comment
    assert result.data.weather.temperature_f == temperature
    codes = {str(d) for d in result.diagnostics}
    assert ("warning:out-of-range-value" in codes) == (temperature is None or "12345" in tail)


def test_run_5_a_run_on_value_before_telemetry_in_other_weather_reports() -> None:
    obj = aprs.decode_tnc2("N0CALL>APZ001:;OBJ      *092345z4903.50N/07201.75W_220/004g005h1234567|!!!!|t072")
    assert obj.data.comment == "t072"
    assert obj.data.weather.humidity_percent is None
    assert "warning:out-of-range-value" in {str(d) for d in obj.diagnostics}
    compressed = aprs.decode_tnc2("VK7DSH-1>APU25N:@252047z/c7NIs@rE_!!bg000t04600780|!)%Z'n|!r000p003P000h94b10236")
    assert compressed.data.comment == "!r000p003P000h94b10236"
    assert compressed.data.weather.temperature_f is None


_ST = Station("M0LTE-7", destination="APZXYZ", symbol=Symbol.CAR)


@pytest.mark.parametrize("comment", ["X", "Z", "Y"])
def test_run_5_mic_e_comment_after_a_frequency(comment: str) -> None:
    info = _ST.mic_e(8.43, 44.11, speed_kmh=0, comment=comment, frequency=144.39).info
    # only a comment that would read back as a device suffix needs the /
    assert info.endswith(b"144.390MHz /X" if comment == "X" else b"144.390MHz " + comment.encode())


def test_run_5_mic_e_suffix_like_comment_needs_no_slash_before_a_dao() -> None:
    info = _ST.mic_e(8.43, 44.11, speed_kmh=0, comment="X", frequency=144.39, dao=True).info
    assert b"144.390MHz X!" in info


def test_run_5_mic_e_comment_that_would_join_the_frequency_fields_follows_it_directly() -> None:
    info = _ST.mic_e(8.43, 44.11, speed_kmh=0, comment="-500 T110", frequency=144.39).info
    assert info.endswith(b"144.390MHz-500 T110")


# Round 5: a garbled timestamp before an uncompressed position.

_GARBLED_POSITION = "2831.00N/09601.00W>hi"


def _garbled(dti: str, stamp: str, rest: str = _GARBLED_POSITION, strict: bool = False) -> aprs.Packet:
    options = aprs.ParseOptions.strict() if strict else aprs.ParseOptions.lenient()
    return aprs.decode_tnc2(f"A>APRS:{dti}{stamp}{rest}".encode(), options)


def _codes(packet: aprs.Packet) -> list[str]:
    return [d.code.value for d in packet.diagnostics]


@pytest.mark.parametrize("indicator", ["z", "/", "h"])
@pytest.mark.parametrize("dti", ["/", "@"])
def test_garbled_timestamp_before_uncompressed_position(dti: str, indicator: str) -> None:
    stamp = "R30549" + indicator
    packet = _garbled(dti, stamp)
    assert isinstance(packet.data, aprs.PositionReport)
    assert packet.data.latitude == pytest.approx(28.516666666666666)
    assert packet.data.comment == "hi"
    assert packet.data.messaging is (dti == "@")
    assert _codes(packet) == ["malformed-timestamp"]
    assert aprs.encode_info(packet.data) == (b"=" if dti == "@" else b"!") + _GARBLED_POSITION.encode()
    strict = _garbled(dti, stamp, strict=True)
    assert isinstance(strict.data, aprs.Unrecognized)
    assert _codes(strict) == ["malformed-timestamp"]


def test_garbled_timestamp_lowercase_hemisphere_and_ambiguity() -> None:
    lower = _garbled("@", "R30549z", "2831.00n/09601.00w>hi")
    assert isinstance(lower.data, aprs.PositionReport)
    assert _codes(lower) == ["malformed-timestamp", "lowercase-hemisphere", "lowercase-hemisphere"]
    strict = _garbled("@", "R30549z", "2831.00n/09601.00w>hi", strict=True)
    assert _codes(strict) == ["malformed-timestamp"]
    blurred = _garbled("/", "R30549z", "283 .  N/09601.  W>hi")
    assert isinstance(blurred.data, aprs.PositionReport)
    assert blurred.data.latitude == pytest.approx(28.583333333333332)
    assert _codes(blurred) == ["malformed-timestamp"]
    assert _codes(_garbled("/", "R30549z", "283 .  N/09601.  W>hi", strict=True)) == ["malformed-timestamp"]


def test_garbled_timestamp_seventh_byte_not_a_time_indicator_reads_straight_after_dti() -> None:
    # Two damaged bytes: the seventh is not z, / or h, so the compressed reading at offset 1 stands.
    packet = _garbled("@", "R30549X")
    assert isinstance(packet.data, aprs.PositionReport)
    assert packet.data.comment != "hi"
    assert _codes(packet) == ["malformed-timestamp"]


def test_garbled_timestamp_short_field_does_not_take_the_new_branch() -> None:
    packet = aprs.decode_tnc2(b"A>APRS:@R30549z")
    assert _codes(packet) == ["malformed-timestamp"]
    assert isinstance(packet.data, aprs.Unrecognized)


_ALT_TELEMETRY = 'N0CALL>S32UVT:`(_fn"Oj/`IO91/G|!:&0hl!Y[/>"4e}=\'p|'


def _line_codes(line: str, options: aprs.ParseOptions | None = None) -> list[str]:
    packet = aprs.decode_tnc2(line) if options is None else aprs.decode_tnc2(line, options)
    return [d.code.value for d in packet.diagnostics]


@pytest.mark.parametrize("tail", [" DG2MM", " ", " x y"])
def test_round_5_mic_e_telemetry_split_by_a_lifted_altitude_is_text(tail: str) -> None:
    # the bars either side of the altitude do not join: no telemetry, so the locator's space is missing
    packet = aprs.decode_tnc2(_ALT_TELEMETRY + tail)
    assert sorted(_line_codes(_ALT_TELEMETRY + tail)) == ["mic-e-altitude-not-first", "missing-space-after-locator"]
    assert packet.data.telemetry is None
    assert packet.data.comment == "|!:&0hl!Y[/>='p|" + tail
    # strict reads the altitude as text too
    assert "missing-space-after-locator" in _line_codes(_ALT_TELEMETRY + tail, aprs.ParseOptions.strict())


def test_round_5_mic_e_locator_without_telemetry_still_misses_its_space() -> None:
    # nothing left between the bars once the altitude is out, so it is not telemetry
    codes = _line_codes('N0CALL>S32UVT:`(_fn"Oj/`IO91/G|"4e}|DG2MM')
    assert "missing-space-after-locator" in codes


_MIC_E_HEAD = 'N0CALL>S32UVT:`(_fn"Oj/`IO91/G'


def _mic_e_comment(tail: str) -> tuple[str | None, list[str]]:
    packet = aprs.decode_tnc2(_MIC_E_HEAD + tail)
    assert isinstance(packet.data, aprs.MicEReport)
    return packet.data.comment, [d.code.value for d in packet.diagnostics]


@pytest.mark.parametrize(
    ("tail", "comment"),
    [('!W1"4e}2! hi', "!W12! hi"), ('!W1"4e}2!', "!W12!"), ('!W1"4e}2!  hi', "!W12!  hi")],
)
def test_round_5_mic_e_dao_joined_across_an_altitude_is_text_and_needs_the_space(tail: str, comment: str) -> None:
    got, codes = _mic_e_comment(tail)
    assert got == comment
    assert sorted(codes) == ["mic-e-altitude-not-first", "missing-space-after-locator"]


@pytest.mark.parametrize(
    ("tail", "comment"),
    [('"4e}  x', "x"), ('"4e}   x', " x"), ('"4e} /x', "x"), ('"4e}  /x', "/x")],
)
def test_round_5_mic_e_two_spaces_after_the_locator_and_a_later_altitude(tail: str, comment: str) -> None:
    got, codes = _mic_e_comment(tail)
    assert got == comment
    assert codes == ["mic-e-altitude-not-first"]


@pytest.mark.parametrize(
    ("tail", "comment"),
    [("|!:&0hl!Y[/>\"4e}='p|  x", "|!:&0hl!Y[/>='p|  x"), ("|!:&0hl!Y[/>\"4e}='p| /x", "|!:&0hl!Y[/>='p| /x")],
)
def test_round_5_mic_e_text_left_by_a_lifted_altitude_is_not_telemetry(tail: str, comment: str) -> None:
    got, codes = _mic_e_comment(tail)
    assert got == comment
    assert sorted(codes) == ["mic-e-altitude-not-first", "missing-space-after-locator"]


@pytest.mark.parametrize(
    ("tail", "comment"),
    [("|!:&0'p|  x", "x"), ("|!:&0'p| /x", "x"), ("|!:&0'p|   x", " x"), ("|!:&0'p|  ", "")],
)
def test_round_5_mic_e_two_spaces_after_the_locator_and_telemetry(tail: str, comment: str) -> None:
    got, codes = _mic_e_comment(tail)
    assert (got or "") == comment
    assert codes == []


@pytest.mark.parametrize(
    "info",
    [
        '`io91sx/G"4e}!W12!!W12!}=',
        '>IO91/G"4"4T}T}!W1|!:&0\'p|}',
        ">IO91SX/G\"4e}hello|!:&0hl!Y[='p|}",
        "`IO91/Gx!W12!ab}",
        "]IO91/G!w3U!}PHG5132=",
    ],
)
def test_round_5_strict_meets_a_locators_missing_space_before_an_altitude_left_across_a_place(info: str) -> None:
    line = 'N0CALL>S32UVT:`(_fn"Oj/' + info
    strict = aprs.decode_tnc2(line, aprs.ParseOptions.strict())
    errors = [d.code.value for d in strict.diagnostics if d.severity.value == "error"]
    assert errors == ["missing-space-after-locator"]


def test_round_5_strict_reads_text_left_across_a_dao_when_the_locator_has_its_space() -> None:
    strict = aprs.decode_tnc2('N0CALL>S32UVT:`(_fn"Oj/`IO91/G x!W12!ab}', aprs.ParseOptions.strict())
    assert [d.code.value for d in strict.diagnostics if d.severity.value == "error"] == []
    assert isinstance(strict.data, aprs.MicEReport)
    assert strict.data.comment == "xab}"


_R5_POS = "N0CALL>APRS:!4903.50N/07201.75W>"


def _r5_data(line: str) -> aprs.AprsData:
    return aprs.decode_tnc2(line).data


def _r5_refused_as_a_field(line: str) -> None:
    with pytest.raises(EncodeError) as err:
        encode_info(aprs.decode_tnc2(line).data)
    assert err.value.code.value == "text-reads-as-field"


@pytest.mark.parametrize(
    ("tail", "comment", "attr"),
    [
        ("PH!W12!G3330 x", "PHG3330 x", "phg"),
        ("RNG00|!:&0'p|11", "RNG0011", "range_miles"),
        ("DFS3|!:&0'p|330", "DFS3330", "dfs"),
        ("x/A=00!W12!0123", "x/A=000123", "altitude_feet"),
    ],
)
def test_round_5_a_position_element_split_by_another_is_text(tail: str, comment: str, attr: str) -> None:
    data = _r5_data(_R5_POS + tail)
    assert getattr(data, attr) is None
    assert data.comment == comment
    _r5_refused_as_a_field(_R5_POS + tail)


def test_round_5_telemetry_split_by_a_dao_is_text() -> None:
    data = _r5_data(_R5_POS + "|!:&0!W12!'p|")
    assert data.telemetry is None
    assert data.comment == "|!:&0'p|"
    _r5_refused_as_a_field(_R5_POS + "|!:&0!W12!'p|")


def test_round_5_item_phg_split_by_telemetry_is_text() -> None:
    line = "N0CALL>APRS:)ITEM!4903.50N/07201.75W>PHG3|!:&0'p|330"
    data = _r5_data(line)
    assert data.phg is None
    assert data.telemetry is not None
    assert data.comment == "PHG3330"
    _r5_refused_as_a_field(line)


def test_round_5_object_signpost_split_by_an_altitude_is_text() -> None:
    line = "N0CALL>APRS:;SIGN     *092345z4903.50N\\07201.75Wm{5/A=000100 5}"
    data = _r5_data(line)
    assert data.signpost is None
    assert data.altitude_feet == 100
    assert data.comment == "{5 5}"


def test_round_5_weather_software_and_unit_split_by_telemetry_is_text() -> None:
    data = _r5_data("N0CALL>APRS:@092345z4903.50N/07201.75W_220/004g005t077X|!:&0'p|yz")
    assert data.weather.software is None
    assert data.telemetry is not None
    assert data.comment == "Xyz"
    packet = aprs.decode_tnc2("N0CALL>APRS:@092345z4903.50N/07201.75W_220/004g005t077X|!:&0'p|yz")
    assert "weather-comment" in [d.code.value for d in packet.diagnostics]


@pytest.mark.parametrize(
    ("tail", "tone"),
    [("/A=000100 T100 x", True), ("/A=000100 -060 x", False), ("|!:&0'p| T100 x", False), ("!W12! T100 x", False)],
)
def test_round_5_only_an_altitude_stands_between_a_frequency_and_its_fields(tail: str, tone: bool) -> None:
    data = _r5_data(_R5_POS + "146.520MHz" + tail)
    assert data.frequency.mhz == 146.52
    assert (data.frequency.tone is not None) is tone or data.frequency.offset_khz is not None


@pytest.mark.parametrize(
    "tail",
    [
        "/|!:&0'p|146.520MHz T100 x",
        " |!:&0'p|146.520MHz T100 x",
        "/!W12!146.520MHz T100 x",
        " /A=000100146.520MHz T100 x",
    ],
)
def test_round_5_a_frequency_after_a_delimiter_and_a_lifted_element_is_read(tail: str) -> None:
    data = _r5_data(_R5_POS + tail)
    assert data.frequency is not None
    assert data.frequency.mhz == 146.52
    assert data.frequency.tone_value == 100
    assert data.comment == "x"


def test_round_5_a_mic_e_frequency_after_a_slash_and_a_later_altitude_is_read() -> None:
    data = _r5_data('N0CALL>S32UVT:`(_fn"Oj/`/"4e}146.520MHz T100 x')
    assert data.frequency is not None
    assert data.frequency.mhz == 146.52
    assert data.altitude_feet is not None
    assert data.comment == "x"


def test_round_5_a_frequency_split_by_a_lifted_element_after_a_delimiter_is_still_text() -> None:
    data = _r5_data(_R5_POS + "/|!:&0'p|146.5|!:&0'p|20MHz x")
    assert data.frequency is None


def test_round_5_a_frequency_split_by_an_altitude_in_a_mic_e_status_is_text() -> None:
    data = _r5_data('N0CALL>S32UVT:`(_fn"Oj/`146.5/A=00010020MHz T100')
    assert data.frequency is None
    assert data.altitude_feet is not None
    assert data.comment == "146.520MHz T100"


def test_round_5_a_mic_e_phg_split_by_telemetry_after_a_locator_is_text() -> None:
    data = _r5_data("N0CALL>S32UVT:`(_fn\"Oj/`IO91/G PHG3|!:&0'p|330")
    assert data.phg is None
    assert data.comment == "PHG3330"
