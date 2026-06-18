#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_FIFA_API_URL = (
    "https://api.fifa.com/api/v3/calendar/matches"
    "?language=en&count=100&idCompetition=17&idSeason=285023"
    "&from=2026-06-11&to=2026-06-29"
)

TEAM_CODE_TO_CN = {
    "ALG": "阿尔及利亚",
    "ARG": "阿根廷",
    "AUS": "澳大利亚",
    "AUT": "奥地利",
    "BEL": "比利时",
    "BIH": "波黑",
    "BRA": "巴西",
    "CAN": "加拿大",
    "CIV": "科特迪瓦",
    "COD": "民主刚果",
    "COL": "哥伦比亚",
    "CPV": "佛得角",
    "CRO": "克罗地亚",
    "CUW": "库拉索",
    "CZE": "捷克",
    "ECU": "厄瓜多尔",
    "EGY": "埃及",
    "ENG": "英格兰",
    "ESP": "西班牙",
    "FRA": "法国",
    "GER": "德国",
    "GHA": "加纳",
    "HAI": "海地",
    "IRN": "伊朗",
    "IRQ": "伊拉克",
    "JOR": "约旦",
    "JPN": "日本",
    "KOR": "韩国",
    "KSA": "沙特阿拉伯",
    "MAR": "摩洛哥",
    "MEX": "墨西哥",
    "NED": "荷兰",
    "NOR": "挪威",
    "NZL": "新西兰",
    "PAN": "巴拿马",
    "PAR": "巴拉圭",
    "POR": "葡萄牙",
    "QAT": "卡塔尔",
    "RSA": "南非",
    "SCO": "苏格兰",
    "SEN": "塞内加尔",
    "SUI": "瑞士",
    "SWE": "瑞典",
    "TUN": "突尼斯",
    "TUR": "土耳其",
    "URU": "乌拉圭",
    "USA": "美国",
    "UZB": "乌兹别克斯坦",
}

TEAM_NAME_TO_CN = {
    "algeria": "阿尔及利亚",
    "argentina": "阿根廷",
    "australia": "澳大利亚",
    "austria": "奥地利",
    "belgium": "比利时",
    "bosnia and herzegovina": "波黑",
    "brazil": "巴西",
    "cabo verde": "佛得角",
    "canada": "加拿大",
    "colombia": "哥伦比亚",
    "congo dr": "民主刚果",
    "cote d'ivoire": "科特迪瓦",
    "cote divoire": "科特迪瓦",
    "curacao": "库拉索",
    "czech republic": "捷克",
    "czechia": "捷克",
    "ecuador": "厄瓜多尔",
    "egypt": "埃及",
    "england": "英格兰",
    "france": "法国",
    "germany": "德国",
    "ghana": "加纳",
    "haiti": "海地",
    "ir iran": "伊朗",
    "iraq": "伊拉克",
    "japan": "日本",
    "jordan": "约旦",
    "korea republic": "韩国",
    "mexico": "墨西哥",
    "morocco": "摩洛哥",
    "netherlands": "荷兰",
    "new zealand": "新西兰",
    "norway": "挪威",
    "panama": "巴拿马",
    "paraguay": "巴拉圭",
    "portugal": "葡萄牙",
    "qatar": "卡塔尔",
    "saudi arabia": "沙特阿拉伯",
    "scotland": "苏格兰",
    "senegal": "塞内加尔",
    "south africa": "南非",
    "spain": "西班牙",
    "sweden": "瑞典",
    "switzerland": "瑞士",
    "tunisia": "突尼斯",
    "turkiye": "土耳其",
    "turkey": "土耳其",
    "uruguay": "乌拉圭",
    "usa": "美国",
    "uzbekistan": "乌兹别克斯坦",
}


