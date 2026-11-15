"""The read-back: every byte-writing call ends in one unconditional decode and comparison.

Three kinds of test. Per report type, bytes made wrong on the way out must be refused (so a type that
skipped the read-back would return them); data whose naive bytes read back as something else must be
written in an equivalent form or refused; and the comparison itself, which allows only the rule's
three differences and nothing else.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

import pdn_aprs as aprs
from pdn_aprs import EncodeError, RefusalCode
from pdn_aprs import encode as enc
from pdn_aprs._neutral import from_neutral, to_neutral
from pdn_aprs._readback import mismatch

# one valid neutral record for every report type the library writes
SAMPLES: dict[str, dict[str, Any]] = {
    "position": {"type": "position", "latitude": 51.5, "longitude": -0.5, "symbol": "/>", "comment": "hello"},
    "object": {
        "type": "object",
        "name": "OBJ",
        "timestamp": "092345z",
        "latitude": 51.5,
        "longitude": -0.5,
        "symbol": "/>",
        "comment": "hello",
    },
    "item": {"type": "item", "name": "ITEM", "latitude": 51.5, "longitude": -0.5, "symbol": "/>", "comment": "hello"},
    "mic-e": {
        "type": "mic-e",
        "mic_e_message": "off-duty",
        "latitude": 51.5,
        "longitude": -0.5,
        "symbol": "/>",
        "speed_knots": 10,
        "course_degrees": 90,
        "type_code": "`",
        "comment": "hello",
    },
    "message": {"type": "message", "addressee": "N0CALL", "text": "hello", "message_id": "12"},
    "ack": {"type": "ack", "addressee": "N0CALL", "acked_id": "12"},
    "reject": {"type": "reject", "addressee": "N0CALL", "rejected_id": "12"},
    "bulletin": {"type": "bulletin", "addressee": "BLN1", "text": "hello"},
    "nws-bulletin": {"type": "nws-bulletin", "addressee": "NWS-TEST", "text": "hello"},
    "telemetry-names": {"type": "telemetry-names", "addressee": "N0CALL", "names": ["Volts", "Amps"]},
    "telemetry-units": {"type": "telemetry-units", "addressee": "N0CALL", "units": ["V", "A"]},
    "telemetry-coefficients": {"type": "telemetry-coefficients", "addressee": "N0CALL", "coefficients": [0, 0.5, 1]},
    "telemetry-bits": {"type": "telemetry-bits", "addressee": "N0CALL", "bits": "10101010", "project": "Test"},
    "directed-query": {"type": "directed-query", "addressee": "N0CALL", "query_type": "APRSP"},
    "status": {"type": "status", "text": "hello"},
    "telemetry": {
        "type": "telemetry",
        "sequence": "123",
        "analog": [1, 2, 3, 4, 5],
        "bits": "10101010",
        "comment": "hello",
    },
    "weather": {
        "type": "weather",
        "timestamp": "10090556",
        "weather": {"wind_direction_degrees": 100, "wind_speed_mph": 5, "temperature_f": 70},
    },
    "raw-weather": {"type": "raw-weather", "format": "peet-bros-hash", "data": "abc"},
    "nmea": {"type": "nmea", "sentence": "GPGLL,4916.45,N,12311.12,W,225444,A", "comment": ""},
    "maidenhead-beacon": {"type": "maidenhead-beacon", "locator": "IO91SX", "comment": "hello"},
    "query": {"type": "query", "query_type": "APRS"},
    "capabilities": {"type": "capabilities", "capabilities": [["IGATE"], ["MSG_CNT", "n"]]},
    "third-party": {
        "type": "third-party",
        "packet": {"source": "N0CALL", "destination": "APZ001", "data": {"type": "status", "text": "hello"}},
    },
    "user-defined": {"type": "user-defined", "user_id": "A", "packet_type": "B", "data": "hello"},
    "test": {"type": "test", "data": "hello"},
    "agrelo-df": {"type": "agrelo-df", "bearing_degrees": 90, "quality": 5},
}


def test_there_is_a_sample_for_every_encoder() -> None:
    kinds = {cls.kind for cls in enc._ENCODERS}
    assert kinds == set(SAMPLES)


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_every_encoder_returns_forms_never_bytes(kind: str) -> None:
    """An encoder offers forms for the read-back to try: the only way to bytes is the read-back."""
    data = from_neutral(SAMPLES[kind])
    forms = enc._ENCODERS[type(data)](data)
    assert isinstance(forms, enc._Forms)
    assert enc.encode_info(data)


def test_written_bytes_are_only_made_by_the_read_back() -> None:
    with pytest.raises(TypeError):
        enc._Written(b"x", "APZ001", object())


def _tampered(encoder: Callable[[Any], enc._Forms]) -> Callable[[Any], enc._Forms]:
    """An encoder that writes a wrong last byte: a field writer gone wrong."""

    def wrapped(data: Any) -> enc._Forms:
        forms = encoder(data)
        original = forms.candidates

        def candidates() -> Iterator[bytes]:
            for info in original:
                yield info[:-1] + bytes([info[-1] ^ 1])

        forms.candidates = candidates()
        return forms

    return wrapped


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_bytes_a_writer_got_wrong_are_refused_for_every_report_type(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove or skip the read-back for a type and its wrong bytes would come back: they must not."""
    data = from_neutral(SAMPLES[kind])
    good = enc.encode_info(data)
    monkeypatch.setitem(enc._ENCODERS, type(data), _tampered(enc._ENCODERS[type(data)]))
    with pytest.raises(EncodeError):
        enc.encode_info(data)
    with pytest.raises(EncodeError):
        enc.build_packet("N0CALL", data)
    if isinstance(data, aprs.MicEReport):
        with pytest.raises(EncodeError):
            aprs.mic_e_destination(data)
    monkeypatch.undo()
    assert enc.encode_info(data) == good


