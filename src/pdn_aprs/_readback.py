"""The read-back: what it means for bytes to read back as the data they were written from.

Every encoder ends in one check (``encode._read_back``): decode the information field written,
leniently, and compare the result with the data given. This module is the comparison, stated once
for every report type (the vectors' README, Rules, Read-back):

* **Diagnostics.** The decode has no warning and no error, and an ``info`` only where the rules
  attach it to the form the data itself asks for (``obsolete-format`` on a positionless weather
  report, raw weather, an NMEA sentence, a Maidenhead beacon and Mic-E Rev 0 telemetry;
  ``mic-e-missing-device-type`` on a Mic-E report; ``invalid-query`` and
  ``invalid-telemetry-metadata`` on a message). A third-party packet's inner packet is held to the same for its
  warnings and errors; its ``info`` diagnostics are not compared.
* **Fields.** In the neutral data form, at every depth, every field given is in the decode with
  the same value and the decode has no field not given. Strings, booleans, integers and
  enumerations compare exactly, a number without steps within 1e-9. Only three differences are
  allowed: (1) a number the form holds in steps is the value given rounded once, as the Encoding
  rule rounds it, to the step of the form written (the exact rounded value, not a tolerance);
  (2) a value the form must carry where the data leaves it out (the default compression type, a
  Mic-E speed of 0, the fields an NMEA sentence determines); (3) empty and absent are one value
  (the neutral form already leaves out an empty string or list).
"""

from __future__ import annotations

import math
from typing import Any, TypeGuard

from . import _util
from ._comment import MICROWAVE_BASE
from ._decode import Ctx, decode_info
from ._neutral import to_neutral
from .diagnostics import DiagnosticCode, Severity
from .model import (
    AprsData,
    CompressionType,
    MaidenheadBeacon,
    Message,
    MicEReport,
    NmeaSentence,
    PositionlessWeather,
    RawWeather,
    ThirdParty,
)
from .options import _LENIENT

__all__ = ["mismatch"]

_nearest = _util.round_half_away


def _info_allowed(code: DiagnosticCode, decoded: AprsData) -> bool:
    """Whether an ``info`` diagnostic is one the rules attach to the form the data itself asks for:
    ``obsolete-format`` on a positionless weather report, raw weather, an NMEA sentence, a Maidenhead
    beacon and Mic-E Rev 0 telemetry; ``mic-e-missing-device-type`` on a Mic-E report;
    ``invalid-query`` and ``invalid-telemetry-metadata`` on a message the rules read as a plain one.
    An info listed for one form is not accepted on another."""
    if code is DiagnosticCode.OBSOLETE_FORMAT:
        return isinstance(decoded, (PositionlessWeather, RawWeather, NmeaSentence, MaidenheadBeacon)) or (
            isinstance(decoded, MicEReport) and bool(decoded.legacy_telemetry)
        )
    if code is DiagnosticCode.MIC_E_MISSING_DEVICE_TYPE:
        return isinstance(decoded, MicEReport)
    if code in (DiagnosticCode.INVALID_QUERY, DiagnosticCode.INVALID_TELEMETRY_METADATA):
        return isinstance(decoded, Message)
    return False


_NMEA_DETERMINED = ("has_checksum", "latitude", "longitude", "fix", "course_degrees", "speed_knots", "altitude_m")
_NMEA_DETERMINED_TEXT = ("time", "waypoint")
"""The fields an NMEA sentence determines: data that leaves one out reads back with the sentence's own."""

_POSITIONED = ("position", "object", "item", "mic-e")
_AMBIGUITY_BOX = (1, 10, 100, 1000, 6000)
"""The box each ambiguity level leaves, in hundredths of a minute."""


