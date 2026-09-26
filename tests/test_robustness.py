"""Robustness: mutated packets never crash the decoder or the encoder.

The vectors' information fields are mutated at random (with a fixed seed, so the test is
repeatable): the decoder may only raise HeaderError, and the encoder only EncodeError.
"""

from __future__ import annotations

import random

import pytest
from conformance import VECTORS, load_cases, raw_info

import packet_aprs as aprs

if not (VECTORS / "cases").is_dir():
    pytest.skip("the vectors submodule is not checked out", allow_module_level=True)

ALPHABET = bytes(range(0x20, 0x7F)) + b"\r\n\t\x00\x1c\x1d\x7f\x85\xa0\xb0\xb2\xb9\xc0\xdb\xff"


def _seeds() -> list[tuple[str, bytes]]:
    seeds = []
    for case in load_cases():
        if "encode" in case["input"] or "header_error" in case["expect"]:
            continue
        info, _, destination = raw_info(case)
        seeds.append((destination, info))
    return seeds


def _mutate(rng: random.Random, info: bytes) -> bytes:
    b = bytearray(info)
    for _ in range(rng.randint(1, 4)):
        roll = rng.random()
        pos = rng.randint(0, len(b)) if b else 0
        if roll < 0.4 and b:
            b[min(pos, len(b) - 1)] = rng.choice(ALPHABET)
        elif roll < 0.7:
            b[pos:pos] = bytes([rng.choice(ALPHABET)])
        elif b:
            del b[min(pos, len(b) - 1)]
    if rng.random() < 0.2:
        b = b[: rng.randint(0, len(b))]
    return bytes(b)


@pytest.mark.parametrize("seed", range(4))
def test_mutated_packets_do_not_crash(seed: int) -> None:
    rng = random.Random(seed)
    seeds = _seeds()
    for _ in range(1500):
        destination, info = rng.choice(seeds)
        line = f"N0CALL>{destination}:".encode() + _mutate(rng, info)
        for options in (aprs.ParseOptions.lenient(), aprs.ParseOptions.strict()):
            try:
                packet = aprs.decode(line, options)
            except aprs.HeaderError:
                continue
            try:
                aprs.encode_info(packet.data)
                if isinstance(packet.data, aprs.MicEReport):
                    aprs.mic_e_destination(packet.data)
            except aprs.EncodeError:
                pass