def test_a_station_never_builds_a_packet_with_bytes_that_did_not_read_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(enc._ENCODERS, aprs.StatusReport, _tampered(enc._ENCODERS[aprs.StatusReport]))
    with pytest.raises(EncodeError):
        aprs.Station("N0CALL").status("hello")


def test_a_third_party_packet_is_read_back_whole_not_only_its_inner_packet(monkeypatch: pytest.MonkeyPatch) -> None:
    """The inner packet reads back on its own; the outer bytes (header and all) read back too."""
    data = from_neutral(SAMPLES["third-party"])
    original = enc._ENCODERS[aprs.ThirdParty]

    def wrong_header(d: Any) -> enc._Forms:
        forms = original(d)
        wrong = [i.replace(b"N0CALL>", b"N0CALX>") for i in forms.candidates]
        return enc._Forms(wrong, forms.refusal, forms.destination)

    monkeypatch.setitem(enc._ENCODERS, aprs.ThirdParty, wrong_header)
    with pytest.raises(EncodeError):
        enc.encode_info(data)


# ---------------------------------------------------------------- data whose naive bytes read back as something else


def _written(neutral: dict[str, Any]) -> bytes:
    return enc.encode_info(from_neutral(neutral))


def _refused(neutral: dict[str, Any]) -> RefusalCode:
    with pytest.raises(EncodeError) as excinfo:
        enc.encode_info(from_neutral(neutral))
    return excinfo.value.code


POSITION = {"latitude": 49.0583333, "longitude": -72.0291667, "symbol": "/-"}


@pytest.mark.parametrize("kind", ["position", "object", "item"])
def test_a_comment_that_reads_as_course_and_speed_takes_a_slash(kind: str) -> None:
    extra = {"object": {"name": "OBJ", "timestamp": "092345z"}, "item": {"name": "ITEM"}}.get(kind, {})
    info = _written({"type": kind, **POSITION, **extra, "comment": "123/456"})
    assert info.endswith(b"-/123/456")


@pytest.mark.parametrize("kind", ["position", "object", "item"])
@pytest.mark.parametrize("comment", ["/A=001234", "x/A=001234", "PHG2360", "RNG0050"])
def test_a_comment_no_form_of_which_reads_back_as_text_is_refused(kind: str, comment: str) -> None:
    extra = {"object": {"name": "OBJ", "timestamp": "092345z"}, "item": {"name": "ITEM"}}.get(kind, {})
    assert _refused({"type": kind, **POSITION, **extra, "comment": comment}) is RefusalCode.TEXT_READS_AS_FIELD


