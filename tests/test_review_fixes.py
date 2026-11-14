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


def test_whole_exact_telemetry_values_keep_their_digits() -> None:
    big = 10**25 + 1
    info = _ST.telemetry(1, (Fraction(big), Decimal(big), 2, 3, 4), "00000000").info
    assert info.startswith(f"T#001,{big},{big},002,003,004,".encode())


def test_telemetry_sequence_type_error_names_the_type() -> None:
    with pytest.raises(TypeError, match="not Decimal"):
        _ST.telemetry(Decimal(1), (1, 2, 3, 4, 5))  # type: ignore[arg-type]


def test_run_2_non_finite_value_with_no_place_and_gga_altitude() -> None:
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
    assert e.value.code is RefusalCode.FIELD_NOT_ALLOWED
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
