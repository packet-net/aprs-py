"""Data extensions, and the structured elements lifted out of a comment.

The elements are lifted in this order, so that one is not taken for another: base-91
telemetry (between the last two ``|``) and a ``!DAO!`` (the last one outside it); a ``/A=``
altitude anywhere; signpost or corridor braces; a data extension later in the text, only when
none came straight after the symbol; a voice frequency at the start. Last, one leading space or
``/`` is dropped from what is left.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import _util
from .diagnostics import DiagnosticCode
from .model import (
    AreaColor,
    AreaObject,
    AreaShape,
    CommentTelemetry,
    Dao,
    DaoPrecision,
    DfBearing,
    Dfs,
    Phg,
    Storm,
    StormType,
    ToneType,
    VoiceFrequency,
)
from .symbols import Symbol

if TYPE_CHECKING:
    from ._decode import Ctx

C = DiagnosticCode

_PHG = re.compile(r"PHG([0-9])([0-~])([0-9])([0-9])(?:([1-9A-Z])/)?")
_RNG = re.compile(r"RNG([0-9]{4})")
_DFS = re.compile(r"DFS([0-9])([0-~])([0-9])([0-9])")
_CSE_SPD = re.compile(r"([0-9]{3}|\.\.\.|   )/([0-9]{3}|\.\.\.|   )")
_AREA = re.compile(r"([0-9])([0-9 ]{2})(/[0-9]|1[0-5])([0-9 ]{2})")
_DF = re.compile(r"/([0-9]{3})/([0-9])([0-9])([0-9])")
_STORM = re.compile(r"/(TS|HC|TD)/([0-9. ]{3})\^([0-9. ]{3})/([0-9. ]{4})>([0-9. ]{3})&([0-9. ]{3})(?:%([0-9. ]{3}))?")
_ALTITUDE = re.compile(r"/A=(-[0-9]{5}|[0-9]{6})")
_BRACES = re.compile(r"\{([^{}]{1,3})\}")
"""Signpost or corridor braces: the first ``{`` followed by 1-3 characters and a ``}``, wherever
it is. A signpost's characters are printable ASCII (vectors interpretations.md, "Signpost
overlays are printable ASCII"), and a corridor's are digits."""

_FREQ_KHZ = re.compile(r"([0-9A-O][0-9]{2}\.[0-9]{3})[Mm][Hh][Zz]")
_FREQ_10KHZ = re.compile(r"([0-9A-O][0-9]{2}\.[0-9]{2}) [Mm][Hh][Zz]")
_TONE = re.compile(r"([TtCcDd])([0-9]{3})|([Tt])off|([1l])750")
_OFFSET = re.compile(r"([+-])([0-9]{3})")
_RANGE = re.compile(r"R([0-9]{2})([mk])")

MICROWAVE_BASE = {
    "A": 1200,
    "B": 2300,
    "C": 2400,
    "D": 3400,
    "E": 5600,
    "F": 5700,
    "G": 5800,
    "H": 10100,
    "I": 10200,
    "J": 10300,
    "K": 10400,
    "L": 10500,
    "M": 24000,
    "N": 24100,
    "O": 24200,
}


def _height(ch: str) -> int:
    return ord(ch) - ord("0")


def _phg(m: re.Match[str]) -> Phg:
    rate = m.group(5)
    per_hour = None
    if rate is not None:
        per_hour = int(rate) if rate.isdigit() else ord(rate) - ord("A") + 10
    return Phg(int(m.group(1)), _height(m.group(2)), int(m.group(3)), int(m.group(4)), per_hour)


def _dfs(m: re.Match[str]) -> Dfs:
    return Dfs(int(m.group(1)), _height(m.group(2)), int(m.group(3)), int(m.group(4)))


def _opt_int(text: str | None) -> int | None:
    if text is None:
        return None
    t = text.strip(". ")
    if not t or not t.isdigit():
        return None
    return int(t)