@pytest.mark.parametrize("comment", ["RNG0050", "PHG2360", "/PHG2360"])
def test_mic_e_text_that_reads_as_an_extension_is_refused(comment: str) -> None:
    assert _refused(SAMPLES["mic-e"] | {"comment": comment}) is RefusalCode.TEXT_READS_AS_FIELD


def test_mic_e_text_that_starts_like_a_type_code_takes_a_delimiter_and_reads_back() -> None:
    data = from_neutral(SAMPLES["mic-e"] | {"comment": ">x"})
    again = aprs.decode_tnc2(b"N0CALL>" + enc.mic_e_destination(data).encode() + b":" + enc.encode_info(data)).data
    assert isinstance(again, aprs.MicEReport)
    assert again.comment == ">x"


def test_message_text_that_reads_as_an_ack_is_refused() -> None:
    assert _refused({"type": "message", "addressee": "N0CALL", "text": "ack123"}) is RefusalCode.TEXT_READS_AS_FIELD


def test_status_text_that_reads_as_a_beam_is_refused() -> None:
    assert _refused({"type": "status", "text": "hello ^A5"}) is RefusalCode.TEXT_READS_AS_FIELD


def test_a_weather_extra_that_reads_as_another_field_is_refused() -> None:
    neutral = {
        "type": "weather",
        "timestamp": "10090556",
        "weather": {"temperature_f": 70, "extra": [{"letter": "x", "value": "1"}]},
    }
    assert _refused(neutral) is RefusalCode.TEXT_READS_AS_FIELD


def test_raw_weather_and_test_data_and_maidenhead_comment_read_back_as_given() -> None:
    for neutral in (
        {"type": "maidenhead-beacon", "locator": "IO91SX", "comment": "[IO91]x"},
        {"type": "test", "data": "a\tb"},
        {"type": "raw-weather", "format": "ultimeter-packet", "data": "0000"},
    ):
        assert to_neutral(aprs.decode_tnc2(b"N0CALL>APZ001:" + _written(neutral)).data) == neutral


def test_a_capability_value_that_would_read_as_another_item_is_refused() -> None:
    assert _refused({"type": "capabilities", "capabilities": [["A", "x,y"]]}) is RefusalCode.INVALID_CHARACTER


def test_a_query_target_reads_back_or_is_refused() -> None:
    info = _written({"type": "directed-query", "addressee": "N0CALL", "query_type": "APRSP", "target": "G4ABC"})
    assert to_neutral(aprs.decode_tnc2(b"N0CALL>APZ001:" + info).data)["target"] == "G4ABC"


def test_weather_extra_reading_as_software_and_unit_is_free_text_refused() -> None:
    neutral = {
        "type": "position",
        **POSITION,
        "symbol": "/_",
        "weather": {"pressure_mbar": 1013.2, "extra": [{"letter": "A", "value": "A00"}]},
    }
    assert _refused(neutral) is RefusalCode.TEXT_READS_AS_FIELD


def test_an_empty_message_id_is_no_message_id() -> None:
    assert _written({"type": "message", "addressee": "N0CALL", "text": "hi", "message_id": ""}) == b":N0CALL   :hi"


# ---------------------------------------------------------------- the comparison


def _check(neutral: dict[str, Any], info: bytes, destination: str = "APZ001") -> str | None:
    data = from_neutral(neutral)
    return mismatch(data, to_neutral(data), info, destination)


def test_the_comparison_accepts_what_the_encoder_writes_for_every_sample() -> None:
    for neutral in SAMPLES.values():
        data = from_neutral(neutral)
        written = enc._write(data)
        assert mismatch(data, to_neutral(data), written.info, written.destination) is None


def test_a_number_is_compared_with_the_value_rounded_once_not_within_a_tolerance() -> None:
    neutral = {"type": "position", "latitude": 51.5, "longitude": -0.5, "symbol": "/>"}
    # 51.5 degrees is 5130.00; a position a hundredth of a minute off is 1.7e-4 degrees, which a
    # tolerance of 1e-4 would have taken
    assert _check(neutral, b"!5130.00N/00030.00W>") is None
    assert _check(neutral, b"!5130.01N/00030.00W>") is not None
    assert _check(neutral, b"!5130.00N/00030.01W>") is not None


