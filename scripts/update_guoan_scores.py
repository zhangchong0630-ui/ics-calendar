#!/usr/bin/env python3
"""用球迷宝赛事数据更新北京国安 ICS 的赛程与比分。

数据源为直播吧数据频道背后的公开接口 db.qiumibao.com，覆盖中超、足协杯、
亚足联冠军精英联赛三项赛事，返回中文队名、中文球场与北京时间。

默认只在「有比赛刚结束但 ICS 里还没有比分」时才联网，其余情况直接退出，
不请求接口也不改文件。--full 跳过这个判断，做一次全量对账（抓改期、
新阶段赛程、亚冠赛程公布等）。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from icslib import (
    BEIJING_TZ,
    beijing_now,
    event_props,
    first_prop,
    fold_line,
    parse_dtstart,
    parse_ics,
    prop_value,
    text_escape,
    text_unescape,
    utc_now,
)


API_BASE = "https://db.qiumibao.com/f/index"
TEAM = "北京国安"

# 一场比赛按 2 小时计；也用作「开赛多久之后才认为该有比分了」的阈值。
MATCH_DURATION = timedelta(hours=2)
SCORE_READY_AFTER = timedelta(hours=2, minutes=30)
# 超过这个天数仍无比分的，视为延期或数据缺失，交给每周全量对账处理，
# 不再让赛后模式每小时空跑（例：2026 第18轮申花主场因台风延期，补赛待定）。
PENDING_LOOKBACK = timedelta(days=14)

# 赛程刚公布（抽签结束、杯赛进入新阶段）时，接口会对尚未定时的场次返回一个
# 格式合法的假时间做占位，try/except 拦不住。现实中没有比赛在这两个时间点开球。
PLACEHOLDER_KICKOFF = {(23, 59), (0, 0)}


@dataclass(frozen=True)
class Competition:
    key: str          # UID 前缀用
    label: str        # 事件标题里的赛事名
    api_name: str     # 球迷宝 f/index/teams 的 name 参数
    match_id: str     # 球迷宝赛事 id


COMPETITIONS = (
    Competition("round", "中超", "中超", "353"),
    Competition("facup", "足协杯", "足协杯", "352"),
    Competition("acl", "亚冠精英", "亚足联冠军精英联赛", "392"),
)

# 接口用简称，ICS 里用俱乐部全称，只列出两者不一致的。
TEAM_ALIASES = {
    "浙江": "浙江俱乐部绿城",
    "河南": "河南俱乐部",
    "大连英博": "大连英博海发",
}

CALENDAR_HEADER = [
    "VERSION:2.0",
    "PRODID:-//BeijingGuoanCalendar//CN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "X-WR-CALNAME:北京国安2026赛季",
    "X-WR-TIMEZONE:Asia/Shanghai",
    "X-WR-CALDESC:北京国安2026赛季赛程（中超/足协杯/亚冠精英联赛，主队在前），赛后自动更新比分",
    "X-WR-RELCALID:BeijingGuoan-2026",
    "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
    "X-PUBLISHED-TTL:PT1H",
]

CALENDAR_TIMEZONE = [
    "BEGIN:VTIMEZONE",
    "TZID:Asia/Shanghai",
    "X-LIC-LOCATION:Asia/Shanghai",
    "BEGIN:STANDARD",
    "DTSTART:19700101T000000",
    "TZOFFSETFROM:+0800",
    "TZOFFSETTO:+0800",
    "TZNAME:CST",
    "END:STANDARD",
    "END:VTIMEZONE",
]

DEFAULT_ALARM = [
    "BEGIN:VALARM",
    "TRIGGER:-PT1H",
    "ACTION:DISPLAY",
    "DESCRIPTION:比赛提前1小时提醒",
    "END:VALARM",
]


@dataclass(frozen=True)
class Match:
    competition: Competition
    stage: str            # 第21轮 / 1/4决赛
    home: str
    away: str
    dtstart: str          # 20260801T193500
    dtend: str
    venue: str | None
    completed: bool
    home_score: int | None
    away_score: int | None
    uid: str


def api_get(path: str, params: dict[str, str]) -> dict[str, Any]:
    query = urllib.parse.urlencode({"_platform": "web", **params})
    request = urllib.request.Request(
        f"{API_BASE}/{path}?{query}",
        headers={
            "User-Agent": "ics-calendar-score-updater/1.0",
            "Accept": "application/json",
            "Referer": "https://data.zhibo8.cc/",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return payload if isinstance(payload, dict) else {}


def team_name(value: str) -> str:
    return TEAM_ALIASES.get(value, value)


def stage_list(competition: Competition) -> list[dict[str, str]]:
    """返回该赛事需要遍历的分段：联赛制按轮次，杯赛制按阶段。"""
    payload = api_get("teams", {"name": competition.api_name, "test": "1"})
    data = payload.get("data")
    if not isinstance(data, dict):
        return []

    if str(data.get("match_type")) == "1":
        rounds = int(data.get("rounds") or 0)
        return [{"round": str(n)} for n in range(1, rounds + 1)]

    types = data.get("types") or []
    if isinstance(types, dict):
        types = list(types.values())
    return [{"type": t} for t in types if isinstance(t, str) and t.strip()]


def build_match(competition: Competition, raw: dict[str, Any], requested: dict[str, str]) -> Match | None:
    home = str(raw.get("hteam_name") or "")
    away = str(raw.get("gteam_name") or "")
    if TEAM not in (home, away):
        return None

    try:
        start = datetime.strptime(str(raw.get("games_time")), "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING_TZ)
    except ValueError:
        return None

    if (start.hour, start.minute) in PLACEHOLDER_KICKOFF:
        print(
            f"跳过 {home} vs {away}：开赛时间 {raw.get('games_time')} 是数据源的待定占位值",
            file=sys.stderr,
        )
        return None

    # 未开赛的场次接口返回 -1。
    home_score = str(raw.get("hscore"))
    away_score = str(raw.get("gscore"))
    completed = home_score.lstrip("-").isdigit() and away_score.lstrip("-").isdigit() \
        and int(home_score) >= 0 and int(away_score) >= 0

    if requested.get("round"):
        stage = f"第{requested['round']}轮"
    else:
        stage = str(raw.get("type") or requested.get("type") or "").strip()
    if not stage:
        return None

    match_id = str(raw.get("id") or "")
    if competition.key == "round":
        uid = f"guoan-2026-round-{int(requested['round']):02d}"
    else:
        uid = f"guoan-2026-{competition.key}-{match_id}"

    return Match(
        competition=competition,
        stage=stage,
        home=team_name(home),
        away=team_name(away),
        dtstart=start.strftime("%Y%m%dT%H%M%S"),
        dtend=(start + MATCH_DURATION).strftime("%Y%m%dT%H%M%S"),
        venue=str(raw.get("stadium") or "").strip() or None,
        completed=completed,
        home_score=int(home_score) if completed else None,
        away_score=int(away_score) if completed else None,
        uid=uid,
    )


def drop_shared_kickoffs(matches: dict[str, Match]) -> dict[str, Match]:
    """丢掉多场共用同一开赛时间的未完赛场次。

    国安不可能在同一分钟开两场球，所以成批相同的 games_time 只能是数据源给未定时
    场次填的占位值（不限于 PLACEHOLDER_KICKOFF 里的那两个时间点）。已完赛的场次有
    比分佐证，时间是真的，不参与剔除。
    """
    by_start: dict[str, list[Match]] = {}
    for match in matches.values():
        by_start.setdefault(match.dtstart, []).append(match)

    dropped: set[str] = set()
    for dtstart, group in sorted(by_start.items()):
        suspects = [match for match in group if not match.completed] if len(group) > 1 else []
        if not suspects:
            continue
        dropped.update(match.uid for match in suspects)
        names = "、".join(f"{match.home} vs {match.away}" for match in suspects)
        print(
            f"跳过共用开赛时间 {dtstart} 的 {len(suspects)} 场比赛（数据源占位值）：{names}",
            file=sys.stderr,
        )
    return {uid: match for uid, match in matches.items() if uid not in dropped}


def fetch_matches() -> dict[str, Match]:
    """抓取三项赛事里国安的全部场次，按 UID 索引。失败的赛事跳过而不中断。"""
    matches: dict[str, Match] = {}
    for competition in COMPETITIONS:
        try:
            stages = stage_list(competition)
        except Exception as exc:
            print(f"{competition.label}赛程接口不可用，跳过：{exc}", file=sys.stderr)
            continue

        found = 0
        for requested in stages:
            try:
                payload = api_get("schedules", {"id": competition.match_id, **requested})
            except Exception as exc:
                print(f"{competition.label} {requested} 拉取失败，跳过：{exc}", file=sys.stderr)
                continue
            for raw in payload.get("data") or []:
                if not isinstance(raw, dict):
                    continue
                match = build_match(competition, raw, requested)
                if match:
                    matches[match.uid] = match
                    found += 1
        print(f"{competition.label}: 抓到国安 {found} 场（共 {len(stages)} 个分段）")
    return drop_shared_kickoffs(matches)


def has_score(props: dict[str, list[str]]) -> bool:
    summary = text_unescape(prop_value(first_prop(props, "SUMMARY") or ""))
    return summary.startswith("✅")


def split_alarm(event_lines: list[str]) -> tuple[list[str], list[str]]:
    """把 VEVENT 内容拆成普通属性行与 VALARM 块。"""
    property_lines: list[str] = []
    alarm_lines: list[str] = []
    in_alarm = False
    for line in event_lines:
        if line == "BEGIN:VALARM":
            in_alarm = True
        if in_alarm:
            alarm_lines.append(line)
            if line == "END:VALARM":
                in_alarm = False
        else:
            property_lines.append(line)
    return property_lines, alarm_lines


def pending_matches(events: list[list[str]], now: datetime) -> list[str]:
    """列出「已经开赛够久、但 ICS 里还没有比分」的比赛，空列表代表无需联网。"""
    pending: list[str] = []
    for event in events:
        property_lines, _ = split_alarm(event)
        props = event_props(property_lines)
        start = parse_dtstart(prop_value(first_prop(props, "DTSTART") or ""))
        if start is None or has_score(props):
            continue
        if now - PENDING_LOOKBACK <= start <= now - SCORE_READY_AFTER:
            pending.append(text_unescape(prop_value(first_prop(props, "SUMMARY") or "")))
    return pending


def build_summary(match: Match) -> str:
    title = f"{match.competition.label}{match.stage}"
    if match.completed:
        return f"✅ {title}: {match.home} {match.home_score}-{match.away_score} {match.away}"
    return f"⚽ {title}: {match.home} vs {match.away}"


def extract_line(description: str, prefix: str) -> str | None:
    for line in description.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def build_description(match: Match, old_description: str, venue: str | None) -> str:
    side = "主场" if match.home == TEAM else "客场"
    lines = [
        f"{match.competition.label}{match.stage} | {side}",
        f"{match.home} vs {match.away}",
    ]
    if match.completed:
        score_line = f"赛果: {match.home} {match.home_score}-{match.away_score} {match.away}"
        # 比分没变就沿用原来的更新时间，避免每次运行都产生无意义的改动。
        old_score = extract_line(old_description, "赛果:")
        old_updated = extract_line(old_description, "比分更新时间:")
        if old_updated and old_score and f"赛果: {old_score}" == score_line:
            updated_at = old_updated
        else:
            updated_at = f"北京时间 {beijing_now()}"
        lines.extend([score_line, "状态: 已完赛", f"比分更新时间: {updated_at}"])
    if venue:
        lines.append(f"场地: {venue}")
    start = parse_dtstart(match.dtstart)
    if start:
        lines.append(f"北京时间 {start.strftime('%H:%M')}")
    return "\n".join(lines)


def build_event(match: Match, old_event: list[str] | None, now_utc: str) -> tuple[list[str], bool]:
    """生成一个 VEVENT，返回 (行, 是否有实质变化)。"""
    old_property_lines, old_alarm = split_alarm(old_event or [])
    props = event_props(old_property_lines)

    # 接口对未开赛场次不返回球场，此时保留 ICS 里已有的场地，不要覆盖成空。
    venue = match.venue or prop_value(first_prop(props, "LOCATION") or "") or None

    old_description = text_unescape(prop_value(first_prop(props, "DESCRIPTION") or ""))
    summary = build_summary(match)
    description = build_description(match, old_description, venue)
    dtstart = f"DTSTART;TZID=Asia/Shanghai:{match.dtstart}"
    dtend = f"DTEND;TZID=Asia/Shanghai:{match.dtend}"
    location = f"LOCATION:{text_escape(venue)}" if venue else None

    changed = (
        old_event is None
        or text_unescape(prop_value(first_prop(props, "SUMMARY") or "")) != summary
        or old_description != description
        or (first_prop(props, "DTSTART") or "") != dtstart
        or (first_prop(props, "DTEND") or "") != dtend
        or (first_prop(props, "LOCATION") or None) != location
    )

    try:
        sequence = int(prop_value(first_prop(props, "SEQUENCE") or "SEQUENCE:0"))
    except ValueError:
        sequence = 0
    if changed and old_event is not None:
        sequence += 1

    created = prop_value(first_prop(props, "CREATED") or f"CREATED:{now_utc}")
    stamp = now_utc if changed else prop_value(first_prop(props, "DTSTAMP") or f"DTSTAMP:{now_utc}")
    modified = now_utc if changed else prop_value(
        first_prop(props, "LAST-MODIFIED") or f"LAST-MODIFIED:{now_utc}"
    )

    output = [
        "BEGIN:VEVENT",
        f"UID:{match.uid}",
        f"DTSTAMP:{stamp}",
        f"CREATED:{created}",
        f"LAST-MODIFIED:{modified}",
        f"SEQUENCE:{sequence}",
        dtstart,
        dtend,
        f"SUMMARY:{text_escape(summary)}",
        f"DESCRIPTION:{text_escape(description)}",
    ]
    if location:
        output.append(location)
    output.extend(
        [
            "CLASS:PUBLIC",
            f"CATEGORIES:北京国安,{match.competition.label}",
            # 保留 LOCATION 方便查看场地，但关掉 Apple 日历的「该出发了」路况提醒。
            "X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:DISABLED",
            "STATUS:CONFIRMED",
            "TRANSP:OPAQUE",
        ]
    )
    output.extend(old_alarm or DEFAULT_ALARM)
    output.append("END:VEVENT")
    return output, changed


def event_sort_key(event: list[str]) -> tuple[str, str]:
    props = event_props(split_alarm(event)[0])
    return (
        prop_value(first_prop(props, "DTSTART") or ""),
        prop_value(first_prop(props, "UID") or ""),
    )


def build_calendar(events: list[list[str]], matches: dict[str, Match]) -> tuple[str, int, int, int]:
    now = utc_now()
    existing = {
        prop_value(first_prop(event_props(split_alarm(event)[0]), "UID") or ""): event
        for event in events
    }

    rendered: list[list[str]] = []
    changed = added = 0
    for uid, match in matches.items():
        event, is_changed = build_event(match, existing.get(uid), now)
        rendered.append(event)
        changed += int(is_changed)
        added += int(uid not in existing)

    # 接口里没有对应记录的事件原样保留，避免数据缺失时把已有赛程抹掉。
    for uid, event in existing.items():
        if uid not in matches:
            rendered.append(["BEGIN:VEVENT", *event, "END:VEVENT"])

    rendered.sort(key=lambda event: event_sort_key(event[1:-1]))

    output = ["BEGIN:VCALENDAR", *CALENDAR_HEADER, *CALENDAR_TIMEZONE]
    for event in rendered:
        output.extend(event)
    output.append("END:VCALENDAR")

    folded: list[str] = []
    for line in output:
        folded.extend(fold_line(line))
    return "\r\n".join(folded) + "\r\n", changed, added, len(rendered)


def main() -> int:
    parser = argparse.ArgumentParser(description="Update Beijing Guoan ICS schedule and results.")
    parser.add_argument("--ics", default="beijing-guoen-2026.ics", help="要更新的 ICS 文件")
    parser.add_argument("--full", action="store_true", help="跳过赛后判断，做一次全量对账")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不写文件")
    args = parser.parse_args()

    ics_path = Path(args.ics)
    _, _, events = parse_ics(ics_path)
    print(f"读取 {ics_path}：{len(events)} 个事件")

    if not args.full:
        pending = pending_matches(events, datetime.now(BEIJING_TZ))
        if not pending:
            print("没有刚结束待回填比分的比赛，跳过更新。")
            return 0
        print(f"待回填比分 {len(pending)} 场：" + "；".join(pending))

    matches = fetch_matches()
    if not matches:
        print("所有赛事接口都没有返回数据，保持 ICS 不变。", file=sys.stderr)
        return 0

    content, changed, added, total = build_calendar(events, matches)
    scored = sum(1 for match in matches.values() if match.completed)
    summary = f"{total} 个事件，其中新增 {added}、变更 {changed}、已完赛 {scored}"

    if args.dry_run:
        print(f"[dry-run] 将写入 {summary}")
        return 0

    payload = content.encode("utf-8")
    if ics_path.read_bytes() == payload:
        print(f"ICS 无需改动（{summary}）")
        return 0

    ics_path.write_bytes(payload)
    print(f"已更新 {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
