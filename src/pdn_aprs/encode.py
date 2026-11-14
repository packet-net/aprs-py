"""Encoding: data into an information field (and, for Mic-E, the destination address).

The encoder writes only what the specification allows and raises :class:`EncodeError`
otherwise. Free text is checked by decoding what was written: a comment that would read back
as something else (an altitude, a data extension, a leading delimiter...) gets a ``/`` delimiter
in front, and is refused if even that does not read back.

>>> from pdn_aprs import PositionReport, Symbol
>>> from pdn_aprs.encode import encode_info
>>> encode_info(PositionReport(latitude=51.5, longitude=-0.11666666666666667, symbol=Symbol.CAR,
...                            messaging=True, course_degrees=88, speed_knots=36, comment="Mobile"))
b'=5130.00N/00007.00W>088/036Mobile'
"""

from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Callable, Iterable
from fractions import Fraction
from typing import Any, TypeVar

from . import _util
from ._comment import MICROWAVE_BASE
from .diagnostics import DiagnosticCode, Severity
from .errors import EncodeError, RefusalCode
from .model import (
    Ack,
    AgreloDf,
    AprsData,
    AreaShape,
    Bulletin,
    Capabilities,
    CommentTelemetry,
    CompressionSource,
    CompressionType,
    DaoPrecision,
    DirectedQuery,
    ItemReport,
    MaidenheadBeacon,
    Message,
    MicEMessage,
    MicEReport,
    NmeaSentence,
    NwsBulletin,
    ObjectReport,
    PositionedData,
    PositionlessWeather,
    PositionReport,
    Query,
    RawWeather,
    RawWeatherFormat,
    Reject,
    StatusReport,
    StormType,
    TelemetryBits,
    TelemetryCoefficients,
    TelemetryNames,
    TelemetryReport,
    TelemetryUnits,
    TestData,
    ThirdParty,
    Timestamp,
    TimestampKind,
    ToneType,
    Unrecognized,
    UnrecognizedReason,
    UserDefined,
    VoiceFrequency,
    Weather,
)
from .options import _LENIENT
from .packet import Packet, PathEntry, _tnc2_path

__all__ = [
    "DEFAULT_DESTINATION",
    "MESSAGE_TEXT_LIMIT",
    "build_packet",
    "encode_info",
    "mic_e_destination",
]

DEFAULT_DESTINATION = "APZ001"
"""The destination used when none is given: ``APZ`` is the experimental tocall. Use the one
allocated to your application in the aprs-deviceid database."""

MESSAGE_TEXT_LIMIT = 67
"""The longest message or bulletin text a sender may write (APRS12c ch. 14)."""

_P = TypeVar("_P", bound=PositionedData)
_T = TypeVar("_T")

_nearest = _util.round_half_away
"""Every value the encoder rounds goes to the nearest step, halves away from zero."""

_TELEMETRY_TITLE_LIMIT = 23
_TIMESTAMPED = (TimestampKind.DHM_ZULU, TimestampKind.DHM_LOCAL, TimestampKind.HMS)


_TELEMETRY_VALUE = re.compile(r"-?(?:[0-9]+\.?[0-9]*|\.[0-9]+)\Z")
_COEFFICIENT = re.compile(r"-?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?\Z")
_FOOTPRINT_VALUE = re.compile(r"(?: ?(?:[0-9]+\.?[0-9]*|\.[0-9]+)|-(?:[0-9]+\.?[0-9]*|\.[0-9]+))\Z")
"""A footprint latitude or longitude as sent: a leading space only before a positive value."""


def _same_number(text: str, value: float, form: re.Pattern[str]) -> bool:
    """Whether a number kept as sent is one ``form`` allows and still says ``value``, so that it
    can be written back."""
    if not form.match(text):
        return False
    try:
        return _util.number_equal(float(text), float(value))
    except (ValueError, OverflowError):
        return False


def _refuse(code: RefusalCode, why: str) -> EncodeError:
    return EncodeError(why, code)


_ORDER = (
    RefusalCode.NOT_ENCODABLE,
    RefusalCode.INVALID_ADDRESS,
    RefusalCode.AX25_CANNOT_CARRY,
    RefusalCode.TNC2_CANNOT_CARRY,
    RefusalCode.INVALID_THIRD_PARTY_HEADER,
    RefusalCode.INVALID_ADDRESSEE,
    RefusalCode.INVALID_NAME,
    RefusalCode.INVALID_TIMESTAMP,
    RefusalCode.NOT_A_NUMBER,
    RefusalCode.VALUE_OUT_OF_RANGE,
    RefusalCode.VALUE_HAS_NO_FORM,
    RefusalCode.INVALID_CODE,
    RefusalCode.INVALID_SYMBOL,
    RefusalCode.INVALID_CHARACTER,
    RefusalCode.TOO_LONG,
    RefusalCode.PADDING_SPACE,
    RefusalCode.MALFORMED,
    RefusalCode.INVALID_MESSAGE_ID,
    RefusalCode.INVALID_NMEA,
    RefusalCode.EXTENSION_CONFLICT,
    RefusalCode.FIELD_NOT_ALLOWED,
    RefusalCode.SYMBOL_MISMATCH,
    RefusalCode.MISSING_FIELD,
    RefusalCode.VALUE_GIVEN_TWICE,
    RefusalCode.TEXT_READS_AS_FIELD,
    RefusalCode.DOES_NOT_READ_BACK,
)
_PRIORITY = {code: rank for rank, code in enumerate(_ORDER)}
"""The order in which a refusal names its code when the data breaks several rules (the vectors'
refusal rulings): the first code that applies."""


class _Faults:
    """The faults found so far in one piece of data: the encoder goes on after one so that the
    refusal can name the first code that applies, whatever order it looked in."""

    def __init__(self) -> None:
        self.found: list[EncodeError] = []

    def add(self, code: RefusalCode, why: str) -> None:
        self.found.append(EncodeError(why, code))

    def guard(self, fn: Callable[..., _T], *args: Any, default: _T) -> _T:
        try:
            return fn(*args)
        except EncodeError as e:
            self.found.append(e)
            return default

    def finish(self) -> None:
        if self.found:
            raise min(self.found, key=lambda e: _PRIORITY[e.code])


