"""The weather fields of a weather report (APRS12c ch. 12).

The fields are one contiguous run, which ends at the first thing that is not a field, at a
field letter seen before, and at ``c`` once the wind is known. What follows is the software
type and unit, or else ``weather-comment`` text.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .diagnostics import DiagnosticCode
from .model import WeatherExtra

if TYPE_CHECKING:
    from ._decode import Ctx

C = DiagnosticCode

_Convert = Callable[[int], object]

# letter: (field, width, conversion)
_FIELDS: dict[str, tuple[str, int, _Convert]] = {
    "c": ("wind_direction_degrees", 3, int),
    "g": ("wind_gust_mph", 3, int),
    "t": ("temperature_f", 3, int),
    "r": ("rain_1h_in", 3, lambda v: v / 100),
    "p": ("rain_24h_in", 3, lambda v: v / 100),
    "P": ("rain_midnight_in", 3, lambda v: v / 100),
    "h": ("humidity_percent", 2, lambda v: 100 if v == 0 else v),
    "b": ("pressure_mbar", 5, lambda v: v / 10),
    "L": ("luminosity_w_m2", 3, int),
    "l": ("luminosity_w_m2", 3, lambda v: v + 1000),
    "#": ("rain_raw", 3, int),
}
_WIND_SPEED: tuple[str, int, _Convert] = ("wind_speed_mph", 3, int)

_SOFTWARE_UNIT = re.compile(r"([A-Za-z])([A-Za-z0-9_-]{2,4})\Z")
_EXTRA = re.compile(r"[0-9.-]+")


@dataclass
class WeatherFields:
    values: dict[str, object] = field(default_factory=dict)
    text: str = ""
    wind_from_fields: bool = False


def _value_length(text: str, i: int, negative: bool) -> int:
    n = 0
    if negative and text[i : i + 1] == "-":
        n = 1
    while i + n < len(text) and "0" <= text[i + n] <= "9":
        n += 1
    if negative and n == 1 and text[i : i + 1] == "-":
        return 0
    return n


def parse_weather_fields(
    text: str, ctx: Ctx, *, positionless: bool, wind_known: bool, compressed: bool
) -> WeatherFields:
    result = WeatherFields()
    values = result.values
    seen: set[str] = set()
    extras: list[WeatherExtra] = []
    direction_sent = speed_sent = wind_known
    gust_sent = temperature_sent = False
    previous = ""
    i = 0
    n = len(text)
    while i < n:
        letter = text[i]
        if letter == "c" and (direction_sent or "c" in seen):
            break
        spec: tuple[str, int, _Convert] | None
        if letter == "s":
            if previous == "c" and not speed_sent:
                spec = _WIND_SPEED
            else:
                # snowfall keeps its fixed width: three digits (a decimal point allowed) or dots
                chunk = text[i + 1 : i + 4]
                if "snow_24h_in" in seen or len(chunk) != 3 or not re.fullmatch(r"[0-9.]{3}", chunk):
                    break
                seen.add("snow_24h_in")
                if chunk != "...":
                    try:
                        values["snow_24h_in"] = float(chunk)
                    except ValueError:
                        break
                i += 4
                previous = "s"
                continue
        else:
            spec = _FIELDS.get(letter)
        if spec is None:
            if not letter.isalpha() or not letter.isascii():
                break
            m = _EXTRA.match(text, i + 1)
            if not m or len(m.group()) < 2 or not m.group()[-1].isdigit() or letter in seen:
                break
            seen.add(letter)
            extras.append(WeatherExtra(letter, m.group()))
            i = m.end()
            previous = letter
            continue
        key, width, convert = spec
        if key in seen:
            break
        chunk = text[i + 1 : i + 1 + width]
        dots = 0
        while i + 1 + dots < n and text[i + 1 + dots] == ".":
            dots += 1
        if dots >= width or chunk == " " * width:
            value = None
            length = width
        elif dots:
            # an unknown value shorter than its width (b...)
            ctx.defect(C.NON_STANDARD_WEATHER_FIELD_WIDTH)
            value = None
            length = dots
        else:
            length = _value_length(text, i + 1, key == "temperature_f")
            if length == 0:
                break
            if length < width or length == width + 1:
                ctx.defect(C.NON_STANDARD_WEATHER_FIELD_WIDTH)
            elif length > width + 1:
                length = width
            value = int(text[i + 1 : i + 1 + length])
        if key == "wind_direction_degrees":
            if not positionless:
                ctx.defect(C.WIND_FIELDS_INSTEAD_OF_EXTENSION)
                result.wind_from_fields = True
            direction_sent = True
        elif key == "wind_speed_mph":
            speed_sent = True
        elif key == "wind_gust_mph":
            gust_sent = True
        elif key == "temperature_f":
            temperature_sent = True
        seen.add(key)
        if key == "luminosity_w_m2":
            seen.add(key)
        if value is not None:
            converted = convert(value)
            if key == "wind_direction_degrees" and value > 360:
                ctx.defect(C.OUT_OF_RANGE_VALUE)
            elif key == "humidity_percent" and value > 100:
                ctx.defect(C.OUT_OF_RANGE_VALUE)
            else:
                values[key] = converted
        i += 1 + length
        previous = letter
    if extras:
        values["extra"] = tuple(extras)
    if positionless:
        if not (direction_sent and speed_sent and gust_sent and temperature_sent):
            ctx.defect(C.INCOMPLETE_WEATHER)
    else:
        if not compressed and not (direction_sent and speed_sent):
            ctx.defect(C.INCOMPLETE_WEATHER)
        if not (gust_sent and temperature_sent):
            ctx.defect(C.INCOMPLETE_WEATHER)
    result.text = text[i:]
    return result


def weather_tail(rest: str, ctx: Ctx, values: dict[str, object]) -> str:
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