def test_a_value_between_steps_reads_back_as_the_value_rounded() -> None:
    base = {"type": "position", "latitude": 51.5, "longitude": -0.5, "symbol": "/>"}
    assert _check(base | {"course_degrees": 2.5, "speed_knots": 10}, b"!5130.00N/00030.00W>003/010") is None
    assert _check(base | {"course_degrees": 2.5, "speed_knots": 10}, b"!5130.00N/00030.00W>002/010") is not None
    assert _check(base | {"speed_knots": 10.4}, b"!5130.00N/00030.00W>088/011") is not None


def test_a_compressed_value_is_compared_in_its_own_steps() -> None:
    neutral = SAMPLES["position"] | {"compressed": True, "comment": "", "course_degrees": 90, "speed_knots": 36}
    neutral["compression"] = {"fix": "current", "source": "other", "origin": "software"}
    data = from_neutral(neutral)
    info = enc.encode_info(data)
    assert mismatch(data, to_neutral(data), info, "APZ001") is None
    # the speed byte one step up reads back as another speed
    wrong = info[:-2] + bytes([info[-2] + 1]) + info[-1:]
    assert mismatch(data, to_neutral(data), wrong, "APZ001") is not None


def test_the_default_compression_type_is_the_form_carrying_a_value_not_any_type() -> None:
    neutral = {
        "type": "position",
        "latitude": 51.5,
        "longitude": -0.5,
        "symbol": "/>",
        "compressed": True,
        "course_degrees": 88,
        "speed_knots": 36,
    }
    data = from_neutral(neutral)
    info = enc.encode_info(data)
    assert mismatch(data, to_neutral(data), info, "APZ001") is None
    # the same bytes with another type byte are not the default
    other = info[:-1] + bytes([info[-1] + 8])
    assert mismatch(data, to_neutral(data), other, "APZ001") is not None


def test_a_mic_e_speed_left_out_reads_back_as_zero_and_nothing_else() -> None:
    neutral = {k: v for k, v in SAMPLES["mic-e"].items() if k not in ("speed_knots", "course_degrees")}
    data = from_neutral(neutral)
    written = enc._write(data)
    assert mismatch(data, to_neutral(data), written.info, written.destination) is None


def test_a_field_the_data_does_not_give_is_a_difference() -> None:
    assert _check({"type": "status", "text": "hi"}, b">hi^A5") is not None
    assert (
        _check({"type": "position", "latitude": 51.5, "longitude": -0.5, "symbol": "/>"}, b"!5130.00N/00030.00W>x")
        is not None
    )


def test_a_warning_in_the_decode_is_a_difference() -> None:
    assert (
        _check({"type": "position", "latitude": 51.5, "longitude": -0.5, "symbol": "/>"}, b"!5130.00n/00030.00W>")
        is not None
    )


def test_nmea_fields_the_sentence_determines_may_be_left_out_and_given_ones_must_agree() -> None:
    sentence = "GPGLL,4916.45,N,12311.12,W,225444,A"
    neutral = {"type": "nmea", "sentence": sentence}
    assert _check(neutral, b"$" + sentence.encode()) is None
    assert _check(neutral | {"latitude": 49.0}, b"$" + sentence.encode()) is not None


def test_a_third_party_inner_packet_reading_back_with_a_warning_fails_unless_it_is_given() -> None:
    inner = {"source": "G4ABC", "destination": "APZ001", "data": {"type": "status", "text": "Net \x07Control"}}
    info = b"}G4ABC>APZ001:>Net \x07Control"
    neutral = {"type": "third-party", "packet": inner}
    assert _check(neutral, info) is not None
    given = {**neutral, "packet": {**inner, "diagnostics": ["warning:control-character-in-text"]}}
    assert _check(given, info) is None