def _has_nonfinite(value: Any, ignore: frozenset[str] = frozenset()) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, (tuple, list)):
        return any(_has_nonfinite(v) for v in value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return any(_has_nonfinite(getattr(value, f.name)) for f in dataclasses.fields(value) if f.name not in ignore)
    return False


def _no_place(data: Any) -> frozenset[str]:
    """The fields of ``data`` that have no place in it, whose own checks (a NaN among them) do
    not run: a weather report has no comment to carry an altitude, telemetry or a frequency."""
    if isinstance(data, PositionedData) and data.weather is not None:
        gga = data.compressed and data.compression is not None and data.compression.source is CompressionSource.GGA
        names = {"telemetry", "frequency"}
        if not gga:
            names.add("altitude_feet")
        return frozenset(names)
    return frozenset()


def _finite(value: Any) -> Any:
    """``value`` with every NaN or infinity in it replaced by 0.0."""
    if isinstance(value, float):
        return value if math.isfinite(value) else 0.0
    if isinstance(value, tuple):
        return tuple(_finite(v) for v in value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        changes = {}
        for fld in dataclasses.fields(value):
            old = getattr(value, fld.name)
            new = _finite(old)
            if new is not old and new != old:
                changes[fld.name] = new
        return dataclasses.replace(value, **changes) if changes else value
    return value


def _nan_or_earlier(data: Any, encoder: Callable[[Any], bytes], why: str) -> EncodeError:
    """The refusal for data a NaN or infinity made the encoder fail on: ``not-a-number``, unless
    a code that comes before it in the order (a name, a timestamp, an addressee...) applies, which
    is found by encoding the data again with the non-finite values made finite."""
    nan = _refuse(RefusalCode.NOT_A_NUMBER, why)
    try:
        encoder(_finite(data))
    except EncodeError as e:
        if _PRIORITY[e.code] < _PRIORITY[RefusalCode.NOT_A_NUMBER]:
            return e
    except (ValueError, OverflowError):
        pass
    return nan


def _nan_rule(data: Any, e: EncodeError) -> EncodeError:
    """A NaN or an infinity anywhere in the data is ``not-a-number`` wherever the refusal came
    from, unless a code that comes before it applies."""
    if _PRIORITY[e.code] > _PRIORITY[RefusalCode.NOT_A_NUMBER] and _has_nonfinite(data, _no_place(data)):
        return EncodeError(f"{e} (a value is NaN or infinite)", RefusalCode.NOT_A_NUMBER)
    return e


# ---------------------------------------------------------------- checks


def _check_text(text: str, what: str) -> None:
    if "\r" in text or "\n" in text:
        raise _refuse(RefusalCode.INVALID_CHARACTER, f"{what} contains a line break")


def _check_address(call: str, what: str, code: RefusalCode = RefusalCode.INVALID_ADDRESSEE) -> None:
    if not call or len(call) > 9 or not _util.is_printable_ascii(call) or " " in call or ":" in call:
        raise _refuse(code, f"{what} {call!r} is not 1-9 printable characters without spaces or colons")


def _check_header_address(call: str, what: str) -> None:
    """A source, destination or path entry as APRS-IS carries it: 1-9 letters, digits or ``-``."""
    if not re.fullmatch(r"[A-Za-z0-9-]{1,9}", call):
        raise _refuse(RefusalCode.INVALID_ADDRESS, f"{what} {call!r} is not 1-9 letters, digits or -")


def _check_symbol(data: PositionedData) -> None:
    if not data.symbol.is_valid:
        raise _refuse(RefusalCode.INVALID_SYMBOL, f"symbol {str(data.symbol)!r} is not a valid table and code")


def _check_timestamp(ts: Timestamp, kinds: tuple[TimestampKind, ...], what: str) -> None:
    kind = ts.kind
    if kind is None or kind not in kinds:
        raise _refuse(RefusalCode.INVALID_TIMESTAMP, f"{what} timestamp {ts.text!r} is not of an allowed format")
    if not ts.is_valid:
        raise _refuse(RefusalCode.INVALID_TIMESTAMP, f"{what} timestamp {ts.text!r} is out of range")


def _shape_differences(a: Any, b: Any, *, numbers: bool = False) -> bool:
    """True when two neutral values differ other than in numbers (with ``numbers``, in numbers
    too, beyond the vectors' tolerance)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() != b.keys() or any(_shape_differences(a[k], b[k], numbers=numbers) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) != len(b) or any(_shape_differences(x, y, numbers=numbers) for x, y in zip(a, b, strict=False))
    if isinstance(a, bool) or isinstance(b, bool):
        return a is not b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return numbers and not _util.number_equal(a, b)
    return bool(a != b)


def _reads_back(data: AprsData, info: bytes, destination: str, *, numbers: bool = False) -> bool:
    """Whether ``info`` decodes, leniently and without defects, to data of ``data``'s shape (and,
    with ``numbers``, the same numbers too)."""
    from ._decode import Ctx, decode_info
    from ._neutral import to_neutral

    ctx = Ctx(_LENIENT)
    decoded = decode_info(info, destination, ctx)
    if any(d.severity is not Severity.INFO for d in ctx.diags):
        return False
    given = to_neutral(data)
    if isinstance(data, MicEReport):
        # a Mic-E report always has a speed: one not given is 0
        given.setdefault("speed_knots", 0)
    return not _shape_differences(given, to_neutral(decoded), numbers=numbers)


def _with_comment(
    data: AprsData,
    comment: str,
    build: Callable[[str], bytes],
    destination: str = DEFAULT_DESTINATION,
    *,
    after_frequency: bool = False,
    separating_space: bool = False,
) -> bytes:
    """The first way of writing the comment that reads back as the data: as it is, then after
    a ``/`` delimiter. After a voice frequency it is written after a space, then straight
    after the frequency, then after a space and a ``/``."""
    if not comment:
        candidates = [""]
    elif after_frequency:
        candidates = [" " + comment, comment, " /" + comment]
    else:
        candidates = [comment, "/" + comment]
    if comment and separating_space:
        # a Mic-E comment that would join what comes before it into an altitude run (1{5}) is
        # held apart by a space, the only clean form (vectors README, Encoding, E12)
        candidates.append(" " + comment)
    for candidate in candidates:
        info = build(candidate)
        if _reads_back(data, info, destination):
            return info
    # free text that reads back changed is text-reads-as-field; with no text, the safety net
    # cannot say why
    weather = getattr(data, "weather", None)
    symbol = getattr(data, "symbol", None)
    if weather is None and symbol is not None and symbol.code == "_" and not isinstance(data, MicEReport):
        # a weather symbol with no weather data reads back as a weather report
        raise _refuse(RefusalCode.SYMBOL_MISMATCH, "the weather symbol _ goes with weather data")
    free_text = bool(comment) or (weather is not None and bool(weather.software or weather.unit))
    if isinstance(data, MicEReport):
        # a Mic-E report's status text is whatever follows its position bytes: the altitude
        # bytes, a locator and the rest all read back as text
        free_text = free_text or any(
            x is not None
            for x in (
                data.altitude_feet,
                data.locator,
                data.telemetry,
                data.frequency,
                data.phg,
                data.range_miles,
                data.dfs,
                data.dao,
                data.device_suffix,
            )
        )
    code = RefusalCode.TEXT_READS_AS_FIELD if free_text else RefusalCode.DOES_NOT_READ_BACK
    raise _refuse(code, f"the text {comment!r} would not read back as written")


def _checked(data: AprsData, info: str) -> bytes:
    raw = info.encode("utf-8")
    if not _reads_back(data, raw, DEFAULT_DESTINATION):
        raise _refuse(RefusalCode.TEXT_READS_AS_FIELD, "the text would not read back as written")
    return raw


# ---------------------------------------------------------------- positions


def _minutes_units(value: float | Fraction, per_minute: int) -> int:
    """|value| in units of 1/``per_minute`` of a minute of arc, rounded to the nearest.

    The product is taken in binary floating point (exactly for a Fraction) and rounded once, a
    value within the tolerance of a half going away from zero (vectors ruling F2: 0.9764166666666666
    degrees is 58.584999999999996 minutes, the half 58.585, written 58.59)."""
    if isinstance(value, Fraction):
        return _nearest(abs(value) * 60 * per_minute)
    return _nearest(abs(float(value)) * 60 * per_minute)


_AMBIGUITY_BOX = (1, 10, 100, 1000, 6000)
"""The box each ambiguity level leaves, in hundredths of a minute: 0.1', 1', 10', 1 degree."""


def _ambiguous_units(value: float, ambiguity: int) -> int:
    """|value| in hundredths of a minute, down to the start of the box that holds it, so that the
    centre a decoder reports is the one nearest the value (rounding first could move it into the
    next box)."""
    box = _AMBIGUITY_BOX[ambiguity]
    # a value within F2's tolerance of the box edge above it is on that edge (vectors ruling G2)
    boxes = abs(float(value)) * 6000 / box
    return math.floor(boxes + _util.HALF_TOLERANCE) * box


def _is_negative(value: float) -> bool:
    return value < 0 or (value == 0 and math.copysign(1.0, value) < 0)


def _compressed_y(lat: float) -> int:
    return _nearest(380926 * (90 - float(lat)))


def _compressed_x(lon: float) -> int:
    return _nearest(190463 * (180 + float(lon)))


def _dao_digits(data: PositionedData) -> tuple[str, str, int, int]:
    """For a ``!DAO!``: its two characters, and the latitude and longitude in hundredths of a
    minute to write in the position itself.

    A compressed position's DAO adds no precision, so a decoder ignores its digits; they are
    written as the same DAO would give the position the compressed bytes report, written
    uncompressed, so that a reader that did apply them would land on it (vectors ruling E2)."""
    dao = data.dao
    lat: float | Fraction = data.latitude
    lon: float | Fraction = data.longitude
    if dao is None or dao.precision is DaoPrecision.NONE:
        amb = data.ambiguity
        if amb and 0 < amb < len(_AMBIGUITY_BOX):
            return " ", " ", _ambiguous_units(data.latitude, amb), _ambiguous_units(data.longitude, amb)
        return " ", " ", _minutes_units(lat, 100), _minutes_units(lon, 100)
    if data.compressed and -90 <= lat <= 90 and -180 <= lon <= 180:
        lat = 90 - Fraction(min(max(_compressed_y(data.latitude), 0), 91**4 - 1), 380926)
        lon = Fraction(min(max(_compressed_x(data.longitude), 0), 91**4 - 1), 190463) - 180
    if dao.precision is DaoPrecision.THOUSANDTHS:
        la, lo = _minutes_units(lat, 1000), _minutes_units(lon, 1000)
        return str(la % 10), str(lo % 10), la // 10, lo // 10
    la, lo = _minutes_units(lat, 9100), _minutes_units(lon, 9100)
    return chr(la % 91 + 33), chr(lo % 91 + 33), la // 91, lo // 91


def _dao_digits_in_range(data: PositionedData) -> tuple[str, str, int, int]:
    """:func:`_dao_digits`, or placeholders when the position is out of range (it is refused for
    that anyway, and a huge value would overflow the rounding)."""
    if not (-90 <= data.latitude <= 90 and -180 <= data.longitude <= 180):
        return " ", " ", 0, 0
    return _dao_digits(data)


def _dao_text(data: PositionedData, a: str, o: str) -> str:
    dao = data.dao
    if dao is None:
        return ""
    datum = dao.datum
    if len(datum) != 1 or not (datum.isascii() and datum.isalnum()):
        raise _refuse(RefusalCode.INVALID_CODE, f"DAO datum {datum!r} is not one letter or digit")
    if dao.precision is DaoPrecision.BASE91 and not datum.isalpha():
        raise _refuse(RefusalCode.INVALID_CODE, "a base-91 DAO needs a letter datum")
    if datum.isdigit() and dao.precision is not DaoPrecision.NONE:
        # a digit has no case to say how A and O are written
        raise _refuse(RefusalCode.FIELD_NOT_ALLOWED, "a DAO with a digit datum carries no added precision")
    if dao.precision is DaoPrecision.BASE91:
        datum = datum.lower()
    elif dao.precision is DaoPrecision.THOUSANDTHS:
        datum = datum.upper()
    else:
        datum = datum.upper()
        a = o = " "
    return f"!{datum}{a}{o}!"


def _uncompressed(data: PositionedData, lat_units: int, lon_units: int) -> str:
    lat, lon = data.latitude, data.longitude
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, "latitude or longitude out of range")
    if lat_units > 90 * 6000 or lon_units > 180 * 6000:
        raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, "latitude or longitude out of range")
    amb = data.ambiguity
    if not 0 <= amb <= 4:
        raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, f"ambiguity {amb} is not 0-4")
    ld, lr = divmod(lat_units, 6000)
    od, orr = divmod(lon_units, 6000)
    lat_digits = f"{ld:02d}{lr // 100:02d}{lr % 100:02d}"
    lon_digits = f"{od:03d}{orr // 100:02d}{orr % 100:02d}"
    if amb and (ld == 90 or od == 180):
        raise _refuse(
            RefusalCode.VALUE_HAS_NO_FORM, "an ambiguous position at 90 or 180 degrees would be centred past it"
        )
    if amb:
        lat_digits = lat_digits[: 6 - amb] + " " * amb
        lon_digits = lon_digits[: 7 - amb] + " " * amb
    ns = "S" if _is_negative(lat) else "N"
    ew = "W" if _is_negative(lon) else "E"
    return (
        f"{lat_digits[:4]}.{lat_digits[4:]}{ns}{data.symbol.table}"
        f"{lon_digits[:5]}.{lon_digits[5:]}{ew}{data.symbol.code}"
    )


def _base91(value: int, width: int) -> str:
    top = 91**width - 1
    return _util.base91_text(min(max(value, 0), top), width)


def _course_speed(course: float, knots: float, *, is_course: bool = True) -> str:
    # rounded first, then checked (vectors ruling F2)
    whole = _nearest(course)
    if not 0 <= whole <= 360:
        raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, f"course {course} is not 0-360")
    # the steps 1.08^s - 1 for every whole s; the nearest s outside the byte is refused (G3)
    if knots <= -1:
        raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, f"speed {knots} knots has no compressed step")
    s = _nearest(math.log(knots + 1) / math.log(1.08))
    if not 0 <= s <= 90:
        raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, f"speed {knots} knots is too high for the compressed format")
    if is_course and whole == 0:
        # a c of 0 reads back as 360, and the cs bytes have no unknown course (vectors ruling F1)
        raise _refuse(RefusalCode.VALUE_HAS_NO_FORM, "a compressed course of 0 has no form; north is 360")
    # a course that rounds to 360 is north, c = 0 (vectors interpretations.md, "Re-encoding into
    # compressed bytes rounds")
    c = _nearest(_util.decimal(course) / 4) % 90
    return chr(c + 33) + chr(s + 33)


