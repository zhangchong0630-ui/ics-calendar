#!/usr/bin/env python3
"""ICS 文本读写工具，由世界杯与国安两个更新脚本共用。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path


BEIJING_TZ = timezone(timedelta(hours=8))


def unfold(content: str) -> list[str]:
    lines: list[str] = []
    for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not line:
            continue
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def fold_line(line: str, limit: int = 75) -> list[str]:
    if len(line.encode("utf-8")) <= limit:
        return [line]

    folded: list[str] = []
    current = ""
    current_len = 0
    current_limit = limit
    for char in line:
        char_len = len(char.encode("utf-8"))
        if current and current_len + char_len > current_limit:
            folded.append(current)
            current = " " + char
            current_len = 1 + char_len
        else:
            current += char
            current_len += char_len
    if current:
        folded.append(current)
    return folded


def prop_name(line: str) -> str:
    return line.split(":", 1)[0].split(";", 1)[0].upper()


def prop_value(line: str) -> str:
    return line.split(":", 1)[1] if ":" in line else ""


def text_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def text_unescape(value: str) -> str:
    value = value.replace("\\n", "\n").replace("\\N", "\n")
    value = value.replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    return value


def parse_ics(path: Path) -> tuple[list[str], list[str], list[list[str]]]:
    """拆成日历头、VTIMEZONE 块、以及各 VEVENT 的属性行（不含 BEGIN/END）。"""
    header: list[str] = []
    timezone_lines: list[str] = []
    events: list[list[str]] = []
    current_event: list[str] = []
    in_timezone = False
    in_event = False

    for line in unfold(path.read_text(encoding="utf-8-sig")):
        if line in {"BEGIN:VCALENDAR", "END:VCALENDAR"}:
            continue
        if line == "BEGIN:VTIMEZONE":
            in_timezone = True
            timezone_lines.append(line)
            continue
        if in_timezone:
            timezone_lines.append(line)
            if line == "END:VTIMEZONE":
                in_timezone = False
            continue
        if line == "BEGIN:VEVENT":
            in_event = True
            current_event = []
            continue
        if in_event:
            if line == "END:VEVENT":
                events.append(current_event)
                current_event = []
                in_event = False
            else:
                current_event.append(line)
            continue
        header.append(line)
    return header, timezone_lines, events


def event_props(event_lines: list[str]) -> dict[str, list[str]]:
    props: dict[str, list[str]] = {}
    for line in event_lines:
        props.setdefault(prop_name(line), []).append(line)
    return props


def first_prop(props: dict[str, list[str]], name: str) -> str | None:
    values = props.get(name)
    return values[0] if values else None


def parse_dtstart(value: str | None) -> datetime | None:
    """把 ICS 的 20260801T193500 解析成带北京时区的 datetime。"""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=BEIJING_TZ)
    except ValueError:
        return None


def beijing_now() -> str:
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
