#!/usr/bin/env python3
"""用球迷宝赛事数据更新北京首钢 ICS 的赛程与比分。

数据源为直播吧数据频道背后的公开接口 db.qiumibao.com，与国安脚本同源：
CBA 联赛 id 925，用 season 参数一次取回整季赛程。常规赛、季后赛、俱乐部杯
都在同一份数据里，季后赛公布后会自动出现，无需另找接口或改代码。

只保留北京首钢自己的场次（按球队 id 过滤），不收录其他球队的比赛。

默认只在「有比赛刚结束但 ICS 里还没有比分」时才联网，其余情况直接退出，
不请求接口也不改文件。--full 跳过这个判断，做一次全量对账（抓改期、
新阶段赛程、季后赛公布等）。
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
# 中国男子篮球职业联赛（CBA）
LEAGUE_ID = "925"
# CBA 赛季命名：2026 即 2026-27 赛季（2026-10 开打，2027-06 结束）
SEASON = "2026"
# 北京北汽（首钢）在数据源里的球队 id
TEAM_ID = "6936"
# 显示名：数据源用简称「北京」，日历里用球迷习惯的叫法
TEAM_NAME = "北京首钢"

# 计入日历的赛事。季前赛、夏季联赛、潜力赛、全明星、选秀等不计入。
INCLUDED_TYPES = ("常规赛", "季后赛", "俱乐部杯")

# 一场篮球比赛按 2 小时计；也用作「开赛多久之后才认为该有比分了」的阈值。
MATCH_DURATION = timedelta(hours=2)
SCORE_READY_AFTER = timedelta(hours=2, minutes=30)
# 超过这个天数仍无比分的，视为延期或数据缺失，交给每周全量对账处理，
# 不再让赛后模式每小时空跑。
PENDING_LOOKBACK = timedelta(days=14)

# 赛程刚排定、时间未定时，接口可能返回一个格式合法的占位时间。
PLACEHOLDER_KICKOFF = {(23, 59), (0, 0)}

# 数据源对篮球不返回场馆；主场比赛统一用球队资料里的主场馆。
HOME_VENUE = "首钢冰球馆、首都体育馆"

CALENDAR_HEADER = [
    "VERSION:2.0",
    "PRODID:-//BeijingShougangCalendar//CN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "X-WR-CALNAME:北京首钢2026赛季",
    "X-WR-TIMEZONE:Asia/Shanghai",
    "X-WR-CALDESC:北京首钢2026赛季赛程（CBA常规赛/季后赛/俱乐部杯，主队在前），赛后自动更新比分",
    "X-WR-RELCALID:BeijingShougang-2026",
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
    match_type: str       # 常规赛 / 季后赛 / 俱乐部杯
    stage: str            # 第21轮（季后赛、俱乐部杯没有轮次时为空）
    is_home: bool
    home: str
    away: str
    dtstart: str          # 20261018T193500
    dtend: str
    venue: str | None
    completed: bool
    home_score: int | None
    away_score: int | None
    half_home: int | None
    half_away: int | None
    uid: str

    @property
    def title_prefix(self) -> str:
        return f"{self.match_type}{self.stage}"


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


def to_score(value: Any) -> int | None:
    """接口用 -1 表示未开赛，其余负数/非数字视为无效。"""
    text = str(value if value is not None else "").strip()
    if not text.lstrip("-").isdigit():
        return None
    number = int(text)
    return number if number >= 0 else None


def build_match(raw: dict[str, Any]) -> Match | None:
    home_id = str(raw.get("hteam_id") or "")
    away_id = str(raw.get("gteam_id") or "")
    if TEAM_ID not in (home_id, away_id):
        return None

    match_type = str(raw.get("type") or "").strip()
    if match_type not in INCLUDED_TYPES:
        return None

    try:
        start = datetime.strptime(str(raw.get("games_time")), "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING_TZ)
    except ValueError:
        return None

    if (start.hour, start.minute) in PLACEHOLDER_KICKOFF:
        print(
            f"跳过 {raw.get('hteam_name')} vs {raw.get('gteam_name')}："
            f"开赛时间 {raw.get('games_time')} 是数据源的待定占位值",
            file=sys.stderr,
        )
        return None

    is_home = home_id == TEAM_ID
    home_score = to_score(raw.get("hscore"))
    away_score = to_score(raw.get("gscore"))
    completed = home_score is not None and away_score is not None

    # 常规赛有轮次；季后赛与俱乐部杯的 round 恒为 0，只用赛事名。
    stage = ""
    if match_type == "常规赛":
        round_no = str(raw.get("round") or "").strip()
        if round_no.isdigit() and int(round_no) > 0:
            stage = f"第{int(round_no)}轮"

    match_id = str(raw.get("id") or "")
    if not match_id:
        return None

    return Match(
        match_type=match_type,
        stage=stage,
        is_home=is_home,
        home=TEAM_NAME if is_home else str(raw.get("hteam_name") or ""),
        away=TEAM_NAME if not is_home else str(raw.get("gteam_name") or ""),
        dtstart=start.strftime("%Y%m%dT%H%M%S"),
        dtend=(start + MATCH_DURATION).strftime("%Y%m%dT%H%M%S"),
        venue=str(raw.get("stadium") or "").strip() or (HOME_VENUE if is_home else None),
        completed=completed,
        home_score=home_score,
        away_score=away_score,
        half_home=to_score(raw.get("hhalf_score")),
        half_away=to_score(raw.get("ghalf_score")),
        uid=f"shougang-{SEASON}-{match_id}",
    )


def fetch_matches(season: str) -> dict[str, Match]:
    """一次取回整季赛程（含季后赛），只留北京首钢的场次，按 UID 索引。"""
    payload = api_get("schedules", {"id": LEAGUE_ID, "season": season})
    rows = payload.get("data") or []
    if not isinstance(rows, list):
        return {}

    matches: dict[str, Match] = {}
    counts: dict[str, int] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        match = build_match(raw)
        if match:
            matches[match.uid] = match
            counts[match.match_type] = counts.get(match.match_type, 0) + 1

    detail = "、".join(f"{k} {v} 场" for k, v in sorted(counts.items())) or "无"
    print(f"赛季 {season}：接口返回 {len(rows)} 场，其中北京首钢 {len(matches)} 场（{detail}）")
    return matches


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
    if match.completed:
        return f"✅ {match.title_prefix}: {match.home} {match.home_score}-{match.away_score} {match.away}"
    return f"🏀 {match.title_prefix}: {match.home} vs {match.away}"


def extract_line(description: str, prefix: str) -> str | None:
    for line in description.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def build_description(match: Match, old_description: str, venue: str | None) -> str:
    side = "主场" if match.is_home else "客场"
    lines = [
        f"{match.title_prefix} | {side}",
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
        if match.half_home is not None and match.half_away is not None:
            lines.append(f"半场: {match.home} {match.half_home}-{match.half_away} {match.away}")
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
            f"CATEGORIES:北京首钢,{match.match_type}",
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
    parser = argparse.ArgumentParser(description="Update Beijing Shougang ICS schedule and results.")
    parser.add_argument("--ics", default="beijing-shougang-2026.ics", help="要更新的 ICS 文件")
    parser.add_argument("--season", default=SEASON, help="赛季年份，默认 2026")
    parser.add_argument("--full", action="store_true", help="跳过赛后判断，做一次全量对账")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不写文件")
    args = parser.parse_args()

    ics_path = Path(args.ics)
    if ics_path.exists():
        _, _, events = parse_ics(ics_path)
        print(f"读取 {ics_path}：{len(events)} 个事件")
    else:
        events = []
        print(f"{ics_path} 不存在，将新建")

    if not args.full and events:
        pending = pending_matches(events, datetime.now(BEIJING_TZ))
        if not pending:
            print("没有刚结束待回填比分的比赛，跳过更新。")
            return 0
        print(f"待回填比分 {len(pending)} 场：" + "；".join(pending))

    matches = fetch_matches(args.season)
    if not matches:
        print("接口没有返回北京首钢的任何场次，保持 ICS 不变。", file=sys.stderr)
        return 0

    content, changed, added, total = build_calendar(events, matches)
    scored = sum(1 for match in matches.values() if match.completed)
    summary = f"{total} 个事件，其中新增 {added}、变更 {changed}、已完赛 {scored}"

    if args.dry_run:
        print(f"[dry-run] 将写入 {summary}")
        return 0

    payload = content.encode("utf-8")
    if ics_path.exists() and ics_path.read_bytes() == payload:
        print(f"ICS 无需改动（{summary}）")
        return 0

    ics_path.write_bytes(payload)
    print(f"已更新 {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