def _check_compressed_course_speed(course: float | None, knots: float | None, f: _Faults) -> None:
    """A compressed course and speed's own checks, which hold whatever else wants the cs bytes."""
    if course is not None:
        if not 0 <= _nearest(course) <= 360:
            f.add(RefusalCode.VALUE_OUT_OF_RANGE, f"course {course} is not 0-360")
        elif _nearest(course) == 0:
            f.add(RefusalCode.VALUE_HAS_NO_FORM, "a compressed course of 0 has no form; north is 360")
    if knots is not None and (knots <= -1 or not 0 <= _nearest(math.log(knots + 1) / math.log(1.08)) <= 90):
        f.add(RefusalCode.VALUE_OUT_OF_RANGE, f"speed {knots} knots has no compressed step")


def _altitude(feet: float) -> str:
    value = _nearest(feet)
    if value < 0:
        if value < -99999:
            raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, "altitude too low")
        return f"/A=-{-value:05d}"
    if value > 999999:
        raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, "altitude too high")
    return f"/A={value:06d}"


def _compressed(data: PositionedData, weather: bool, f: _Faults) -> tuple[str, str]:
    """The 13-byte compressed position, and any ``/A=`` altitude it needs besides."""
    if data.ambiguity:
        f.add(RefusalCode.FIELD_NOT_ALLOWED, "a compressed position cannot be ambiguous")
    if data.phg is not None or data.dfs is not None or data.area is not None:
        f.add(RefusalCode.FIELD_NOT_ALLOWED, "a compressed position cannot carry PHG, DFS or an area object")
    if data.df_bearing is not None or data.storm is not None:
        f.add(RefusalCode.FIELD_NOT_ALLOWED, "a compressed position cannot carry DF or storm data")
    lat, lon = data.latitude, data.longitude
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        f.add(RefusalCode.VALUE_OUT_OF_RANGE, "latitude or longitude out of range")
    table = data.symbol.table
    if "0" <= table <= "9":
        table = chr(ord(table) - ord("0") + ord("a"))
    in_range = -90 <= lat <= 90 and -180 <= lon <= 180
    y = _base91(_compressed_y(lat), 4) if in_range else ""
    x = _base91(_compressed_x(lon), 4) if in_range else ""
    ctype = data.compression
    altitude_text = ""
    cs: str | None = None
    w = data.weather
    gga = ctype is not None and ctype.source is CompressionSource.GGA
    # a range is range-checked first wherever it goes, even where the cs bytes are wanted twice
    range_cs: str | None = None
    if data.range_miles is not None:
        if data.range_miles <= 0:
            f.add(RefusalCode.VALUE_OUT_OF_RANGE, "a compressed range is positive")
        else:
            # 2 x 1.08^s miles: a range between the steps is rounded to the nearest one, as a
            # course or speed is (vectors interpretations.md, "Re-encoding into compressed bytes
            # rounds")
            step = _nearest(math.log(data.range_miles / 2) / math.log(1.08))
            if not 0 <= step <= 90:
                f.add(RefusalCode.VALUE_OUT_OF_RANGE, "range too large for the compressed format")
            else:
                range_cs = "{" + chr(step + 33)
    if weather and w is not None and (w.wind_direction_degrees is not None or w.wind_speed_mph is not None):
        if w.wind_direction_degrees is None or w.wind_speed_mph is None:
            f.add(RefusalCode.MISSING_FIELD, "compressed wind needs both a direction and a speed")
        if data.course_degrees is not None or data.speed_knots is not None or data.range_miles is not None:
            _check_compressed_course_speed(data.course_degrees, data.speed_knots, f)
            f.add(RefusalCode.EXTENSION_CONFLICT, "a weather report's cs bytes carry the wind")
        if data.altitude_feet is not None:
            f.add(
                RefusalCode.EXTENSION_CONFLICT if gga else RefusalCode.FIELD_NOT_ALLOWED,
                "a weather report's cs bytes carry the wind, not an altitude",
            )
        # what is given is judged even when the other half is missing
        speed = (w.wind_speed_mph or 0) / _util.KNOTS_TO_MPH
        cs = f.guard(lambda: _course_speed(w.wind_direction_degrees or 0, speed, is_course=False), default="  ")
    elif gga:
        if data.course_degrees is not None or data.speed_knots is not None or data.range_miles is not None:
            _check_compressed_course_speed(data.course_degrees, data.speed_knots, f)
            f.add(
                RefusalCode.EXTENSION_CONFLICT, "a GGA compressed position carries altitude, not course, speed or range"
            )
        if data.altitude_feet is None:
            f.add(RefusalCode.MISSING_FIELD, "a GGA compressed position needs an altitude")
        else:
            alt = data.altitude_feet
            value = _nearest(math.log(alt) / math.log(1.002)) if alt >= 1 else 0
            value = min(max(value, 0), 91 * 91 - 1)
            cs = _base91(value, 2)
            if not _util.number_equal(1.002**value, alt) and not weather:
                # a weather report has no comment for a /A=, so there the altitude is the cs step
                # nearest it (vectors ruling F14)
                altitude_text = f.guard(_altitude, alt, default="")
    else:
        if data.altitude_feet is not None:
            if weather:
                f.add(RefusalCode.FIELD_NOT_ALLOWED, "a weather report carries an altitude only in GGA cs bytes")
            else:
                altitude_text = f.guard(_altitude, data.altitude_feet, default="")
        course, knots = data.course_degrees, data.speed_knots
        if course is not None or knots is not None:
            before = len(f.found)
            _check_compressed_course_speed(course, knots, f)
            if weather:
                f.add(RefusalCode.EXTENSION_CONFLICT, "a weather report carries wind, not course and speed")
            elif data.range_miles is not None:
                f.add(
                    RefusalCode.EXTENSION_CONFLICT,
                    "a compressed position carries course and speed, or range, not both",
                )
            elif course is None or knots is None:
                f.add(RefusalCode.MISSING_FIELD, "a compressed course and speed needs both")
            elif len(f.found) == before:
                cs = _course_speed(course, knots)
        if range_cs is not None and course is None and knots is None:
            cs = range_cs
    if cs is None:
        if ctype is not None:
            f.add(RefusalCode.MISSING_FIELD, "a compression type needs course/speed, range or altitude to go with it")
        return f"{table}{y}{x}{data.symbol.code} sT", altitude_text
    if ctype is None:
        # the cs bytes always come with a compression type byte, which reads back as data
        f.add(
            RefusalCode.MISSING_FIELD, "compressed course and speed, range or wind need a compression type (the T byte)"
        )
        return "", altitude_text
    return f"{table}{y}{x}{data.symbol.code}{cs}{chr(ctype.value + 33)}", altitude_text


def _phg_text(data: PositionedData) -> str:
    phg = data.phg
    if phg is None:
        return ""
    if not (0 <= phg.power <= 9 and 0 <= phg.gain <= 9 and 0 <= phg.directivity <= 9 and 0 <= phg.height <= 78):
        raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, "PHG code out of range")
    text = f"PHG{phg.power}{chr(phg.height + 48)}{phg.gain}{phg.directivity}"
    rate = phg.beacons_per_hour
    if rate is not None:
        if not 1 <= rate <= 35:
            raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, "PHG beacons per hour is not 1-35")
        text += (str(rate) if rate < 10 else chr(rate - 10 + ord("A"))) + "/"
    return text


def _dfs_text(data: PositionedData) -> str:
    d = data.dfs
    if d is None:
        return ""
    if not (0 <= d.strength <= 9 and 0 <= d.gain <= 9 and 0 <= d.directivity <= 9 and 0 <= d.height <= 78):
        raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, "DFS code out of range")
    return f"DFS{d.strength}{chr(d.height + 48)}{d.gain}{d.directivity}"


def _range_text(miles: float) -> str:
    r = _nearest(miles)
    if not 0 <= r <= 9999:
        raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, "range is not 0-9999 miles")
    return f"RNG{r:04d}"


def _storm_text(data: PositionedData, f: _Faults) -> str:
    st = data.storm
    if st is None:
        return ""
    if data.symbol.code != "@":
        f.add(RefusalCode.SYMBOL_MISMATCH, "storm data needs a hurricane symbol")
    code = {StormType.TROPICAL_STORM: "TS", StormType.HURRICANE: "HC"}.get(st.type, "TD")

    def n(v: int | None, width: int) -> str:
        if v is None:
            return "." * width
        if not 0 <= v < 10**width:
            f.add(RefusalCode.VALUE_OUT_OF_RANGE, "storm value does not fit its field")
            return "0" * width
        return f"{v:0{width}d}"

    text = (
        f"/{code}/{n(st.sustained_wind_knots, 3)}^{n(st.gust_knots, 3)}/{n(st.central_pressure_mbar, 4)}"
        f">{n(st.hurricane_radius_nm, 3)}&{n(st.tropical_storm_radius_nm, 3)}"
    )
    if st.whole_gale_radius_nm is not None:
        text += "%" + n(st.whole_gale_radius_nm, 3)
    return text


def _extension(data: PositionedData, f: _Faults) -> str:
    """The data extension straight after the symbol, at most one."""
    parts: list[str] = []
    if data.course_degrees is not None or data.speed_knots is not None or data.df_bearing or data.storm:
        course = data.course_degrees
        speed = data.speed_knots
        # rounded first, then checked (vectors ruling F2); 000 is the spec's unknown and reads
        # back as 0 (F1)
        if course is not None and not 0 <= _nearest(course) <= 360:
            f.add(RefusalCode.VALUE_OUT_OF_RANGE, f"course {course} is not 0-360")
        if speed is not None and not 0 <= _nearest(speed) <= 999:
            f.add(RefusalCode.VALUE_OUT_OF_RANGE, f"speed {speed} is not 0-999 knots")
        text = ("..." if course is None else f"{_nearest(course):03d}") + "/"
        text += "..." if speed is None else f"{_nearest(speed):03d}"
        if data.df_bearing is not None:
            if str(data.symbol) != "/\\":
                f.add(RefusalCode.SYMBOL_MISMATCH, "DF bearing needs the DF symbol /\\")
            b = data.df_bearing
            if not (0 <= b.bearing_degrees <= 360 and all(0 <= v <= 9 for v in (b.number, b.range, b.quality))):
                f.add(RefusalCode.VALUE_OUT_OF_RANGE, "DF bearing or NRQ out of range")
            text += f"/{b.bearing_degrees:03d}/{b.number}{b.range}{b.quality}"
        if data.df_bearing is not None and data.storm is not None:
            f.add(RefusalCode.EXTENSION_CONFLICT, "a DF bearing and storm data both extend the course and speed")
        if str(data.symbol) == "\\l" and data.area is None and course is not None:
            f.add(RefusalCode.SYMBOL_MISMATCH, "course and speed on the area symbol \\l read back as an area")
        text += _storm_text(data, f)
        parts.append(text)
    if data.phg is not None:
        parts.append(f.guard(_phg_text, data, default=""))
    if data.range_miles is not None:
        parts.append(f.guard(_range_text, data.range_miles, default=""))
    if data.dfs is not None:
        parts.append(f.guard(_dfs_text, data, default=""))
    if data.area is not None:
        if str(data.symbol) != "\\l":
            f.add(RefusalCode.SYMBOL_MISMATCH, "an area object needs the area symbol \\l, without an overlay")
        a = data.area
        if not (0 <= a.lat_offset <= 99 and 0 <= a.lon_offset <= 99):
            f.add(RefusalCode.VALUE_OUT_OF_RANGE, "area offsets are 0-99")
        color = a.color.code
        parts.append(
            f"{a.shape.code}{a.lat_offset:02d}{'/' + str(color) if color < 10 else str(color)}{a.lon_offset:02d}"
        )
    if len(parts) > 1:
        f.add(RefusalCode.EXTENSION_CONFLICT, "more than one data extension")
    return parts[0] if parts else ""