def parse_extension(
    rest: str, symbol: Symbol, ctx: Ctx, *, mic_e: bool = False
) -> tuple[str, int, dict[str, Any]] | None:
    """A data extension at the start of ``rest``: its kind, length and fields."""
    if not mic_e:
        # only \l is an area object: with an overlay, l is an ordinary symbol (APRS12c ch. 11)
        if str(symbol) == "\\l":
            m = _AREA.match(rest)
            if m:
                color = m.group(3)
                color_code = int(color[1]) if color[0] == "/" else int(color)
                area = AreaObject(
                    list(AreaShape)[int(m.group(1))],
                    list(AreaColor)[color_code],
                    int(m.group(2).replace(" ", "0")),
                    int(m.group(4).replace(" ", "0")),
                )
                return "area", 7, {"area": area}
        m = _CSE_SPD.match(rest)
        if m:
            values: dict[str, Any] = {}
            course = _opt_int(m.group(1))
            speed = _opt_int(m.group(2))
            if course is not None:
                if course > 360:
                    ctx.defect(C.OUT_OF_RANGE_VALUE)
                else:
                    values["course_degrees"] = course
            if speed is not None:
                values["speed_knots"] = speed
            consumed = 7
            if str(symbol) == "/\\":
                df = _DF.match(rest, 7)
                if df:
                    bearing = int(df.group(1))
                    if bearing > 360:
                        # a bearing is degrees: the whole /BRG/NRQ goes, as an out-of-range course does
                        ctx.defect(C.OUT_OF_RANGE_VALUE)
                    else:
                        values["df_bearing"] = DfBearing(bearing, int(df.group(2)), int(df.group(3)), int(df.group(4)))
                    consumed = df.end()
            elif symbol.code == "@":
                st = _STORM.match(rest, 7)
                if st:
                    values["storm"] = Storm(
                        {"TS": StormType.TROPICAL_STORM, "HC": StormType.HURRICANE}.get(
                            st.group(1), StormType.TROPICAL_DEPRESSION
                        ),
                        _opt_int(st.group(2)),
                        _opt_int(st.group(3)),
                        _opt_int(st.group(4)),
                        _opt_int(st.group(5)),
                        _opt_int(st.group(6)),
                        _opt_int(st.group(7)),
                    )
                    consumed = st.end()
            return "course", consumed, values
    m = _PHG.match(rest)
    if m:
        return "phg", m.end(), {"phg": _phg(m)}
    m = _RNG.match(rest)
    if m:
        return "range", 7, {"range_miles": int(m.group(1))}
    m = _DFS.match(rest)
    if m:
        return "dfs", 7, {"dfs": _dfs(m)}
    return None


@dataclass
class CommentParts:
    """What a comment held: lifted fields, a DAO and its extra minutes, and the free text."""

    fields: dict[str, Any] = field(default_factory=dict)
    dao: Dao | None = None
    dao_lat: float = 0.0
    dao_lon: float = 0.0
    comment: str = ""
    altitude_feet: float | None = None


def _telemetry(text: str) -> tuple[CommentTelemetry, int, int] | None:
    """Base-91 telemetry between the last two ``|``: the telemetry and its span."""
    end = text.rfind("|")
    if end <= 0:
        return None
    start = text.rfind("|", 0, end)
    if start < 0:
        return None
    body = text[start + 1 : end]
    n = len(body)
    if n < 4 or n > 14 or n % 2 or not _util.is_base91(body):
        return None
    values = [_util.base91_value(body[i : i + 2]) for i in range(0, n, 2)]
    # eight binary channels; bits 9 to 13 are reserved (APRS12c ch. 13)
    digital = values[6] & 0xFF if len(values) == 7 else None
    return CommentTelemetry(values[0], tuple(values[1:6]), digital), start, end + 1


def _dao_at(text: str, i: int) -> tuple[Dao, float, float] | None:
    """The ``!DAO!`` at ``i``. A letter datum's case gives the precision of A and O; a digit
    datum has no case, so it is only read with spaces for them (vectors interpretations.md)."""
    if text[i] != "!" or text[i + 4] != "!":
        return None
    d, a, o = text[i + 1], text[i + 2], text[i + 3]
    if not (d.isascii() and d.isalnum()):
        return None
    if a == " " and o == " ":
        return Dao(d.upper(), DaoPrecision.NONE), 0.0, 0.0
    if "a" <= d <= "z":
        if not _util.is_base91(a + o):
            return None
        return (
            Dao(d.upper(), DaoPrecision.BASE91),
            (ord(a) - 33) / 91 * 0.01,
            (ord(o) - 33) / 91 * 0.01,
        )
    if not ("A" <= d <= "Z" and "0" <= a <= "9" and "0" <= o <= "9"):
        return None
    return Dao(d, DaoPrecision.THOUSANDTHS), int(a) * 0.001, int(o) * 0.001


def _last_dao(text: str, skip: tuple[int, int] | None, cuts: tuple[int, ...]) -> tuple[Dao, float, float, int] | None:
    """The last ``!DAO!``, five bytes as sent: not overlapping the ``skip`` span (the telemetry),
    and not across a cut, a place where other text was already taken out."""
    for i in range(len(text) - 5, -1, -1):
        if text[i] != "!":
            continue
        if skip is not None and i < skip[1] and i + 5 > skip[0]:
            continue
        if any(i < cut < i + 5 for cut in cuts):
            continue
        found = _dao_at(text, i)
        if found is not None:
            return (*found, i)
    return None


