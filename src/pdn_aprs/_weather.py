"""The weather fields of a weather report (APRS12c ch. 12).

The fields are one contiguous run, which ends at the first thing that is not a field, at a
defined field already read, and at ``c`` once the wind is known (vectors interpretations.md,
"Which weather field a letter is"). What follows is the software type and unit, or else
``weather-comment`` text.

The fields are read without raising their defects: the caller raises them in reading order,
after what it met before the fields (the wind, in a positioned report).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .diagnostics import DiagnosticCode
from .model import WeatherExtra

if TYPE_CHECKING:
    from ._decode import Ctx

C = DiagnosticCode

_Convert = Callable[[int], object]


def _scaled(value: int, divisor: int) -> float:
    """``value / divisor``, as an int when whole."""
    whole, rest = divmod(value, divisor)
    return whole if rest == 0 else value / divisor


# letter: (field, width, conversion)
_FIELDS: dict[str, tuple[str, int, _Convert]] = {
    "c": ("wind_direction_degrees", 3, int),
    "g": ("wind_gust_mph", 3, int),
    "t": ("temperature_f", 3, int),
    "r": ("rain_1h_in", 3, lambda v: _scaled(v, 100)),
    "p": ("rain_24h_in", 3, lambda v: _scaled(v, 100)),
    "P": ("rain_midnight_in", 3, lambda v: _scaled(v, 100)),
    "h": ("humidity_percent", 2, lambda v: 100 if v == 0 else v),
    "b": ("pressure_mbar", 5, lambda v: _scaled(v, 10)),
    "L": ("luminosity_w_m2", 3, int),
    "l": ("luminosity_w_m2", 3, lambda v: v + 1000),
    "#": ("rain_raw", 3, int),
}
_WIND_SPEED: tuple[str, int, _Convert] = ("wind_speed_mph", 3, int)
_SNOWFALL = "snow_24h_in"

_SOFTWARE_UNIT = re.compile(r"([A-Za-z])([A-Za-z0-9_-]{2,4})\Z")
_EXTRA = re.compile(r"[0-9.-]+")
_SNOW_VALUE = re.compile(r"[0-9.]{1,3}")


@dataclass
class WeatherFields:
    """What the fields held, the text after them, and their defects in reading order."""

    values: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    defects: list[DiagnosticCode] = field(default_factory=list)
    direction_sent: bool = False
    speed_sent: bool = False
    gust_sent: bool = False
    temperature_sent: bool = False
    wind_from_fields: bool = False
    """A ``c`` field was read: the wind came as fields."""


def _value_length(text: str, i: int, negative: bool) -> int:
    n = 0
    if negative and text[i : i + 1] == "-":
        n = 1
    while i + n < len(text) and "0" <= text[i + n] <= "9":
        n += 1
    if negative and n == 1 and text[i : i + 1] == "-":
        return 0
    return n


def _dots(text: str, i: int) -> int:
    n = 0
    while i + n < len(text) and text[i + n] == ".":
        n += 1
    return n


def parse_weather_fields(text: str, *, positionless: bool, wind_known: bool) -> WeatherFields:
    """The fields at the start of ``text``. ``wind_known``: the wind came before the fields (the
    ``DDD/SSS`` extension, or compressed cs bytes), so ``c`` ends them and ``s`` is snowfall.

    ``c`` is the wind direction until the direction is known, but only with a value after it.
    When the wind comes as fields (always in a positionless report; in a positioned one once a
    ``c`` field is read), ``s`` is the wind speed until the speed is known, and snowfall after
    that. Extra fields are a list, so a repeated extra letter does not end the run.
    """
    result = WeatherFields()
    values = result.values
    defects = result.defects
    seen: set[str] = set()
    extras: list[WeatherExtra] = []
    wind_as_fields = positionless
    result.direction_sent = result.speed_sent = wind_known
    i = 0
    n = len(text)
    while i < n:
        letter = text[i]
        spec: tuple[str, int, _Convert] | None
        if letter == "c":
            if result.direction_sent:
                break
            spec = _FIELDS["c"]
        elif letter == "s":
            if wind_as_fields and not result.speed_sent:
                spec = _WIND_SPEED
            else:
                # snowfall keeps its width: three characters, digits with at most one decimal
                # point, or dots. A value that holds a digit is a number, and only a run of dots
                # (unknown) may be shorter, with a width warning.
                if _SNOWFALL in seen:
                    break
                value_text = _SNOW_VALUE.match(text, i + 1)
                chunk = value_text.group() if value_text else ""
                if any("0" <= ch <= "9" for ch in chunk):
                    if len(chunk) != 3 or chunk.count(".") > 1:
                        break
                    values[_SNOWFALL] = float(chunk)
                elif len(chunk) < 3:
                    if not chunk:
                        break
                    defects.append(C.NON_STANDARD_WEATHER_FIELD_WIDTH)
                length = len(chunk)
                seen.add(_SNOWFALL)
                i += 1 + length
                continue
        else:
            spec = _FIELDS.get(letter)
        if spec is None:
            if not letter.isalpha() or not letter.isascii():
                break
            # a letter the spec does not define, and the whole run after it, ending in a digit
            m = _EXTRA.match(text, i + 1)
            if not m or len(m.group()) < 2 or not m.group()[-1].isdigit():
                break
            extras.append(WeatherExtra(letter, m.group()))
            i = m.end()
            continue
        key, width, convert = spec
        if key in seen:
            break
        chunk = text[i + 1 : i + 1 + width]
        dots = _dots(text, i + 1)
        if dots >= width or chunk == " " * width:
            value = None
            length = width
        elif dots:
            # an unknown value shorter than its width (b...)
            defects.append(C.NON_STANDARD_WEATHER_FIELD_WIDTH)
            value = None
            length = dots
        else:
            length = _value_length(text, i + 1, key == "temperature_f")
            if length == 0:
                break
            if length < width or length == width + 1:
                defects.append(C.NON_STANDARD_WEATHER_FIELD_WIDTH)
            elif length > width + 1:
                length = width
            value = int(text[i + 1 : i + 1 + length])
        if key == "wind_direction_degrees":
            result.direction_sent = True
            if not positionless:
                result.wind_from_fields = True
                wind_as_fields = True
        elif key == "wind_speed_mph":
            result.speed_sent = True
        elif key == "wind_gust_mph":
            result.gust_sent = True
        elif key == "temperature_f":
            result.temperature_sent = True
        seen.add(key)
        if value is not None:
            if (key == "wind_direction_degrees" and value > 360) or (key == "humidity_percent" and value > 100):
                defects.append(C.OUT_OF_RANGE_VALUE)
            else:
                values[key] = convert(value)
        i += 1 + length
    if extras:
        values["extra"] = tuple(extras)
    result.text = text[i:]
    return result


def raise_field_defects(result: WeatherFields, ctx: Ctx, *, positionless: bool) -> None:
    """The fields' defects in reading order, then ``incomplete-weather`` for the fields a report
    must have: in a positionless one ``c``, ``s``, ``g`` and ``t``; otherwise ``g`` and ``t``
    (the wind is judged where its extension belongs)."""
    for code in result.defects:
        ctx.defect(code)
    if positionless:
        if not (result.direction_sent and result.speed_sent and result.gust_sent and result.temperature_sent):
            ctx.defect(C.INCOMPLETE_WEATHER)
    elif not (result.gust_sent and result.temperature_sent):
        ctx.defect(C.INCOMPLETE_WEATHER)


def weather_tail(rest: str, ctx: Ctx, values: dict[str, Any]) -> str:
    """What follows the weather fields: the software type and unit, or else comment text
    (``weather-comment``), which is returned."""
    if not rest:
        return ""
    m = _SOFTWARE_UNIT.match(rest)
    if m and not m.group(2).isdigit():
        values["software"] = m.group(1)
        values["unit"] = m.group(2)
        return ""
    ctx.defect(C.WEATHER_COMMENT)
    return rest