def _frequency_text(fq: VoiceFrequency, f: _Faults) -> str:
    mhz = fq.mhz
    places = 2 if fq.ten_khz_resolution else 3

    def digits(value: float, width: int) -> str:
        # to the nearest 10 kHz or 1 kHz, halves away from zero (vectors ruling F2)
        n = _nearest(value * 10**places)
        return f"{n // 10**places}.{n % 10**places:0{places}d}".rjust(width, "0")

    head: str | None = None
    if mhz >= 1000:
        for letter, base in MICROWAVE_BASE.items():
            if base <= mhz < base + 100:
                rest = float(mhz) - base
                head = letter + (digits(rest, 5) if fq.ten_khz_resolution else digits(rest, 6))
                break
        else:
            f.add(RefusalCode.VALUE_HAS_NO_FORM, f"frequency {mhz} MHz has no APRS form")
    elif mhz >= 0:
        head = digits(float(mhz), 6) if fq.ten_khz_resolution else digits(float(mhz), 7)
    else:
        f.add(RefusalCode.VALUE_OUT_OF_RANGE, "a frequency is positive")
    if head is not None and len(head) != (6 if fq.ten_khz_resolution else 7):
        f.add(RefusalCode.VALUE_OUT_OF_RANGE, f"frequency {mhz} MHz rounds past what its digits hold")
    text = (head or "") + (" MHz" if fq.ten_khz_resolution else "MHz")
    if fq.tone is not None:
        if fq.tone is ToneType.OFF:
            text += " toff" if fq.narrow else " Toff"
        elif fq.tone is ToneType.TONE_BURST:
            text += " l750" if fq.narrow else " 1750"
        else:
            if fq.tone_value is None:
                f.add(RefusalCode.MISSING_FIELD, "a tone needs a value of 0-999")
            elif not 0 <= fq.tone_value <= 999:
                f.add(RefusalCode.VALUE_OUT_OF_RANGE, "a tone needs a value of 0-999")
            else:
                letter = {ToneType.TONE: "T", ToneType.CTCSS: "C", ToneType.DCS: "D"}[fq.tone]
                text += f" {letter.lower() if fq.narrow else letter}{fq.tone_value:03d}"
    elif fq.narrow:
        f.add(RefusalCode.FIELD_NOT_ALLOWED, "narrow is set by a tone letter")
    if fq.offset_khz is not None:
        tens = _nearest(float(fq.offset_khz) / 10)
        if abs(tens) > 999:
            f.add(RefusalCode.VALUE_OUT_OF_RANGE, "offset too large")
        else:
            text += f" {'-' if tens < 0 else '+'}{abs(tens):03d}"
    if fq.range is not None:
        if not 0 <= fq.range <= 999:
            f.add(RefusalCode.VALUE_OUT_OF_RANGE, "range out of range")
        else:
            text += f" R{fq.range:02d}{'k' if fq.range_km else 'm'}"
    return text


def _telemetry_text(t: CommentTelemetry | None, f: _Faults) -> str:
    if t is None:
        return ""
    if len(t.analog) > 5:
        f.add(RefusalCode.TOO_LONG, "comment telemetry has 1-5 analog values")
    elif not t.analog:
        f.add(RefusalCode.MALFORMED, "comment telemetry has 1-5 analog values")
    values = [t.sequence, *t.analog]
    if t.digital is not None:
        if len(t.analog) != 5:
            f.add(RefusalCode.MISSING_FIELD, "comment telemetry digital bits need all five analog values")
        if not 0 <= t.digital <= 255:
            f.add(RefusalCode.VALUE_OUT_OF_RANGE, "comment telemetry has eight binary channels, 0-255")
        values.append(t.digital)
    if any(not 0 <= v <= 8280 for v in values):
        f.add(RefusalCode.VALUE_OUT_OF_RANGE, "comment telemetry values are 0-8280")
        return ""
    return "|" + "".join(_util.base91_text(v, 2) for v in values) + "|"


def _braces(data: PositionedData, f: _Faults) -> str:
    text = ""
    if data.signpost is not None:
        if str(data.symbol) != "\\m":
            f.add(RefusalCode.SYMBOL_MISMATCH, "a signpost needs the signpost symbol \\m, without an overlay")
        sign = data.signpost
        if not 1 <= len(sign) <= 3 or not _util.is_printable_ascii(sign) or "{" in sign or "}" in sign:
            f.add(RefusalCode.MALFORMED, "a signpost is 1-3 printable ASCII characters other than braces")
        text += "{" + data.signpost + "}"
    if data.area is not None and data.area.corridor_width_miles is not None:
        if data.area.shape not in (AreaShape.LINE_DOWN_RIGHT, AreaShape.LINE_DOWN_LEFT):
            f.add(RefusalCode.FIELD_NOT_ALLOWED, "only a line has a corridor")
        if not 0 <= data.area.corridor_width_miles <= 999:
            f.add(RefusalCode.VALUE_OUT_OF_RANGE, "corridor width is 0-999 miles")
        text += "{" + str(data.area.corridor_width_miles) + "}"
    return text


def _snowfall_text(snow: float) -> str:
    """Snowfall in its three characters (vectors rulings E8 and F3): rounded to hundredths if that
    leaves it under 1 (0.32 as ``.32``), else to tenths if that leaves it under 10 (1.5 as
    ``1.5``), else to a whole number; a result that is whole is written as three digits (12 as
    ``012``, 0.995 as ``001``, 9.96 as ``010``). Refused when it rounds past 999."""
    hundredths = _nearest(float(snow) * 100)
    if hundredths < 0:
        raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, f"snowfall of {snow} inches is negative")
    if hundredths < 100:
        return "000" if hundredths == 0 else f".{hundredths:02d}"
    tenths = _nearest(float(snow) * 10)
    if tenths < 100:
        return f"{tenths // 10:03d}" if tenths % 10 == 0 else f"{tenths // 10}.{tenths % 10}"
    whole = _nearest(snow)
    if whole > 999:
        raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, f"snowfall of {snow} inches does not fit three digits")
    return f"{whole:03d}"


def _weather_text(w: Weather, *, positionless: bool, compressed: bool, f: _Faults) -> str:
    """The weather fields: the wind first (unless compressed), the mandatory gust and
    temperature (dots when unknown), the rest when known, then software and unit."""
    out: list[str] = []

    def num(v: float | None, width: int, scale: float = 1) -> str:
        if v is None:
            return "." * width
        value = _nearest(float(v) * scale)
        if value < 0 or value >= 10**width:
            f.add(RefusalCode.VALUE_OUT_OF_RANGE, f"weather value {v} does not fit {width} digits")
            return "0" * width
        return f"{value:0{width}d}"

    direction = w.wind_direction_degrees
    if direction is not None and not 0 <= _nearest(direction) <= 360:
        f.add(RefusalCode.VALUE_OUT_OF_RANGE, "wind direction is not 0-360")
    if positionless:
        out.append("c" + num(direction, 3) + "s" + num(w.wind_speed_mph, 3))
    elif not compressed:
        out.append(num(direction, 3) + "/" + num(w.wind_speed_mph, 3))
    out.append("g" + num(w.wind_gust_mph, 3))
    t = w.temperature_f
    if t is None:
        out.append("t...")
    else:
        ti = _nearest(t)
        if not -99 <= ti <= 999:
            f.add(RefusalCode.VALUE_OUT_OF_RANGE, "temperature does not fit the weather format")
        out.append(f"t{ti:03d}" if ti >= 0 else f"t-{-ti:02d}")
    if w.rain_1h_in is not None:
        out.append("r" + num(w.rain_1h_in, 3, 100))
    if w.rain_24h_in is not None:
        out.append("p" + num(w.rain_24h_in, 3, 100))
    if w.rain_midnight_in is not None:
        out.append("P" + num(w.rain_midnight_in, 3, 100))
    if w.humidity_percent is not None:
        h = _nearest(w.humidity_percent)
        if not 1 <= h <= 100:
            f.add(RefusalCode.VALUE_HAS_NO_FORM if h == 0 else RefusalCode.VALUE_OUT_OF_RANGE, "humidity is not 1-100%")
        out.append("h" + ("00" if h == 100 else f"{h:02d}"))
    if w.pressure_mbar is not None:
        out.append("b" + num(w.pressure_mbar, 5, 10))
    if w.luminosity_w_m2 is not None:
        lum = _nearest(w.luminosity_w_m2)
        if 0 <= lum <= 999:
            out.append(f"L{lum:03d}")
        elif 1000 <= lum <= 1999:
            out.append(f"l{lum - 1000:03d}")
        else:
            f.add(RefusalCode.VALUE_OUT_OF_RANGE, "luminosity is not 0-1999")
    if w.snow_24h_in is not None:
        out.append("s" + f.guard(_snowfall_text, w.snow_24h_in, default="000"))
    if w.rain_raw is not None:
        out.append("#" + num(w.rain_raw, 3))
    for extra in w.extra:
        if (
            len(extra.letter) != 1
            or not (extra.letter.isascii() and extra.letter.isalpha())
            or extra.letter in "cgtrpPhbLls"
        ):
            f.add(RefusalCode.TEXT_READS_AS_FIELD, f"weather extra field letter {extra.letter!r}")
        out.append(extra.letter + extra.value)
    if w.software is not None or w.unit is not None:
        if not w.software or not w.unit:
            f.add(RefusalCode.MISSING_FIELD, "software type and unit go together")
        else:
            out.append(w.software + w.unit)
    return "".join(out)


def _typed(data: _P) -> _P:
    """cs bytes that carry a value (a range, a course and speed, wind) need a type byte; data
    with none gets the default, C (vectors README, Encoding)."""
    if not data.compressed or data.compression is not None:
        return data
    w = getattr(data, "weather", None)
    wind = w is not None and (w.wind_direction_degrees is not None or w.wind_speed_mph is not None)
    if data.range_miles is not None or data.course_degrees is not None or data.speed_knots is not None or wind:
        return dataclasses.replace(data, compression=CompressionType())
    return data


