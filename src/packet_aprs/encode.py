"""Encoding (stub)."""

from __future__ import annotations

from .errors import EncodeError
from .model import AprsData, MicEReport


def encode_info(data: AprsData) -> bytes:
    raise EncodeError("not implemented")


def mic_e_destination(data: MicEReport) -> str:
    raise EncodeError("not implemented")
