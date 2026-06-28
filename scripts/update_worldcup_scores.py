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
DEFAULT_KNOCKOUT_API_URL = (
    "https://api.fifa.com/api/v3/calendar/matches"
    "?language=en&count=200&idCompetition=17&idSeason=285023"
    "&from=2026-06-28&to=2026-07-20"
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

VENUE_NAME_TO_CN = {
    "Atlanta Stadium": "美国·亚特兰大 亚特兰大体育场",
    "Boston Stadium": "美国·波士顿 波士顿体育场",
    "Dallas Stadium": "美国·达拉斯 达拉斯体育场",
    "Guadalajara Stadium": "墨西哥·瓜达拉哈拉 阿克伦体育场",
    "Houston Stadium": "美国·休斯敦 休斯敦体育场",
    "Kansas City Stadium": "美国·堪萨斯城 堪萨斯城体育场",
    "Los Angeles Stadium": "美国·洛杉矶 洛杉矶体育场",
    "Mexico City Stadium": "墨西哥·墨西哥城 墨西哥城体育场",
    "Miami Stadium": "美国·迈阿密 迈阿密体育场",
    "Monterrey Stadium": "墨西哥·蒙特雷 蒙特雷体育场",
    "New York/New Jersey Stadium": "美国·纽约/新泽西 纽约新泽西体育场",
    "Philadelphia Stadium": "美国·费城 费城体育场",
    "San Francisco Bay Area Stadium": "美国·旧金山湾区 旧金山湾区体育场",
    "Seattle Stadium": "美国·西雅图 西雅图体育场",
    "Toronto Stadium": "加拿大·多伦多 多伦多体育场",
    "Vancouver Stadium": "加拿大·温哥华 温哥华体育场",
}

COUNTRY_CODE_TO_CN = {
    "CAN": "加拿大",
    "MEX": "墨西哥",
    "USA": "美国",
}


@dataclass(frozen=True)
class MatchInfo:
    group: str
    round_name: str
    stage_name: str
    home: str
    away: str
    dtstart: str
    dtend: str
    venue: str | None
    completed: bool
    home_score: int | None
    away_score: int | None
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


def localized_group(values: list[dict[str, Any]] | None) -> str | None:
    description = localized_description(values)
    if not description:
        return None
    match = re.search(r"Group ([A-L])", description)
    return f"{match.group(1)}组" if match else None


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


def venue_to_cn(stadium: dict[str, Any] | None) -> str | None:
    if not isinstance(stadium, dict):
        return None
    stadium_name = localized_description(stadium.get("Name"))
    if stadium_name in VENUE_NAME_TO_CN:
        return VENUE_NAME_TO_CN[stadium_name]

    city = localized_description(stadium.get("CityName"))
    country = COUNTRY_CODE_TO_CN.get(stadium.get("IdCountry"), stadium.get("IdCountry"))
    parts = []
    if country or city:
        parts.append("·".join(part for part in [country, city] if part))
    if stadium_name:
        parts.append(stadium_name)
    return " ".join(parts) if parts else None


def fifa_date_to_beijing_dtstart(value: str | None) -> str | None:
    if not value:
        return None
    try:
        utc_dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return utc_dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y%m%dT%H%M%S")


def parse_dtstart(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=timezone(timedelta(hours=8)))
    except ValueError:
        return None


def fetch_matches(source_url: str) -> list[MatchInfo]:
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

    raw_matches: list[dict[str, Any]] = []
    for source_order, match in enumerate(results):
        if not isinstance(match, dict):
            continue
        home = team_to_cn(match.get("Home"))
        away = team_to_cn(match.get("Away"))
        group = localized_group(match.get("GroupName"))
        dtstart = fifa_date_to_beijing_dtstart(match.get("Date"))
        start_dt = parse_dtstart(dtstart)
        if not home or not away or not group or not dtstart or not start_dt:
            continue

        home_score = (match.get("Home") or {}).get("Score")
        away_score = (match.get("Away") or {}).get("Score")
        completed = str(match.get("MatchStatus")) == "0" and home_score is not None and away_score is not None
        raw_matches.append(
            {
                "group": group,
                "home": home,
                "away": away,
                "dtstart": dtstart,
                "dtend": (start_dt + timedelta(hours=2)).strftime("%Y%m%dT%H%M%S"),
                "venue": venue_to_cn(match.get("Stadium")),
                "completed": completed,
                "home_score": int(home_score) if completed else None,
                "away_score": int(away_score) if completed else None,
                "match_id": str(match.get("IdMatch") or ""),
                "source_order": source_order,
            }
        )

    raw_matches.sort(key=lambda item: (item["group"], item["dtstart"], item["source_order"]))
    group_counts: dict[str, int] = {}
    matches: list[MatchInfo] = []
    for item in raw_matches:
        index = group_counts.get(item["group"], 0)
        group_counts[item["group"]] = index + 1
        matches.append(
            MatchInfo(
                group=item["group"],
                round_name=f"第{index // 2 + 1}轮",
                stage_name="小组赛",
                home=item["home"],
                away=item["away"],
                dtstart=item["dtstart"],
                dtend=item["dtend"],
                venue=item["venue"],
                completed=item["completed"],
                home_score=item["home_score"],
                away_score=item["away_score"],
                match_id=item["match_id"],
            )
        )
    return matches


def stage_to_cn(stage_name: str | None) -> str | None:
    mapping = {
        "Round of 32": "32强赛",
        "Round of 16": "16强赛",
        "Quarter-final": "1/4决赛",
        "Quarter-finals": "1/4决赛",
        "Semi-final": "半决赛",
        "Semi-finals": "半决赛",
        "Play-off for third place": "三四名决赛",
        "Final": "决赛",
    }
    return mapping.get(stage_name or "")


def fetch_knockout_matches(source_url: str) -> list[MatchInfo]:
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
        raise ValueError("Knockout source did not return a match list")

    matches: list[MatchInfo] = []
    for match in results:
        if not isinstance(match, dict):
            continue
        stage_name = stage_to_cn(localized_description(match.get("StageName")))
        home = team_to_cn(match.get("Home"))
        away = team_to_cn(match.get("Away"))
        dtstart = fifa_date_to_beijing_dtstart(match.get("Date"))
        start_dt = parse_dtstart(dtstart)
        if not stage_name or not home or not away or not dtstart or not start_dt:
            continue

        home_score = (match.get("Home") or {}).get("Score")
        away_score = (match.get("Away") or {}).get("Score")
        completed = str(match.get("MatchStatus")) == "0" and home_score is not None and away_score is not None
        matches.append(
            MatchInfo(
                group=stage_name,
                round_name="",
                stage_name=stage_name,
                home=home,
                away=away,
                dtstart=dtstart,
                dtend=(start_dt + timedelta(hours=2)).strftime("%Y%m%dT%H%M%S"),
                venue=venue_to_cn(match.get("Stadium")),
                completed=completed,
                home_score=int(home_score) if completed else None,
                away_score=int(away_score) if completed else None,
                match_id=str(match.get("IdMatch") or ""),
            )
        )
    return sorted(matches, key=lambda item: (item.dtstart, item.match_id))


def event_group_round(props: dict[str, list[str]]) -> tuple[str, str]:
    summary = text_unescape(prop_value(first_prop(props, "SUMMARY") or ""))
    match = re.match(r"^[⚽✅]?\s*([A-L]组)(第\d轮):", summary)
    if match:
        return match.group(1), match.group(2)

    uid = prop_value(first_prop(props, "UID") or "")
    match = re.match(r"wc2026-([A-L]组)-r(第\d轮)-", uid)
    if match:
        return match.group(1), match.group(2)

    raise ValueError(f"Cannot parse event group/round from UID/SUMMARY: {uid or summary}")


def event_identity(props: dict[str, list[str]]) -> tuple[str, str, str, str]:
    uid = prop_value(first_prop(props, "UID") or "")
    match = re.match(r"wc2026-([A-L]组)-r(第\d轮)-(.+)-(.+)@worldcup2026", uid)
    if match:
        return match.group(1), match.group(2), match.group(3), match.group(4)

    summary = text_unescape(prop_value(first_prop(props, "SUMMARY") or ""))
    match = re.match(r"^[⚽✅]?\s*([A-L]组)(第\d轮):\s*(.+?)\s+vs\s+(.+)$", summary)
    if match:
        return match.group(1), match.group(2), match.group(3), match.group(4)
    match = re.match(
        r"^[⚽✅]?\s*([A-L]组)(第\d轮):\s*(.+?)\s+\d+\s*[-–]\s*\d+\s+(.+)$",
        summary,
    )
    if match:
        return match.group(1), match.group(2), match.group(3), match.group(4)

    raise ValueError(f"Cannot parse event identity from UID/SUMMARY: {uid or summary}")


def group_events(events: list[list[str]]) -> dict[tuple[str, str], list[list[str]]]:
    grouped: dict[tuple[str, str], list[list[str]]] = {}
    for event in events:
        props = event_props(event)
        try:
            key = event_group_round(props)
        except ValueError:
            continue
        grouped.setdefault(key, []).append(event)
    return grouped


def group_matches(matches: list[MatchInfo]) -> dict[tuple[str, str], list[MatchInfo]]:
    grouped: dict[tuple[str, str], list[MatchInfo]] = {}
    for match in matches:
        grouped.setdefault((match.group, match.round_name), []).append(match)
    return grouped


def beijing_now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def beijing_time_label(dtstart: str) -> str:
    dt = parse_dtstart(dtstart)
    return dt.strftime("%H:%M") if dt else dtstart[-6:-4] + ":" + dtstart[-4:-2]


def build_summary(match: MatchInfo) -> str:
    if match.completed:
        return f"✅ {match.group}{match.round_name}: {match.home} {match.home_score}-{match.away_score} {match.away}"
    return f"⚽ {match.group}{match.round_name}: {match.home} vs {match.away}"


def extract_line(description: str, prefix: str) -> str | None:
    for line in description.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def build_description(match: MatchInfo, old_description: str) -> str:
    lines = [
        "2026美加墨世界杯",
        f"{match.group}{match.round_name}",
        f"{match.home} vs {match.away}",
    ]
    if match.completed:
        score_line = f"赛果: {match.home} {match.home_score}-{match.away_score} {match.away}"
        old_score = extract_line(old_description, "赛果:")
        old_update = extract_line(old_description, "比分更新时间:")
        if old_score and f"赛果: {old_score}" == score_line and old_update:
            updated_at = old_update
        else:
            updated_at = f"北京时间 {beijing_now()}"
        lines.extend([score_line, "状态: 已完赛", f"比分更新时间: {updated_at}"])
    if match.venue:
        lines.append(f"场地: {match.venue}")
    lines.append(f"北京时间 {beijing_time_label(match.dtstart)}")
    return "\n".join(lines)


def build_event(event_lines: list[str], match: MatchInfo, now_utc: str) -> tuple[list[str], bool, bool]:
    props = event_props(event_lines)
    old_summary = text_unescape(prop_value(first_prop(props, "SUMMARY") or ""))
    old_description = text_unescape(prop_value(first_prop(props, "DESCRIPTION") or ""))
    old_dtstart = first_prop(props, "DTSTART") or ""
    old_dtend = first_prop(props, "DTEND") or ""

    summary = build_summary(match)
    description = build_description(match, old_description)
    dtstart = f"DTSTART;TZID=Asia/Shanghai:{match.dtstart}"
    dtend = f"DTEND;TZID=Asia/Shanghai:{match.dtend}"

    semantic_changed = (
        old_summary != summary
        or old_description != description
        or old_dtstart != dtstart
        or old_dtend != dtend
    )
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
    output.append(dtstart)
    output.append(dtend)
    output.append(f"SUMMARY:{text_escape(summary)}")
    output.append(f"DESCRIPTION:{text_escape(description)}")
    output.append("CLASS:PUBLIC")
    output.append(f"CATEGORIES:世界杯,2026 FIFA World Cup,{match.group}")
    output.append("X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:DISABLED")
    add_existing("STATUS")
    add_existing("TRANSP")
    output.append("END:VEVENT")
    return output, changed, match.completed


def knockout_uid(match: MatchInfo) -> str:
    safe_stage = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "-", match.group).strip("-")
    if match.match_id:
        return f"wc2026-{safe_stage}-{match.match_id}@worldcup2026"
    return f"wc2026-{safe_stage}-{match.dtstart}-{match.home}-{match.away}@worldcup2026"