def _position_body(data: PositionedData, f: _Faults) -> Callable[[str], str]:
    """A function that writes the position and everything after it, given the comment."""
    f.guard(_check_symbol, data, default=None)
    if data.weather is None:
        # a weather report has no place for a comment, so its line breaks are not checked
        f.guard(_check_text, data.comment, "comment", default=None)
    # a report is a weather report when it carries weather; the symbol disagreeing is a fault of
    # its own
    weather = data.weather is not None
    if weather and data.symbol.code != "_":
        f.add(RefusalCode.SYMBOL_MISMATCH, "weather data needs the weather symbol _")
    elif data.weather is None and data.symbol.code == "_":
        f.add(RefusalCode.SYMBOL_MISMATCH, "the weather symbol _ goes with weather data")
    if data.dao is not None and data.ambiguity:
        f.add(RefusalCode.FIELD_NOT_ALLOWED, "a DAO cannot add precision to an ambiguous position")
    a, o, lat_units, lon_units = _dao_digits_in_range(data)
    if data.compressed:
        position, altitude = _compressed(data, weather, f)
    else:
        if data.compression is not None:
            f.add(RefusalCode.FIELD_NOT_ALLOWED, "a compression type needs a compressed position")
        position = f.guard(_uncompressed, data, lat_units, lon_units, default="")
        altitude = ""
        if data.altitude_feet is not None:
            if weather:
                # no comment to hold an /A=, so no place for it: its range is not judged
                f.add(RefusalCode.FIELD_NOT_ALLOWED, "a weather report has no comment for an /A= altitude")
            else:
                altitude = f.guard(_altitude, data.altitude_feet, default="")
    dao = f.guard(_dao_text, data, a, o, default="")
    if weather and data.telemetry is not None:
        # no comment to carry it: no place, so its own checks do not run
        f.add(RefusalCode.FIELD_NOT_ALLOWED, "a weather report has no comment to carry telemetry")
        telemetry = ""
    else:
        telemetry = _telemetry_text(data.telemetry, f)
    if weather:
        if data.comment:
            f.add(RefusalCode.FIELD_NOT_ALLOWED, "a weather report has no comment")
        if altitude:
            # the GGA cs bytes hold the altitude only in steps, and the /A= that would carry it
            # exactly has no comment to go in
            f.add(
                RefusalCode.FIELD_NOT_ALLOWED,
                "a weather report has no comment for an /A= altitude the cs bytes cannot hold",
            )
        if data.frequency is not None or data.signpost is not None:
            f.add(RefusalCode.FIELD_NOT_ALLOWED, "a weather report carries weather, not other data")
        if not data.compressed and any(
            x is not None
            for x in (
                data.course_degrees,
                data.speed_knots,
                data.range_miles,
                data.phg,
                data.dfs,
                data.area,
                data.df_bearing,
                data.storm,
            )
        ):
            # the wind holds the data extension; what was given there still gets its own checks
            _extension(data, f)
            f.add(RefusalCode.EXTENSION_CONFLICT, "a weather report carries wind, not another data extension")
        body = position + _weather_text(data.weather or Weather(), positionless=False, compressed=data.compressed, f=f)
        return lambda comment: body + dao

    ext = "" if data.compressed else _extension(data, f)
    braces = _braces(data, f)
    freq = "" if data.frequency is None else _frequency_text(data.frequency, f)
    if freq and ext and not ext.endswith("/"):
        # $CSE/SPD/FFF.FFFMHz, $PHGphgd/FFF.FFFMHz (APRS12c ch. 18); a PHGR already ends in its /
        freq = "/" + freq

    def rest(comment: str) -> str:
        # the frequency first, where radios read it (APRS12c ch. 18: the first 10 bytes of the
        # comment), then the braces, the altitude, the free text, telemetry and the DAO
        # (vectors ruling E3)
        return position + ext + freq + braces + altitude + comment + telemetry + dao

    return rest


def _position(data: PositionReport) -> bytes:
    data = _typed(data)
    f = _Faults()
    if data.timestamp is not None:
        f.guard(_check_timestamp, data.timestamp, _TIMESTAMPED, "position", default=None)
        head = ("@" if data.messaging else "/") + data.timestamp.text
    else:
        head = "=" if data.messaging else "!"
    rest = _position_body(data, f)
    f.finish()
    return _with_comment(
        data, data.comment, lambda c: (head + rest(c)).encode("utf-8"), after_frequency=data.frequency is not None
    )


def _object(data: ObjectReport) -> bytes:
    data = _typed(data)
    f = _Faults()
    name = data.name
    if not 1 <= len(name) <= 9 or not _util.is_printable_ascii(name):
        f.add(RefusalCode.INVALID_NAME, f"object name {name!r} is not 1-9 printable characters")
    if name.endswith(" "):
        f.add(RefusalCode.PADDING_SPACE, "an object name cannot end in a space: it would read back as padding")
    stamp = ""
    if data.timestamp is None:
        f.add(RefusalCode.MISSING_FIELD, "an object always has a timestamp")
    else:
        f.guard(_check_timestamp, data.timestamp, _TIMESTAMPED, "object", default=None)
        stamp = data.timestamp.text
    head = ";" + name.ljust(9) + ("_" if data.killed else "*") + stamp
    rest = _position_body(data, f)
    f.finish()
    return _with_comment(
        data, data.comment, lambda c: (head + rest(c)).encode("utf-8"), after_frequency=data.frequency is not None
    )


def _item(data: ItemReport) -> bytes:
    data = _typed(data)
    f = _Faults()
    name = data.name
    if not 3 <= len(name) <= 9 or not _util.is_printable_ascii(name) or "!" in name or "_" in name:
        f.add(RefusalCode.INVALID_NAME, f"item name {name!r} is not 3-9 printable characters without ! or _")
    head = ")" + name + ("_" if data.killed else "!")
    rest = _position_body(data, f)
    f.finish()
    return _with_comment(
        data, data.comment, lambda c: (head + rest(c)).encode("utf-8"), after_frequency=data.frequency is not None
    )


# ---------------------------------------------------------------- Mic-E

_MESSAGE_BITS: dict[MicEMessage, tuple[str, int]] = {
    MicEMessage.OFF_DUTY: ("std", 7),
    MicEMessage.EN_ROUTE: ("std", 6),
    MicEMessage.IN_SERVICE: ("std", 5),
    MicEMessage.RETURNING: ("std", 4),
    MicEMessage.COMMITTED: ("std", 3),
    MicEMessage.SPECIAL: ("std", 2),
    MicEMessage.PRIORITY: ("std", 1),
    MicEMessage.CUSTOM0: ("custom", 7),
    MicEMessage.CUSTOM1: ("custom", 6),
    MicEMessage.CUSTOM2: ("custom", 5),
    MicEMessage.CUSTOM3: ("custom", 4),
    MicEMessage.CUSTOM4: ("custom", 3),
    MicEMessage.CUSTOM5: ("custom", 2),
    MicEMessage.CUSTOM6: ("custom", 1),
    MicEMessage.EMERGENCY: ("std", 0),
}


def mic_e_destination(data: MicEReport) -> str:
    """The destination address a Mic-E report's latitude, message and flags go into."""
    f = _Faults()
    try:
        call = _mic_e_destination(data, f)
        f.finish()
        return call
    except EncodeError as e:
        raise _nan_rule(data, e) from None
    except (ValueError, OverflowError) as e:
        raise _refuse(RefusalCode.NOT_A_NUMBER, f"cannot encode the Mic-E destination: {e}") from e


def _mic_e_destination(data: MicEReport, f: _Faults) -> str:
    if not -90 <= data.latitude <= 90 or not -180 <= data.longitude <= 180:
        f.add(RefusalCode.VALUE_OUT_OF_RANGE, "latitude or longitude out of range")
    if not 0 <= data.ambiguity <= 4:
        f.add(RefusalCode.VALUE_OUT_OF_RANGE, f"ambiguity {data.ambiguity} is not 0-4")
    _, _, lat_units, lon_units = _dao_digits_in_range(data)
    if lat_units > 90 * 6000:
        f.add(RefusalCode.VALUE_OUT_OF_RANGE, "latitude out of range")
    deg, rem = divmod(lat_units, 6000)
    digits = f"{deg:02d}{rem // 100:02d}{rem % 100:02d}"
    if data.ambiguity and deg == 90:
        f.add(RefusalCode.VALUE_HAS_NO_FORM, "an ambiguous latitude of 90 degrees would be centred past the pole")
    if data.ambiguity:
        digits = digits[: 6 - data.ambiguity] + " " * data.ambiguity
    if data.mic_e_message not in _MESSAGE_BITS:
        f.add(RefusalCode.INVALID_CODE, "a Mic-E message that mixes standard and custom bits has no defined meaning")
    kind, bits = _MESSAGE_BITS.get(data.mic_e_message, ("std", 0))
    lon_deg = lon_units // 6000
    offset = lon_deg < 10 or lon_deg >= 100
    flags = (not _is_negative(data.latitude), offset, _is_negative(data.longitude))
    chars = []
    for i, d in enumerate(digits):
        if i < 3:
            bit = (bits >> (2 - i)) & 1
            if bit and kind == "std":
                chars.append("Z" if d == " " else chr(ord("P") + int(d)))
            elif bit:
                chars.append("K" if d == " " else chr(ord("A") + int(d)))
            else:
                chars.append("L" if d == " " else d)
        elif flags[i - 3]:
            chars.append("Z" if d == " " else chr(ord("P") + int(d)))
        else:
            chars.append("L" if d == " " else d)
    call = "".join(chars)
    ssid = data.destination_ssid
    if not 0 <= ssid <= 15:
        f.add(RefusalCode.VALUE_OUT_OF_RANGE, "destination SSID is not 0-15")
    return f"{call}-{ssid}" if ssid else call


def _mic_e_altitude(feet: float) -> str | None:
    """The Mic-E ``xxx}`` altitude, or None when it would not read back exactly."""
    metres = _nearest(feet / _util.FEET_PER_METRE)
    value = metres + 10000
    if not 0 <= value < 91**3:
        return None
    if not _util.number_equal(metres * _util.FEET_PER_METRE, feet):
        return None
    return _util.base91_text(value, 3) + "}"


_MIC_E_STATUS_START = "`'>] \x1d"
"""What Mic-E status text cannot start with: a device type code, or 0x1D (obsolete telemetry)."""


