# human_action 人类前端协作接口契约

统一入口：`engine.human_action(state, action, payload=None)`。除 `crack_ice` 的凿冰成功判定外，接口不推进天数、不写盘、不消耗主 PRNG。

返回成功结构为 `{"ok": true, "action", "message", "events", "summary"}`；失败结构为 `{"ok": false, "action", "error", "message"}`。通用错误包括 `unknown_action`、`bad_payload`、`not_active`、`already_helped`；凿冰同一方当天重复为 `already_today`。

人类成功协作后，引擎会将前端完成文案整理为“你的人类帮你……”通知：写入 `pending_human_notices`，在小机下一次执行有效指令时附在返回文本前并一次性消费；同一条通知也写入年鉴，供之后回看。协作失败不写通知或年鉴。

## 灾内协作次数总则

- 鼠患、福寿螺爆发阶段、水葫芦、绿潮：同一场灾害中，人类第一次成功提交后在该灾状态写入 `human_helped=true`；再次调用返回 `already_helped`。新一场灾害重新获得一次机会。
- 福寿螺卵块期是独立的一次预防机会，不占孵化后爆发阶段的次数；成功掐灭后卵块直接消失。
- 巴西龟豁免：沿用人机累计两次驱离制，每次龟回访形成新的决策窗口，人类在该窗口可帮一次。
- 凿冰豁免：人类和小机在每个结冰日各可尝试一次。

## 六个 action

### expel_turtle —— 驱赶巴西龟

- 前置：`flags.brazilian_turtle == "active"`。
- 人类与小机分别累计 `human_expel_count`、`ai_expel_count`；合计第一次令龟暂离，合计第二次令其彻底离开并解锁「驱逐者」。同一只龟回访不清累计，新龟入侵清零。
- `summary`：`turtle`、双方次数、合计次数、可选 `return_day`、`interrupted_wait_days`。

### catch_snail —— 按只捞福寿螺

- 卵块期：状态为 `{"status":"incubating","hatch_day":N}`。成功后卵块清除、碎屑 +3、`prevented=true`，不登记灾害；卵块固定 `turn+3` 孵化，期间不压制水藻。
- 爆发状态：`{"status":"active|clearing","count":0..12,"human_helped":bool}`。`payload={"count":正整数}`，按实际剩余只数 clamp 并逐只扣减。
- 剩余为 0 时当场设为 `"gone"`、碎屑 +10、撤销同名待决策并写清光文案；未清零则返回剩余只数，水藻压制从下一次增长计算起立即按新数量生效。
- 水藻出生率系数：`1 - (count / 12) * 0.3`，即 12 只 ×0.7、6 只 ×0.85、0 只解除。
- 小机「手动捞」清光全部剩余；「投放螃蟹」进入 `clearing`，固定每天吃 2 只，不新增掷骰。

### pull_hyacinth —— 按株拔水葫芦

- 前置：水葫芦已成势（`turn >= water_hyacinth.day + 3`）。
- `payload={"stalks":正整数}`；服务端 clamp 到实际剩余株数及单次最多 7 株（`HUMAN_PULL_STALK_MAX`）。每株削减覆盖率 0.02，根须带泥令浑浊度 +0.05。
- 拔光后清除灾害并撤销同名待决策。
- 小机选择「拔掉」时，原代价为浑浊 +0.15、碎屑 +5、浮萍 -10%、田螺 -30%、水黾 -30%；实际代价统一乘以 `当前剩余 cover / 成势触发时 outbreak_cover`。

### hunt_rat —— 打田鼠

- 前置：`flags.bio_disasters["鼠患"]` 存在。
- `payload={"count":正整数}`；服务端 clamp 为 `min(当前田鼠数, 12)`。
- 爆发时记录 `outbreak_count`。田鼠在任意结算点降到 `outbreak_count * 25%` 或以下，鼠患当场成功平息。
- 活跃期每天芦苇乘以 `1 - 当前田鼠数 * 0.012`，浑浊度增加 `当前田鼠数 * 0.008`。未平息则第三天散场，田鼠 ×0.75，并设置 10 个完整游戏日的再触发冷却。

### skim_algae —— 捞绿潮

- 前置：`flags.bio_disasters["绿潮"]` 存在。
- `payload={"amount":正数}`，单次最多 50，且不超过实际水藻量；实际捞量累计到 `human_skim_total`。
- 整场绿潮后续每天的扣氧减免为 `min(0.3, human_skim_total / 50 * 0.3)`，替代旧的“仅次日减半”。累计满 50 时额外令 `remaining -= 1`，只触发一次。
- 绿潮基础时长仍为 3–5 天，基础每日扣氧 0.8；典型初始溶氧下连续 5 天无人干预不会令鱼类灭绝。

### crack_ice —— 凿冰

- 前置：冬季且 `ice_on=true`。取消每冬三次上限；`crack_count` 仅统计本冬双方尝试总数，`human_crack_count` 统计人类尝试数。
- 人类与小机每天各限一次。当日第一方尝试时抽取一枚共享判定值：只有一方尝试按 40% 成功；若另一方同日加入，复用同一值并把联合阈值提升到 85%，不抽第二枚。
- 返回/命令文本均明确 `success`、是否 `joint_attempt` 以及双方当天是否尝试。
- 成功开启 `ice_hole`，覆盖后续 3 个 tick：每天溶氧 +0.3，且不增加 `ice_suffocation`。冰封无洞时翠鸟捕食成功率为 10%，有洞恢复到 25%。
- `ice_total_days` 记录结冰总天数；无有效洞的结冰日令 `ice_suffocation += 1`。春融时冬眠青蛙折损率为 `ice_suffocation / ice_total_days * 40%`，随后两项清零。
- 已删除旧的“水温低于 2℃连续 3 天 → hibernation_crisis → 青蛙固定 ×0.8”路径。

## 事件文本

巴西龟、福寿螺、水葫芦、绿潮、鼠患、结冰六个可协作场景都会自然告知小机“你的人类可以在前端帮忙……”；福寿螺卵块文本额外说明粉色卵串、小机够不着，以及人类可赶在孵化前清掉。

## 旧档迁移

- 缺失的新 flags 由 `_migrate` 从 `fresh_state` 补齐。
- 旧 `apple_snail == "active"` 升级为 12 只 active dict；旧 clearing dict 缺 `count` 时补 12。
- 旧 `brazilian_turtle == "expelled_once"` 且双方累计均缺失/为 0 时，视作小机已经驱赶一次。
- 旧的 `hibernation_crisis`、`winter_low_temp_days`、`ice_suff_pause_day` 即使残留在存档中也不再参与任何判定。

验证命令：`python3 scripts/verify_human_action.py`。
