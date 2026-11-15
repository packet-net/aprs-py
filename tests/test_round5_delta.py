"""Round 5, the read-back delta: a builder's empty message ID, a data fault before a header the form cannot carry,
a frame's empty destination and a builder's Mic-E altitude."""

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


def test_a_data_fault_comes_before_a_header_the_form_cannot_carry() -> None:
    when = aprs.Timestamp.dhm(27, 9, 23)
    with pytest.raises(aprs.EncodeError) as caught:
        aprs.Station("N0CALL", path="QAR123456").object("TOOLONGNAME", 1, 2, aprs.Symbol.CAR, timestamp=when)
    assert caught.value.code is aprs.RefusalCode.INVALID_NAME
    # with sound data the call that writes a form names the header
    packet = aprs.Station("N0CALL", path="QAR123456").status("hi")
    assert packet.to_tnc2() == b"N0CALL>APZ001,QAR123456:>hi"
    with pytest.raises(aprs.EncodeError) as caught:
        packet.to_ax25()
    assert caught.value.code is aprs.RefusalCode.AX25_CANNOT_CARRY


def test_a_path_that_reads_back_used_is_refused_when_the_header_is_given() -> None:
    when = aprs.Timestamp.dhm(27, 9, 23)
    # before a data fault, and before the size, in every form
    with pytest.raises(aprs.EncodeError) as caught:
        aprs.Station("N0CALL", path=["WIDE1-1", "N0CALL-1*"]).object(
            "TOOLONGNAME", 1, 2, aprs.Symbol.CAR, timestamp=when
        )
    assert caught.value.code is aprs.RefusalCode.INVALID_PATH
    with pytest.raises(aprs.EncodeError) as caught:
        aprs.Station("N0CALL", path=["WIDE1-1", "N0CALL-1*"]).status("hi")
    assert caught.value.code is aprs.RefusalCode.INVALID_PATH
    with pytest.raises(aprs.EncodeError) as caught:
        aprs.build_packet("N0CALL", aprs.StatusReport(text="hi"), path=["A", "B*"])
    assert caught.value.code is aprs.RefusalCode.INVALID_PATH
    # an invalid address comes first
    with pytest.raises(aprs.EncodeError) as caught:
        aprs.build_packet("N0CALL", aprs.StatusReport(text="hi"), path=["A", "B*", "C D"])
    assert caught.value.code is aprs.RefusalCode.INVALID_ADDRESS


def test_an_empty_destination_in_a_frame_is_ax25_cannot_carry() -> None:
    packet = aprs.decode_tnc2(b"N0CALL>:>x")
    assert packet.destination == ""
    assert packet.to_tnc2() == b"N0CALL>:>x"
    with pytest.raises(aprs.EncodeError) as caught:
        packet.to_ax25()
    assert caught.value.code is aprs.RefusalCode.AX25_CANNOT_CARRY


def test_a_builders_mic_e_altitude_in_whole_feet_goes_in_the_bytes_first() -> None:
    station = aprs.Station("N0CALL")
    assert station.mic_e(51.5, -0.5, aprs.Symbol.CAR, altitude_feet=1000).info.endswith(b"}")
    with_comment = station.mic_e(51.5, -0.5, aprs.Symbol.CAR, altitude_feet=1000, comment="/A=001234 x")
    assert b"/A=001000//A=001234 x" in with_comment.info