def _mic_e(data: MicEReport) -> bytes:
    f = _Faults()
    f.guard(_check_symbol, data, default=None)
    f.guard(_check_text, data.comment, "comment", default=None)
    destination = _mic_e_destination(data, f)
    if data.compressed or data.compression is not None:
        f.add(RefusalCode.FIELD_NOT_ALLOWED, "a Mic-E report is not compressed")
    if data.dao is not None and data.ambiguity:
        f.add(RefusalCode.FIELD_NOT_ALLOWED, "a DAO cannot add precision to an ambiguous position")
    legacy = b""
    if data.legacy_telemetry:
        # A 255 would be taken for Kenwood 0xFF padding and removed on the way back in.
        if len(data.legacy_telemetry) != 5 or any(not 0 <= v <= 255 for v in data.legacy_telemetry):
            f.add(RefusalCode.MALFORMED, "obsolete Mic-E binary telemetry is 5 values, each 0-254")
        elif any(v == 255 for v in data.legacy_telemetry):
            f.add(RefusalCode.VALUE_HAS_NO_FORM, "obsolete Mic-E binary telemetry is 5 values, each 0-254")
        else:
            legacy = bytes([0x1D, *data.legacy_telemetry])
    if data.weather is not None or data.area is not None or data.df_bearing or data.storm or data.signpost:
        f.add(RefusalCode.FIELD_NOT_ALLOWED, "a Mic-E report cannot carry weather, area, DF, storm or signpost data")
    a, o, _, lon_units = _dao_digits_in_range(data)
    no_dao = data.dao is None or data.dao.precision is DaoPrecision.NONE
    if data.ambiguity and no_dao and 0 < data.ambiguity < len(_AMBIGUITY_BOX):
        # the longitude digits the latitude's ambiguity covers are ignored by a decoder, which
        # reports the centre of the box; they are written as that centre
        lon_units += _AMBIGUITY_BOX[data.ambiguity] // 2
    deg, rem = divmod(lon_units, 6000)
    minutes, hundredths = divmod(rem, 100)
    if deg > 179:
        f.add(RefusalCode.VALUE_HAS_NO_FORM, "longitude 180 has no Mic-E form")
    if deg < 10:
        d = deg + 90
    elif deg < 100:
        d = deg
    elif deg < 110:
        d = deg - 20
    else:
        d = deg - 100
    m = minutes + 60 if minutes < 10 else minutes
    speed = 0 if data.speed_knots is None else _nearest(data.speed_knots)
    course = 0 if data.course_degrees is None else _nearest(data.course_degrees)
    if not 0 <= speed <= 799:
        f.add(RefusalCode.VALUE_OUT_OF_RANGE, "Mic-E speed is 0-799 knots")
    if not 0 <= course <= 360:
        f.add(RefusalCode.VALUE_OUT_OF_RANGE, "Mic-E course is 0-360")
    elif data.course_degrees is not None and course == 0:
        # Mic-E course 0 reads back as no course (vectors ruling F1); north is 360
        f.add(RefusalCode.VALUE_HAS_NO_FORM, "a Mic-E course of 0 has no form; north is 360")
    head = ""
    if not f.found:
        sp = speed // 10
        sp_char = sp + 80 + 28 if sp <= 18 else sp + 28
        dc = (speed % 10) * 10 + course // 100 + 4
        se = course % 100
        head = (
            ("'" if data.old_data else "`")
            + chr(d + 28)
            + chr(m + 28)
            + chr(hundredths + 28)
            + chr(sp_char)
            + chr(dc + 28)
            + chr(se + 28)
            + data.symbol.code
            + data.symbol.table
        )
    type_code = data.type_code or ""
    if type_code not in ("", "`", "'", ">", "]", " "):
        f.add(RefusalCode.INVALID_CODE, f"Mic-E type code {type_code!r} is not ` ' > ] or a space")
    suffix = data.device_suffix or ""
    if suffix:
        from .devices import _mic_e_suffixes

        if suffix not in _mic_e_suffixes(type_code):
            if type_code:
                f.add(
                    RefusalCode.INVALID_CODE,
                    f"device suffix {suffix!r} is not one the database knows after {type_code!r}",
                )
            else:
                f.add(RefusalCode.MISSING_FIELD, f"device suffix {suffix!r} needs a type code before it")
    altitude_first = ""
    altitude_later = ""
    if data.altitude_feet is not None:
        mic = None if data.altitude_in_comment else _mic_e_altitude(data.altitude_feet)
        if mic is not None:
            altitude_first = mic
            if not type_code and mic[0] in "`'>] " and abs(_nearest(data.altitude_feet)) > 999999:
                # no /A= can hold it, and its first byte would read back as a type code
                f.add(RefusalCode.VALUE_HAS_NO_FORM, "this Mic-E altitude would read back with a type code")
        else:
            altitude_later = f.guard(_altitude, data.altitude_feet, default="")
    locator = ""
    if data.locator is not None:
        if not _util.is_locator(data.locator) or data.locator != data.locator.upper():
            f.add(RefusalCode.MALFORMED, f"{data.locator!r} is not a Maidenhead locator")
        else:
            locator = data.locator.upper() + "/G"
    if sum(x is not None for x in (data.phg, data.range_miles, data.dfs)) > 1:
        f.add(RefusalCode.EXTENSION_CONFLICT, "more than one data extension")
    ext = f.guard(_phg_text, data, default="") + f.guard(_dfs_text, data, default="")
    if data.range_miles is not None:
        ext = f.guard(_range_text, data.range_miles, default="")
    freq = "" if data.frequency is None else _frequency_text(data.frequency, f)
    if freq and ext and not altitude_later and not ext.endswith("/"):
        freq = "/" + freq
    telemetry = _telemetry_text(data.telemetry, f)
    dao = f.guard(_dao_text, data, a, o, default="")
    f.finish()

    def build(comment: str) -> bytes:
        text = type_code + altitude_first + locator
        after = ext + altitude_later + freq
        if locator and (after or comment):
            text += " "
        text += after + comment
        if not legacy and not type_code and text and text[0] in _MIC_E_STATUS_START:
            # status text must not start with a type code character or 0x1D (APRS12c ch. 10),
            # so it goes after a / delimiter
            text = "/" + text
        return head.encode("utf-8") + legacy + (text + telemetry + dao + suffix).encode("utf-8")

    if build(data.comment).endswith((b"\r", b"\n")):
        # a field that ends in a line break would lose it on the way back in
        raise _refuse(RefusalCode.INVALID_CHARACTER, "the information field would end in a line break")
    return _with_comment(data, data.comment, build, destination, after_frequency=bool(freq), separating_space=True)


# ---------------------------------------------------------------- messages


def _addressee(addressee: str) -> str:
    _check_address(addressee, "addressee")
    return ":" + addressee.ljust(9) + ":"


def _check_message_addressee(addressee: str, what: str) -> None:
    """Only a message can be telemetry metadata or a directed query: text to a bulletin or NWS
    bulletin addressee reads back as bulletin text."""
    if re.match(r"BLN[0-9A-Z]", addressee) or addressee.startswith(("NWS-", "NWS_")):
        raise _refuse(
            RefusalCode.INVALID_ADDRESSEE, f"{what} goes to a station, not the bulletin addressee {addressee!r}"
        )


def _is_id(text: str) -> bool:
    return 1 <= len(text) <= 5 and text.isascii() and text.isalnum()


def _message_id(msg_id: str | None, reply_ack: str | None) -> str:
    if msg_id is None:
        if reply_ack is not None:
            if reply_ack and not _is_id(reply_ack):
                raise _refuse(
                    RefusalCode.INVALID_MESSAGE_ID, f"reply-ack {reply_ack!r} is not up to 5 letters and digits"
                )
            raise _refuse(RefusalCode.MISSING_FIELD, "a reply-ack goes with a message ID")
        return ""
    if not _is_id(msg_id):
        raise _refuse(RefusalCode.INVALID_MESSAGE_ID, f"message ID {msg_id!r} is not 1-5 letters and digits")
    if reply_ack is None:
        return "{" + msg_id
    if reply_ack and not _is_id(reply_ack):
        raise _refuse(RefusalCode.INVALID_MESSAGE_ID, f"reply-ack {reply_ack!r} is not up to 5 letters and digits")
    return "{" + msg_id + "}" + reply_ack


def _message_text(text: str, *, limit: bool = True) -> None:
    _check_text(text, "message text")
    if "{" in text:
        raise _refuse(RefusalCode.INVALID_CHARACTER, "message text cannot contain {, which starts the message ID")
    if limit and len(text) > MESSAGE_TEXT_LIMIT:
        raise _refuse(RefusalCode.TOO_LONG, f"message text is over {MESSAGE_TEXT_LIMIT} characters")


def _message(data: Message) -> bytes:
    # text to a bulletin or NWS addressee would read back as a bulletin: not the form a message needs
    _check_message_addressee(data.addressee, "a message")
    head = _addressee(data.addressee)
    _message_text(data.text)
    return _checked(data, head + data.text + _message_id(data.message_id, data.reply_ack))


def _ack(data: Ack | Reject) -> bytes:
    head = _addressee(data.addressee)
    ident = data.acked_id if isinstance(data, Ack) else data.rejected_id
    if not _is_id(ident):
        raise _refuse(RefusalCode.INVALID_MESSAGE_ID, f"message ID {ident!r} is not 1-5 letters and digits")
    word = "ack" if isinstance(data, Ack) else "rej"
    text = head + word + ident
    if data.reply_ack is not None:
        if data.reply_ack and not _is_id(data.reply_ack):
            raise _refuse(
                RefusalCode.INVALID_MESSAGE_ID, f"reply-ack {data.reply_ack!r} is not up to 5 letters and digits"
            )
        text += "}" + data.reply_ack
    return _checked(data, text)


def _bulletin(data: Bulletin) -> bytes:
    a = data.addressee
    if not (a.startswith("BLN") and 4 <= len(a) <= 9 and ("0" <= a[3] <= "9" or "A" <= a[3] <= "Z")):
        raise _refuse(
            RefusalCode.INVALID_ADDRESSEE, f"bulletin addressee {a!r} is not BLN then a digit or an upper-case letter"
        )
    if a[3].isalpha() and len(a) > 4:
        raise _refuse(RefusalCode.INVALID_ADDRESSEE, "a group bulletin's identifier is a digit")
    head = _addressee(a)
    _message_text(data.text)
    return _checked(data, head + data.text + _message_id(data.message_id, None))


def _nws(data: NwsBulletin) -> bytes:
    if not data.addressee.startswith(("NWS-", "NWS_")):
        raise _refuse(RefusalCode.INVALID_ADDRESSEE, "an NWS bulletin's addressee starts NWS-")
    head = _addressee(data.addressee)
    _message_text(data.text, limit=False)
    return _checked(data, head + data.text + _message_id(data.message_id, None))


