"""Round 5, final pass: a later Mic-E altitude never uses the bytes of a whole ``/A=``, and a long
run of candidate elements is decoded in linear time."""

from __future__ import annotations

import time

import pytest

import pdn_aprs as aprs


def _mic_e(status: str, options: aprs.ParseOptions | None = None) -> aprs.MicEReport:
    line = 'N0CALL>S32UVT:`(_fn"Oj/>' + status
    packet = aprs.decode_tnc2(line, options) if options is not None else aprs.decode_tnc2(line)
    assert isinstance(packet.data, aprs.MicEReport)
    return packet.data


@pytest.mark.parametrize("options", [None, aprs.ParseOptions.strict()], ids=["lenient", "strict"])
@pytest.mark.parametrize(
    ("status", "feet", "comment"),
    [
        ("x/A=000100}", 100, "x}"),
        ("/A=000100}", 100, "}"),
        ("x/A=-00016}y", -16, "x}y"),
        ("/A=000100}/A=000200}", 100, "}/A=000200}"),
    ],
)
def test_a_whole_altitude_protects_its_bytes_from_a_later_mic_e_altitude(
    options: aprs.ParseOptions | None, status: str, feet: float, comment: str
) -> None:
    data = _mic_e(status, options)
    assert data.altitude_feet == feet
    assert data.comment == comment


def test_a_later_mic_e_altitude_clear_of_the_altitude_is_still_lifted() -> None:
    data = _mic_e('x/A=000100}y"4e}z')
    assert data.altitude_feet == 100
    assert data.comment == "x}yz"
    assert [d.code for d in aprs.decode_tnc2('N0CALL>S32UVT:`(_fn"Oj/>x/A=000100}y"4e}z').diagnostics] == [
        aprs.DiagnosticCode.MIC_E_ALTITUDE_NOT_FIRST
    ]


def test_a_five_digit_altitude_protects_nothing() -> None:
    # not whole, so it is text, and its bytes are a later Mic-E altitude (lenient); strict reads text
    data = _mic_e("x/A=00100}")
    assert data.altitude_feet == pytest.approx(406417.32283464563)
    assert data.comment == "x/A=00"
    strict = _mic_e("x/A=00100}", aprs.ParseOptions.strict())
    assert strict.altitude_feet is None
    assert strict.comment == "x/A=00100}"


def test_a_comment_after_an_altitude_that_looks_like_an_altitude_is_written_straight_on() -> None:
    report = _mic_e("/A=000100x}")
    assert report.altitude_feet == 100
    assert report.comment == "x}"
    packet = aprs.build_packet("N0CALL", report)
    assert packet.info.endswith(b"/A=000100x}")


# ------------------------------------------------------------------ hostile input stays linear

_ELEMENTS = ["{", "PHG1", "|!!|", "/A=000001", "/A=000001}", "!W12!", '"4e}', "{5}"]
_SMALL, _LARGE = 25_000, 100_000
_POSITION = "!4903.50N/07201.75W-"
_SIGNPOST = "!4903.50N\\07201.75Wm"
_MIC_E = '`(_fn"Oj/>'


def _best(raw: bytes, options: aprs.ParseOptions) -> float:
    best = float("inf")
    for _ in range(3):
        started = time.perf_counter()
        aprs.decode_tnc2(raw, options)
        best = min(best, time.perf_counter() - started)
    return best


@pytest.mark.parametrize("element", _ELEMENTS)
@pytest.mark.parametrize("prefix", [_POSITION, _SIGNPOST, _MIC_E], ids=["position", "signpost", "mic-e"])
@pytest.mark.parametrize("options", [aprs.ParseOptions(), aprs.ParseOptions.strict()], ids=["lenient", "strict"])
def test_decoding_time_grows_in_proportion_to_the_comment(
    element: str, prefix: str, options: aprs.ParseOptions
) -> None:
    destination = "S32UVT" if prefix is _MIC_E else "APRS"

    def packet(size: int) -> bytes:
        comment = (element * (size // len(element) + 1))[:size]
        return f"N0CALL>{destination}:{prefix}{comment}".encode()

    small, large = _best(packet(_SMALL), options), _best(packet(_LARGE), options)
    # four times the text: a linear decoder takes about four times as long, a quadratic one sixteen
    assert large < max(small, 0.004) * 9, f"{element!r}: {small:.4f} s at {_SMALL}, {large:.4f} s at {_LARGE}"


@pytest.mark.parametrize("comment", ["/x}", "/=}", "/{}WX"])
def test_a_comment_starting_with_a_slash_after_an_altitude_is_written_after_a_space(comment: str) -> None:
    report = aprs.MicEReport(
        latitude=33.427333,
        longitude=-112.129,
        symbol=aprs.Symbol("/", "j"),
        course_degrees=251,
        speed_knots=20,
        mic_e_message="returning",
        type_code=">",
        altitude_feet=123,
        comment=comment,
    )
    info = aprs.encode_info(report)
    assert info.decode().endswith("/A=000123 " + comment)
    back = aprs.decode_tnc2("N0CALL>S32UVT:" + info.decode()).data
    assert isinstance(back, aprs.MicEReport)
    assert back.comment == comment
    assert back.altitude_feet == 123
