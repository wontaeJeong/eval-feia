from __future__ import annotations

from collections.abc import Sequence

from rich.console import Console


def print_plain_table(
    console: Console,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
) -> None:
    widths = [len(header) for header in headers[:-1]]
    for row in rows:
        for index, value in enumerate(row[:-1]):
            widths[index] = max(widths[index], len(value))

    console.print(_format_plain_table_row(headers, widths), markup=False, soft_wrap=True)
    for row in rows:
        console.print(_format_plain_table_row(row, widths), markup=False, soft_wrap=True)


def _format_plain_table_row(values: Sequence[str], widths: Sequence[int]) -> str:
    padded = [value.ljust(widths[index]) for index, value in enumerate(values[:-1])]
    return "  ".join([*padded, values[-1]])
