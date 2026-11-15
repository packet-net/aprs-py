"""Round 5, the read-back delta: a builder's empty message ID, a header fault before a data fault in
the form written, a frame's empty destination and a builder's Mic-E altitude."""

from __future__ import annotations

import pytest

import pdn_aprs as aprs


def test_a_builders_empty_message_id_is_invalid_not_missing() -> None:
    station = aprs.Station("N0CALL")
    for reply_ack in (None, "", "1"):
        with pytest.raises(aprs.EncodeError) as caught:
            station.message("N0CALL", "hi", message_id="", reply_ack=reply_ack)
        assert caught.value.code is aprs.RefusalCode.INVALID_MESSAGE_ID
    assert station.message("N0CALL", "hi").info == b":N0CALL   :hi"


def test_a_header_fault_comes_before_a_data_fault_in_the_form_written() -> None:
    station = aprs.Station("N0CALL", path=["WIDE1-1", "N0CALL-1*"])
    with pytest.raises(aprs.EncodeError) as caught:
        station.object("TOOLONGNAME", 1, 2, aprs.Symbol.CAR, timestamp=aprs.Timestamp.dhm(27, 9, 23))
    assert caught.value.code is aprs.RefusalCode.TNC2_CANNOT_CARRY
    assert caught.value.frame_code is aprs.RefusalCode.AX25_CANNOT_CARRY
    # a header only a frame cannot carry: the line's code is the data's
    with pytest.raises(aprs.EncodeError) as caught:
        aprs.Station("N0CALL", path="QAR123456").object(
            "TOOLONGNAME", 1, 2, aprs.Symbol.CAR, timestamp=aprs.Timestamp.dhm(27, 9, 23)
        )
    assert caught.value.code is aprs.RefusalCode.INVALID_NAME
    assert caught.value.frame_code is aprs.RefusalCode.AX25_CANNOT_CARRY


def test_an_empty_destination_is_written_as_six_spaces_in_a_frame() -> None:
    packet = aprs.decode_tnc2(b"N0CALL>:>x")
    assert packet.destination == ""
    assert packet.to_tnc2() == b"N0CALL>:>x"
    frame = packet.to_ax25()
    assert frame[:7] == bytes([0x40] * 6 + [0xE0])
    assert aprs.decode_ax25(frame).destination == ""


def test_a_builders_mic_e_altitude_in_whole_feet_goes_in_the_bytes_first() -> None:
    station = aprs.Station("N0CALL")
    assert station.mic_e(51.5, -0.5, aprs.Symbol.CAR, altitude_feet=1000).info.endswith(b"}")
    with_comment = station.mic_e(51.5, -0.5, aprs.Symbol.CAR, altitude_feet=1000, comment="/A=001234 x")
    assert b"/A=001000//A=001234 x" in with_comment.info
