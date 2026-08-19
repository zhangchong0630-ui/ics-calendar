# ICS Calendar Subscriptions

日历订阅文件托管仓库。

## 订阅链接

- ⚽ 2026美加墨世界杯小组赛：`https://raw.githubusercontent.com/zhangchong0630-ui/ics-calendar/main/worldcup2026_groupstage.ics`
- ⚽ 北京国安2026赛季：`https://raw.githubusercontent.com/zhangchong0630-ui/ics-calendar/main/beijing-guoen-2026.ics`

## 订阅方式

1. 打开日历App（Apple日历 / Google Calendar / Outlook）
2. 选择“添加订阅日历”
3. 粘贴上面的 .ics 链接
4. 确认订阅

更新赛程后 push 新文件即可，订阅链接自动生效。

## 北京国安比分更新

`beijing-guoen-2026.ics` 一个文件包含国安本赛季**中超、足协杯、亚冠精英联赛**的全部比赛，按时间排序，每场保留提前 1 小时提醒。事件标题区分是否完赛：

```
⚽ 中超第22轮: 北京国安 vs 深圳新鹏城
✅ 中超第21轮: 北京国安 2-1 浙江俱乐部绿城
✅ 足协杯1/8决赛: 大连可为 1-2 北京国安
```

数据源是直播吧数据频道背后的公开接口 `db.qiumibao.com`（赛事 id：中超 353、足协杯 352、亚足联冠军精英联赛 392），返回中文队名、中文球场与北京时间，无需 API key。

### 更新规则

`scripts/update_guoan_scores.py` 由 GitHub Actions 调度，**不是每天无条件刷新**：

- **赛后模式**（北京时间 17:00–次日 01:00 每小时）：先读 ICS 判断有没有「已开赛超过 2.5 小时、但还没有比分」的比赛。没有就直接退出，不请求接口、不产生提交；有才联网回填比分。
- **全量对账**（每周一北京时间 11:07，或手动触发时勾选 full）：跳过上面的判断完整同步一次，用于抓改期、新阶段赛程和亚冠赛程公布。

其他行为：

- 开球时间和球场以接口为准，改期会自动同步 `DTSTART`/`DTEND` 并递增 `SEQUENCE` 通知订阅端；接口对未开赛场次不返回球场，此时保留 ICS 里已有的 `LOCATION`，不会覆盖成空。
- 比分没变时沿用原来的“比分更新时间”，避免每次运行都产生无意义的改动。
- 接口里查不到对应记录的事件原样保留，不会因为数据缺失把已有赛程抹掉。
- 超过 14 天仍无比分的比赛视为延期（例如 2026 第 18 轮客场对申花因台风延期、补赛待定），交给每周全量对账处理，不会让赛后模式一直空跑。
- 足协杯、亚冠的新比赛在接口出现真实对阵后自动追加，不提前写占位赛程。亚冠精英联赛联赛阶段 8 场已于 2026-08-18 抽签后公布并收录。
- 赛程刚公布时接口会对尚未定时的场次返回假时间做占位，这类场次会被跳过、等下次抓到真实时间再收录，并在 Actions 日志里打出跳过原因。识别两种占位：开球时间落在 23:59 / 00:00，或多场未完赛比赛共用同一个开赛时间（国安不可能同一分钟开两场球）。
- 保留 `LOCATION` 方便查看场地，同时设置 `X-APPLE-TRAVEL-ADVISORY-BEHAVIOR:DISABLED`，避免 Apple 日历对客场比赛弹出“该出发了”的路况提醒。

本地手动跑：

```bash
python3 scripts/update_guoan_scores.py --dry-run   # 只看会改什么
python3 scripts/update_guoan_scores.py --full      # 全量对账并写入
```

## 世界杯比分更新

`worldcup2026_groupstage.ics` 由 `scripts/update_worldcup_scores.py` 读取 FIFA 赛程与赛果数据生成。已完赛比赛在日历标题中显示比分，未开赛比赛保持赛程标题，时间统一按北京时间写入。

2026 世界杯已于 7 月结束、赛果不再变化，**定时任务已关闭**；如需再跑一次，在 Actions 页面手动触发 “Update World Cup results”。

为避免 Apple 日历触发“从当前位置出发到比赛地”的路况提醒，世界杯 ICS 不使用 `LOCATION` 字段，场馆信息保留在事件详情里。

## 脚本结构

- `scripts/icslib.py` — 两个更新脚本共用的 ICS 文本工具（折行、转义、解析）
- `scripts/update_guoan_scores.py` — 北京国安赛程与比分
- `scripts/update_worldcup_scores.py` — 世界杯赛程与比分
