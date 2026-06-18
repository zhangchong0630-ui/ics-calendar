# ICS Calendar Subscriptions

日历订阅文件托管仓库。

## 订阅链接

- ⚽ 2026美加墨世界杯小组赛：`https://raw.githubusercontent.com/zhangchong0630-ui/ics-calendar/main/worldcup2026_groupstage.ics`
- ⚽ 北京国安2026中超：`https://raw.githubusercontent.com/zhangchong0630-ui/ics-calendar/main/beijing-guoen-2026.ics`

## 订阅方式

1. 打开日历App（Apple日历 / Google Calendar / Outlook）
2. 选择"添加订阅日历"
3. 粘贴上面的 .ics 链接
4. 确认订阅

更新赛程后 push 新文件即可，订阅链接自动生效。

## 世界杯比分更新

仓库已配置 GitHub Actions，每小时自动读取 FIFA 赛程与赛果数据并更新 `worldcup2026_groupstage.ics`。已完赛比赛会在日历标题中显示比分，未开赛比赛保持赛程标题，时间统一按北京时间写入。

小组赛结束后，脚本会继续检查淘汰赛阶段；只有 FIFA 数据中出现真实双方球队时，才会自动把下一阶段比赛追加到同一个 ICS 订阅文件里，不会提前添加空白占位赛程。

为避免 Apple 日历触发“从当前位置出发到比赛地”的路况提醒，世界杯 ICS 不使用 `LOCATION` 字段，场馆信息保留在事件详情里。