def test_a_third_party_header_is_compared_too() -> None:
    neutral = SAMPLES["third-party"]
    assert _check(neutral, b"}N0CALL>APZ001:>hello") is None
    assert _check(neutral, b"}N0CALX>APZ001:>hello") is not None
    assert _check(neutral, b"}N0CALL>APZ001,WIDE1-1*:>hello") is not None


# ---------------------------------------------------------------- the header


def _packet(path: list[aprs.PathEntry]) -> aprs.Packet:
    return aprs.Packet("N0CALL", "APZ001", tuple(path), b">hi", aprs.StatusReport(text="hi"))


UNUSED_THEN_USED = [aprs.PathEntry("WIDE1-1"), aprs.PathEntry("N0CALL-1", True)]


def test_a_line_writes_a_star_on_the_last_used_entry_only() -> None:
    packet = _packet([aprs.PathEntry("WIDE1-1", True), aprs.PathEntry("N0CALL-1", True), aprs.PathEntry("WIDE2-1")])
    assert packet.to_tnc2() == b"N0CALL>APZ001,WIDE1-1,N0CALL-1*,WIDE2-1:>hi"
    assert aprs.decode_tnc2(packet.to_tnc2()).path == packet.path


def test_a_frame_sets_the_h_bit_of_every_used_entry() -> None:
    packet = _packet([aprs.PathEntry("WIDE1-1", True), aprs.PathEntry("N0CALL-1", True), aprs.PathEntry("WIDE2-1")])
    again = aprs.decode_ax25(packet.to_ax25())
    assert again.path == packet.path


def test_an_entry_not_marked_used_before_a_used_one_cannot_be_carried_by_a_line() -> None:
    packet = _packet(UNUSED_THEN_USED)
    for write in (packet.to_tnc2, lambda: packet.header, lambda: str(packet)):
        with pytest.raises(EncodeError) as excinfo:
            write()
        assert excinfo.value.code is RefusalCode.TNC2_CANNOT_CARRY


def test_an_entry_not_marked_used_before_a_used_one_cannot_be_carried_by_a_frame() -> None:
    packet = _packet(UNUSED_THEN_USED)
    for write in (packet.to_ax25, packet.to_kiss):
        with pytest.raises(EncodeError) as excinfo:
            write()
        assert excinfo.value.code is RefusalCode.AX25_CANNOT_CARRY


def test_a_builder_path_entry_ending_in_a_star_is_a_used_entry() -> None:
    packet = aprs.Station("N0CALL", path=["WIDE1-1*", "N0CALL-1*", "WIDE2-1"]).status("hi")
    assert packet.path == (aprs.PathEntry("WIDE1-1", True), aprs.PathEntry("N0CALL-1", True), aprs.PathEntry("WIDE2-1"))
    assert packet.to_tnc2() == b"N0CALL>APZ001,WIDE1-1,N0CALL-1*,WIDE2-1:>hi"


def test_a_builder_path_with_no_used_entry_is_written() -> None:
    assert aprs.Station("N0CALL", path=["WIDE1-1", "WIDE2-1"]).status("hi").to_tnc2() == (
        b"N0CALL>APZ001,WIDE1-1,WIDE2-1:>hi"
    )


def test_a_header_that_does_not_read_back_is_refused_in_a_pass_through_writer() -> None:
    odd = aprs.Packet("N0 CALL", "APZ001", (), b">hi", aprs.StatusReport(text="hi"))
    with pytest.raises(EncodeError):
        odd.to_tnc2()
    with pytest.raises(EncodeError):
        odd.to_ax25()


def test_a_decoded_packet_writes_its_information_field_as_received() -> None:
    line = b"N0CALL>APZ001,WIDE1-1*,WIDE2-1:>hi\x07there"
    packet = aprs.decode_tnc2(line)
    assert packet.to_tnc2() == line


def test_a_third_party_inner_header_is_read_back_as_the_outer_line_is() -> None:
    data = from_neutral(
        {
            "type": "third-party",
            "packet": {
                "source": "G4ABC",
                "destination": "APZ001",
                "path": ["WIDE1-1*", "N0CALL-1*"],
                "data": {"type": "status", "text": "hi"},
            },
        }
    )
    assert enc.encode_info(data) == b"}G4ABC>APZ001,WIDE1-1,N0CALL-1*:>hi"