def build_new_event(match: MatchInfo, now_utc: str) -> list[str]:
    description = build_description(match, "")
    output = [
        "BEGIN:VEVENT",
        f"UID:{knockout_uid(match)}",
        f"DTSTAMP:{now_utc}",
        f"CREATED:{now_utc}",
        f"LAST-MODIFIED:{now_utc}",
        "SEQUENCE:0",
        f"DTSTART;TZID=Asia/Shanghai:{match.dtstart}",
        f"DTEND;TZID=Asia/Shanghai:{match.dtend}",
        f"SUMMARY:{text_escape(build_summary(match))}",
        f"DESCRIPTION:{text_escape(description)}",
        "CLASS:PUBLIC",
        f"CATEGORIES:世界杯,2026 FIFA World Cup,{match.group}",
        "X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:DISABLED",
        "STATUS:CONFIRMED",
        "TRANSP:OPAQUE",
        "END:VEVENT",
    ]
    return output


def ordered_event_match_pairs(events: list[list[str]], matches: list[MatchInfo]) -> list[tuple[list[str], MatchInfo]]:
    events_by_round = group_events(events)
    matches_by_round = group_matches(matches)

    event_keys = set(events_by_round)
    match_keys = set(matches_by_round)
    if event_keys != match_keys:
        missing_events = sorted(match_keys - event_keys)
        missing_matches = sorted(event_keys - match_keys)
        raise ValueError(f"Round mismatch. Missing events: {missing_events}; missing matches: {missing_matches}")

    pairs_by_event_id: dict[int, MatchInfo] = {}
    for key, round_events in events_by_round.items():
        round_matches = matches_by_round[key]
        remaining_matches = list(matches_by_round[key])
        if len(round_events) != len(round_matches):
            raise ValueError(f"{key} has {len(round_events)} events but {len(round_matches)} official matches")
        for event in round_events:
            _, _, event_home, event_away = event_identity(event_props(event))

            def match_score(match: MatchInfo) -> int:
                event_pair = {event_home, event_away}
                match_pair = {match.home, match.away}
                if event_pair == match_pair:
                    return 100
                score = len(event_pair & match_pair) * 10
                if match.home == event_home:
                    score += 3
                if match.away == event_away:
                    score += 2
                if match.home == event_away:
                    score += 1
                if match.away == event_home:
                    score += 1
                return score

            best_match = max(remaining_matches, key=match_score)
            remaining_matches.remove(best_match)
            pairs_by_event_id[id(event)] = best_match

    return [
        (event, pairs_by_event_id[id(event)])
        for event in events
        if id(event) in pairs_by_event_id
    ]


