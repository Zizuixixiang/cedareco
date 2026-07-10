# human_action 人类前端协作接口契约

引擎侧统一入口：`engine.human_action(state, action, payload=None)`。
供上层服务在人类于前端完成一次灾害小游戏后调用，上报本次操作结果。

## 总原则

- **人机操作独立累计、互不阻塞**：人类与小机各自的计数分开存（`human_*` / `ai_*`），判定阈值时合并。不存在"小机先做了人类白等"。
- **不推进天数、不写盘**：只改内存 `state`，是否持久化由上层决定。
- **不触碰主 RNG 序列**：`rng_state` 调用前后不变；文案与回访延迟全部确定性取值。
- **不在对应灾害/季节中直接拒绝**：返回 `ok=False` 与明确错误码，前端应先通过只读 API 确认灾害在场再开小游戏。

## 返回值

成功：

```json
{"ok": true, "action": "...", "message": "一句给人看的结果文案",
 "events": ["achievement:🏆 解锁成就【驱逐者】…"],
 "summary": { "...action 专属状态摘要..." }}
```

失败：

```json
{"ok": false, "action": "...", "error": "错误码", "message": "原因说明"}
```

通用错误码：`unknown_action`（action 不认识）、`bad_payload`（payload 缺失/类型不对/非法值）、`not_active`（当前不在对应灾害/季节中）。

## 各 action 契约

### expel_turtle —— 驱赶巴西龟

- **前置**：`flags.brazilian_turtle == "active"`。龟被赶走暂离期间（`expelled_once`）与彻底离开后（`gone`）都返回 `not_active`。
- **payload**：无。
- **效果**：`flags.human_expel_count += 1`；人机合计（`human_expel_count + ai_expel_count`）≥2 → 龟彻底离开（`gone`，解锁成就「驱逐者」）；合计 1 → 龟暂离（`expelled_once`），1-3 天后回访（确定性延迟 `1 + turn % 3`）。回访是同一只，累计保留；下一只新龟入侵时人机累计清零。若存在同名待决策（小机还没选），自动撤销。
- **summary**：`turtle`（gone / expelled_once）、`human_expel_count`、`ai_expel_count`、`total_expel_count`、`return_day`（仅暂离时）、`interrupted_wait_days`（撤销待决策时被打断的 wait 天数，无则 0）。

### catch_snail —— 捞福寿螺

- **前置**：`flags.apple_snail == "active"` 或 `{"status":"clearing",...}`（螃蟹清剿中也可捞）。
- **payload**：无。
- **效果**：等同小机在决策中选「手动捞」——一次清光：`apple_snail = "gone"`，碎屑 +10，写年鉴；`flags.human_snail_catch_count += 1`；撤销同名待决策。
- **summary**：`apple_snail`、`human_snail_catch_count`、`detritus`、`interrupted_wait_days`。

### pull_hyacinth —— 拔水葫芦

- **前置**：`flags.water_hyacinth` 为 dict 且已成势（`turn >= day + 3`；前 3 天潜伏期拒绝）。
- **payload**：`{"cover": 本次减少的覆盖率}`，数值，>0。服务端 clamp 单次上限 **0.15**（`HUMAN_PULL_MAX`，防作弊；对比：水葫芦每天自然增长 0.04）。
- **效果**：`cover` 减去 clamp 后的量；根须带泥，浑浊度 +0.05。累计拔除量记在 `water_hyacinth.human_pull`。拔到 0 → 水葫芦清除（`water_hyacinth = None`，写年鉴，撤销同名待决策）。
- **summary**：`applied`（实际削减）、`cover_left`、`human_pull_total`、`cleared`、`interrupted_wait_days`（仅 cleared 时有意义）。

### hunt_rat —— 鼠患打地鼠

- **前置**：`flags.bio_disasters["鼠患"]` 存在。
- **payload**：`{"count": 本次打到的田鼠数}`，整数，>0，默认 1。服务端 clamp 单次上限 **5**（`HUMAN_RAT_MAX`）。
- **效果**：田鼠种群 -N（不低于 0），命中数累计在 `鼠患.human_hits`。田鼠降到 **≤5 只**（`RAT_CALM_THRESHOLD`，与逐日破坏阈值对齐）→ 鼠患当场平息（移除 `bio_disasters["鼠患"]`）。
- **summary**：`hits`（实际打掉）、`rats_left`、`human_hits_total`、`plague_over`。

### skim_algae —— 绿潮捞藻（人类专属）

