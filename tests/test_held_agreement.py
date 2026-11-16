"""A held packet's data, header and information field must agree when it is written: every writer
decodes the held field under the header it writes and refuses ``not-encodable`` on any difference."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

import pdn_aprs as aprs
from pdn_aprs import EncodeError, RefusalCode

MIC_E_NEST = 'N0CALL>APRS:}Y>APRS:}X>S32U6T:`(_fn"Oj/]hi='


def _code(fn: Any, *args: Any) -> RefusalCode:
    with pytest.raises(EncodeError) as caught:
        fn(*args)
    return caught.value.code


def _retarget(destination: str) -> aprs.ThirdParty:
    """The two-deep nest with the innermost destination changed in place."""
    outer = aprs.decode_tnc2(MIC_E_NEST).data
    assert isinstance(outer, aprs.ThirdParty)
    middle = outer.packet.data
    assert isinstance(middle, aprs.ThirdParty)
    innermost = dataclasses.replace(middle.packet, destination=destination)
    return dataclasses.replace(
        outer, packet=dataclasses.replace(outer.packet, data=dataclasses.replace(middle, packet=innermost))
    )


@pytest.mark.parametrize("destination", ["APRS", "S32U6Q", "S32U6T-2"])
def test_an_inner_destination_changed_at_depth_two_is_not_encodable(destination: str) -> None:
    held = _retarget(destination)
    with pytest.raises(EncodeError) as caught:
        aprs.build_packet("N0CALL", held)
    assert caught.value.code is RefusalCode.NOT_ENCODABLE
    assert "disagree" in str(caught.value)


def test_an_inner_destination_unchanged_at_depth_two_is_written_as_received() -> None:
    assert aprs.build_packet("N0CALL", _retarget("S32U6T")).info == b'}Y>APRS:}X>S32U6T:`(_fn"Oj/]hi='


def test_an_inner_destination_changed_at_depth_one_is_not_encodable() -> None:
    outer = aprs.decode_tnc2('N0CALL>APRS:}Y>S32U6T:`(_fn"Oj/]hi=').data
    assert isinstance(outer, aprs.ThirdParty)
    held = dataclasses.replace(outer, packet=dataclasses.replace(outer.packet, destination="APRS"))
    assert _code(aprs.build_packet, "N0CALL", held) is RefusalCode.NOT_ENCODABLE


@pytest.mark.parametrize(
    ("line", "change"),
    [
        ("N0CALL>APRS:!4903.50N/07201.75W>hi", {"latitude": 10.0}),
        ("N0CALL>APRS:>hi", {"text": "ho"}),
        ("N0CALL>APRS:=4903.50N/07201.75W>hi", {"comment": "ho"}),
    ],
)
@pytest.mark.parametrize("writer", ["to_tnc2", "to_ax25", "to_kiss"])
def test_data_changed_in_place_no_longer_matches_the_field_and_every_writer_refuses(
    line: str, change: dict[str, Any], writer: str
) -> None:
    packet = aprs.decode_tnc2(line)
    held = dataclasses.replace(packet, data=dataclasses.replace(packet.data, **change))
    assert _code(getattr(held, writer)) is RefusalCode.NOT_ENCODABLE
    assert getattr(packet, writer)()


def test_changed_raw_bytes_no_longer_match_the_data() -> None:
    packet = aprs.decode_tnc2("N0CALL>APRS:>hi")
    held = dataclasses.replace(packet, info=b">ho")
    assert _code(held.to_tnc2) is RefusalCode.NOT_ENCODABLE
    assert _code(held.to_ax25) is RefusalCode.NOT_ENCODABLE


def test_a_decoded_position_is_compared_exactly_not_within_the_rounding() -> None:
    packet = aprs.decode_tnc2("N0CALL>APRS:!4903.50N/07201.75W>hi")
    nudged = dataclasses.replace(packet.data, latitude=packet.data.latitude + 1e-6)
    held = dataclasses.replace(packet, data=nudged)
    assert _code(held.to_tnc2) is RefusalCode.NOT_ENCODABLE


def test_a_built_packet_keeps_its_rounding_allowance_in_a_copy() -> None:
    data = aprs.PositionReport(latitude=51.45751234, longitude=-0.5, symbol=aprs.Symbol("/", ">"))
    built = aprs.build_packet("N0CALL", data)
    assert built.to_tnc2() == b"N0CALL>APZ001:!5127.45N/00030.00W>"
    assert dataclasses.replace(built, path=(aprs.PathEntry("WIDE1-1"),)).to_tnc2().startswith(b"N0CALL>APZ001,WIDE1-1")


def test_the_message_names_the_disagreement_not_a_mic_e_destination() -> None:
    packet = aprs.decode_tnc2("N0CALL>APRS:>hi")
    with pytest.raises(EncodeError, match="data and the information field disagree"):
        dataclasses.replace(packet, data=aprs.StatusReport(text="ho")).to_tnc2()


def test_a_bool_is_not_a_number_in_a_numeric_field() -> None:
    base = aprs.PositionReport(latitude=1.0, longitude=1.0, symbol=aprs.Symbol("/", ">"))
    for name in ("latitude", "longitude", "course_degrees", "speed_knots", "altitude_feet", "range_miles", "ambiguity"):
        for value in (True, False):
            assert _code(aprs.encode_info, dataclasses.replace(base, **{name: value})) is RefusalCode.NOT_A_NUMBER
    assert _code(aprs.encode_info, aprs.TelemetryReport("001", (1.0, True, 3.0, 4.0, 5.0), "00000000")) is (
        RefusalCode.NOT_A_NUMBER
    )
    # a bool where a bool belongs is fine
    assert aprs.encode_info(aprs.StatusReport(text="x")) == b">x"


def test_the_up_front_walk_names_a_non_finite_value_in_data_the_encoder_never_writes() -> None:
    """The inner packet is written from its held field, so no encoder meets its NaN: only the walk
    over the data names it, and says so (not the read-back's disagreement)."""
    outer = aprs.decode_tnc2("N0CALL>APRS:}Y>APRS:!4903.50N/07201.75W>hi").data
    assert isinstance(outer, aprs.ThirdParty)
    bad = dataclasses.replace(outer.packet, data=dataclasses.replace(outer.packet.data, latitude=float("nan")))
    with pytest.raises(EncodeError) as caught:
        aprs.build_packet("N0CALL", aprs.ThirdParty(bad))
    assert caught.value.code is RefusalCode.NOT_A_NUMBER
    assert str(caught.value) == "a value is not a finite number"


@pytest.mark.parametrize("destination", ["APRS", "S32U6Q", "S32U6T-2"])
def test_the_comparison_never_copies_a_decoded_destination_over_a_given_one(destination: str) -> None:
    """The read-back's own comparison, whatever checks come before it: a Mic-E inner packet whose
    destination was given as something else at depth two does not read back."""
    from pdn_aprs._neutral import to_neutral
    from pdn_aprs._readback import mismatch

    held = _retarget(destination)
    info = b'}Y>APRS:}X>S32U6T:`(_fn"Oj/]hi='
    assert mismatch(held, to_neutral(held), info, "APRS") is not None
    assert mismatch(_retarget("S32U6T"), to_neutral(_retarget("S32U6T")), info, "APRS") is None
