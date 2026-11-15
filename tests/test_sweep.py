"""A sweep: hostile numbers in every numeric field of every data type and builder argument, at depth 0, 1
and 2 of third-party nesting. Each call must either refuse with an ``EncodeError`` or write bytes that read
back as the data given, and never raise anything else; a NaN or an infinity is never written."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Iterator
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

import pdn_aprs as aprs
from pdn_aprs import EncodeError
from pdn_aprs import encode as enc
from pdn_aprs._neutral import from_neutral, to_neutral
from pdn_aprs._readback import mismatch

NAN, INF = float("nan"), float("inf")
NUMBERS: list[Any] = [
    NAN,
    INF,
    -INF,
    1.7976931348623157e308,
    -1.7976931348623157e308,
    5e-324,
    -0.0,
    0.5,
    -1,
    2**63,
    10**400,
    -(10**400),
    Decimal("1.5"),
    Decimal("NaN"),
    Fraction(1, 2),
]
WRONG_TYPES: list[Any] = [True, None, "x"]
NON_FINITE = (NAN, INF, -INF)

NMEA = "GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
POSITION = {"type": "position", "latitude": 51.5, "longitude": -0.5, "symbol": "/>"}
MIC_E = {"type": "mic-e", "mic_e_message": "off-duty", "latitude": 51.5, "longitude": -0.5, "symbol": "/>"}
WEATHER = {
    "wind_direction_degrees": 100,
    "wind_speed_mph": 5,
    "wind_gust_mph": 9,
    "temperature_f": 70,
    "rain_1h_in": 0.1,
    "rain_24h_in": 0.2,
    "rain_midnight_in": 0.3,
    "humidity_percent": 50,
    "pressure_mbar": 1013.2,
    "luminosity_w_m2": 200,
    "snow_24h_in": 1.5,
    "rain_raw": 5,
}
SAMPLES: list[dict[str, Any]] = [
    POSITION | {"course_degrees": 90, "speed_knots": 10, "altitude_feet": 100, "ambiguity": 1},
    POSITION | {"compressed": True, "course_degrees": 90, "speed_knots": 10},
    POSITION | {"range_miles": 5, "dao": {"datum": "W", "precision": "base91"}},
    POSITION | {"phg": {"power": 4, "height": 1, "gain": 3, "directivity": 2, "beacons_per_hour": 2}},
    POSITION | {"dfs": {"strength": 4, "height": 1, "gain": 3, "directivity": 2}},
    POSITION | {"symbol": "\\l", "area": {"shape": "open-circle", "color": "blue", "lat_offset": 1, "lon_offset": 2}},
    POSITION
    | {
        "symbol": "/\\",
        "course_degrees": 10,
        "speed_knots": 5,
        "df_bearing": {"bearing_degrees": 100, "number": 1, "range": 2, "quality": 3},
    },
    POSITION
    | {
        "symbol": "\\@",
        "storm": {
            "type": "hurricane",
            "sustained_wind_knots": 100,
            "gust_knots": 120,
            "central_pressure_mbar": 950,
            "hurricane_radius_nm": 40,
            "tropical_storm_radius_nm": 80,
            "whole_gale_radius_nm": 150,
        },
    },
    POSITION
    | {
        "comment": "hi",
        "telemetry": {"sequence": 10, "analog": [1, 2, 3, 4, 5], "digital": 3},
        "frequency": {"mhz": 146.52, "tone": "tone", "tone_value": 100, "offset_khz": 600, "range": 25},
    },
    POSITION | {"symbol": "/_", "weather": WEATHER},
    {
        "type": "object",
        "name": "OBJ",
        "timestamp": "092345z",
        **{k: POSITION[k] for k in ("latitude", "longitude", "symbol")},
    }
    | {"altitude_feet": 100},
    {"type": "item", "name": "ITEM", "latitude": 51.5, "longitude": -0.5, "symbol": "/>", "course_degrees": 1},
    MIC_E | {"course_degrees": 90, "speed_knots": 10, "altitude_feet": 100, "destination_ssid": 3, "type_code": "`"},
    MIC_E | {"legacy_telemetry": [1, 2, 3, 4, 5]},
    {"type": "weather", "timestamp": "10090556", "weather": WEATHER},
    {"type": "telemetry", "sequence": "1", "analog": [1, 2, 3, 4, 5], "bits": "00000000"},
    {"type": "telemetry-coefficients", "addressee": "N0CALL", "coefficients": [0, 0.5, 1]},
    {"type": "query", "query_type": "APRS", "footprint": {"latitude": 1.0, "longitude": 2.0, "radius_miles": 50}},
    {"type": "nmea", "sentence": NMEA, "has_checksum": True, "latitude": 48.1173, "longitude": 11.516666666666667}
    | {"fix": "valid", "altitude_m": 545.4},
    {"type": "agrelo-df", "bearing_degrees": 90, "quality": 5},
]


def _leaves(obj: Any, path: tuple[Any, ...] = ()) -> Iterator[tuple[Any, ...]]:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield path
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            yield from _leaves(getattr(obj, f.name), (*path, f.name))
    elif isinstance(obj, tuple):
        for i, v in enumerate(obj):
            yield from _leaves(v, (*path, i))


def _put(obj: Any, path: tuple[Any, ...], value: Any) -> Any:
    if not path:
        return value
    head, rest = path[0], path[1:]
    if isinstance(head, int):
        items = list(obj)
        items[head] = _put(items[head], rest, value)
        return tuple(items)
    return dataclasses.replace(obj, **{head: _put(getattr(obj, head), rest, value)})


def _wrap(data: aprs.AprsData, depth: int) -> aprs.AprsData:
    for _ in range(depth):
        data = aprs.ThirdParty(aprs.Packet("N0CALL", "APRS", (), b"", data))
    return data


def _check(data: aprs.AprsData, value: Any, where: str) -> None:
    try:
        info = enc.encode_info(data)
    except EncodeError:
        return
    except Exception as e:  # the point of the sweep
        pytest.fail(f"{where} = {value!r}: {type(e).__name__}: {e}")
    if isinstance(value, float) and not math.isfinite(value):
        pytest.fail(f"{where} = {value!r} was written: {info!r}")
    written = enc._write(data)
    data = enc._normalise(data, enc._real)  # a Decimal or Fraction is the number it reads as
    assert mismatch(data, to_neutral(data), written.info, written.destination) is None, f"{where} = {value!r}"


@pytest.mark.parametrize("depth", [0, 1, 2])
@pytest.mark.parametrize("sample", range(len(SAMPLES)))
def test_every_numeric_field_takes_hostile_numbers_without_a_crash(sample: int, depth: int) -> None:
    base = from_neutral(SAMPLES[sample])
    assert enc.encode_info(_wrap(base, depth))  # the sample itself is sound
    for path in _leaves(base):
        for value in [*NUMBERS, *WRONG_TYPES]:
            try:
                data = _put(base, path, value)
            except Exception:
                continue
            _check(_wrap(data, depth), value, ".".join(map(str, path)))


def test_a_non_finite_number_is_never_written_in_an_nmea_field_or_an_inner_packet() -> None:
    nmea = from_neutral(SAMPLES[-2])
    for field in ("latitude", "longitude", "course_degrees", "speed_knots", "altitude_m"):
        for value in NON_FINITE:
            data = dataclasses.replace(nmea, **{field: value})
            for depth in (0, 1, 2):
                with pytest.raises(EncodeError) as caught:
                    enc.encode_info(_wrap(data, depth))
                assert caught.value.code is aprs.RefusalCode.NOT_A_NUMBER
                with pytest.raises(EncodeError):
                    aprs.build_packet("N0CALL", _wrap(data, depth))


def test_a_decoded_inner_packet_given_an_infinity_is_refused() -> None:
    held = aprs.decode_tnc2(b"N0CALL>APRS:}X>APRS:!5130.00N/00030.00W>088/036")
    assert isinstance(held.data, aprs.ThirdParty)
    inner = held.data.packet
    assert isinstance(inner.data, aprs.PositionReport)
    for kw in ({"latitude": INF}, {"course_degrees": -INF}, {"longitude": NAN}):
        data = aprs.ThirdParty(dataclasses.replace(inner, data=dataclasses.replace(inner.data, **kw)))
        with pytest.raises(EncodeError) as caught:
            enc.encode_info(data)
        assert caught.value.code is aprs.RefusalCode.NOT_A_NUMBER


def test_a_non_finite_number_equals_nothing_in_the_comparison() -> None:
    from pdn_aprs import _util

    for value in NON_FINITE:
        assert not _util.number_equal(value, 48.1173)
        assert not _util.number_equal(48.1173, value)
        assert not _util.number_equal(value, value)


# ---------------------------------------------------------------- builder arguments

STATION = aprs.Station("N0CALL", symbol=aprs.Symbol.CAR)
BUILDERS: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = [
    ("position", (51.5, -0.5), {"course_degrees": 90, "speed_knots": 10, "altitude_feet": 100, "ambiguity": 1}),
    ("position", (51.5, -0.5), {"range_miles": 5, "phg": aprs.Phg(1, 2, 3, 4), "speed_kmh": 5, "altitude_m": 5}),
    ("mic_e", (51.5, -0.5), {"course_degrees": 90, "speed_knots": 10, "altitude_feet": 100, "ambiguity": 1}),
    ("mic_e", (51.5, -0.5), {"speed_kmh": 10, "altitude_m": 100}),
    ("weather", (51.5, -0.5), {k: v for k, v in WEATHER.items() if k != "rain_raw"}),
    ("telemetry", (5, [1, 2, 3, 4, 5], "00000000"), {}),
]


@pytest.mark.parametrize("which", range(len(BUILDERS)))
def test_every_numeric_builder_argument_takes_hostile_numbers_without_a_crash(which: int) -> None:
    name, args, kwargs = BUILDERS[which]
    method = getattr(STATION, name)
    spots: list[tuple[Any, ...]] = [("arg", i) for i, a in enumerate(args) if isinstance(a, (int, float))]
    spots += [("kw", k) for k, v in kwargs.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    for kind, key in spots:
        for value in [*NUMBERS, *WRONG_TYPES]:
            a, kw = list(args), dict(kwargs)
            if kind == "arg":
                a[key] = value
            else:
                kw[key] = value
            try:
                packet = method(*a, **kw)
            except EncodeError:
                continue
            except (ValueError, TypeError) as e:
                # a call that cannot mean anything (documented): a ValueError, or the telemetry
                # sequence's own "must be an int" TypeError
                if not (isinstance(e, ValueError) or "must be" in str(e)):
                    pytest.fail(f"{name}({key}={value!r}): {e!r}")
                continue
            except Exception as e:
                pytest.fail(f"{name}({key}={value!r}): {type(e).__name__}: {e}")
            if isinstance(value, float) and not math.isfinite(value):
                pytest.fail(f"{name}({key}={value!r}) built {packet.info!r}")
            assert packet.to_tnc2()


# ---------------------------------------------------------------- hidden text that keeps a number as sent

HOSTILE_TEXT = ["nan", "inf", "-inf", "1e999", "", "0x10", "-0", "1_0", "١٢", " 1", "1 ", "+1", "1.", ".", "--1"]


@pytest.mark.parametrize("depth", [0, 1, 2])
def test_hidden_text_that_keeps_a_number_as_sent_never_crashes_or_reads_back_wrong(depth: int) -> None:
    query = from_neutral(SAMPLES[17])
    assert isinstance(query, aprs.Query)
    assert query.footprint is not None
    telemetry = from_neutral(SAMPLES[15])
    coefficients = from_neutral(SAMPLES[16])
    cases: list[tuple[aprs.AprsData, str, Any]] = []
    for text in HOSTILE_TEXT:
        for name in ("latitude_text", "longitude_text"):
            footprint = dataclasses.replace(query.footprint, **{name: text})
            cases.append((dataclasses.replace(query, footprint=footprint), name, text))
        for i in range(5):
            texts = tuple(text if j == i else "" for j in range(5))
            cases.append((dataclasses.replace(telemetry, analog_text=texts), "analog_text", texts))
        for i in range(3):
            texts = tuple(text if j == i else "0" for j in range(3))
            cases.append((dataclasses.replace(coefficients, coefficients_text=texts), "coefficients_text", texts))
    for data, name, value in cases:
        _check(_wrap(data, depth), value, name)