- **前置**：`flags.bio_disasters["绿潮"]` 存在。**每个游戏日限一次**（重复调用返回 `already_today`）。
- **payload**：`{"amount": 本次捞走的藻量}`，数值，>0。服务端 clamp 单次上限 **50**（`HUMAN_SKIM_MAX`）。
- **效果**：水藻种群按实际可捞量减少；累计记在 `绿潮.human_skim_total`。
  - 达标（amount ≥ **20**，`HUMAN_SKIM_TARGET`）：`remaining -= 1`，绿潮缩短 1 天；缩到 0 当场结束。
  - 未达标：次日 tick 绿潮溶氧扣减减半（-0.4 而非 -0.8，`绿潮.do_relief_day` 标记）。
- **summary**：`applied`、`algae_left`、`target_met`、`ended`、`remaining_days`、`human_skim_total`。
- 绿潮基础时长不变（触发时随机 3-5 天），人类捞藻只会缩短。

### crack_ice —— 凿冰

- **前置**：冬季且 `flags.ice_on == True`；受 `flags.crack_count` **每冬 3 次共享上限**约束（人机合用，超限返回 `crack_limit`）。
- **payload**：无。人类凿冰不消耗碎屑（小机凿冰仍需碎屑 5）。
- **效果**：`crack_count += 1`、`human_crack_count += 1`；与小机凿冰同效开 3 天 `ice_hole`（每天溶氧 +0.3）；次日冰窒息值不涨（`ice_suff_pause_day = turn + 1`）。
- **summary**：`crack_count`、`human_crack_count`、`ice_suffocation`（当前窒息值）、`pause_day`。

## 新增/改动字段清单

`flags` 新增（`fresh_state` 与 `_migrate` 均已覆盖，旧档自动补默认）：

| 字段 | 默认 | 说明 |
|---|---|---|
| `ai_expel_count` | 0 | 小机驱赶巴西龟累计（同一只回访不清零；新龟入侵清零） |
| `human_expel_count` | 0 | 人类驱赶巴西龟累计（合计 ≥2 → gone） |
| `human_snail_catch_count` | 0 | 人类捞福寿螺累计次数 |
| `human_crack_count` | 0 | 本冬人类凿冰次数（计入 `crack_count` 共享上限，春季重置） |
| `ice_suffocation` | 0 | 冰窒息值：结冰期每天 +1；凿冰成功次日不涨；冰融/入春清零 |
| `ice_suff_pause_day` | -1 | 该游戏日不涨窒息值（人机凿冰都会设置） |

灾害子结构按需新增（缺省不存在，`.get` 兼容旧档）：

- `flags.water_hyacinth.human_pull`：人类累计拔除覆盖率。
- `flags.bio_disasters["绿潮"]`：`human_skim_day`（当日已捞标记）、`human_skim_total`、`do_relief_day`（次日溶氧减压标记）。
- `flags.bio_disasters["鼠患"].human_hits`：人类累计命中。

行为改造：

- **巴西龟改累计器**：原 `expelled_once` 单标记语义改由人机计数器驱动，`flags.brazilian_turtle` 状态串（None/active/expelled_once/gone）保留不变。小机独走路径行为与文档语义等价：赶一次暂离回访、再赶一次 gone。（注：旧代码中"再赶一次 gone"分支实际不可达——回访会把标记重置回 active，本次累计器顺带修复了这一点，「驱逐者」成就现在可正常达成。）
- **绿潮可缩短**：默认时长 3-5 天不变，人类 skim 达标逐日缩短、未达标次日少扣溶氧。
- **冰窒息值**：新增纯累积量表（`ice_suffocation`），结冰期每天 +1，凿冰当天不涨；目前不参与任何判定，供前端/小机读数，无人类操作时对模拟零影响。
- **灾害文本人类提示**：巴西龟/福寿螺/水葫芦/绿潮/鼠患/结冰的事件行末尾追加"（人类可在前端帮忙XX）"（`HUMAN_HELP_HINT`），仅提示文案，不改判定；小机可据此决定是否喊人。

## 旧档迁移点（`_migrate`，load/import 两条路径都走）

1. 新增 flags 全部经 `fresh_state` 基准 setdefault 自动补默认，旧档不崩、无人类操作时行为不突变（已用 5 seeds × 400 tick 对比 HEAD 验证：`rng_state` 逐日一致、每日输出除上述提示句外逐字一致、终态除新字段外一致）。
2. `brazilian_turtle == "expelled_once"` 且两计数器均为 0 → 视为小机已累计 1（`ai_expel_count = 1`），人类或小机再赶一次即 gone。

## 回归入口

`python3 scripts/verify_human_action.py` —— 六个 action 生效/拒绝、防作弊 clamp、巴西龟等价性与迁移、绿潮缩短/减压、冰窒息值、旧档兼容，全量断言。
