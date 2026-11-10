"""Small helpers shared by the decoder and the encoder."""

from __future__ import annotations

import math
import re
from decimal import Decimal
from fractions import Fraction

KNOTS_TO_MPH = 1852 / 1609.344
"""Miles per hour in a knot: a nautical mile is 1852 m, a statute mile 1609.344 m."""

FEET_PER_METRE = 1 / 0.3048

KMH_PER_KNOT = 1.852
"""Kilometres per hour in a knot: a nautical mile is exactly 1852 m."""

MM_PER_INCH = 25.4

BASE91_MIN = 33
BASE91_MAX = 123

_LOCATOR6 = re.compile(r"[A-Ra-r]{2}[0-9]{2}[A-Xa-x]{2}\Z")
_LOCATOR4 = re.compile(r"[A-Ra-r]{2}[0-9]{2}\Z")


def is_base91(text: str) -> bool:
    """True when every character is a base-91 digit (``!`` to ``{``)."""
    return all(BASE91_MIN <= ord(c) <= BASE91_MAX for c in text)


def base91_value(text: str) -> int:
    value = 0
    for c in text:
        value = value * 91 + ord(c) - BASE91_MIN
    return value


def base91_text(value: int, width: int) -> str:
    """``value`` as ``width`` base-91 digits. The caller checks it fits."""
    chars = []
    for _ in range(width):
        value, digit = divmod(value, 91)
        chars.append(chr(digit + BASE91_MIN))
    return "".join(reversed(chars))


def is_locator(text: str) -> bool:
    """True for a 4- or 6-character Maidenhead locator (either case)."""
    return bool(_LOCATOR6.match(text) or _LOCATOR4.match(text))


def is_locator6(text: str) -> bool:
    return bool(_LOCATOR6.match(text))


def is_locator4(text: str) -> bool:
    return bool(_LOCATOR4.match(text))


def is_printable_ascii(text: str) -> bool:
    """True when every character is printable ASCII, space included."""
    return all(" " <= c <= "~" for c in text)


def is_symbol_table(c: str) -> bool:
    return c == "/" or c == "\\" or "0" <= c <= "9" or "A" <= c <= "Z"


def is_symbol_code(c: str) -> bool:
    return "!" <= c <= "~"


def utf8_or_latin1(text: str) -> tuple[str, bool]:
    """Read a field held one character per byte as UTF-8, or as Latin-1 when it is not UTF-8.

    Returns the text and whether it was UTF-8.
    """
    if text.isascii():
        return text, True
    raw = text.encode("latin-1")
    try:
        return raw.decode("utf-8"), True
    except UnicodeDecodeError:
        return text, False


def number_text(value: float) -> str:
    """A number as the shortest decimal text that reads back as it, with no exponent, no ``+``,
    a leading ``0`` before a point and no trailing ``.0``: ``5.2``, ``-32``, ``0.53``, ``190``,
    and 1e61 as ``1`` and 61 zeros (vectors ruling F11)."""
    if isinstance(value, int):
        return str(value)
    text = format(Decimal(repr(float(value))), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text


def decimal(value: float) -> Decimal:
    """``value`` as the decimal number its shortest text says (``1.69475``, not the binary
    fraction just below it), so that a value written as a half rounds as a half, and the step a
    value rounds to does not depend on how floating point rounds on the way."""
    return Decimal(repr(float(value)))


HALF_TOLERANCE = 1e-6
"""How close to a step's half, in steps, a value is taken as the half (vectors ruling F2)."""


def round_half_away(value: float | Decimal | Fraction) -> int:
    """``value``, a number of steps, rounded to the nearest whole step, halves away from zero
    (2.5 to 3, -2.5 to -3), as the vectors' rule F2 rounds every field.

    The value is the binary floating-point number computed from the data, and one within 1e-6 of
    a half is the half: the half the decimal text means then wins although its binary value lies
    a few ulps either side (986.9499999999999 tenths is 9869.5, written 9870). Python's ``round``
    takes halves to the even number instead."""
    x = float(value)
    magnitude = abs(x)
    whole = math.floor(magnitude)
    if magnitude - whole >= 0.5 - HALF_TOLERANCE:
        whole += 1
    return -whole if x < 0 else whole


def number_equal(a: float, b: float) -> bool:
    """Equal within 1e-9, relative to the larger magnitude (absolute below 1)."""
    scale = max(abs(a), abs(b))
    return abs(a - b) <= 1e-9 * (scale if scale >= 1 else 1)
