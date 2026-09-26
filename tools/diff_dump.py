#!/usr/bin/env python3
"""Differential dump: decode every line of a capture and write what was made of it, in the form
the conformance vectors' ``tools/compare.py`` reads.

  python3 tools/diff_dump.py lines.hex.gz py.jsonl.gz [--jobs N] [--limit N]

``lines.hex.gz`` holds one hex-encoded TNC2 line per line (packet.net's ``aprs-corpus diff
lines`` writes it). Each output line is

  {"n": 0, "lenient": R, "strict": R, "reencode": "identical|equivalent|refused|fails|none"}

where R is ``{"header", "data", "diagnostics"}`` in the vectors' neutral form, or
``{"header_error": [...]}``; ``reencode`` says how the lenient data encodes again. The work is
spread over processes; the output keeps the input's order.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from collections.abc import Iterator
from multiprocessing import Pool
from typing import Any

from pdn_aprs import EncodeError, HeaderError, MicEReport, Packet, ParseOptions, Unrecognized, decode_tnc2
from pdn_aprs.encode import encode_info, mic_e_destination
from pdn_aprs.neutral import packet_to_neutral, to_neutral

LENIENT = ParseOptions.lenient()
STRICT = ParseOptions.strict()


def _number_equal(a: float, b: float) -> bool:
    scale = max(abs(a), abs(b))
    return abs(a - b) <= 1e-9 * (scale if scale >= 1 else 1)


def same(a: Any, b: Any) -> bool:
    """Equal by the vectors' rules: exact keys, numbers within 1e-9."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return _number_equal(a, b)
    return bool(a == b)


def result(line: bytes, options: ParseOptions) -> tuple[dict[str, Any], Packet | None]:
    try:
        packet = decode_tnc2(line, options)
    except HeaderError as e:
        return {"header_error": [str(d) for d in e.diagnostics]}, None
    return packet_to_neutral(packet), packet


def reencode(packet: Packet | None) -> str:
    if packet is None or isinstance(packet.data, Unrecognized):
        return "none"
    data = packet.data
    try:
        info = encode_info(data)
        destination = mic_e_destination(data) if isinstance(data, MicEReport) else packet.destination
    except EncodeError:
        return "refused"
    if info == packet.info.rstrip(b"\r\n") and destination == packet.destination:
        return "identical"
    try:
        again = decode_tnc2(f"{packet.source}>{destination}".encode("ascii") + b":" + info, LENIENT)
    except HeaderError:
        return "fails"
    if any(d.severity.value != "info" for d in again.diagnostics):
        return "fails"
    return "equivalent" if same(to_neutral(data), to_neutral(again.data)) else "fails"


def dump_line(n: int, hex_line: str) -> str:
    line = bytes.fromhex(hex_line)
    try:
        lenient, packet = result(line, LENIENT)
        strict, _ = result(line, STRICT)
        how = reencode(packet)
    except Exception as e:  # a crash is a bug: record it so the comparison shows it
        print(f"line {n}: {type(e).__name__}: {e}", file=sys.stderr)
        crash = {"header_error": [f"error:crash-{type(e).__name__}"]}
        return json.dumps({"n": n, "lenient": crash, "strict": crash, "reencode": "none"})
    record = {"n": n, "lenient": lenient, "strict": strict, "reencode": how}
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def dump_chunk(chunk: tuple[int, list[str]]) -> list[str]:
    start, lines = chunk
    return [dump_line(start + i, h) for i, h in enumerate(lines)]


def chunks(path: str, size: int, limit: int | None) -> Iterator[tuple[int, list[str]]]:
    with gzip.open(path, "rt", encoding="ascii") as f:
        batch: list[str] = []
        start = 0
        for n, raw in enumerate(f):
            if limit is not None and n >= limit:
                break
            batch.append(raw.strip())
            if len(batch) == size:
                yield start, batch
                start += size
                batch = []
        if batch:
            yield start, batch


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("lines")
    ap.add_argument("out")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--chunk", type=int, default=5000)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    started = time.monotonic()
    count = 0
    with gzip.open(args.out, "wt", encoding="utf-8", compresslevel=3) as out, Pool(args.jobs) as pool:
        for records in pool.imap(dump_chunk, chunks(args.lines, args.chunk, args.limit), chunksize=1):
            out.write("\n".join(records))
            out.write("\n")
            count += len(records)
            if count % 500_000 < args.chunk:
                rate = count / (time.monotonic() - started)
                print(f"{count:,} lines, {rate:,.0f}/s", file=sys.stderr)
    print(f"{count:,} lines in {time.monotonic() - started:,.0f} s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