def _frequency(text: str) -> tuple[VoiceFrequency, int] | None:
    """A voice frequency at the start of ``text``, after at most one space or ``/``."""
    start = 1 if text[:1] in (" ", "/") else 0
    m = _FREQ_KHZ.match(text, start)
    ten_khz = False
    if not m:
        m = _FREQ_10KHZ.match(text, start)
        ten_khz = True
        if not m:
            return None
    digits = m.group(1)
    if digits[0] in MICROWAVE_BASE:
        mhz = MICROWAVE_BASE[digits[0]] + float(digits[1:])
    else:
        mhz = float(digits)
    values: dict[str, Any] = {"mhz": mhz, "ten_khz_resolution": ten_khz}
    i = m.end()

    def field_at(pattern: re.Pattern[str]) -> re.Match[str] | None:
        if text[i : i + 1] != " ":
            return None
        fm = pattern.match(text, i + 1)
        if fm and (fm.end() == len(text) or text[fm.end()] == " "):
            return fm
        return None

    tm = field_at(_TONE)
    if tm:
        if tm.group(1):
            letter = tm.group(1)
            values["tone"] = {"T": ToneType.TONE, "C": ToneType.CTCSS, "D": ToneType.DCS}[letter.upper()]
            values["tone_value"] = int(tm.group(2))
            values["narrow"] = letter.islower()
        elif tm.group(3):
            values["tone"] = ToneType.OFF
            values["narrow"] = tm.group(3) == "t"
        else:
            values["tone"] = ToneType.TONE_BURST
            values["narrow"] = tm.group(4) == "l"
        i = tm.end()
    om = field_at(_OFFSET)
    if om:
        sign = -1 if om.group(1) == "-" else 1
        values["offset_khz"] = sign * int(om.group(2)) * 10
        i = om.end()
    rm = field_at(_RANGE)
    if rm:
        values["range"] = int(rm.group(1))
        values["range_km"] = rm.group(2) == "k"
        i = rm.end()
    if text[i : i + 1] == " ":
        i += 1
    return VoiceFrequency(**values), i


def lift_comment(
    text: str,
    ctx: Ctx,
    *,
    symbol: Symbol | None,
    late_extensions: bool = True,
    area: object = None,
    cuts: tuple[int, ...] = (),
) -> CommentParts:
    """Lift the structured elements out of a comment; see the module docstring for the order.
    ``cuts``: places in ``text`` where something was already taken out, which no ``!DAO!``
    spans."""
    parts = CommentParts()
    text = lift_telemetry_dao(text, parts, cuts)
    text = _lift_rest(text, ctx, parts, symbol=symbol, late_extensions=late_extensions, area=area)
    if text[:1] in (" ", "/"):
        text = text[1:]
    parts.comment = text
    return parts


def lift_telemetry_dao(text: str, parts: CommentParts, cuts: tuple[int, ...] = ()) -> str:
    """Lift base-91 telemetry and a ``!DAO!`` into ``parts``; returns the text left.

    The telemetry is found first, and the DAO is the last one outside it, in the text as sent, so
    that taking the telemetry out never joins one.
    """
    tel = _telemetry(text) if "|" in text else None
    dao = _last_dao(text, None if tel is None else (tel[1], tel[2]), cuts) if "!" in text else None
    spans: list[tuple[int, int]] = []
    if tel is not None:
        parts.fields["telemetry"] = tel[0]
        spans.append((tel[1], tel[2]))
    if dao is not None:
        parts.dao, parts.dao_lat, parts.dao_lon, at = dao
        spans.append((at, at + 5))
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + text[end:]
    return text


def _lift_rest(
    text: str, ctx: Ctx, parts: CommentParts, *, symbol: Symbol | None, late_extensions: bool, area: object
) -> str:
    """Lift the altitude, braces, a late data extension and a voice frequency."""
    if "/A=" in text:
        m = _ALTITUDE.search(text)
        if m:
            value = int(m.group(1))
            parts.fields["altitude_feet"] = value
            parts.altitude_feet = value
            text = text[: m.start()] + text[m.end() :]
    if "{" in text and symbol is not None:
        # only \m is a signpost: with an overlay, m is an ordinary symbol (APRS12c ch. 11)
        is_signpost = str(symbol) == "\\m"
        is_line = isinstance(area, AreaObject) and area.shape in (
            AreaShape.LINE_DOWN_RIGHT,
            AreaShape.LINE_DOWN_LEFT,
        )
        m = _BRACES.search(text) if is_signpost or is_line else None
        if m is not None:
            content = m.group(1)
            if is_signpost and _util.is_printable_ascii(content):
                parts.fields["signpost"] = content
                text = text[: m.start()] + text[m.end() :]
            elif is_line and isinstance(area, AreaObject) and content.isascii() and content.isdigit():
                parts.fields["area"] = AreaObject(
                    area.shape, area.color, area.lat_offset, area.lon_offset, int(content)
                )
                text = text[: m.start()] + text[m.end() :]
    if late_extensions:
        late = _late_extension(text)
        if late is not None and ctx.tolerates(C.DATA_EXTENSION_IN_COMMENT):
            ctx.warn(C.DATA_EXTENSION_IN_COMMENT)
            key, late_value, start, end = late
            parts.fields[key] = late_value
            text = text[:start] + text[end:]
    freq = _frequency(text)
    if freq is not None:
        parts.fields["frequency"] = freq[0]
        text = text[freq[1] :]
    return text


def _late_extension(text: str) -> tuple[str, object, int, int] | None:
    """The first PHG anywhere, else the first RNG, else the first DFS."""
    if "PHG" in text:
        m = _PHG.search(text)
        if m:
            return "phg", _phg(m), m.start(), m.end()
    if "RNG" in text:
        m = _RNG.search(text)
        if m:
            return "range_miles", int(m.group(1)), m.start(), m.end()
    if "DFS" in text:
        m = _DFS.search(text)
        if m:
            return "dfs", _dfs(m), m.start(), m.end()
    return None
