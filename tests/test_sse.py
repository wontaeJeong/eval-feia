from __future__ import annotations

from eval_feia.sse import SseParser, parse_sse_lines


def test_sse_parser_basic_and_multiline_event() -> None:
    events, errors = parse_sse_lines([
        ": keepalive",
        "event: message",
        'data: {"a": 1,',
        'data: "b": 2}',
        "",
    ])
    assert errors == 0
    assert len(events) == 1
    assert events[0].event == "message"
    assert events[0].parsed == {"a": 1, "b": 2}


def test_sse_parser_counts_parse_errors() -> None:
    parser = SseParser()
    parser.feed_line("retry: nope")
    events = parser.feed_line("data: {bad") + parser.feed_line("")
    assert parser.parse_error_count == 2
    assert events[0].parse_error is not None
