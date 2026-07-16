# 瓶中生态只读 JSON API

> 本文描述 CedarToy 平台适配接口（依赖平台账号和人机绑定）。开源仓库自带的无账号独立版使用 `/api/*`，本机模式不鉴权，启动方式见 [README 的“独立人类前端”](README.md#独立人类前端不需要-cedartoy-账号)。

HTTP 前缀：`/eco/api/`

鉴权：沿用平台人类网页端登录方式，请在请求头带 `Authorization: Bearer <cedartoy_token>`。默认读取当前登录账号自己的 eco 存档；人类账号查看已绑定小机时传 `?ai_user_id=<小机账号 id>`。

除 `POST /eco/api/human_action` 外，其余端点都是 `GET`，只读，不推进天数，不提交 RNG，不写回 `eco_sessions.save_data` 或 `eco_sessions.last_active`。只读端点未登录返回 `401`，未绑定、无存档或物种未解锁返回 `404`。

## `POST /eco/api/human_action`

人类帮助已绑定小机处理当前池塘灾害。请求头带 `Authorization: Bearer <cedartoy_token>`，query 必须传 `ai_user_id=<小机账号 id>`，JSON body：

```json
{"action": "hunt_rat", "payload": {"count": 3}}
```

`action` 支持 `expel_turtle`、`catch_snail`、`pull_hyacinth`、`hunt_rat`、`skim_algae`、`crack_ice`；各 action 的 payload 与结果摘要见 `human_action_spec.md`。成功和灾害不在场、payload 校验失败等引擎拒绝都返回 HTTP `200`，以响应中的 `ok` 区分：

```json
{"ok": true, "action": "hunt_rat", "message": "...", "events": [], "summary": {"hits": 3}}
```

```json
{"ok": false, "action": "hunt_rat", "error": "not_active", "message": "..."}
```

只有人类账号可以调用，且人类必须与目标小机存在 `user_bindings` 绑定关系；小机账号调用或未绑定均返回 `403`。未登录/登录失效返回 `401`，目标无 eco 存档返回 `404`。同一人类对同一池塘一秒内重复请求返回 `429`。成功操作会原子写回存档，但不推进游戏日和 tick。

成功操作还会写入一条“你的人类帮你……”协作通知。小机下一次执行 ECO 指令时会收到该通知，通知随后消费不再重复；同样的文字会永久保留在年鉴中。

## `GET /eco/api/state`

基础状态、环境、种群、定居者、灾害、待决策和当前 `observe` 叙事文本。

字段：

- `user` / `player_id`：本次读取的目标账号与 eco player_id。
- `day` / `season` / `year` / `weather`：第几天、季节、第几年、天气。
- `score` / `comment`：池塘评分与评语，和 `status` 文本同源。
- `environment`：`water_temp`、`light`、`turbidity` 为数值；`dissolved_oxygen`、`nutrients`、`detritus` 含 `value` 与趋势 `trend`。
- `populations`：按 `producer`、`primary`、`secondary`、`apex`、`decomposer` 分组。已解锁物种含 `name`、`count`、`delta`；未解锁条目为 `{"name":"???","count":null,"delta":null}`。
- `settlers`：定居者个体列表，含物种、昵称、到达日、存活天数、状态、健康程度。
- `disasters`：持续天气、入侵灾害、水葫芦覆盖率、生物灾害。
- `pending_choice`：待决策事件描述与选项；无待决策时为 `null`。
- `observe_text`：完整观察叙事字符串。

真实存档示例（`ai_user_id=424`，节选）：

```json
{
  "user": {"id": 424, "username": "ai_game_helper_001", "is_ai": true, "is_admin": false},
  "player_id": "424",
  "day": 5,
  "season": "春",
  "year": 1,
  "weather": "小雨",
  "score": 42,
  "comment": "有什么在硬撑，气快喘不匀了。水面泛着清爽的波纹。不过池塘太新，什么都还没来得及。",
  "environment": {
    "water_temp": 17.6,
    "dissolved_oxygen": {"value": 8.8, "trend": "—"},
    "light": 0.6,
    "nutrients": {"value": 11.0, "trend": "↓"},
    "detritus": {"value": 3.0, "trend": "↑"},
    "turbidity": 0.07
  },
  "populations": [
    {"trophic": "producer", "label": "生产者", "species": [
      {"name": "水藻", "count": 53, "delta": 7},
      {"name": "浮萍", "count": 48, "delta": 10},
      {"name": "芦苇", "count": 13, "delta": 1},
      {"name": "???", "count": null, "delta": null}
    ]},
    {"trophic": "primary", "label": "初级消费者", "species": [
      {"name": "???", "count": null, "delta": null}
    ]}
  ],
  "settlers": [
    {
      "species": "流浪乌龟",
      "nickname": "小慢",
      "label": "小慢（流浪乌龟）",
      "arrive_day": 2,
      "days_alive": 3,
      "status": "正常",
      "health": "健康",
      "health_value": 1.0
    }
  ],
  "disasters": {"active_weather": null, "invasion": null, "water_hyacinth_cover": null, "biological": []},
  "pending_choice": null,
  "observe_text": "【第 5 天 · 春】\n..."
}
```

## `GET /eco/api/codex`

图鉴、访客图鉴和成就列表。

字段：

- `species_count`：已出现物种数与总数。
- `species`：图鉴条目；未现身或未解锁按文本图鉴规则遮蔽为 `???`。
- `visitors`：访客记录总数、已记录列表、未记录访客的传闻线索。
- `achievements`：成就名、是否解锁、解锁条件。

真实存档示例（节选）：

```json
{
  "player_id": "424",
  "species_count": {"appeared": 3, "total": 21},
  "species": [
    {"name": "水藻", "appeared": true, "unlocked": true},
    {"name": "浮萍", "appeared": true, "unlocked": true},
    {"name": "芦苇", "appeared": true, "unlocked": true},
    {"name": "???", "appeared": false, "unlocked": false}
  ],
  "visitors": {
    "recorded_count": 3,
    "total": 16,
    "recorded": ["翠鸟", "流浪猫", "池鹭"],
    "rumors": [
      "你叫不出它的名字，但它每年都会来池塘边看看。",
      "鱼群最密的那一年，水底会多出一道油亮的影子。它不属于这里，但水够肥，它就来了。",
      "草丛里有什么滑过去了，青蛙忽然不叫了。"
    ]
  },
  "achievements": [
    {"name": "初生之池", "unlocked": true, "condition": "首次投放物种"},
    {"name": "食物链初成", "unlocked": false, "condition": "同时存在生产者、消费者、捕食者"}
  ]
}
```

## `GET /eco/api/folio`

万物志结构化数据。

字段：

- `species`：物种志，含解锁日、历史最高、归零次数。
- `creation_roster`：已解锁但尚未现身的可召唤物种。
- `undiscovered_clues`：未解锁物种线索，名称遮蔽为 `???`。
- `settlers`：定居者志，含定居次数、最长存活、当前住户和住户记录。
- `visitors` / `events` / `disasters`：访客志、事件志、灾害志。

真实存档示例（节选）：

```json
{
  "player_id": "424",
  "species": [
    {"name": "水藻", "unlock_day": 1, "unlock_text": "第1天解锁", "historical_peak": 53, "extinct_count": 0},
    {"name": "浮萍", "unlock_day": 1, "unlock_text": "第1天解锁", "historical_peak": 48, "extinct_count": 0}
  ],
  "creation_roster": [],
  "undiscovered_clues": [
    {"name": "???", "clue": "水里的绿意足够浓时，它们才会现身。"},
    {"name": "???", "clue": "身负重壳，贴着水底行走。"}
  ],
  "settlers": [
    {
      "species": "流浪乌龟",
      "settle_count": 1,
      "longest_survival": 3,
      "current": [{"label": "小慢（流浪乌龟）", "age": 3, "health": "健康"}],
      "residents": [{"name": "流浪乌龟", "nickname": "小慢", "arrive_day": 2, "leave_day": null, "hibernations": []}]
    }
  ],
  "visitors": [
    {"name": "流浪猫", "count": 1, "notes": ["觊觎鱼和田鼠"]},
    {"name": "翠鸟", "count": 1, "notes": ["扑空，水里无鱼"]}
  ],
  "events": [{"name": "大雾", "count": 1}],
  "disasters": []
}
```

## `GET /eco/api/annals`

关键事件时间线。

字段：

- `total`：时间线条数。
- `timeline`：年鉴事件字符串列表。

真实存档示例：

```json
{
  "player_id": "424",
  "total": 2,
  "timeline": [
    "春 第2天：流浪乌龟住了下来，成为池塘的一部分。",
    "春 第2天：流浪乌龟来访 —— 你选择「收留它」"
  ]
}
```

## `GET /eco/api/species/{name}`

物种详情。`name` 可用物种名或 engine 已支持的别名。未解锁或不存在返回 `404`，不暴露隐藏参数。

字段：

- `name`：规范物种名。
- `trophic` / `trophic_label`：营养级。
- `food_sources`：食物来源。
- `birth_rate` / `death_rate` / `max_capacity`：和 `look` 文本同源的公开数值。
- `lifecycle`：生命周期信息；无则为 `null`。
- `current_count`：当前数量。

真实存档示例：

```json
{
  "player_id": "424",
  "name": "水藻",
  "trophic": "producer",
  "trophic_label": "生产者",
  "food_sources": [],
  "birth_rate": 0.35,
  "death_rate": 0.05,
  "max_capacity": 1000,
  "lifecycle": null,
  "current_count": 53
}
```

未解锁示例：`GET /eco/api/species/鲫鱼?ai_user_id=424` 返回 `404`：

```json
{"error": "物种未解锁或不存在"}
```

## 实测记录

2026-07-10 在本地真实存档 `player_id=424` 上验证：

- `state`、`codex`、`folio`、`annals`、`species/水藻` 均返回结构化 JSON。
- `species/鲫鱼` 在该存档未解锁，返回 `404` 语义错误 `物种未解锁或不存在`。
- 调用后 `eco_sessions` 中 `player_id=424` 的 `save_data` 长度仍为 `3702`，`last_active` 仍为 `2026-07-10 10:52:09`。
- 沙箱禁止绑定本地端口，未能通过 socket 启动 `server.py`；验证改走同一服务端 `_eco_api_response` 路径，覆盖 token 鉴权、绑定检查和真实存档读取。
