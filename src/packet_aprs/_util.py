"""Small helpers shared by the decoder and the encoder."""

from __future__ import annotations

import re

KNOTS_TO_MPH = 1852 / 1609.344
"""Miles per hour in a knot: a nautical mile is 1852 m, a statute mile 1609.344 m."""

FEET_PER_METRE = 1 / 0.3048

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
    """A number as short decimal text: ``5.2``, ``-32``, ``0.53``."""
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        if isinstance(value, float) and abs(value) >= 1e16:
            return repr(value)
        return str(int(value))
    text = repr(float(value))
    if "e" in text or "E" in text:
        text = f"{value:.15f}".rstrip("0").rstrip(".")
    return text
