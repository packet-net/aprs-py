"""Data extensions, and the structured elements lifted out of a comment.

The elements are lifted in this order, so that one is not taken for another: base-91
telemetry (the last valid block between neighbouring ``|``) and a ``!DAO!`` (the last one outside it); a ``/A=``
altitude anywhere; signpost or corridor braces; a data extension later in the text, only when
none came straight after the symbol; a voice frequency at the start. Last, one leading space or
``/`` is dropped from what is left.

Lifting an element never joins the text either side of it. The comment is held as fragments (see
``Fragments``): each lift splits the fragment it came from, and every element is recognised
within one fragment, so nothing is read across a place something was lifted from. The one
exception is a lifted ``/A=``, which does not cut a voice frequency off from its fields.
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
_AREA = re.compile(r"([0-9])([0-9]{2})(/[0-9]|1[0-5])([0-9]{2})")
_DF = re.compile(r"/([0-9]{3})/([0-9])([0-9])([0-9])")
_STORM = re.compile(r"/(TS|HC|TD)/([0-9]{3})\^([0-9]{3})/([0-9]{4})>([0-9]{3})&([0-9]{3})(?:%([0-9]{3}))?")
_ALTITUDE = re.compile(r"/A=(-[0-9]{5}|[0-9]{6})")
_SIGNPOST = re.compile(r"\{([ -z|~]{1,3})\}")
"""Signpost braces: the first ``{``, 1-3 printable ASCII characters that are not braces, and ``}``,
wherever they are (vectors interpretations.md, "Signpost overlays are printable ASCII"). Braces
that do not qualify are comment text and do not stop the search."""
_CORRIDOR = re.compile(r"\{([0-9]{1,3})\}")
"""Corridor braces: the first ``{``, 1-3 digits and ``}``, wherever they are."""

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
                    int(m.group(2)),
                    int(m.group(4)),
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
                        int(st.group(2)),
                        int(st.group(3)),
                        int(st.group(4)),
                        int(st.group(5)),
                        int(st.group(6)),
                        int(st.group(7)) if st.group(7) is not None else None,
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


_PLAIN = "lifted"
_ALT = "altitude"


class Fragments:
    """The text of a comment as the fragments left between the places elements were lifted from.

    ``kinds[i]`` says what was lifted between ``texts[i]`` and ``texts[i + 1]``: ``_ALT`` for a
    ``/A=`` altitude, which a voice frequency reads across, ``_PLAIN`` for anything else. A
    fragment may be empty (two lifts side by side)."""

    __slots__ = ("kinds", "texts")

    def __init__(self, text: str, cuts: tuple[int, ...] = ()) -> None:
        self.texts: list[str] = []
        self.kinds: list[str] = []
        previous = 0
        for cut in sorted(cuts):
            self.texts.append(text[previous:cut])
            self.kinds.append(_PLAIN)
            previous = cut
        self.texts.append(text[previous:])

    def joined(self) -> str:
        """The text left, with nothing marking the places lifted from."""
        return "".join(self.texts)

    def lift(self, index: int, start: int, end: int, kind: str = _PLAIN) -> None:
        """Take ``start:end`` out of fragment ``index``, leaving two fragments."""
        text = self.texts[index]
        self.texts[index : index + 1] = [text[:start], text[end:]]
        self.kinds.insert(index, kind)

    def lift_span(self, start: int, end: int) -> None:
        """Take ``start:end`` (offsets in the text left) out of the one fragment that holds it."""
        base = 0
        for index, text in enumerate(self.texts):
            if base <= start and end <= base + len(text):
                self.lift(index, start - base, end - base)
                return
            base += len(text)

    def find(self, pattern: re.Pattern[str]) -> tuple[int, re.Match[str]] | None:
        """The first match of ``pattern``, searching each fragment in turn."""
        for index, text in enumerate(self.texts):
            m = pattern.search(text)
            if m:
                return index, m
        return None

    def drop_leading(self, chars: str) -> None:
        """Drop the first character of the text left when it is one of ``chars``."""
        for index, text in enumerate(self.texts):
            if text:
                if text[0] in chars:
                    self.texts[index] = text[1:]
                return

    def dropped_to(self, index: int, offset: int) -> str:
        """The text left from ``offset`` in fragment ``index`` onward."""
        return self.texts[index][offset:] + "".join(self.texts[index + 1 :])


def _telemetry(text: str, cuts: tuple[int, ...] = ()) -> tuple[CommentTelemetry, int, int] | None:
    """Base-91 telemetry: the last pair of neighbouring ``|`` (as sent) enclosing a valid block, 4 to
    14 bytes, an even number, each ``!`` to ``{``. The pairs slide: each ``|`` closes one pair and
    opens the next. Bars around anything else are text, with no diagnostic, and a pair a cut runs
    through does not stand whole, so it is no block. One backward pass: linear in the text."""
    end = text.rfind("|")
    while end > 0:
        start = text.rfind("|", 0, end)
        if start < 0:
            return None
        n = end - start - 1
        whole = not any(start < cut < end + 1 for cut in cuts)
        if 4 <= n <= 14 and not n % 2 and whole and _util.is_base91(text[start + 1 : end]):
            body = text[start + 1 : end]
            values = [_util.base91_value(body[i : i + 2]) for i in range(0, n, 2)]
            # eight binary channels; bits 9 to 13 are reserved (APRS12c ch. 13)
            digital = values[6] & 0xFF if len(values) == 7 else None
            return CommentTelemetry(values[0], tuple(values[1:6]), digital), start, end + 1
        end = start
    return None


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


def _frequency(frags: Fragments) -> tuple[VoiceFrequency, str] | None:
    """A voice frequency at the start of the text left, after at most one space or ``/``, with
    the text after it (and its fields, and one space) left over. The delimiter, judged on the text
    left, may be a piece of its own before a lifted element.

    The frequency stands whole in one fragment. A field (tone, offset, range) is a space and its
    value; it may stand after a lifted ``/A=`` (and only that: anything else lifted cuts the
    fields off), and it is complete at a space, the end of its fragment or any place something was
    lifted from."""
    texts, kinds = frags.texts, frags.kinds
    first = next((n for n, t in enumerate(texts) if t), None)
    if first is None:
        return None
    text = texts[first]
    start = 1 if text[:1] in (" ", "/") else 0
    if text in (" ", "/"):
        # the delimiter stands alone before a lifted element: the frequency starts the next
        # non-empty piece, and the delimiter goes with it
        nxt = next((n for n in range(first + 1, len(texts)) if texts[n]), None)
        if nxt is not None:
            first, text, start = nxt, texts[nxt], 0
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
    at = (first, m.end())

    def field_at(pattern: re.Pattern[str]) -> re.Match[str] | None:
        nonlocal at
        n, i = at
        while i == len(texts[n]) and n + 1 < len(texts) and kinds[n] == _ALT:
            n, i = n + 1, 0
        t = texts[n]
        if t[i : i + 1] != " ":
            return None
        fm = pattern.match(t, i + 1)
        if fm and (fm.end() == len(t) or t[fm.end()] == " "):
            at = (n, fm.end())
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
    om = field_at(_OFFSET)
    if om:
        sign = -1 if om.group(1) == "-" else 1
        values["offset_khz"] = sign * int(om.group(2)) * 10
    rm = field_at(_RANGE)
    if rm:
        values["range"] = int(rm.group(1))
        values["range_km"] = rm.group(2) == "k"
    rest = frags.dropped_to(*at)
    if rest[:1] == " ":
        rest = rest[1:]
    return VoiceFrequency(**values), rest


def lift_comment(
    text: str,
    ctx: Ctx,
    *,
    symbol: Symbol | None,
    late_extensions: bool = True,
    area: object = None,
    cuts: tuple[int, ...] = (),
    after_locator: bool = False,
) -> CommentParts:
    """Lift the structured elements out of a comment; see the module docstring for the order.
    ``cuts``: places in ``text`` where something was already taken out, which nothing is read
    across. ``after_locator``: the text follows a Mic-E locator with no space straight after it;
    the space is judged on what is left once telemetry and the ``!DAO!`` are lifted (a space
    there separates the locator and is not comment, text there is a missing space)."""
    parts = CommentParts()
    frags = lift_telemetry_dao(text, parts, cuts)
    if after_locator and frags.joined():
        if frags.joined()[0] == " ":
            frags.drop_leading(" ")
        else:
            ctx.defect(C.MISSING_SPACE_AFTER_LOCATOR)
    left = _lift_rest(frags, ctx, parts, symbol=symbol, late_extensions=late_extensions, area=area)
    if left[:1] in (" ", "/"):
        left = left[1:]
    parts.comment = left
    return parts


def trailing_lifted_start(text: str) -> int:
    """Where the first base-91 telemetry or ``!DAO!`` lifted from ``text`` starts (``len(text)``
    when none is): the end of a positioned weather report's weather text, wherever the element
    sits. What follows it is comment text on its own; taking the element out never joins the text
    either side of it."""
    tel = _telemetry(text) if "|" in text else None
    dao = _last_dao(text, None if tel is None else (tel[1], tel[2]), ()) if "!" in text else None
    starts = ([tel[1]] if tel is not None else []) + ([dao[3]] if dao is not None else [])
    return min(starts, default=len(text))


def lift_telemetry_dao(text: str, parts: CommentParts, cuts: tuple[int, ...] = ()) -> Fragments:
    """Lift base-91 telemetry and a ``!DAO!`` into ``parts``; returns the fragments left.

    The telemetry is found first, and the DAO is the last one outside it, in the text as sent
    (across no cut): taking the telemetry out never joins one.
    """
    tel = _telemetry(text, cuts) if "|" in text else None
    dao = _last_dao(text, None if tel is None else (tel[1], tel[2]), cuts) if "!" in text else None
    spans: list[tuple[int, int]] = []
    if tel is not None:
        parts.fields["telemetry"] = tel[0]
        spans.append((tel[1], tel[2]))
    if dao is not None:
        parts.dao, parts.dao_lat, parts.dao_lon, at = dao
        spans.append((at, at + 5))
    frags = Fragments(text, cuts)
    for start, end in sorted(spans, reverse=True):
        frags.lift_span(start, end)
    return frags


def _lift_rest(
    frags: Fragments, ctx: Ctx, parts: CommentParts, *, symbol: Symbol | None, late_extensions: bool, area: object
) -> str:
    """Lift the altitude, braces, a late data extension and a voice frequency; returns the text
    left."""
    found = frags.find(_ALTITUDE)
    if found:
        index, m = found
        value = int(m.group(1))
        parts.fields["altitude_feet"] = value
        parts.altitude_feet = value
        frags.lift(index, m.start(), m.end(), _ALT)
    if symbol is not None and any("{" in t for t in frags.texts):
        # only \m is a signpost: with an overlay, m is an ordinary symbol (APRS12c ch. 11)
        is_signpost = str(symbol) == "\\m"
        is_line = isinstance(area, AreaObject) and area.shape in (
            AreaShape.LINE_DOWN_RIGHT,
            AreaShape.LINE_DOWN_LEFT,
        )
        if is_signpost:
            found = frags.find(_SIGNPOST)
            if found:
                index, m = found
                parts.fields["signpost"] = m.group(1)
                frags.lift(index, m.start(), m.end())
        elif is_line and isinstance(area, AreaObject):
            found = frags.find(_CORRIDOR)
            if found:
                index, m = found
                parts.fields["area"] = AreaObject(
                    area.shape, area.color, area.lat_offset, area.lon_offset, int(m.group(1))
                )
                frags.lift(index, m.start(), m.end())
    if late_extensions:
        late = _late_extension(frags)
        if late is not None and ctx.tolerates(C.DATA_EXTENSION_IN_COMMENT):
            ctx.warn(C.DATA_EXTENSION_IN_COMMENT)
            index, key, late_value, start, end = late
            parts.fields[key] = late_value
            frags.lift(index, start, end)
    freq = _frequency(frags)
    if freq is not None:
        parts.fields["frequency"] = freq[0]
        return freq[1]
    return frags.joined()


def _late_extension(frags: Fragments) -> tuple[int, str, object, int, int] | None:
    """The first PHG anywhere, else the first RNG, else the first DFS, each whole in one
    fragment."""
    for word, pattern, key in (("PHG", _PHG, "phg"), ("RNG", _RNG, "range_miles"), ("DFS", _DFS, "dfs")):
        if not any(word in t for t in frags.texts):
            continue
        found = frags.find(pattern)
        if found:
            index, m = found
            value: object
            if key == "phg":
                value = _phg(m)
            elif key == "dfs":
                value = _dfs(m)
            else:
                value = int(m.group(1))
            return index, key, value, m.start(), m.end()
    return None
