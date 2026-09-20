"""Audit exact, one-to-one CSV joins without discarding duplicate records.

Original AI-assisted technical sample prepared for Devam Kakoty; synthetic
inputs; no client/production deployment claim.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


STATUSES = ("blank_key", "ambiguous", "matched", "unmatched")


@dataclass(frozen=True)
class Row:
    position: int  # One-based data-record position; header is not counted.
    line_start: int
    line_end: int
    key: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class Table:
    headers: tuple[str, ...]
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class Decision:
    row: Row
    status: str
    own_count: int
    other_count: int
    partner_position: int | None


@dataclass(frozen=True)
class Audit:
    left: tuple[Decision, ...]
    right: tuple[Decision, ...]

    def summary(self) -> dict[str, object]:
        """Return counts only: never emit input keys or cell contents."""
        result: dict[str, object] = {}
        for side, decisions in (("left", self.left), ("right", self.right)):
            counts = Counter(item.status for item in decisions)
            result[side] = {
                "rows": len(decisions),
                **{status: counts[status] for status in STATUSES},
            }
        result["matched_pairs"] = sum(d.status == "matched" for d in self.left)
        return result

    def has_issues(self) -> bool:
        return any(
            item.status != "matched"
            for decisions in (self.left, self.right)
            for item in decisions
        )


def read_csv(stream: TextIO, key_column: str = "id") -> Table:
    """Read comma-separated CSV; reject invalid schema/width before auditing.

    Open disk streams with encoding='utf-8-sig', newline=''. Whitespace-only
    keys are invalid, but nonblank keys are otherwise compared unchanged.
    """
    reader = csv.reader(stream, dialect="excel", strict=True)
    try:
        header = next(reader, None)
        if not header:
            raise ValueError("missing CSV header")
        if any(not name.strip() for name in header):
            raise ValueError("blank column name")
        if len(set(header)) != len(header):
            raise ValueError("duplicate column name")
        if key_column not in header:
            raise ValueError("key column is absent")
        key_index = header.index(key_column)
        rows = []
        while True:
            line_start = reader.line_num + 1
            values = next(reader, None)
            if values is None:
                break
            position = len(rows) + 1
            if len(values) != len(header):
                raise ValueError(
                    f"record {position}, lines {line_start}-{reader.line_num}: "
                    f"expected {len(header)} fields, got {len(values)}"
                )
            rows.append(
                Row(position, line_start, reader.line_num,
                    values[key_index], tuple(values))
            )
    except csv.Error as exc:
        # Avoid repeating cell contents in error messages.
        raise ValueError(f"invalid CSV near physical line {reader.line_num}") from exc
    return Table(tuple(header), tuple(rows))


def load_csv(path: Path, key_column: str = "id") -> Table:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return read_csv(stream, key_column)


def audit_join(left: Table, right: Table) -> Audit:
    """Classify every row in each table; input tables should come from read_csv."""
    def index(table: Table) -> dict[str, list[Row]]:
        groups: dict[str, list[Row]] = defaultdict(list)
        for row in table.rows:
            if row.key.strip():
                groups[row.key].append(row)
        return groups

    left_index, right_index = index(left), index(right)

    def classify(
        table: Table,
        own: dict[str, list[Row]],
        other: dict[str, list[Row]],
    ) -> tuple[Decision, ...]:
        decisions = []
        for row in table.rows:
            if not row.key.strip():
                decisions.append(Decision(row, "blank_key", 0, 0, None))
                continue
            own_count = len(own[row.key])
            candidates = other.get(row.key, ())
            other_count = len(candidates)
            partner = None
            if own_count > 1 or other_count > 1:
                status = "ambiguous"
            elif other_count == 1:
                status = "matched"
                partner = candidates[0].position
            else:
                status = "unmatched"
            decisions.append(Decision(row, status, own_count, other_count, partner))
        return tuple(decisions)

    return Audit(
        classify(left, left_index, right_index),
        classify(right, right_index, left_index),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--key", default="id", help="exact column name in both files")
    args = parser.parse_args(argv)
    try:
        report = audit_join(
            load_csv(args.left, args.key),
            load_csv(args.right, args.key),
        )
    except (OSError, UnicodeError, ValueError) as exc:
        # Exception class is sufficient for this bounded CLI; API callers get
        # structural details. Do not leak filenames or data in console logs.
        print(f"Input rejected ({type(exc).__name__}); no audit produced.",
              file=sys.stderr)
        return 2
    print(json.dumps(report.summary(), sort_keys=True))
    return 1 if report.has_issues() else 0


if __name__ == "__main__":
    raise SystemExit(main())