def mismatch(data: AprsData, given: dict[str, Any], info: bytes, destination: str) -> str | None:
    """Why ``info`` does not read back as ``data`` (whose neutral form is ``given``), or None when
    it does. The information field is decoded leniently, under ``destination``."""
    ctx = Ctx(_LENIENT)
    decoded = decode_info(info, destination, ctx)
    for diag in ctx.diags:
        if diag.severity is not Severity.INFO or not _info_allowed(diag.code, decoded):
            return f"it decodes with {diag}"
    found = to_neutral(decoded)
    expected = _clone(given)
    _prepare(expected, found, decoded)
    return _differences(expected, found, "")


# ---------------------------------------------------------------- comparing


def _clone(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clone(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clone(v) for v in value]
    return value


def _differences(expected: Any, found: Any, path: str) -> str | None:
    """The first difference between the data given (with its allowances applied) and the decode."""
    if isinstance(expected, dict) and isinstance(found, dict):
        # a third-party packet's inner packet is held to the same: its warnings and errors are a field
        # of the data like any other (given, they are written as received; not given, they fail the
        # read-back), and its info diagnostics, given or decoded, are not compared
        if _inner_diagnostics(expected) != _inner_diagnostics(found):
            return f"{path}diagnostics read back as {_inner_diagnostics(found)}, not {_inner_diagnostics(expected)}"
        for key in expected:
            if key == "diagnostics":
                continue
            if key not in found:
                return f"{path}{key} is not read back"
            sub = _differences(expected[key], found[key], f"{path}{key}.")
            if sub is not None:
                return sub
        for key in found:
            if key not in expected and key != "diagnostics":
                return f"{path}{key} was not given"
        return None
    if isinstance(expected, list) and isinstance(found, list):
        if len(expected) != len(found):
            return f"{path[:-1]} has {len(found)} items, not {len(expected)}"
        for i, (x, y) in enumerate(zip(expected, found, strict=True)):
            sub = _differences(x, y, f"{path[:-1]}[{i}].")
            if sub is not None:
                return sub
        return None
    if isinstance(expected, bool) or isinstance(found, bool):
        same = expected is found
    elif isinstance(expected, (int, float)) and isinstance(found, (int, float)):
        same = _same_number(expected, found)
    else:
        same = bool(expected == found) and type(expected) is type(found)
    return None if same else f"{path[:-1]} reads back as {found!r}, not {expected!r}"


def _inner_diagnostics(values: dict[str, Any]) -> list[str]:
    """An inner packet's warnings and errors, in order of their text: its infos are left out."""
    diagnostics = values.get("diagnostics")
    if not isinstance(diagnostics, list):
        return []
    return sorted(str(d) for d in diagnostics if not str(d).startswith("info:"))


def _same_number(a: float, b: float) -> bool:
    if isinstance(a, int) and isinstance(b, int) and max(abs(a), abs(b)) <= 2**53:
        return a == b
    try:
        return _util.number_equal(a, b)
    except OverflowError:
        return bool(a == b)


# ---------------------------------------------------------------- the data given, as the form holds it


def _prepare(given: dict[str, Any], found: dict[str, Any], decoded: AprsData) -> None:
    """Apply the allowances to ``given``, in place: each number the form holds in steps becomes the
    value rounded to the step of the form actually written, and each value the form must carry,
    where the data leaves it out, is the one the decode has."""
    kind = given.get("type")
    if kind != found.get("type"):
        return
    if kind in _POSITIONED:
        _positioned(given, found, decoded)
    elif kind == "weather":
        _weather(given.get("weather"), found.get("weather"), cs=False)
    elif kind == "agrelo-df":
        _round_key(given, "bearing_degrees", _nearest)
    elif kind == "query":
        footprint = given.get("footprint")
        if isinstance(footprint, dict):
            _round_key(footprint, "radius_miles", _nearest)
    elif kind == "nmea":
        for key in _NMEA_DETERMINED + _NMEA_DETERMINED_TEXT:
            if key not in given and key in found:
                given[key] = found[key]
    elif kind == "third-party" and isinstance(decoded, ThirdParty):
        _third_party(given, found, decoded)


def _third_party(given: dict[str, Any], found: dict[str, Any], decoded: ThirdParty) -> None:
    packet, inner = given.get("packet"), found.get("packet")
    if not isinstance(packet, dict) or not isinstance(inner, dict):
        return
    data, found_data = packet.get("data"), inner.get("data")
    if isinstance(data, dict) and isinstance(found_data, dict):
        if data.get("type") == "mic-e":
            # a Mic-E report's destination is computed from the data, and read back through the data
            packet["destination"] = inner.get("destination", packet.get("destination"))
        _prepare(data, found_data, decoded.packet.data)


def _round_key(values: dict[str, Any], key: str, rounder: Any) -> None:
    value = values.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        values[key] = rounder(value)


def _is_negative(value: float) -> bool:
    return value < 0 or (value == 0 and math.copysign(1.0, value) < 0)


def _number(value: Any) -> TypeGuard[float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _position(value: float, *, latitude: bool, compressed: bool, ambiguity: int, dao: str) -> float:
    """A latitude or longitude as the form written holds it."""
    if compressed:
        if latitude:
            y = min(max(_nearest(380926 * (90 - float(value))), 0), 91**4 - 1)
            return 90 - y / 380926
        x = min(max(_nearest(190463 * (180 + float(value))), 0), 91**4 - 1)
        return -180 + x / 190463
    magnitude = abs(float(value))
    if ambiguity and 0 < ambiguity < len(_AMBIGUITY_BOX):
        # the centre of the box that holds the value, which is cut, not rounded
        box = _AMBIGUITY_BOX[ambiguity]
        units = math.floor(magnitude * 6000 / box + _util.HALF_TOLERANCE) * box + box / 2
        result = units / 6000
    elif dao == "thousandths":
        result = _nearest(magnitude * 60 * 1000) / (60 * 1000)
    elif dao == "base91":
        result = _nearest(magnitude * 60 * 9100) / (60 * 9100)
    else:
        result = _nearest(magnitude * 6000) / 6000
    return -result if _is_negative(float(value)) else result


def _cs_course(value: float) -> int:
    """A course in cs bytes: steps of 4 degrees, north reading back as 360."""
    c = _nearest(_util.decimal(value) / 4) % 90
    return 360 if c == 0 else c * 4


def _cs_speed(knots: float) -> float:
    return float(1.08 ** _nearest(math.log(knots + 1) / math.log(1.08)) - 1)


def _positioned(given: dict[str, Any], found: dict[str, Any], decoded: AprsData) -> None:
    mic_e = given["type"] == "mic-e"
    compressed = bool(found.get("compressed"))
    ambiguity = found.get("ambiguity", 0)
    ambiguity = ambiguity if isinstance(ambiguity, int) else 0
    dao_found = found.get("dao")
    dao = dao_found.get("precision", "none") if isinstance(dao_found, dict) else "none"
    for key, latitude in (("latitude", True), ("longitude", False)):
        if _number(given.get(key)):
            given[key] = _position(given[key], latitude=latitude, compressed=compressed, ambiguity=ambiguity, dao=dao)
    weather = isinstance(given.get("weather"), dict)
    source = (found.get("compression") or {}).get("source") if isinstance(found.get("compression"), dict) else None
    if compressed:
        if _number(given.get("course_degrees")):
            given["course_degrees"] = _cs_course(given["course_degrees"])
        if _number(given.get("speed_knots")):
            given["speed_knots"] = _cs_speed(given["speed_knots"])
        if _number(given.get("range_miles")) and given["range_miles"] > 0:
            step = _nearest(math.log(given["range_miles"] / 2) / math.log(1.08))
            given["range_miles"] = 2 * 1.08**step
    else:
        _round_key(given, "course_degrees", _nearest)
        _round_key(given, "speed_knots", _nearest)
        _round_key(given, "range_miles", _nearest)
    altitude = given.get("altitude_feet")
    if _number(altitude):
        if mic_e and not getattr(decoded, "altitude_in_comment", False):
            given["altitude_feet"] = _nearest(altitude / _util.FEET_PER_METRE) * _util.FEET_PER_METRE
        elif mic_e:
            # a /A= beside the Mic-E bytes is allowed only where it holds the value exactly (whole feet)
            if abs(altitude - round(altitude)) <= 1e-6:
                given["altitude_feet"] = _nearest(altitude)
        elif compressed and source == "gga":
            held = 1.002 ** min(
                max(_nearest(math.log(altitude) / math.log(1.002)) if altitude >= 1 else 0, 0), 91 * 91 - 1
            )
            if weather or _util.number_equal(held, altitude):
                # the cs bytes alone, and 1 foot or less is 1 foot; a /A= wins where they cannot say it
                given["altitude_feet"] = held
            else:
                given["altitude_feet"] = _nearest(altitude)
        else:
            given["altitude_feet"] = _nearest(altitude)
    frequency = given.get("frequency")
    if isinstance(frequency, dict):
        found_frequency = found.get("frequency")
        ten = isinstance(found_frequency, dict) and bool(found_frequency.get("ten_khz_resolution"))
        _frequency(frequency, ten)
    _weather(given.get("weather"), found.get("weather"), cs=compressed)
    # a value the form must carry where the data leaves it out
    if mic_e and "speed_knots" not in given and found.get("speed_knots") == 0:
        given["speed_knots"] = 0
    if compressed and "compression" not in given and found.get("compression") == _default_compression():
        carries = any(key in given for key in ("course_degrees", "speed_knots", "range_miles")) or (
            isinstance(given.get("weather"), dict)
            and any(key in given["weather"] for key in ("wind_direction_degrees", "wind_speed_mph"))
        )
        if carries:
            given["compression"] = found["compression"]


def _default_compression() -> dict[str, str]:
    default = CompressionType()
    return {"fix": default.fix.value, "source": default.source.value, "origin": default.origin.value}


def _frequency(frequency: dict[str, Any], ten_khz: bool) -> None:
    places = 2 if ten_khz else 3
    scale = 10**places
    mhz = frequency.get("mhz")
    if _number(mhz) and mhz >= 0:
        if mhz >= 1000:
            for base in MICROWAVE_BASE.values():
                if base <= mhz < base + 100:
                    frequency["mhz"] = base + _nearest((float(mhz) - base) * scale) / scale
                    break
        else:
            frequency["mhz"] = _nearest(float(mhz) * scale) / scale


def _snowfall(snow: float) -> float:
    """Snowfall as its three characters hold it: hundredths under 1, tenths under 10, else whole."""
    hundredths = _nearest(float(snow) * 100)
    if hundredths < 100:
        return hundredths / 100
    tenths = _nearest(float(snow) * 10)
    if tenths < 100:
        return tenths / 10
    return float(_nearest(snow))


def _weather(given: Any, found: Any, *, cs: bool) -> None:
    if not isinstance(given, dict):
        return
    if cs:
        # the wind in a compressed position's cs bytes: a direction in steps of 4 degrees (north
        # reads back as 0) and a speed in knots' steps
        direction = given.get("wind_direction_degrees")
        if _number(direction):
            given["wind_direction_degrees"] = (_nearest(_util.decimal(direction) / 4) % 90) * 4
        speed = given.get("wind_speed_mph")
        if _number(speed) and speed / _util.KNOTS_TO_MPH > -1:
            given["wind_speed_mph"] = _cs_speed(speed / _util.KNOTS_TO_MPH) * _util.KNOTS_TO_MPH
    else:
        _round_key(given, "wind_direction_degrees", _nearest)
        _round_key(given, "wind_speed_mph", _nearest)
    for key in ("wind_gust_mph", "temperature_f", "humidity_percent", "luminosity_w_m2", "rain_raw"):
        _round_key(given, key, _nearest)
    for key in ("rain_1h_in", "rain_24h_in", "rain_midnight_in"):
        _round_key(given, key, lambda v: _nearest(float(v) * 100) / 100)
    _round_key(given, "pressure_mbar", lambda v: _nearest(float(v) * 10) / 10)
    _round_key(given, "snow_24h_in", _snowfall)
