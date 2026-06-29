"""
Parser for Zaman Pardaz fingerprint/card device exports (GLG_XXX.TXT format).

File format (tab-separated):
    No  TMNo  EnNo  Name  Mode  INOUT  DateTime

- No: sequential record number in the export
- TMNo: device/terminal number
- EnNo: enrolled employee number on the device (THIS is what we match to employees.device_enroll_no)
- Name: a secondary numeric code, often blank — NOT reliable, ignore for matching
- Mode: verification method (1=fingerprint, 3=card, etc.) — informational only
- INOUT: punch direction flag as recorded by device firmware — NOT fully reliable
         (we recompute true IN/OUT by alternating sequence per employee per day)
- DateTime: 'YYYY/MM/DD HH:MM:SS' (Gregorian)
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class RawPunch:
    seq_no: int
    terminal_no: str
    device_enroll_no: str
    mode: str
    raw_inout_flag: str
    punch_datetime: datetime


def parse_zamanpardaz_txt(path: str | Path) -> list[RawPunch]:
    """Parse a Zaman Pardaz .TXT export into a list of RawPunch records.

    Skips the header line. Tolerant of ragged whitespace/tabs since the
    'Name' column is frequently blank or contains stray characters.
    """
    path = Path(path)
    punches: list[RawPunch] = []

    with path.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    if not lines:
        return punches

    # First non-empty line is the header (No\tTMNo\tEnNo\tName\tMode\tINOUT\tDateTime)
    data_lines = lines[1:] if lines[0].lower().startswith("no") else lines

    dt_pattern = re.compile(r"(\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})")

    for line_no, line in enumerate(data_lines, start=2):
        line = line.rstrip("\n")
        if not line.strip():
            continue

        fields = line.split("\t")
        if len(fields) < 7:
            # Try to recover: datetime is always the last well-formed token
            m = dt_pattern.search(line)
            if not m:
                continue  # unparsable line; caller can log this
            dt_str = m.group(1)
            head = line[: m.start()].split("\t")
            fields = head + [dt_str]

        try:
            seq_no = int(fields[0].strip())
            terminal_no = fields[1].strip()
            en_no = fields[2].strip()
            # fields[3] = Name column (unreliable, skip)
            mode = fields[4].strip()
            inout_flag = fields[5].strip()
            dt_raw = fields[6].strip()
            punch_dt = datetime.strptime(dt_raw, "%Y/%m/%d %H:%M:%S")
        except (ValueError, IndexError):
            continue  # malformed line — skip; production version should log this

        punches.append(
            RawPunch(
                seq_no=seq_no,
                terminal_no=terminal_no,
                device_enroll_no=en_no,
                mode=mode,
                raw_inout_flag=inout_flag,
                punch_datetime=punch_dt,
            )
        )

    return punches


def infer_in_out_sequence(punches: list[RawPunch]) -> list[tuple[RawPunch, str]]:
    """Given all punches for ONE employee (any date range), infer IN/OUT by
    alternating sequence per calendar day, ignoring the unreliable INOUT flag.

    Rule: first punch of a "work session" within a day = IN, next = OUT,
    next = IN, etc. A work session can cross midnight for night shifts, so
    this function expects punches to already be grouped sensibly by caller
    if overnight handling is needed; for now we group strictly by calendar
    date of the punch.
    """
    by_day: dict[str, list[RawPunch]] = {}
    for p in sorted(punches, key=lambda x: x.punch_datetime):
        day_key = p.punch_datetime.strftime("%Y-%m-%d")
        by_day.setdefault(day_key, []).append(p)

    result: list[tuple[RawPunch, str]] = []
    for day_key, day_punches in by_day.items():
        for i, p in enumerate(day_punches):
            direction = "IN" if i % 2 == 0 else "OUT"
            result.append((p, direction))
    return result


if __name__ == "__main__":
    import sys

    test_path = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads/GLG_001.TXT"
    parsed = parse_zamanpardaz_txt(test_path)
    print(f"Parsed {len(parsed)} punch records.")
    if parsed:
        print("First record:", parsed[0])
        print("Last record:", parsed[-1])

        # Quick sanity check: unique enroll numbers seen
        enroll_nos = sorted(set(p.device_enroll_no for p in parsed))
        print(f"Distinct device_enroll_no values ({len(enroll_nos)}):", enroll_nos)