def build_calendar(
    header: list[str],
    timezone_lines: list[str],
    events: list[list[str]],
    matches: list[MatchInfo],
    knockout_matches: list[MatchInfo],
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
    for event, match in ordered_event_match_pairs(events, matches):
        event_output, changed, scored = build_event(event, match, now)
        output.extend(event_output)
        changed_events += int(changed)
        scored_events += int(scored)

    # Knockout events already present in the calendar: refresh their score
    # from the knockout source when available, otherwise keep them as-is so
    # they are never dropped. (Group-stage events were emitted above.)
    knockout_by_uid = {knockout_uid(match): match for match in knockout_matches}
    existing_uids: set[str] = set()
    for event in events:
        props = event_props(event)
        try:
            event_group_round(props)
            continue
        except ValueError:
            pass
        uid = prop_value(first_prop(props, "UID") or "")
        existing_uids.add(uid)
        match = knockout_by_uid.get(uid)
        if match is not None:
            event_output, changed, scored = build_event(event, match, now)
            output.extend(event_output)
            changed_events += int(changed)
            scored_events += int(scored)
        else:
            output.append("BEGIN:VEVENT")
            output.extend(event)
            output.append("END:VEVENT")
            scored_events += int("✅" in text_unescape(prop_value(first_prop(props, "SUMMARY") or "")))

    # New knockout matches not yet in the calendar: append them.
    for match in knockout_matches:
        uid = knockout_uid(match)
        if uid in existing_uids:
            continue
        output.extend(build_new_event(match, now))
        existing_uids.add(uid)
        changed_events += 1
        scored_events += int(match.completed)

    output.append("END:VCALENDAR")

    folded: list[str] = []
    for line in output:
        folded.extend(fold_line(line))
    return "\r\n".join(folded) + "\r\n", changed_events, scored_events


def main() -> int:
    parser = argparse.ArgumentParser(description="Update World Cup ICS schedule and results from FIFA match data.")
    parser.add_argument("--ics", default="worldcup2026_groupstage.ics", help="ICS file to update")
    parser.add_argument("--source-url", default=os.environ.get("SCORE_API_URL", DEFAULT_FIFA_API_URL))
    parser.add_argument(
        "--knockout-source-url",
        default=os.environ.get("KNOCKOUT_API_URL", DEFAULT_KNOCKOUT_API_URL),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ics_path = Path(args.ics)
    try:
        matches = fetch_matches(args.source_url)
    except Exception as exc:
        print(f"Score source unavailable; keeping ICS unchanged: {exc}", file=sys.stderr)
        return 0

    if len(matches) != 72:
        raise SystemExit(f"Expected 72 official World Cup group-stage matches, found {len(matches)}")

    try:
        knockout_matches = fetch_knockout_matches(args.knockout_source_url)
    except Exception as exc:
        print(f"Knockout source unavailable; keeping knockout events unchanged: {exc}", file=sys.stderr)
        knockout_matches = []

    header, timezone_lines, events = parse_ics(ics_path)
    if len(events) < 72:
        raise SystemExit(f"Expected at least 72 World Cup events, found {len(events)}")

    content, changed_events, scored_events = build_calendar(
        header,
        timezone_lines,
        events,
        matches,
        knockout_matches,
    )
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