@dataclass(frozen=True)
class Score:
    home: str
    away: str
    home_score: int
    away_score: int
    match_id: str


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


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("’", "'").replace("`", "'").replace("´", "'")
    value = re.sub(r"[^a-zA-Z0-9']+", " ", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def localized_description(values: list[dict[str, Any]] | None) -> str | None:
    if not values:
        return None
    for item in values:
        if item.get("Locale") in {"en-GB", "en-US", "en"}:
            return item.get("Description")
    return values[0].get("Description")


def team_to_cn(team: dict[str, Any] | None) -> str | None:
    if not isinstance(team, dict):
        return None
    code = team.get("IdCountry") or team.get("Abbreviation")
    if code in TEAM_CODE_TO_CN:
        return TEAM_CODE_TO_CN[code]

    candidates = [
        team.get("ShortClubName"),
        localized_description(team.get("TeamName")),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        normalized = normalize_name(str(candidate))
        if normalized in TEAM_NAME_TO_CN:
            return TEAM_NAME_TO_CN[normalized]
    return None


def fetch_scores(source_url: str) -> dict[tuple[str, str], Score]:
    request = urllib.request.Request(
        source_url,
        headers={
            "User-Agent": "ics-calendar-score-updater/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)

    results = payload.get("Results") if isinstance(payload, dict) else payload
    if not isinstance(results, list):
        raise ValueError("Score source did not return a match list")

    scores: dict[tuple[str, str], Score] = {}
    for match in results:
        if not isinstance(match, dict):
            continue
        if str(match.get("MatchStatus")) != "0":
            continue

        home = team_to_cn(match.get("Home"))
        away = team_to_cn(match.get("Away"))
        if not home or not away:
            continue

        home_score = (match.get("Home") or {}).get("Score")
        away_score = (match.get("Away") or {}).get("Score")
        if home_score is None or away_score is None:
            continue

        score = Score(
            home=home,
            away=away,
            home_score=int(home_score),
            away_score=int(away_score),
            match_id=str(match.get("IdMatch") or ""),
        )
        scores[(home, away)] = score
        scores[(away, home)] = Score(
            home=away,
            away=home,
            home_score=score.away_score,
            away_score=score.home_score,
            match_id=score.match_id,
        )
    return scores


def parse_event_identity(props: dict[str, list[str]]) -> tuple[str, str, str, str]:
    uid_line = first_prop(props, "UID") or ""
    uid = prop_value(uid_line)
    match = re.match(r"wc2026-([A-L]组)-r(第\d轮)-(.+)-(.+)@worldcup2026", uid)
    if match:
        group, round_name, home, away = match.groups()
        return group, round_name, home, away

    summary = text_unescape(prop_value(first_prop(props, "SUMMARY") or ""))
    match = re.match(r"^[⚽✅]?\s*([A-L]组)(第\d轮):\s*(.+?)\s+vs\s+(.+)$", summary)
    if match:
        group, round_name, home, away = match.groups()
        return group, round_name, home, away

    match = re.match(
        r"^[⚽✅]?\s*([A-L]组)(第\d轮):\s*(.+?)\s+\d+\s*[-–]\s*\d+\s+(.+)$",
        summary,
    )
    if match:
        group, round_name, home, away = match.groups()
        return group, round_name, home, away

    raise ValueError(f"Cannot parse event identity from UID/SUMMARY: {uid or summary}")


def extract_line(description: str, prefix: str) -> str | None:
    for line in description.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def existing_score(description: str, summary: str, home: str, away: str) -> Score | None:
    patterns = [
        rf"赛果:\s*{re.escape(home)}\s+(\d+)\s*[-–]\s*(\d+)\s+{re.escape(away)}",
        rf"{re.escape(home)}\s+(\d+)\s*[-–]\s*(\d+)\s+{re.escape(away)}",
    ]
    for text in [description, summary]:
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return Score(home, away, int(match.group(1)), int(match.group(2)), "")
    return None


def beijing_now() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_description(
    group: str,
    round_name: str,
    home: str,
    away: str,
    venue: str | None,
    beijing_time: str | None,
    score: Score | None,
    old_description: str,
) -> str:
    lines = [
        "2026美加墨世界杯小组赛",
        f"{group}{round_name}",
        f"{home} vs {away}",
    ]
    if score:
        score_line = f"赛果: {home} {score.home_score}-{score.away_score} {away}"
        old_score = extract_line(old_description, "赛果:")
        old_update = extract_line(old_description, "比分更新时间:")
        if old_score and f"赛果: {old_score}" == score_line and old_update:
            updated_at = old_update
        else:
            updated_at = f"北京时间 {beijing_now()}"
        lines.extend([score_line, "状态: 已完赛", f"比分更新时间: {updated_at}"])
    if venue:
        lines.append(f"场地: {venue}")
    if beijing_time:
        lines.append(f"北京时间 {beijing_time}")
    return "\n".join(lines)


def build_event(
    event_lines: list[str],
    scores: dict[tuple[str, str], Score],
    now_utc: str,
) -> tuple[list[str], bool, bool]:
    props = event_props(event_lines)
    group, round_name, home, away = parse_event_identity(props)

    old_summary = text_unescape(prop_value(first_prop(props, "SUMMARY") or ""))
    old_description = text_unescape(prop_value(first_prop(props, "DESCRIPTION") or ""))
    old_location = text_unescape(prop_value(first_prop(props, "LOCATION") or ""))
    venue = extract_line(old_description, "场地:") or old_location or None
    beijing_time = extract_line(old_description, "北京时间")

    score = scores.get((home, away)) or existing_score(old_description, old_summary, home, away)
    if score:
        summary = f"✅ {group}{round_name}: {home} {score.home_score}-{score.away_score} {away}"
    else:
        summary = f"⚽ {group}{round_name}: {home} vs {away}"

    description = build_description(
        group=group,
        round_name=round_name,
        home=home,
        away=away,
        venue=venue,
        beijing_time=beijing_time,
        score=score,
        old_description=old_description,
    )

    semantic_changed = old_summary != summary or old_description != description
    metadata_changed = (
        "LOCATION" in props
        or "X-APPLE-TRAVEL-ADVISORY-BEHAVIOR" not in props
        or "DTSTAMP" not in props
        or "CREATED" not in props
        or "LAST-MODIFIED" not in props
        or "SEQUENCE" not in props
        or "CLASS" not in props
        or "CATEGORIES" not in props
    )
    changed = semantic_changed or metadata_changed

    old_sequence_value = prop_value(first_prop(props, "SEQUENCE") or "SEQUENCE:0")
    try:
        old_sequence = int(old_sequence_value)
    except ValueError:
        old_sequence = 0
    sequence = old_sequence + 1 if semantic_changed else old_sequence

    stamp = now_utc if changed else prop_value(first_prop(props, "DTSTAMP") or f"DTSTAMP:{now_utc}")
    created = prop_value(first_prop(props, "CREATED") or f"CREATED:{now_utc}")
    modified = now_utc if changed else prop_value(first_prop(props, "LAST-MODIFIED") or f"LAST-MODIFIED:{now_utc}")

    output = ["BEGIN:VEVENT"]

    def add_existing(name: str) -> None:
        for value in props.get(name, []):
            output.append(value)

    add_existing("UID")
    output.append(f"DTSTAMP:{stamp}")
    output.append(f"CREATED:{created}")
    output.append(f"LAST-MODIFIED:{modified}")
    output.append(f"SEQUENCE:{sequence}")
    add_existing("DTSTART")
    add_existing("DTEND")
    output.append(f"SUMMARY:{text_escape(summary)}")
    output.append(f"DESCRIPTION:{text_escape(description)}")
    output.append("CLASS:PUBLIC")
    output.append(f"CATEGORIES:世界杯,2026 FIFA World Cup,{group}")
    output.append("X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:DISABLED")
    add_existing("STATUS")
    add_existing("TRANSP")
    output.append("END:VEVENT")
    return output, changed, score is not None


def build_calendar(
    header: list[str],
    timezone_lines: list[str],
    events: list[list[str]],
    scores: dict[tuple[str, str], Score],
) -> tuple[str, int, int]:
    now = utc_now()
    output = ["BEGIN:VCALENDAR"]

    skip_header = {"REFRESH-INTERVAL", "X-PUBLISHED-TTL"}
    for line in header:
        if prop_name(line) not in skip_header:
            output.append(line)
    output.append("REFRESH-INTERVAL;VALUE=DURATION:PT1H")
    output.append("X-PUBLISHED-TTL:PT1H")
    output.extend(timezone_lines)

    changed_events = 0
    scored_events = 0
    for event in events:
        event_output, changed, scored = build_event(event, scores, now)
        output.extend(event_output)
        changed_events += int(changed)
        scored_events += int(scored)

    output.append("END:VCALENDAR")

    folded: list[str] = []
    for line in output:
        folded.extend(fold_line(line))
    return "\r\n".join(folded) + "\r\n", changed_events, scored_events


def main() -> int:
    parser = argparse.ArgumentParser(description="Update World Cup ICS results from FIFA match data.")
    parser.add_argument("--ics", default="worldcup2026_groupstage.ics", help="ICS file to update")
    parser.add_argument("--source-url", default=os.environ.get("SCORE_API_URL", DEFAULT_FIFA_API_URL))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ics_path = Path(args.ics)
    try:
        scores = fetch_scores(args.source_url)
    except Exception as exc:
        print(f"Score source unavailable; keeping ICS unchanged: {exc}", file=sys.stderr)
        return 0

    if not scores:
        print("No completed matches found; keeping existing scores and optimizing metadata only.")

    header, timezone_lines, events = parse_ics(ics_path)
    if len(events) != 72:
        raise SystemExit(f"Expected 72 World Cup group-stage events, found {len(events)}")

    content, changed_events, scored_events = build_calendar(header, timezone_lines, events, scores)
    if args.dry_run:
        print(f"Would update {changed_events} events; {scored_events} events have final scores.")
        return 0

    old_content = ics_path.read_text(encoding="utf-8-sig")
    if old_content != content:
        ics_path.write_text(content, encoding="utf-8")
        print(f"Updated {changed_events} events; {scored_events} events have final scores.")
    else:
        print(f"No ICS changes needed; {scored_events} events have final scores.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
