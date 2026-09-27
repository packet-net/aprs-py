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

import math
import re
from collections.abc import Callable, Iterable
from typing import Any

from . import _util
from ._comment import MICROWAVE_BASE
from .diagnostics import DiagnosticCode, Severity
from .errors import EncodeError
from .model import (
    Ack,
    AgreloDf,
    AprsData,
    AreaShape,
    Bulletin,
    Capabilities,
    CommentTelemetry,
    DaoPrecision,
    DirectedQuery,
    ItemReport,
    MaidenheadBeacon,
    Message,
    MicEMessage,
    MicEReport,
    NmeaSentence,
    NmeaSource,
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
from .options import LENIENT
from .packet import Packet, PathEntry, tnc2_path

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

_TELEMETRY_TITLE_LIMIT = 23
_TIMESTAMPED = (TimestampKind.DHM_ZULU, TimestampKind.DHM_LOCAL, TimestampKind.HMS)


_TELEMETRY_VALUE = re.compile(r"-?(?:[0-9]+\.?[0-9]*|\.[0-9]+)\Z")
_COEFFICIENT = re.compile(r"-?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?\Z")


def _same_number(text: str, value: float, form: re.Pattern[str]) -> bool:
    """Whether a number kept as sent is one ``form`` allows and still says ``value``, so that it
    can be written back."""
    if not form.match(text):
        return False
    try:
        return _util.number_equal(float(text), float(value))
    except (ValueError, OverflowError):
        return False


def _refuse(why: str) -> EncodeError:
    return EncodeError(why)


# ---------------------------------------------------------------- checks


def _check_text(text: str, what: str) -> None:
    if "\r" in text or "\n" in text:
        raise _refuse(f"{what} contains a line break")


def _check_address(call: str, what: str) -> None:
    if not call or len(call) > 9 or not _util.is_printable_ascii(call) or " " in call or ":" in call:
        raise _refuse(f"{what} {call!r} is not 1-9 printable characters without spaces or colons")


def _check_symbol(data: PositionedData) -> None:
    if not data.symbol.is_valid:
        raise _refuse(f"symbol {str(data.symbol)!r} is not a valid table and code")


def _check_timestamp(ts: Timestamp, kinds: tuple[TimestampKind, ...], what: str) -> None:
    kind = ts.kind
    if kind is None or kind not in kinds:
        raise _refuse(f"{what} timestamp {ts.text!r} is not of an allowed format")
    if not ts.is_valid:
        raise _refuse(f"{what} timestamp {ts.text!r} is out of range")


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
    from .neutral import to_neutral

    ctx = Ctx(LENIENT)
    decoded = decode_info(info, destination, ctx)
    if any(d.severity is not Severity.INFO for d in ctx.diags):
        return False
    return not _shape_differences(to_neutral(data), to_neutral(decoded), numbers=numbers)


def _with_comment(
    data: AprsData,
    comment: str,
    build: Callable[[str], bytes],
    destination: str = DEFAULT_DESTINATION,
    *,
    after_frequency: bool = False,
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
    for candidate in candidates:
        info = build(candidate)
        if _reads_back(data, info, destination):
            return info
    raise _refuse(f"the text {comment!r} would not read back as written")


def _checked(data: AprsData, info: str) -> bytes:
    raw = info.encode("utf-8")
    if not _reads_back(data, raw, DEFAULT_DESTINATION):
        raise _refuse("the text would not read back as written")
    return raw


# ---------------------------------------------------------------- positions


def _minutes_units(value: float, per_minute: int) -> int:
    """|value| in units of 1/``per_minute`` of a minute of arc, rounded."""
    return round(abs(value) * 60 * per_minute)


def _is_negative(value: float) -> bool:
    return value < 0 or (value == 0 and math.copysign(1.0, value) < 0)


def _dao_digits(data: PositionedData) -> tuple[str, str, int, int]:
    """For a ``!DAO!``: its two characters, and the latitude and longitude in hundredths of a
    minute to write in the position itself."""
    dao = data.dao
    lat, lon = data.latitude, data.longitude
    if dao is None or dao.precision is DaoPrecision.NONE or data.compressed:
        return " ", " ", _minutes_units(lat, 100), _minutes_units(lon, 100)
    if dao.precision is DaoPrecision.THOUSANDTHS:
        la, lo = _minutes_units(lat, 1000), _minutes_units(lon, 1000)
        return str(la % 10), str(lo % 10), la // 10, lo // 10
    la, lo = _minutes_units(lat, 9100), _minutes_units(lon, 9100)
    return chr(la % 91 + 33), chr(lo % 91 + 33), la // 91, lo // 91


def _dao_text(data: PositionedData, a: str, o: str) -> str:
    dao = data.dao
    if dao is None:
        return ""
    datum = dao.datum
    if len(datum) != 1 or not (datum.isascii() and datum.isalnum()):
        raise _refuse(f"DAO datum {datum!r} is not one letter or digit")
    if datum.isdigit() and dao.precision is not DaoPrecision.NONE:
        # a digit has no case to say how A and O are written
        raise _refuse("a DAO with a digit datum carries no added precision")
    if dao.precision is DaoPrecision.BASE91:
        if not datum.isalpha():
            raise _refuse("a base-91 DAO needs a letter datum")
        datum = datum.lower()
        if data.compressed:
            a = o = "!"
    elif dao.precision is DaoPrecision.THOUSANDTHS:
        datum = datum.upper()
        if data.compressed:
            a = o = "0"
    else:
        datum = datum.upper()
        a = o = " "
    return f"!{datum}{a}{o}!"


def _uncompressed(data: PositionedData, lat_units: int, lon_units: int) -> str:
    lat, lon = data.latitude, data.longitude
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise _refuse("latitude or longitude out of range")
    if lat_units > 90 * 6000 or lon_units > 180 * 6000:
        raise _refuse("latitude or longitude out of range")
    amb = data.ambiguity
    if not 0 <= amb <= 4:
        raise _refuse(f"ambiguity {amb} is not 0-4")
    ld, lr = divmod(lat_units, 6000)
    od, orr = divmod(lon_units, 6000)
    lat_digits = f"{ld:02d}{lr // 100:02d}{lr % 100:02d}"
    lon_digits = f"{od:03d}{orr // 100:02d}{orr % 100:02d}"
    if amb and (ld == 90 or od == 180):
        raise _refuse("an ambiguous position at 90 or 180 degrees would be centred past it")
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


def _course_speed(course: float, knots: float) -> str:
    if not 0 <= course <= 360:
        raise _refuse(f"course {course} is not 0-360")
    c = math.floor(course / 4 + 0.5) % 90
    s = round(math.log(knots + 1) / math.log(1.08)) if knots > 0 else 0
    if not 0 <= s <= 90:
        raise _refuse(f"speed {knots} knots is too high for the compressed format")
    return chr(c + 33) + chr(s + 33)


def _altitude(feet: float) -> str:
    value = round(feet)
    if value < 0:
        if value < -99999:
            raise _refuse("altitude too low")
        return f"/A=-{-value:05d}"
    if value > 999999:
        raise _refuse("altitude too high")
    return f"/A={value:06d}"


def _compressed(data: PositionedData, weather: bool) -> tuple[str, str]:
    """The 13-byte compressed position, and any ``/A=`` altitude it needs besides."""
    if data.ambiguity:
        raise _refuse("a compressed position cannot be ambiguous")
    if data.phg is not None or data.dfs is not None or data.area is not None:
        raise _refuse("a compressed position cannot carry PHG, DFS or an area object")
    if data.df_bearing is not None or data.storm is not None:
        raise _refuse("a compressed position cannot carry DF or storm data")
    lat, lon = data.latitude, data.longitude
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise _refuse("latitude or longitude out of range")
    table = data.symbol.table
    if "0" <= table <= "9":
        table = chr(ord(table) - ord("0") + ord("a"))
    y = _base91(round(380926 * (90 - lat)), 4)
    x = _base91(round(190463 * (180 + lon)), 4)
    ctype = data.compression
    altitude_text = ""
    cs: str | None = None
    w = data.weather
    if weather and w is not None and (w.wind_direction_degrees is not None or w.wind_speed_mph is not None):
        if w.wind_direction_degrees is None or w.wind_speed_mph is None:
            raise _refuse("compressed wind needs both a direction and a speed")
        if data.course_degrees is not None or data.speed_knots is not None or data.range_miles is not None:
            raise _refuse("a weather report's cs bytes carry the wind")
        if data.altitude_feet is not None:
            raise _refuse("a weather report's cs bytes carry the wind, not an altitude")
        cs = _course_speed(w.wind_direction_degrees, w.wind_speed_mph / _util.KNOTS_TO_MPH)
    elif ctype is not None and ctype.source is NmeaSource.GGA:
        if data.course_degrees is not None or data.speed_knots is not None or data.range_miles is not None:
            raise _refuse("a GGA compressed position carries altitude, not course, speed or range")
        if data.altitude_feet is None:
            raise _refuse("a GGA compressed position needs an altitude")
        alt = data.altitude_feet
        value = round(math.log(alt) / math.log(1.002)) if alt >= 1 else 0
        value = min(max(value, 0), 91 * 91 - 1)
        cs = _base91(value, 2)
        if not _util.number_equal(1.002**value, alt):
            altitude_text = _altitude(alt)
    else:
        if data.altitude_feet is not None:
            if weather:
                raise _refuse("a weather report carries an altitude only in GGA cs bytes")
            altitude_text = _altitude(data.altitude_feet)
        if data.course_degrees is not None or data.speed_knots is not None:
            if weather:
                raise _refuse("a weather report carries wind, not course and speed")
            if data.range_miles is not None:
                raise _refuse("a compressed position carries course and speed, or range, not both")
            if data.course_degrees is None or data.speed_knots is None:
                raise _refuse("a compressed course and speed needs both")
            cs = _course_speed(data.course_degrees, data.speed_knots)
        elif data.range_miles is not None:
            if data.range_miles < 2:
                raise _refuse("a compressed range is at least 2 miles")
            s = round(math.log(data.range_miles / 2) / math.log(1.08))
            if not 0 <= s <= 90:
                raise _refuse("range too large for the compressed format")
            step = 2 * 1.08**s
            if not _util.number_equal(step, data.range_miles):
                # interpretations.md lets an encoder round a range into the cs bytes or refuse:
                # this one refuses, rather than write a different range
                raise _refuse(
                    f"a compressed range is 2 x 1.08^n miles, so {data.range_miles:g} miles cannot be written"
                    f" exactly (the nearest step is {step:.2f} miles)"
                )
            cs = "{" + chr(s + 33)
    if cs is None:
        if ctype is not None:
            raise _refuse("a compression type needs course/speed, range or altitude to go with it")
        return f"{table}{y}{x}{data.symbol.code} sT", altitude_text
    if ctype is None:
        # the cs bytes always come with a compression type byte, which reads back as data
        raise _refuse("compressed course and speed, range or wind need a compression type (the T byte)")
    return f"{table}{y}{x}{data.symbol.code}{cs}{chr(ctype.value + 33)}", altitude_text


def _phg_text(data: PositionedData) -> str:
    phg = data.phg
    if phg is None:
        return ""
    if not (0 <= phg.power <= 9 and 0 <= phg.gain <= 9 and 0 <= phg.directivity <= 9 and 0 <= phg.height <= 78):
        raise _refuse("PHG code out of range")
    text = f"PHG{phg.power}{chr(phg.height + 48)}{phg.gain}{phg.directivity}"
    rate = phg.beacons_per_hour
    if rate is not None:
        if not 1 <= rate <= 35:
            raise _refuse("PHG beacons per hour is not 1-35")
        text += (str(rate) if rate < 10 else chr(rate - 10 + ord("A"))) + "/"
    return text


def _dfs_text(data: PositionedData) -> str:
    d = data.dfs
    if d is None:
        return ""
    if not (0 <= d.strength <= 9 and 0 <= d.gain <= 9 and 0 <= d.directivity <= 9 and 0 <= d.height <= 78):
        raise _refuse("DFS code out of range")
    return f"DFS{d.strength}{chr(d.height + 48)}{d.gain}{d.directivity}"


def _range_text(miles: float) -> str:
    r = round(miles)
    if not 0 <= r <= 9999:
        raise _refuse("range is not 0-9999 miles")
    return f"RNG{r:04d}"


def _storm_text(data: PositionedData) -> str:
    st = data.storm
    if st is None:
        return ""
    if data.symbol.code != "@":
        raise _refuse("storm data needs a hurricane symbol")
    code = {StormType.TROPICAL_STORM: "TS", StormType.HURRICANE: "HC"}.get(st.type, "TD")

    def n(v: int | None, width: int) -> str:
        if v is None:
            return "." * width
        if not 0 <= v < 10**width:
            raise _refuse("storm value does not fit its field")
        return f"{v:0{width}d}"

    text = (
        f"/{code}/{n(st.sustained_wind_knots, 3)}^{n(st.gust_knots, 3)}/{n(st.central_pressure_mbar, 4)}"
        f">{n(st.hurricane_radius_nm, 3)}&{n(st.tropical_storm_radius_nm, 3)}"
    )
    if st.whole_gale_radius_nm is not None:
        text += "%" + n(st.whole_gale_radius_nm, 3)
    return text


def _extension(data: PositionedData) -> str:
    """The data extension straight after the symbol, at most one."""
    parts: list[str] = []
    if data.course_degrees is not None or data.speed_knots is not None or data.df_bearing or data.storm:
        course = data.course_degrees
        speed = data.speed_knots
        if course is not None and not 0 <= course <= 360:
            raise _refuse(f"course {course} is not 0-360")
        if speed is not None and not 0 <= round(speed) <= 999:
            raise _refuse(f"speed {speed} is not 0-999 knots")
        text = ("..." if course is None else f"{round(course):03d}") + "/"
        text += "..." if speed is None else f"{round(speed):03d}"
        if data.df_bearing is not None:
            if str(data.symbol) != "/\\":
                raise _refuse("DF bearing needs the DF symbol /\\")
            b = data.df_bearing
            if not (0 <= b.bearing_degrees <= 360 and all(0 <= v <= 9 for v in (b.number, b.range, b.quality))):
                raise _refuse("DF bearing or NRQ out of range")
            text += f"/{b.bearing_degrees:03d}/{b.number}{b.range}{b.quality}"
        text += _storm_text(data)
        parts.append(text)
    if data.phg is not None:
        parts.append(_phg_text(data))
    if data.range_miles is not None:
        parts.append(_range_text(data.range_miles))
    if data.dfs is not None:
        parts.append(_dfs_text(data))
    if data.area is not None:
        if str(data.symbol) != "\\l":
            raise _refuse("an area object needs the area symbol \\l, without an overlay")
        a = data.area
        if not (0 <= a.lat_offset <= 99 and 0 <= a.lon_offset <= 99):
            raise _refuse("area offsets are 0-99")
        color = a.color.code
        parts.append(
            f"{a.shape.code}{a.lat_offset:02d}{'/' + str(color) if color < 10 else str(color)}{a.lon_offset:02d}"
        )
    if len(parts) > 1:
        raise _refuse("more than one data extension")
    return parts[0] if parts else ""


def _frequency_text(f: VoiceFrequency) -> str:
    mhz = f.mhz
    if mhz >= 1000:
        for letter, base in MICROWAVE_BASE.items():
            if base <= mhz < base + 100:
                rest = mhz - base
                head = f"{letter}{rest:05.2f}" if f.ten_khz_resolution else f"{letter}{rest:06.3f}"
                break
        else:
            raise _refuse(f"frequency {mhz} MHz has no APRS form")
    elif mhz >= 0:
        head = f"{mhz:06.2f}" if f.ten_khz_resolution else f"{mhz:07.3f}"
    else:
        raise _refuse("a frequency is positive")
    text = head + (" MHz" if f.ten_khz_resolution else "MHz")
    if f.tone is not None:
        if f.tone is ToneType.OFF:
            text += " toff" if f.narrow else " Toff"
        elif f.tone is ToneType.TONE_BURST:
            text += " l750" if f.narrow else " 1750"
        else:
            if f.tone_value is None or not 0 <= f.tone_value <= 999:
                raise _refuse("a tone needs a value of 0-999")
            letter = {ToneType.TONE: "T", ToneType.CTCSS: "C", ToneType.DCS: "D"}[f.tone]
            text += f" {letter.lower() if f.narrow else letter}{f.tone_value:03d}"
    elif f.narrow:
        raise _refuse("narrow is set by a tone letter")
    if f.offset_khz is not None:
        tens = round(f.offset_khz / 10)
        if abs(tens) > 999:
            raise _refuse("offset too large")
        text += f" {'-' if tens < 0 else '+'}{abs(tens):03d}"
    if f.range is not None:
        if not 0 <= f.range <= 999:
            raise _refuse("range out of range")
        text += f" R{f.range:02d}{'k' if f.range_km else 'm'}"
    return text


def _telemetry_text(t: CommentTelemetry | None) -> str:
    if t is None:
        return ""
    if not 1 <= len(t.analog) <= 5:
        raise _refuse("comment telemetry has 1-5 analog values")
    values = [t.sequence, *t.analog]
    if t.digital is not None:
        if len(t.analog) != 5:
            raise _refuse("comment telemetry digital bits need all five analog values")
        if not 0 <= t.digital <= 255:
            raise _refuse("comment telemetry has eight binary channels, 0-255")
        values.append(t.digital)
    if any(not 0 <= v <= 8280 for v in values):
        raise _refuse("comment telemetry values are 0-8280")
    return "|" + "".join(_util.base91_text(v, 2) for v in values) + "|"


def _braces(data: PositionedData) -> str:
    text = ""
    if data.signpost is not None:
        if str(data.symbol) != "\\m":
            raise _refuse("a signpost needs the signpost symbol \\m, without an overlay")
        sign = data.signpost
        if not 1 <= len(sign) <= 3 or not _util.is_printable_ascii(sign) or "{" in sign or "}" in sign:
            raise _refuse("a signpost is 1-3 printable ASCII characters other than braces")
        text += "{" + data.signpost + "}"
    if data.area is not None and data.area.corridor_width_miles is not None:
        if data.area.shape not in (AreaShape.LINE_DOWN_RIGHT, AreaShape.LINE_DOWN_LEFT):
            raise _refuse("only a line has a corridor")
        if not 0 <= data.area.corridor_width_miles <= 999:
            raise _refuse("corridor width is 0-999 miles")
        text += "{" + str(data.area.corridor_width_miles) + "}"
    return text


def _weather_text(w: Weather, *, positionless: bool, compressed: bool) -> str:
    """The weather fields: the wind first (unless compressed), the mandatory gust and
    temperature (dots when unknown), the rest when known, then software and unit."""
    out: list[str] = []

    def num(v: float | None, width: int, scale: float = 1) -> str:
        if v is None:
            return "." * width
        value = round(v * scale)
        if value < 0 or value >= 10**width:
            raise _refuse(f"weather value {v} does not fit {width} digits")
        return f"{value:0{width}d}"

    direction = w.wind_direction_degrees
    if direction is not None and not 0 <= direction <= 360:
        raise _refuse("wind direction is not 0-360")
    if positionless:
        out.append("c" + num(direction, 3) + "s" + num(w.wind_speed_mph, 3))
    elif not compressed:
        out.append(num(direction, 3) + "/" + num(w.wind_speed_mph, 3))
    out.append("g" + num(w.wind_gust_mph, 3))
    t = w.temperature_f
    if t is None:
        out.append("t...")
    else:
        ti = round(t)
        if not -99 <= ti <= 999:
            raise _refuse("temperature does not fit the weather format")
        out.append(f"t{ti:03d}" if ti >= 0 else f"t-{-ti:02d}")
    if w.rain_1h_in is not None:
        out.append("r" + num(w.rain_1h_in, 3, 100))
    if w.rain_24h_in is not None:
        out.append("p" + num(w.rain_24h_in, 3, 100))
    if w.rain_midnight_in is not None:
        out.append("P" + num(w.rain_midnight_in, 3, 100))
    if w.humidity_percent is not None:
        h = round(w.humidity_percent)
        if not 1 <= h <= 100:
            raise _refuse("humidity is not 1-100%")
        out.append("h" + ("00" if h == 100 else f"{h:02d}"))
    if w.pressure_mbar is not None:
        out.append("b" + num(w.pressure_mbar, 5, 10))
    if w.luminosity_w_m2 is not None:
        lum = round(w.luminosity_w_m2)
        if 0 <= lum <= 999:
            out.append(f"L{lum:03d}")
        elif 1000 <= lum <= 1999:
            out.append(f"l{lum - 1000:03d}")
        else:
            raise _refuse("luminosity is not 0-1999")
    if w.snow_24h_in is not None:
        snow = w.snow_24h_in
        text = f"{round(snow):03d}" if float(snow).is_integer() else f"{snow:.1f}"
        if len(text) != 3:
            raise _refuse("snowfall does not fit the weather format")
        out.append("s" + text)
    if w.rain_raw is not None:
        out.append("#" + num(w.rain_raw, 3))
    for extra in w.extra:
        if (
            len(extra.letter) != 1
            or not (extra.letter.isascii() and extra.letter.isalpha())
            or extra.letter in "cgtrpPhbLls"
        ):
            raise _refuse(f"weather extra field letter {extra.letter!r}")
        out.append(extra.letter + extra.value)
    if w.software is not None or w.unit is not None:
        if not w.software or not w.unit:
            raise _refuse("software type and unit go together")
        out.append(w.software + w.unit)
    return "".join(out)


def _position_body(data: PositionedData) -> Callable[[str], str]:
    """A function that writes the position and everything after it, given the comment."""
    _check_symbol(data)
    _check_text(data.comment, "comment")
    weather = data.symbol.code == "_"
    if data.weather is not None and not weather:
        raise _refuse("weather data needs the weather symbol _")
    if data.dao is not None and data.ambiguity:
        raise _refuse("a DAO cannot add precision to an ambiguous position")
    a, o, lat_units, lon_units = _dao_digits(data)
    if data.compressed:
        position, altitude = _compressed(data, weather)
    else:
        if data.compression is not None:
            raise _refuse("a compression type needs a compressed position")
        position = _uncompressed(data, lat_units, lon_units)
        altitude = "" if data.altitude_feet is None else _altitude(data.altitude_feet)
    dao = _dao_text(data, a, o)
    telemetry = _telemetry_text(data.telemetry)
    if weather:
        if data.comment:
            raise _refuse("a weather report has no comment")
        if telemetry:
            raise _refuse("a weather report has no comment to carry telemetry")
        others = (data.phg, data.dfs, data.area, data.df_bearing, data.storm, data.frequency, data.signpost)
        if any(x is not None for x in others):
            raise _refuse("a weather report carries weather, not other data")
        if not data.compressed and (
            data.altitude_feet is not None
            or data.course_degrees is not None
            or data.speed_knots is not None
            or data.range_miles is not None
        ):
            raise _refuse("a weather report carries wind, not course, speed, range or altitude")
        body = position + _weather_text(data.weather or Weather(), positionless=False, compressed=data.compressed)
        return lambda comment: body + dao

    ext = "" if data.compressed else _extension(data)
    braces = _braces(data)
    freq = "" if data.frequency is None else _frequency_text(data.frequency)
    if freq and ext and not braces and not altitude:
        freq = "/" + freq

    def rest(comment: str) -> str:
        return position + ext + braces + altitude + freq + comment + telemetry + dao

    return rest


def _position(data: PositionReport) -> bytes:
    if data.timestamp is not None:
        _check_timestamp(data.timestamp, _TIMESTAMPED, "position")
        head = ("@" if data.messaging else "/") + data.timestamp.text
    else:
        head = "=" if data.messaging else "!"
    rest = _position_body(data)
    return _with_comment(
        data, data.comment, lambda c: (head + rest(c)).encode("utf-8"), after_frequency=data.frequency is not None
    )


def _object(data: ObjectReport) -> bytes:
    name = data.name
    if not 1 <= len(name) <= 9 or not _util.is_printable_ascii(name):
        raise _refuse(f"object name {name!r} is not 1-9 printable characters")
    if name.endswith(" "):
        raise _refuse("an object name cannot end in a space: it would read back as padding")
    if data.timestamp is None:
        raise _refuse("an object always has a timestamp")
    _check_timestamp(data.timestamp, _TIMESTAMPED, "object")
    head = ";" + name.ljust(9) + ("_" if data.killed else "*") + data.timestamp.text
    rest = _position_body(data)
    return _with_comment(
        data, data.comment, lambda c: (head + rest(c)).encode("utf-8"), after_frequency=data.frequency is not None
    )


def _item(data: ItemReport) -> bytes:
    name = data.name
    if not 3 <= len(name) <= 9 or not _util.is_printable_ascii(name) or "!" in name or "_" in name:
        raise _refuse(f"item name {name!r} is not 3-9 printable characters without ! or _")
    head = ")" + name + ("_" if data.killed else "!")
    rest = _position_body(data)
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
    try:
        return _mic_e_destination(data)
    except EncodeError:
        raise
    except (ValueError, OverflowError) as e:
        raise _refuse(f"cannot encode the Mic-E destination: {e}") from e


def _mic_e_destination(data: MicEReport) -> str:
    if data.mic_e_message not in _MESSAGE_BITS:
        raise _refuse("a Mic-E message that mixes standard and custom bits has no defined meaning")
    if not -90 <= data.latitude <= 90 or not -180 <= data.longitude <= 180:
        raise _refuse("latitude or longitude out of range")
    if not 0 <= data.ambiguity <= 4:
        raise _refuse(f"ambiguity {data.ambiguity} is not 0-4")
    _, _, lat_units, lon_units = _dao_digits(data)
    if lat_units > 90 * 6000:
        raise _refuse("latitude out of range")
    deg, rem = divmod(lat_units, 6000)
    digits = f"{deg:02d}{rem // 100:02d}{rem % 100:02d}"
    if data.ambiguity and deg == 90:
        raise _refuse("an ambiguous latitude of 90 degrees would be centred past the pole")
    if data.ambiguity:
        digits = digits[: 6 - data.ambiguity] + " " * data.ambiguity
    kind, bits = _MESSAGE_BITS[data.mic_e_message]
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
        raise _refuse("destination SSID is not 0-15")
    return f"{call}-{ssid}" if ssid else call


def _mic_e_altitude(feet: float) -> str | None:
    """The Mic-E ``xxx}`` altitude, or None when it would not read back exactly."""
    metres = round(feet / _util.FEET_PER_METRE)
    value = metres + 10000
    if not 0 <= value < 91**3:
        return None
    if not _util.number_equal(metres * _util.FEET_PER_METRE, feet):
        return None
    return _util.base91_text(value, 3) + "}"


_MIC_E_STATUS_START = "`'>] \x1d"
"""What Mic-E status text cannot start with: a device type code, or 0x1D (obsolete telemetry)."""


def _mic_e(data: MicEReport) -> bytes:
    _check_symbol(data)
    _check_text(data.comment, "comment")
    destination = mic_e_destination(data)
    if data.compressed or data.compression is not None:
        raise _refuse("a Mic-E report is not compressed")
    legacy = b""
    if data.legacy_telemetry:
        # A 255 would be taken for Kenwood 0xFF padding and removed on the way back in.
        if len(data.legacy_telemetry) != 5 or any(not 0 <= v <= 254 for v in data.legacy_telemetry):
            raise _refuse("obsolete Mic-E binary telemetry is 5 values, each 0-254")
        legacy = bytes([0x1D, *data.legacy_telemetry])
    if data.weather is not None or data.area is not None or data.df_bearing or data.storm or data.signpost:
        raise _refuse("a Mic-E report cannot carry weather, area, DF, storm or signpost data")
    a, o, _, lon_units = _dao_digits(data)
    deg, rem = divmod(lon_units, 6000)
    minutes, hundredths = divmod(rem, 100)
    if deg > 179:
        raise _refuse("longitude 180 has no Mic-E form")
    if deg < 10:
        d = deg + 90
    elif deg < 100:
        d = deg
    elif deg < 110:
        d = deg - 20
    else:
        d = deg - 100
    m = minutes + 60 if minutes < 10 else minutes
    speed = 0 if data.speed_knots is None else round(data.speed_knots)
    course = 0 if data.course_degrees is None else round(data.course_degrees)
    if not 0 <= speed <= 799:
        raise _refuse("Mic-E speed is 0-799 knots")
    if not 0 <= course <= 360:
        raise _refuse("Mic-E course is 0-360")
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
        raise _refuse(f"Mic-E type code {type_code!r} is not ` ' > ] or a space")
    suffix = data.device_suffix or ""
    if suffix:
        from .devices import mic_e_suffixes

        if suffix not in mic_e_suffixes(type_code):
            raise _refuse(f"device suffix {suffix!r} is not one the database knows after {type_code!r}")
    altitude_first = ""
    altitude_later = ""
    if data.altitude_feet is not None:
        mic = _mic_e_altitude(data.altitude_feet)
        if mic is not None:
            altitude_first = mic
        else:
            altitude_later = _altitude(data.altitude_feet)
    locator = ""
    if data.locator is not None:
        if not _util.is_locator(data.locator):
            raise _refuse(f"{data.locator!r} is not a Maidenhead locator")
        locator = data.locator.upper() + "/G"
    if sum(x is not None for x in (data.phg, data.range_miles, data.dfs)) > 1:
        raise _refuse("more than one data extension")
    ext = _phg_text(data) + _dfs_text(data)
    if data.range_miles is not None:
        ext = _range_text(data.range_miles)
    freq = "" if data.frequency is None else _frequency_text(data.frequency)
    if freq and ext and not altitude_later:
        freq = "/" + freq
    telemetry = _telemetry_text(data.telemetry)
    dao = _dao_text(data, a, o)

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

    return _with_comment(data, data.comment, build, destination, after_frequency=bool(freq))


# ---------------------------------------------------------------- messages


def _addressee(addressee: str) -> str:
    _check_address(addressee, "addressee")
    return ":" + addressee.ljust(9) + ":"


def _is_id(text: str) -> bool:
    return 1 <= len(text) <= 5 and text.isascii() and text.isalnum()


def _message_id(msg_id: str | None, reply_ack: str | None) -> str:
    if msg_id is None:
        if reply_ack is not None:
            raise _refuse("a reply-ack goes with a message ID")
        return ""
    if not _is_id(msg_id):
        raise _refuse(f"message ID {msg_id!r} is not 1-5 letters and digits")
    if reply_ack is None:
        return "{" + msg_id
    if reply_ack and not _is_id(reply_ack):
        raise _refuse(f"reply-ack {reply_ack!r} is not up to 5 letters and digits")
    return "{" + msg_id + "}" + reply_ack


def _message_text(text: str, *, limit: bool = True) -> None:
    _check_text(text, "message text")
    if "{" in text:
        raise _refuse("message text cannot contain {, which starts the message ID")
    if limit and len(text) > MESSAGE_TEXT_LIMIT:
        raise _refuse(f"message text is over {MESSAGE_TEXT_LIMIT} characters")


def _message(data: Message) -> bytes:
    _message_text(data.text)
    return _checked(data, _addressee(data.addressee) + data.text + _message_id(data.message_id, data.reply_ack))


def _ack(data: Ack | Reject) -> bytes:
    ident = data.acked_id if isinstance(data, Ack) else data.rejected_id
    if not _is_id(ident):
        raise _refuse(f"message ID {ident!r} is not 1-5 letters and digits")
    word = "ack" if isinstance(data, Ack) else "rej"
    text = _addressee(data.addressee) + word + ident
    if data.reply_ack is not None:
        if data.reply_ack and not _is_id(data.reply_ack):
            raise _refuse(f"reply-ack {data.reply_ack!r} is not up to 5 letters and digits")
        text += "}" + data.reply_ack
    return _checked(data, text)


def _bulletin(data: Bulletin) -> bytes:
    a = data.addressee
    if not (a.startswith("BLN") and 4 <= len(a) <= 9 and ("0" <= a[3] <= "9" or "A" <= a[3] <= "Z")):
        raise _refuse(f"bulletin addressee {a!r} is not BLN then a digit or an upper-case letter")
    if a[3].isalpha() and len(a) > 4:
        raise _refuse("a group bulletin's identifier is a digit")
    _message_text(data.text)
    return _checked(data, _addressee(a) + data.text + _message_id(data.message_id, None))


def _nws(data: NwsBulletin) -> bytes:
    if not data.addressee.startswith(("NWS-", "NWS_")):
        raise _refuse("an NWS bulletin's addressee starts NWS-")
    _message_text(data.text, limit=False)
    return _checked(data, _addressee(data.addressee) + data.text + _message_id(data.message_id, None))


def _metadata_list(items: tuple[str, ...], limit: int, what: str) -> str:
    if len(items) > limit:
        raise _refuse(f"{what} has at most {limit} entries")
    for item in items:
        _check_text(item, what)
        if "," in item or "{" in item:
            raise _refuse(f"{what} entries cannot contain , or {{")
    return ",".join(items)


def _telemetry_metadata(data: TelemetryNames | TelemetryUnits | TelemetryCoefficients | TelemetryBits) -> bytes:
    head = _addressee(data.addressee)
    if isinstance(data, TelemetryNames):
        body = "PARM." + _metadata_list(data.names, 13, "PARM.")
    elif isinstance(data, TelemetryUnits):
        body = "UNIT." + _metadata_list(data.units, 13, "UNIT.")
    elif isinstance(data, TelemetryCoefficients):
        if not 1 <= len(data.coefficients) <= 15:
            raise _refuse("EQNS. carries 1-15 coefficients")
        if not all(math.isfinite(v) for v in data.coefficients):
            raise _refuse("a coefficient is a finite number")
        texts = data.coefficients_text
        if len(texts) != len(data.coefficients) or any(
            not _same_number(t, v, _COEFFICIENT) for t, v in zip(texts, data.coefficients, strict=False)
        ):
            texts = tuple(_util.number_text(v) for v in data.coefficients)
        body = "EQNS." + ",".join(texts)
    else:
        if len(data.bits) != 8 or any(b not in "01" for b in data.bits):
            raise _refuse("BITS. needs eight 0/1 bits")
        if len(data.project) > _TELEMETRY_TITLE_LIMIT:
            raise _refuse(f"a telemetry project title is at most {_TELEMETRY_TITLE_LIMIT} characters")
        _check_text(data.project, "project title")
        if "{" in data.project:
            raise _refuse("the project title cannot contain {")
        body = "BITS." + data.bits + ("," + data.project if data.project else "")
    return _checked(data, head + body + _message_id(data.message_id, None))


_DEFINED_QUERIES = ("APRSD", "APRSH", "APRSM", "APRSO", "APRSP", "APRSS", "APRST", "PING?")


def _directed_query(data: DirectedQuery) -> bytes:
    qtype = data.query_type
    if qtype != "PING?" and (not qtype or not all("A" <= c <= "Z" for c in qtype)):
        raise _refuse(f"query type {qtype!r} is not upper-case letters")
    target = data.target or ""
    if target and (len(target) > 9 or not all(c.isascii() and (c.isalnum() or c == "-") for c in target)):
        raise _refuse(f"query target {target!r} is not a callsign")
    # a defined type's target goes straight after it, an APRSH one padded to 9 characters
    # (APRS12c 1.2 notes); any other type's after one space, since its length is not fixed
    if target and qtype == "APRSH":
        target = target.ljust(9)
    elif target and qtype not in _DEFINED_QUERIES:
        target = " " + target
    return _checked(data, _addressee(data.addressee) + "?" + qtype + target)


# ---------------------------------------------------------------- the rest


def _status(data: StatusReport) -> bytes:
    _check_text(data.text, "status text")
    text = ">"
    if data.timestamp is not None:
        _check_timestamp(data.timestamp, (TimestampKind.DHM_ZULU,), "status")
        if data.locator is not None:
            raise _refuse("a status report with a grid locator has no timestamp")
        text += data.timestamp.text
    if data.locator is not None:
        if not _util.is_locator(data.locator):
            raise _refuse(f"{data.locator!r} is not a Maidenhead locator")
        if data.symbol is None or not data.symbol.is_valid:
            raise _refuse("a grid locator status report needs a symbol")
        text += data.locator.upper() + str(data.symbol)
        if data.text or data.beam:
            text += " "
    elif data.symbol is not None:
        raise _refuse("a status report's symbol goes with a grid locator")
    text += data.text
    if data.beam is not None:
        b = data.beam
        if not ("0" <= b.heading_code <= "9" or "A" <= b.heading_code <= "Z") or not (
            "1" <= b.power_code <= "9" or ":" <= b.power_code <= "K"
        ):
            raise _refuse("beam heading or power code out of range")
        text += "^" + b.heading_code + b.power_code
    return _checked(data, text)


def _telemetry(data: TelemetryReport) -> bytes:
    seq = data.sequence
    if not seq or not (seq.isascii() and seq.isalnum()):
        raise _refuse("a telemetry sequence is letters and digits")
    if len(data.analog) != 5:
        raise _refuse("a telemetry report has five analog values")
    if data.bits is None or len(data.bits) != 8 or any(b not in "01" for b in data.bits):
        raise _refuse("a telemetry report has eight 0/1 bits")
    _check_text(data.comment, "comment")
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
    _check_timestamp(data.timestamp, (TimestampKind.MDHM,), "weather")
    if data.comment:
        raise _refuse("a weather report has no comment")
    return _checked(data, "_" + data.timestamp.text + _weather_text(data.weather, positionless=True, compressed=False))


def _raw_weather(data: RawWeather) -> bytes:
    if not _util.is_printable_ascii(data.data):
        raise _refuse("raw weather data is printable ASCII")
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
        raise _refuse("an NMEA sentence is printable ASCII")
    star = s.find("*")
    if star >= 0 and (star != len(s) - 3 or not all(c in "0123456789ABCDEFabcdef" for c in s[star + 1 :])):
        raise _refuse("a * in an NMEA sentence starts its checksum, *hh at the end")
    if data.has_checksum != (star >= 0):
        raise _refuse("has_checksum does not say whether the sentence ends with a *hh checksum")
    if star >= 0:
        got = 0
        for ch in s[:star]:
            got ^= ord(ch)
        if got != int(s[star + 1 :], 16):
            raise _refuse("the NMEA checksum does not match the sentence")
    _check_text(data.comment, "comment")
    if data.comment and not data.has_checksum:
        raise _refuse("a comment goes after the sentence's checksum")
    raw = ("$" + s).encode("ascii") + data.comment.encode("utf-8")
    if not _reads_back(data, raw, DEFAULT_DESTINATION, numbers=True):
        raise _refuse("the sentence does not read back as the same NMEA data")
    return raw


def _maidenhead(data: MaidenheadBeacon) -> bytes:
    if not _util.is_locator(data.locator):
        raise _refuse(f"{data.locator!r} is not a Maidenhead locator")
    _check_text(data.comment, "comment")
    return _checked(data, "[" + data.locator.upper() + "]" + data.comment)


def _query(data: Query) -> bytes:
    if not data.query_type or not all("A" <= c <= "Z" for c in data.query_type):
        raise _refuse("a query type is upper-case letters")
    text = "?" + data.query_type + "?"
    if data.footprint is not None:
        f = data.footprint
        if not 0 <= f.radius_miles <= 9999:
            raise _refuse("footprint radius is 0-9999 miles")
        if not (-90 <= f.latitude <= 90 and -180 <= f.longitude <= 180):
            raise _refuse("footprint latitude or longitude out of range")
        text += f" {_util.number_text(f.latitude)},{_util.number_text(f.longitude)},{f.radius_miles:04d}"
    return _checked(data, text)


def _capabilities(data: Capabilities) -> bytes:
    if not data.capabilities:
        raise _refuse("no capabilities")
    items = []
    for cap in data.capabilities:
        if not 1 <= len(cap) <= 2:
            raise _refuse("a capability is a token or a token and a value")
        token = cap[0]
        if not token or any(c in " =," or c < " " or c == "\x7f" for c in token):
            raise _refuse(f"capability token {token!r} is free text")
        if len(cap) == 2:
            value = cap[1]
            if any(c < " " or c == "\x7f" for c in value):
                raise _refuse("a capability value with a control character would read back as free text")
            if "," in value:
                raise _refuse("a capability value cannot contain a comma")
            if value != value.strip(" "):
                raise _refuse("spaces around a capability value are padding and would be dropped")
            items.append(f"{token}={value}")
        else:
            items.append(token)
    return _checked(data, "<" + ",".join(items))


_INNER_HEADER_DEFECTS = frozenset(
    {DiagnosticCode.EMPTY_DESTINATION, DiagnosticCode.EMPTY_PATH_ENTRY, DiagnosticCode.MULTIPLE_USED_MARKERS}
)


def _third_party(data: ThirdParty) -> bytes:
    from ._decode import _ADDRESS, _THIRD_PARTY_SOURCE

    inner = data.packet
    if any(d.code in _INNER_HEADER_DEFECTS for d in inner.diagnostics):
        # the defect is part of the data, and no clean header reproduces it
        raise _refuse("the third-party packet's inner header has a defect a clean header cannot carry")
    if not _THIRD_PARTY_SOURCE.match(inner.source):
        raise _refuse(f"third-party source {inner.source!r} is not 1-9 printable characters other than > and :")
    if inner.info or inner.data == Unrecognized(UnrecognizedReason.EMPTY):
        # the original information field must not be changed (APRS12c ch. 17), even when empty
        info = inner.info
        destination = inner.destination
    else:
        info = encode_info(inner.data)
        destination = mic_e_destination(inner.data) if isinstance(inner.data, MicEReport) else inner.destination
    if not _ADDRESS.match(destination) or any(not _ADDRESS.match(p.call) for p in inner.path):
        raise _refuse("a third-party destination or path entry is not 1-9 letters, digits or -")
    used = [p.used for p in inner.path]
    if used != sorted(used, reverse=True):
        raise _refuse("in TNC2 a path entry before a used one is used too")
    path = tnc2_path(inner.path)
    header = f"{inner.source}>{destination}" + ("," + path if path else "")
    return b"}" + header.encode("ascii") + b":" + info


def _user_defined(data: UserDefined) -> bytes:
    if len(data.user_id) != 1 or len(data.packet_type) != 1:
        raise _refuse("user ID and packet type are one character each")
    try:
        return ("{" + data.user_id + data.packet_type + data.data).encode("latin-1")
    except UnicodeEncodeError:
        raise _refuse("user-defined data is bytes: one character U+0000-U+00FF per byte") from None


def _test(data: TestData) -> bytes:
    _check_text(data.data, "test data")
    return _checked(data, "," + data.data)


def _agrelo(data: AgreloDf) -> bytes:
    if not 0 <= data.bearing_degrees <= 360 or not 0 <= data.quality <= 9:
        raise _refuse("an Agrelo bearing is 0-360 degrees and its quality one digit")
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
        raise _refuse(f"{type(data).__name__} cannot be encoded")
    try:
        return encoder(data)
    except EncodeError:
        raise
    except (ValueError, OverflowError) as e:
        # a value no packet can hold, such as a NaN latitude
        raise _refuse(f"cannot encode {type(data).__name__}: {e}") from e


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
    _check_address(source, "source")
    entries = tuple(p if isinstance(p, PathEntry) else PathEntry(p.rstrip("*"), p.endswith("*")) for p in path)
    for entry in entries:
        _check_address(entry.call, "path entry")
    if len(entries) > 8:
        raise _refuse("at most 8 digipeaters")
    if isinstance(data, MicEReport):
        destination = mic_e_destination(data)
    else:
        _check_address(destination, "destination")
    info = encode_info(data)
    return Packet(source, destination, entries, info, data)
