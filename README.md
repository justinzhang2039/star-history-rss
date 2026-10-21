# Star History 周榜 RSS 订阅

本仓库通过 GitHub Actions 自动生成 [Star History](https://www.star-history.com) 周榜 RSS 订阅源。

## 功能说明

订阅源会在以下情况推送新条目：

1. **🆕 新进榜单 Top20** — 有新项目进入滚动周榜前 20
2. **🔥 新进前 5** — 有新项目进入前 5（该条目会列出当前前 5 及各自近 7 天新增星数）

数据来源：Star History 网站左侧栏 "Weekly" 榜单公布的 7 天统计窗口。曾观察到窗口按日移动；上游当前没有已核实的每日发布时间承诺。

## 订阅地址

```
https://raw.githubusercontent.com/justinzhang2039/star-history-rss/main/star-history-weekly.xml
```

将此链接添加到你的 RSS 阅读器即可订阅。

## 更新频率

GitHub Actions 每天计划于 01:30 和 13:30 UTC 各检查一次（约北京时间 09:30 和 21:30，实际运行可能延迟）。检查频率、上游生成频率、RSS 产生新条目的频率是三件不同的事：榜单可以更新而没有符合规则的新条目，RSS 无新条目不能单独证明数据过期。

生成脚本、测试或工作流修改合入 `main` 时也会检查一次；自动生成的数据提交不会触发循环。PR 只运行回归测试，不写订阅数据。

## 2026-10-21 新鲜度诊断

约 11:54 UTC 实测，[官网](https://www.star-history.com/)与其[实际数据包](https://www.star-history.com/assets/index-Opgt0na-.js)均公布 **10 月 12–18 日**窗口，和仓库状态一致；同包总榜日期已是 10 月 20 日。旧脚本当天读到的确实是上游当前公布的数据，`window unchanged` 并非此次停留在 18 日的原因。

[PR #1](https://github.com/justinzhang2039/star-history-rss/pull/1)的初始快照为 10 月 11–17 日，随后移动至 12–18 日，不能把当前不变简单解释为“自然周榜正常等下周”。公开的[旧上游生成代码](https://github.com/star-history/star-history/blob/608d0e39be441665c01cd6ac1fd01ca5ec1eaf39/gh/star-fetch.ts)与现网版本不同；目前无法确认延迟发生在上游采集、计算还是发布环节，也无法确认它的正常延迟上限。

旧机制确有两个缺口：仅比较窗口会遗漏同一窗口内的数据修订；工作流成功不代表源数据新鲜。现在每次验证完整榜单，并比较窗口和内容摘要；同窗口修订也会处理，重复运行按原有 GUID 去重，拒绝窗口倒退。已有有效条目保留，不靠强制生成条目表示“更新过”。

## 如何判断运行状态

每次检查写入 `health.json`，并在 Actions 摘要中展示结果：

| 字段 | 含义 |
| --- | --- |
| `checked_at` | 最近一次检查时间，含失败检查 |
| `last_successful_fetch_at` | 最近一次成功获取并接受有效榜单的时间 |
| `source_window` / `accepted_window` | 本次观察窗口 / 已接受窗口；出错时应结合 `error` 判断 |
| `source_asset_url` / `source_hash` | 数据包地址 / 已接受榜单内容摘要 |
| `window_first_observed_at` | 首次观察到当前窗口的时间 |
| `source_age_hours` | 统计结束日结束后已过去的小时数，按 UTC 计算 |
| `status` / `error` | `fresh`、`stale`、`error`，及错误原因 |
| `content_changed` / `new_items` | 榜单内容是否变化 / 本次新增 RSS 条目数 |

默认 `MAX_SOURCE_AGE_HOURS=48`：从统计结束日之后的 **UTC 零点**起算，未超过 48 小时为 `fresh`，超过为 `stale`。这是本仓库可调整的运行策略，**不是上游 SLA**。例如窗口结束于 10 月 18 日，起算点为 19 日 00:00 UTC；21 日 11:54 已约 60 小时，属于过期告警。

- 窗口未变且 `fresh`：在本地容忍范围内等待；不重复推送。
- `stale`：已成功取到数据，但公布窗口超出容忍范围；标记疑似上游滞后，不能据此断言生产任务故障。若有效窗口仍有推进，可保存其数据，健康检查仍失败。
- `error`：网络、解析、数据校验或窗口倒退等错误；记录原因，保留原有效状态和 RSS，不把失败当作“没有变化”。

工作流先保存并提交健康记录，再以 `health.json` 的状态执行最终检查；`stale` 或 `error` 都会使工作流失败。单独运行脚本遇到 `stale` 会记录告警但返回 0，自动化调用方必须检查 `status`；抓取或解析错误返回非零。`--force` 仅保留兼容性，不绕过校验、去重或新鲜度策略。

还应区分“脚本运行后发现上游旧”和“脚本根本没运行”：手动查看 `checked_at`，若距现在超过 **36 小时**，检查 Actions 是否停用、延迟或运行失败；结合 `last_successful_fetch_at` 判断是否持续抓取失败。此项是排查指引，仓库未另建监控服务。

## 手动触发

1. 进入本仓库的 **Actions** 页面
2. 左侧选择 **Update Star History RSS Feed**
3. 点击 **Run workflow** → **Run workflow**

或使用 GitHub CLI：

```bash
gh workflow run update-feed.yml
```

## 本地验证（保留正式数据）

先运行回归测试：

```bash
python3 -m unittest -v
```

再用当前状态的临时副本实测，不直接覆盖正式文件：

```bash
rss_check_dir=$(mktemp -d)
cp state.json star-history-weekly.xml "$rss_check_dir/"
if [ -f health.json ]; then
  cp health.json "$rss_check_dir/"
fi
STATE="$rss_check_dir/state.json" \
OUT="$rss_check_dir/star-history-weekly.xml" \
HEALTH="$rss_check_dir/health.json" \
MAX_SOURCE_AGE_HOURS=48 \
python3 star_weekly_feed.py

python3 - "$rss_check_dir/health.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as source:
    health = json.load(source)
print(json.dumps(health, ensure_ascii=False, indent=2))
sys.exit(0 if health["status"] == "fresh" else 1)
PY
```

若需调整容忍时间，本地设置环境变量 `MAX_SOURCE_AGE_HOURS`，Actions 在仓库 Settings → Secrets and variables → Actions → Variables 设置同名变量；不要仅为消除失败状态放宽阈值，应先核对源窗口与上游证据。
