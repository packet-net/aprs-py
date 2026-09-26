"""Device identification from the aprs-deviceid database.

A Mic-E report names its device by the type code after the symbol and a suffix at the end of
the comment; any other packet by its destination address (the "tocall", ``APxxxx``). The
database is https://github.com/aprsorg/aprs-deviceid by Heikki Hannikainen, OH7LZB, under
CC BY-SA 2.0; ``DATABASE_VERSION`` says which commit this copy was generated from.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache, lru_cache
from typing import TYPE_CHECKING

from . import _deviceid_data as _db

if TYPE_CHECKING:
    from .packet import Packet

__all__ = ["DATABASE_VERSION", "Device", "identify", "identify_mic_e", "identify_tocall"]

DATABASE_VERSION: str = _db.VERSION


@dataclass(frozen=True, slots=True)
class Device:
    """A device or application from the database. Empty strings where it says nothing."""

    vendor: str
    model: str
    device_class: str = ""
    os: str = ""
    features: tuple[str, ...] = ()

    @property
    def class_description(self) -> str:
        """The device class as the database shows it, e.g. ``"HT"`` or ``"Mobile app"``."""
        return _db.CLASSES.get(self.device_class, "")

    def __str__(self) -> str:
        return " ".join(part for part in (self.vendor, self.model) if part)


def _device(entry: _db.Entry) -> Device:
    vendor, model, device_class, os, features = entry
    return Device(vendor, model, device_class, os, features)


@cache
def mic_e_suffixes(type_code: str) -> tuple[str, ...]:
    """The device suffixes the database knows after this Mic-E type code, longest first."""
    if type_code in ("`", "'"):
        suffixes = list(_db.MICE)
    elif type_code in (">", "]"):
        suffixes = [suffix for prefix, suffix in _db.MICE_LEGACY if prefix == type_code and suffix]
    else:
        return ()
    return tuple(sorted(suffixes, key=len, reverse=True))


def identify_mic_e(type_code: str | None, suffix: str | None) -> Device | None:
    """The device a Mic-E type code and device suffix identify."""
    if type_code in ("`", "'") and suffix:
        entry = _db.MICE.get(suffix)
        return _device(entry) if entry else None
    if type_code in (">", "]"):
        entry = _db.MICE_LEGACY.get((type_code, suffix or ""))
        return _device(entry) if entry else None
    return None


def _matches(pattern: str, call: str) -> bool:
    if pattern.endswith("*"):
        stem = pattern[:-1]
        return len(call) >= len(stem) and all(p in ("?", c) for p, c in zip(stem, call, strict=False))
    return len(pattern) == len(call) and all(p in ("?", c) for p, c in zip(pattern, call, strict=False))


@lru_cache(maxsize=4096)
def identify_tocall(destination: str) -> Device | None:
    """The device a destination address (tocall) identifies; the most specific match wins."""
    call = destination.partition("-")[0].upper()
    best: tuple[int, str] | None = None
    for pattern in _db.TOCALLS:
        if _matches(pattern, call):
            score = sum(1 for ch in pattern if ch not in "?*")
            if best is None or score > best[0]:
                best = (score, pattern)
    return _device(_db.TOCALLS[best[1]]) if best else None


def identify(packet: Packet) -> Device | None:
    """The device that sent a packet: by Mic-E type code and suffix, else by tocall."""
    from .model import MicEReport

    data = packet.data
    if isinstance(data, MicEReport):
        return identify_mic_e(data.type_code, data.device_suffix)
    return identify_tocall(packet.destination)
