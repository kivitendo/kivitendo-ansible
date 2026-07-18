#!/usr/bin/env python3
"""Normalize CSV files for kivitendo imports.

kivitendo's CSV importer is strict about delimiters and quoting. A file that is
valid for spreadsheet software can still fail during import with errors such as
`EIF - Loose unescaped quote` when the selected import delimiter does not match
or when free-text fields contain quotes/newlines. This tool rewrites a source CSV
into a conservative semicolon-separated, quote-free CSV that is easier to import
reliably through kivitendo's web UI.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Iterable

DEFAULT_HEADERS = (
    "partnumber",
    "description",
    "partsgroup",
    "unit",
    "sellprice",
    "listprice",
    "longdescription",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize a CSV file into a kivitendo-safe semicolon CSV."
    )
    parser.add_argument("input", type=Path, help="Source CSV path")
    parser.add_argument("output", type=Path, help="Normalized output CSV path")
    parser.add_argument(
        "--delimiter",
        default=";",
        help="Source and output delimiter. Defaults to ';'.",
    )
    parser.add_argument(
        "--expected-headers",
        default=",".join(DEFAULT_HEADERS),
        help=(
            "Comma-separated header names expected in exact order. Use an empty "
            "value to disable header validation."
        ),
    )
    return parser.parse_args()


def clean_cell(value: object, delimiter: str) -> str:
    text = "" if value is None else str(value)
    text = text.replace(delimiter, ",")
    text = text.replace('"', "'")
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s{2,}", " ", text).strip()


def read_rows(path: Path, delimiter: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter, quotechar='"', strict=True)
            headers = reader.fieldnames
            if not headers:
                raise ValueError("CSV file does not contain a header row")
            rows = list(reader)
    except csv.Error as exc:
        raise ValueError(
            f"CSV parser failed before normalization: {exc}. Verify that the "
            f"source file uses delimiter {delimiter!r} and valid RFC-style quotes."
        ) from exc

    if any(key is None for row in rows for key in row):
        raise ValueError(
            "At least one row contains more fields than the header. Verify the delimiter "
            "and remove unescaped separators from free-text fields."
        )

    return list(headers), rows


def validate_headers(actual: Iterable[str], expected_csv: str) -> None:
    expected = [value.strip() for value in expected_csv.split(",") if value.strip()]
    if expected and list(actual) != expected:
        raise ValueError(f"Unexpected CSV headers. Expected {expected!r}.")


def write_safe_csv(path: Path, headers: list[str], rows: list[dict[str, str]], delimiter: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=headers,
            delimiter=delimiter,
            quotechar='"',
            quoting=csv.QUOTE_NONE,
            escapechar="\\",
            lineterminator="\r\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({header: clean_cell(row.get(header, ""), delimiter) for header in headers})


def verify_safe_csv(path: Path, headers: list[str], delimiter: str) -> None:
    content = path.read_text(encoding="utf-8")
    if '"' in content:
        raise ValueError("Normalized CSV still contains double quotes")

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter, quotechar='"', strict=True)
        for line_number, row in enumerate(reader, start=1):
            if len(row) != len(headers):
                raise ValueError(
                    f"Line {line_number} has {len(row)} fields; expected {len(headers)}."
                )


def main() -> int:
    args = parse_args()
    if len(args.delimiter) != 1:
        print("Delimiter must be exactly one character.", file=sys.stderr)
        return 2

    try:
        headers, rows = read_rows(args.input, args.delimiter)
        validate_headers(headers, args.expected_headers)
        write_safe_csv(args.output, headers, rows, args.delimiter)
        verify_safe_csv(args.output, headers, args.delimiter)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {len(rows)} normalized rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