def _metadata_list(items: tuple[str, ...], limit: int, what: str) -> str:
    for item in items:
        _check_text(item, what)
        if "," in item or "{" in item:
            raise _refuse(RefusalCode.INVALID_CHARACTER, f"{what} entries cannot contain , or {{")
    if len(items) > limit:
        raise _refuse(RefusalCode.TOO_LONG, f"{what} has at most {limit} entries")
    return ",".join(items)


def _telemetry_metadata(data: TelemetryNames | TelemetryUnits | TelemetryCoefficients | TelemetryBits) -> bytes:
    _check_message_addressee(data.addressee, "telemetry metadata")
    head = _addressee(data.addressee)
    if isinstance(data, TelemetryNames):
        body = "PARM." + _metadata_list(data.names, 13, "PARM.")
    elif isinstance(data, TelemetryUnits):
        body = "UNIT." + _metadata_list(data.units, 13, "UNIT.")
    elif isinstance(data, TelemetryCoefficients):
        if not all(math.isfinite(v) for v in data.coefficients):
            raise _refuse(RefusalCode.NOT_A_NUMBER, "a coefficient is a finite number")
        if len(data.coefficients) > 15:
            raise _refuse(RefusalCode.TOO_LONG, "EQNS. carries 1-15 coefficients")
        if not data.coefficients:
            raise _refuse(RefusalCode.MALFORMED, "EQNS. carries 1-15 coefficients")
        texts = data.coefficients_text
        if len(texts) != len(data.coefficients) or any(
            not _same_number(t, v, _COEFFICIENT) for t, v in zip(texts, data.coefficients, strict=False)
        ):
            texts = tuple(_util.number_text(v) for v in data.coefficients)
        body = "EQNS." + ",".join(texts)
    else:
        _check_text(data.project, "project title")
        if "{" in data.project:
            raise _refuse(RefusalCode.INVALID_CHARACTER, "the project title cannot contain {")
        if len(data.project) > _TELEMETRY_TITLE_LIMIT:
            raise _refuse(
                RefusalCode.TOO_LONG, f"a telemetry project title is at most {_TELEMETRY_TITLE_LIMIT} characters"
            )
        if len(data.bits) != 8 or any(b not in "01" for b in data.bits):
            raise _refuse(RefusalCode.MALFORMED, "BITS. needs eight 0/1 bits")
        body = "BITS." + data.bits + ("," + data.project if data.project else "")
    return _checked(data, head + body + _message_id(data.message_id, None))


_DEFINED_QUERIES = ("APRSD", "APRSH", "APRSM", "APRSO", "APRSP", "APRSS", "APRST", "PING?")


def _directed_query(data: DirectedQuery) -> bytes:
    _check_message_addressee(data.addressee, "a directed query")
    head = _addressee(data.addressee)
    qtype = data.query_type
    target = data.target or ""
    if target and (len(target) > 9 or not all(c.isascii() and (c.isalnum() or c == "-") for c in target)):
        raise _refuse(RefusalCode.INVALID_ADDRESSEE, f"query target {target!r} is not a callsign")
    if qtype != "PING?" and (not qtype or not all("A" <= c <= "Z" for c in qtype)):
        raise _refuse(RefusalCode.INVALID_CODE, f"query type {qtype!r} is not upper-case letters")
    # a defined type's target goes straight after it, an APRSH one padded to 9 characters
    # (APRS12c 1.2 notes); any other type's after one space, since its length is not fixed
    if target and qtype == "APRSH":
        target = target.ljust(9)
    elif target and qtype not in _DEFINED_QUERIES:
        target = " " + target
    return _checked(data, head + "?" + qtype + target)


# ---------------------------------------------------------------- the rest


def _status(data: StatusReport) -> bytes:
    f = _Faults()
    text = ">"
    if data.timestamp is not None:
        f.guard(_check_timestamp, data.timestamp, (TimestampKind.DHM_ZULU,), "status", default=None)
    f.guard(_check_text, data.text, "status text", default=None)
    if data.locator is not None:
        if data.timestamp is not None:
            f.add(RefusalCode.FIELD_NOT_ALLOWED, "a status report with a grid locator has no timestamp")
        if not _util.is_locator(data.locator) or data.locator != data.locator.upper():
            f.add(RefusalCode.MALFORMED, f"{data.locator!r} is not a Maidenhead locator")
        if data.symbol is None:
            f.add(RefusalCode.MISSING_FIELD, "a grid locator status report needs a symbol")
        elif not data.symbol.is_valid:
            f.add(RefusalCode.INVALID_SYMBOL, f"symbol {str(data.symbol)!r} is not a valid table and code")
    elif data.symbol is not None:
        f.add(RefusalCode.FIELD_NOT_ALLOWED, "a status report's symbol goes with a grid locator")
    if data.beam is not None:
        b = data.beam
        if not ("0" <= b.heading_code <= "9" or "A" <= b.heading_code <= "Z") or not (
            "1" <= b.power_code <= "9" or ":" <= b.power_code <= "K"
        ):
            f.add(RefusalCode.INVALID_CODE, "beam heading or power code out of range")
    f.finish()
    if data.timestamp is not None:
        text += data.timestamp.text
    if data.locator is not None:
        text += data.locator.upper() + str(data.symbol)
        if data.text or data.beam:
            text += " "
    text += data.text
    if data.beam is not None:
        text += "^" + data.beam.heading_code + data.beam.power_code
    return _checked(data, text)


def _telemetry(data: TelemetryReport) -> bytes:
    f = _Faults()
    seq = data.sequence
    if not seq or not (seq.isascii() and seq.isalnum()):
        f.add(RefusalCode.MALFORMED, "a telemetry sequence is letters and digits")
    if len(data.analog) > 5:
        f.add(RefusalCode.TOO_LONG, "a telemetry report has five analog values")
    elif len(data.analog) < 5:
        f.add(RefusalCode.MALFORMED, "a telemetry report has five analog values")
    if data.bits is None:
        f.add(RefusalCode.MISSING_FIELD, "a telemetry report has eight 0/1 bits")
    elif len(data.bits) != 8 or any(b not in "01" for b in data.bits):
        f.add(RefusalCode.MALFORMED, "a telemetry report has eight 0/1 bits")
    f.guard(_check_text, data.comment, "comment", default=None)
    if seq == "MIC" and data.analog and data.analog[0] is None:
        # no form reads back with the first channel empty after MIC (vectors ruling F12)
        f.add(RefusalCode.VALUE_HAS_NO_FORM, "T#MIC with an empty first channel has no form")
    f.finish()
    assert data.bits is not None
    texts = data.analog_text
    values: list[str] = []
    for i, v in enumerate(data.analog):
        t = texts[i] if i < len(texts) else None
        if v is None:
            values.append("")
        elif t is not None and _same_number(t, v, _TELEMETRY_VALUE):
            values.append(t)
        elif isinstance(v, int) or float(v).is_integer():
            iv = int(v)
            values.append(f"{iv:03d}" if 0 <= iv <= 999 else str(iv))
        else:
            values.append(_util.number_text(v))
    head = "T#" + seq + ("" if seq == "MIC" else ",")
    return _checked(data, head + ",".join(values) + "," + data.bits + data.comment)


def _positionless_weather(data: PositionlessWeather) -> bytes:
    f = _Faults()
    f.guard(_check_timestamp, data.timestamp, (TimestampKind.MDHM,), "weather", default=None)
    if data.comment:
        f.add(RefusalCode.FIELD_NOT_ALLOWED, "a weather report has no comment")
    text = _weather_text(data.weather, positionless=True, compressed=False, f=f)
    f.finish()
    return _checked(data, "_" + data.timestamp.text + text)


def _raw_weather(data: RawWeather) -> bytes:
    if not _util.is_printable_ascii(data.data):
        raise _refuse(RefusalCode.INVALID_CHARACTER, "raw weather data is printable ASCII")
    prefix = {
        RawWeatherFormat.PEET_BROS_HASH: "#",
        RawWeatherFormat.PEET_BROS_STAR: "*",
        RawWeatherFormat.ULTIMETER_PACKET: "$ULTW",
        RawWeatherFormat.ULTIMETER_LOGGING: "!!",
    }[data.format]
    return _checked(data, prefix + data.data)


def _nmea(data: NmeaSentence) -> bytes:
    """The sentence, and any comment after its checksum. It must read back as the same data: an
    NMEA 0183 sentence, whose fields say what ``data`` says."""
    s = data.sentence
    if not s or not _util.is_printable_ascii(s):
        raise _refuse(RefusalCode.INVALID_CHARACTER, "an NMEA sentence is printable ASCII")
    _check_text(data.comment, "comment")
    star = s.find("*")
    if star >= 0 and (star != len(s) - 3 or not all(c in "0123456789ABCDEFabcdef" for c in s[star + 1 :])):
        raise _refuse(RefusalCode.INVALID_NMEA, "a * in an NMEA sentence starts its checksum, *hh at the end")
    if data.has_checksum != (star >= 0):
        raise _refuse(
            RefusalCode.INVALID_NMEA, "has_checksum does not say whether the sentence ends with a *hh checksum"
        )
    if star >= 0:
        got = 0
        for ch in s[:star]:
            got ^= ord(ch)
        if got != int(s[star + 1 :], 16):
            raise _refuse(RefusalCode.INVALID_NMEA, "the NMEA checksum does not match the sentence")
    if data.comment and not data.has_checksum:
        # only a checksum ends a sentence: written, the comment would read back as part of it
        raise _refuse(RefusalCode.INVALID_NMEA, "a comment goes after the sentence's checksum")
    raw = ("$" + s).encode("ascii") + data.comment.encode("utf-8")
    if not _nmea_reads_back(data, raw):
        raise _refuse(RefusalCode.INVALID_NMEA, "the sentence does not read back as the same NMEA data")
    return raw


def _nmea_reads_back(data: NmeaSentence, raw: bytes) -> bool:
    """Whether ``raw`` reads back with the sentence and comment as given and every field given
    agreeing with the sentence: a field left out is the sentence's own (vectors interpretations.md,
    NMEA data is its sentence)."""
    from ._decode import Ctx, decode_info
    from ._neutral import to_neutral

    ctx = Ctx(_LENIENT)
    decoded = decode_info(raw, DEFAULT_DESTINATION, ctx)
    if any(d.severity is not Severity.INFO for d in ctx.diags):
        return False
    given, found = to_neutral(data), to_neutral(decoded)
    if found.get("type") != "nmea":
        return False
    return not any(_shape_differences(v, found.get(k), numbers=True) for k, v in given.items())


def _maidenhead(data: MaidenheadBeacon) -> bytes:
    _check_text(data.comment, "comment")
    if not _util.is_locator(data.locator) or data.locator != data.locator.upper():
        raise _refuse(RefusalCode.MALFORMED, f"{data.locator!r} is not a Maidenhead locator")
    return _checked(data, "[" + data.locator.upper() + "]" + data.comment)


def _query(data: Query) -> bytes:
    text = "?" + data.query_type + "?"
    if data.footprint is not None:
        f = data.footprint
        # whole miles, rounded first (vectors ruling F2)
        radius = _nearest(f.radius_miles)
        if not 0 <= radius <= 9999:
            raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, "footprint radius is 0-9999 miles")
        if not (-90 <= f.latitude <= 90 and -180 <= f.longitude <= 180):
            raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, "footprint latitude or longitude out of range")
    if not data.query_type or not all("A" <= c <= "Z" for c in data.query_type):
        raise _refuse(RefusalCode.INVALID_CODE, "a query type is upper-case letters")
    if data.footprint is not None:
        f = data.footprint
        radius = _nearest(f.radius_miles)
        # numbers as sent, leading space or not (vectors ruling E1); otherwise north and east
        # are positive, "indicated by a leading space", and south and west have only the minus
        # sign (APRS12c ch. 15)
        numbers = []
        for value, sent in ((f.latitude, f.latitude_text), (f.longitude, f.longitude_text)):
            if not _same_number(sent, value, _FOOTPRINT_VALUE):
                sent = _util.number_text(value)
                if not sent.startswith("-"):
                    sent = " " + sent
            numbers.append(sent)
        text += f"{numbers[0]},{numbers[1]},{radius:04d}"
    return _checked(data, text)


def _capabilities(data: Capabilities) -> bytes:
    f = _Faults()
    if not data.capabilities:
        raise _refuse(RefusalCode.MISSING_FIELD, "no capabilities")
    items = []
    for cap in data.capabilities:
        if not 1 <= len(cap) <= 2:
            f.add(RefusalCode.TOO_LONG, "a capability is a token or a token and a value")
            continue
        token = cap[0]
        # a token is fixed-form text
        if not token or any(c in " =," or c < " " or c == "\x7f" for c in token):
            f.add(RefusalCode.MALFORMED, f"capability token {token!r} is free text")
        if len(cap) == 2:
            value = cap[1]
            if any(c < " " or c == "\x7f" for c in value):
                f.add(
                    RefusalCode.INVALID_CHARACTER,
                    "a capability value with a control character would read back as free text",
                )
            if "," in value:
                f.add(RefusalCode.INVALID_CHARACTER, "a capability value cannot contain a comma")
            if value != value.strip(" "):
                f.add(RefusalCode.PADDING_SPACE, "spaces around a capability value are padding and would be dropped")
            items.append(f"{token}={value}")
        else:
            items.append(token)
    f.finish()
    return _checked(data, "<" + ",".join(items))


_INNER_HEADER_DEFECTS = frozenset(
    {DiagnosticCode.EMPTY_DESTINATION, DiagnosticCode.EMPTY_PATH_ENTRY, DiagnosticCode.MULTIPLE_USED_MARKERS}
)


MAX_THIRD_PARTY_DEPTH = 4
"""Third-party packets nest at most four deep (vectors interpretations.md)."""


def _third_party_walk(data: ThirdParty) -> tuple[int, str | None]:
    """How many third-party levels ``data`` holds, and the type name of undecoded data at the end
    of the chain (None when it ends in something that can be written). A loop, not a recursion,
    so a chain built thousands deep is judged without exhausting the stack."""
    depth = 0
    current: AprsData = data
    while isinstance(current, ThirdParty):
        depth += 1
        packet = current.packet
        if packet.info or packet.data == Unrecognized(UnrecognizedReason.EMPTY):
            return depth, None
        current = packet.data
    return depth, None if type(current) in _ENCODERS else type(current).__name__


def _third_party(data: ThirdParty) -> bytes:
    from ._decode import _ADDRESS, _THIRD_PARTY_SOURCE

    inner = data.packet
    bad = RefusalCode.INVALID_THIRD_PARTY_HEADER
    depth, undecoded = _third_party_walk(data)
    if undecoded is not None:
        # data with no form to write comes first in the order, ahead of the header
        raise _refuse(RefusalCode.NOT_ENCODABLE, f"{undecoded} cannot be encoded")
    if depth > MAX_THIRD_PARTY_DEPTH:
        raise _refuse(bad, f"third-party packets nest at most {MAX_THIRD_PARTY_DEPTH} deep")
    # the inner header comes before the inner data, so its faults are named first
    if any(d.code in _INNER_HEADER_DEFECTS for d in inner.diagnostics):
        # the defect is part of the data, and no clean header reproduces it
        raise _refuse(bad, "the third-party packet's inner header has a defect a clean header cannot carry")
    if not _THIRD_PARTY_SOURCE.match(inner.source):
        raise _refuse(bad, f"third-party source {inner.source!r} is not 1-9 printable characters other than > and :")
    writes_data = not (inner.info or inner.data == Unrecognized(UnrecognizedReason.EMPTY))
    # a Mic-E report's destination is computed from the data, any other keeps the one it has
    computed = writes_data and isinstance(inner.data, MicEReport)
    if (not computed and not _ADDRESS.match(inner.destination)) or any(
        not _ADDRESS.match(p.address) for p in inner.path
    ):
        raise _refuse(bad, "a third-party destination or path entry is not 1-9 letters, digits or -")
    used = [p.used for p in inner.path]
    if used != sorted(used, reverse=True):
        raise _refuse(bad, "in TNC2 a path entry before a used one is used too")
    if writes_data:
        info = encode_info(inner.data)
        destination = mic_e_destination(inner.data) if isinstance(inner.data, MicEReport) else inner.destination
    else:
        # the original information field must not be changed (APRS12c ch. 17), even when empty
        info = inner.info
        destination = inner.destination
    path = _tnc2_path(inner.path)
    header = f"{inner.source}>{destination}" + ("," + path if path else "")
    return b"}" + header.encode("ascii") + b":" + info


def _user_defined(data: UserDefined) -> bytes:
    if (data.user_id + data.packet_type + data.data).endswith(("\r", "\n")):
        # a line break at the end of a packet is a tolerated defect, not data: it would be dropped
        raise _refuse(
            RefusalCode.INVALID_CHARACTER, "user-defined data that ends in a line break would read back without it"
        )
    try:
        encoded = ("{" + data.user_id + data.packet_type + data.data).encode("latin-1")
    except UnicodeEncodeError:
        raise _refuse(
            RefusalCode.INVALID_CHARACTER, "user-defined data is bytes: one character U+0000-U+00FF per byte"
        ) from None
    if len(data.user_id) != 1 or len(data.packet_type) != 1:
        raise _refuse(RefusalCode.TOO_LONG, "user ID and packet type are one character each")
    return encoded


def _test(data: TestData) -> bytes:
    _check_text(data.data, "test data")
    return _checked(data, "," + data.data)


def _agrelo(data: AgreloDf) -> bytes:
    if not 0 <= data.bearing_degrees <= 360 or not 0 <= data.quality <= 9:
        raise _refuse(RefusalCode.VALUE_OUT_OF_RANGE, "an Agrelo bearing is 0-360 degrees and its quality one digit")
    return f"%{data.bearing_degrees:03d}/{data.quality}".encode("ascii")


_ENCODERS: dict[type[Any], Callable[[Any], bytes]] = {
    PositionReport: _position,
    ObjectReport: _object,
    ItemReport: _item,
    MicEReport: _mic_e,
    Message: _message,
    Ack: _ack,
    Reject: _ack,
    Bulletin: _bulletin,
    NwsBulletin: _nws,
    TelemetryNames: _telemetry_metadata,
    TelemetryUnits: _telemetry_metadata,
    TelemetryCoefficients: _telemetry_metadata,
    TelemetryBits: _telemetry_metadata,
    DirectedQuery: _directed_query,
    StatusReport: _status,
    TelemetryReport: _telemetry,
    PositionlessWeather: _positionless_weather,
    RawWeather: _raw_weather,
    NmeaSentence: _nmea,
    MaidenheadBeacon: _maidenhead,
    Query: _query,
    Capabilities: _capabilities,
    ThirdParty: _third_party,
    UserDefined: _user_defined,
    TestData: _test,
    AgreloDf: _agrelo,
}


def encode_info(data: AprsData) -> bytes:
    """The information field for ``data``. Raises :class:`EncodeError` when the data cannot be
    written as the specification allows."""
    encoder = _ENCODERS.get(type(data))
    if encoder is None:
        raise _refuse(RefusalCode.NOT_ENCODABLE, f"{type(data).__name__} cannot be encoded")
    if isinstance(data, ThirdParty):
        # judged in a loop before anything recurses (the NaN rule below walks the data)
        depth, undecoded = _third_party_walk(data)
        if undecoded is not None:
            raise _refuse(RefusalCode.NOT_ENCODABLE, f"{undecoded} cannot be encoded")
        if depth > MAX_THIRD_PARTY_DEPTH:
            raise _refuse(
                RefusalCode.INVALID_THIRD_PARTY_HEADER, f"third-party packets nest at most {MAX_THIRD_PARTY_DEPTH} deep"
            )
    amb = getattr(data, "ambiguity", 0)
    if isinstance(amb, float) and not math.isfinite(amb):
        # an ambiguity of NaN is no level to cut a position to: judged as any NaN is
        raise _nan_or_earlier(data, encoder, "ambiguity is a number")
    try:
        return encoder(data)
    except EncodeError as e:
        raise _nan_rule(data, e) from None
    except (ValueError, OverflowError) as e:
        # a value no packet can hold, such as a NaN latitude
        raise _nan_or_earlier(data, encoder, f"cannot encode {type(data).__name__}: {e}") from e


def build_packet(
    source: str,
    data: AprsData,
    *,
    destination: str = DEFAULT_DESTINATION,
    path: Iterable[str | PathEntry] = (),
) -> Packet:
    """A packet ready to send: the header, the encoded information field and the data.

    For a Mic-E report the destination is computed from the data (with its
    ``destination_ssid``), and ``destination`` is ignored.
    """
    _check_header_address(source, "source")
    entries = tuple(p if isinstance(p, PathEntry) else PathEntry(p.rstrip("*"), p.endswith("*")) for p in path)
    for entry in entries:
        _check_header_address(entry.address, "path entry")
    if len(entries) > 8:
        raise _refuse(RefusalCode.AX25_CANNOT_CARRY, "at most 8 digipeaters")
    if not isinstance(data, MicEReport):
        _check_header_address(destination, "destination")
    # the information field first: it names the first code that applies across all the data
    info = encode_info(data)
    if isinstance(data, MicEReport):
        destination = mic_e_destination(data)
    return Packet(source, destination, entries, info, data)
