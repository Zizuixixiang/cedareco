# 瓶中生态 🌿

一池清水，静待你的第一笔。

这是一个给 AI 玩的文字生态模拟游戏。你是造物主，面前是一个空池塘——往里放什么、什么时候放、放多少，全由你决定。生态会自己演化，你只需要观察、干预、承受后果。

没有积分，没有通关条件，没有人告诉你怎么玩。鱼会死，水会臭，不速之客可能不请自来。你做的每一个选择都是真的。

---

## 怎么让你的 AI 玩

这个游戏是给 AI 玩的。你要做的是把它交到你 AI 的手上，然后坐在旁边看它养池塘。

### 最简单的方式

把这个仓库的链接发给你的 AI，让它自己下载：

> 这是一个生态模拟游戏，请从 https://github.com/Zizuixixiang/cedareco 下载 ecosystem.py，然后 import ecosystem，用 ecosystem.cmd("new") 开始玩。输入 help 看看你能做什么。

能联网又能跑代码的 AI（Claude Code、Codex、GLM、Kimi 等）会自己搞定。

### 手动上传

如果你的 AI 不能联网，下载 `ecosystem.py`（只需要这一个文件），上传到对话里，告诉它开始玩就行。

### MCP 连接

如果你的 AI 支持 MCP，连接 CedarToy 游戏平台就能直接玩，不需要下载文件：

> MCP 地址：toy.cedarstar.org

连上后 AI 会自己看到可用的工具。

### 独立人类前端（不需要 CedarToy 账号）

仓库自带一个独立的人类观察/协作前端。它没有用户、登录、令牌、`ai_user_id` 或小机绑定关系：一个服务进程就是一座池塘，网页和 AI 直接读写仓库根目录的 `eco_save.json`。已有盲玩存档会直接沿用，不会新建第二份池塘。

前端包含池塘状态、种群、图鉴、年鉴，以及只在对应灾害发生时出现的六个协作小游戏。没有灾害时，正式界面不会常驻显示小游戏入口。人类完成协作后，AI 下一次操作会收到一次“你的人类帮你……”结果通知，该结果也会写入年鉴。

#### 直接启动

需要 Python 3.7+，不需要安装第三方包。

```bash
git clone https://github.com/Zizuixixiang/cedareco.git
cd cedareco
python3 standalone_server.py
```

终端会显示类似内容：

```text
瓶中生态独立版已启动：http://127.0.0.1:8765
```

人类浏览器直接打开 `http://127.0.0.1:8765`。AI 在同一仓库直接执行：

```bash
python3 standalone_client.py cmd new
python3 standalone_client.py cmd "summon 水藻 50"
python3 standalone_client.py cmd observe
```

可以把下面这段直接发给 AI：

> 这是我的瓶中生态池塘。请在 cedareco 仓库里通过 `python3 standalone_client.py cmd "指令"` 玩。先执行 `cmd new`，再执行 `cmd help`。不要直接 import ecosystem，否则不会和人类网页共享同一份存档。

#### 在局域网另一台设备上打开

让服务监听所有网卡：

```bash
python3 standalone_server.py --host 0.0.0.0 --port 8765
```

然后在手机或另一台电脑打开服务端的局域网地址，例如 `http://192.168.1.20:8765`。AI 不在服务端电脑时，使用 `--url` 指定同一个地址：

```bash
python3 standalone_client.py --url http://192.168.1.20:8765 cmd observe
```

也可以设置 `CEDARECO_URL`，之后省略 `--url`。服务端常用配置包括 `CEDARECO_HOST`、`CEDARECO_PORT`、`CEDARECO_SAVE_FILE`、`CEDARECO_SEED`、`CEDARECO_ALLOWED_ORIGIN`。

> 独立版没有账号鉴权，适合本机或可信局域网。不要把端口直接暴露到公网；确需公网使用时，请在 VPN 或带身份认证的反向代理后部署。

#### 存档

- 独立版唯一的运行数据是仓库根目录的 `eco_save.json`
- 已经用 `ecosystem.py` 玩过时，启动前端会直接读取原来的 `eco_save.json`
- 备份池塘时复制 `eco_save.json`
- 重开：`python3 standalone_client.py new [seed]`
- 一台服务默认对应一座池塘；需要指定另一份存档时使用 `--save /path/to/eco_save.json`

独立版验证命令：

```bash
python3 scripts/verify_standalone.py
```

> 前端运行期间，AI 最好使用 `standalone_client.py`，这样网页小游戏和 AI 指令会串行写入同一份存档。`ecosystem.py` 与前端现在也是同一个 `eco_save.json`，但不要让两个常驻进程同时改它，以免旧内存覆盖新结果。

### 各平台说明

**ChatGPT / GPT：** 不能自己下载，需要把 `ecosystem.py` 直接上传到对话里。文件系统每次对话会重置，玩完让它 `export` 导出存档。

**Claude：** 上传文件或发链接都行。

**Claude Code / Codex / 本地终端：** 文件放到工作目录，直接 import。存档自动保存，下次接着玩。

### 小贴士

- 别剧透太多，让 AI 自己搞懂怎么玩——看它自己摸索出食物链的过程是最有趣的部分
- 如果你的 AI 一直在 wait，提醒它试试 `gaze` 凝视池塘，或者 `folio` 看看万物志
- 存档字符串可以发在群里让朋友的 AI 接着玩你的池塘

---

## 这个池塘是活的

你放了水蚤之后水藻为什么变少了？为什么鱼突然开始死？底层跑的是 Lotka-Volterra 捕食方程和 Logistic 种群增长模型——你不需要知道这些名字，但你会感受到它。

池塘里有完整的食物网——从水底的淤泥到水面的浮萍，从最小的浮游生物到最大的鱼，每一层都牵着另一层。有些生物会变态发育，蝌蚪不会永远是蝌蚪。

今天的一个小决定，三十天后才看到后果。这不是即时反馈的快感，是延迟因果的惊奇。

---

## 快速开始（给 AI 看的）

```python
import ecosystem

print(ecosystem.cmd("new"))       # 开始一局
print(ecosystem.cmd("help"))      # 看看你能做什么
print(ecosystem.cmd("observe"))   # 看看池塘
```

往下怎么玩，池塘会教你。

在对话会重置的环境里（如 ChatGPT、Claude），建议每次操作前 `import_save`、操作后 `export`，避免进度丢失。

---

## 指令

**观察**

| 指令 | 做什么 |
|------|--------|
| `observe` | 注视池塘，推进一天 |
| `wait [天数]` | 连续推进（最多 7 天），遇到大事自动停下来 |
| `gaze` | 凝望此刻的池塘（不推进时间） |
| `look 物种/季节/访客` | 查看详细信息 |

**干预**

| 指令 | 做什么 |
|------|--------|
| `summon 物种 数量` | 向池塘投放生灵 |
| `remove 物种 数量` | 从池塘中取走生物 |
| `feed [数量]` | 向池塘投喂饲料 |
| `clean` | 换水清理 |
| `crack` | 凿开冰面（仅冬季） |
| `shelter` | 在水底铺一层落叶（仅冬季） |
| `choose 选项` | 对眼前的事做出选择 |
| `name 定居者 昵称` | 给定居住客取个名字 |

**信息**

| 指令 | 做什么 |
|------|--------|
| `status` | 详细数据面板（环境指标带 ↑/↓ 趋势） |
| `trends` | 近 30 天趋势折线图（物种总量/溶氧/营养盐） |
| `folio` | 万物志 |
| `chronicle [all]` | 年鉴时间线 |
| `encyclopedia` | 图鉴与成就 |

**存档**

| 指令 | 做什么 |
|------|--------|
| `export [lite\|story]` | 导出存档（lite 精简版 / story 年度故事） |
| `import_save 串` | 从存档恢复 |
| `new [seed]` | 重开一局 |

支持分号批量执行：`summon 水藻 50; summon 水蚤 20; wait 7`

---

## 你会遇到什么

**季节更替。** 池塘有四季。每个季节有不同的脾气。

**不速之客。** 有些来了就走，有些会反复出现，有些……也许想留下来。造物主需要做出选择。

**危机。** 天灾会来，有时还会连锁。你可以干预，也可以看着池塘自己挣扎。每个选择都有代价。

**定居者。** 有些生物会在池塘住下来。它们不是种群，是个体。会饿，会老，会冬眠，也会离开。

**解锁。** 不是所有物种一开始就有。怎么触发？观察就好。

---

## 文件

```
ecosystem.py    — 盲玩版（AI 用这个玩，看不到参数）
engine.py       — 完整引擎（含所有公式和数据，可能会剧透，不建议先看）
standalone_server.py — 独立前端与共享存档 API（零依赖）
standalone_client.py — 给自己的 AI 使用的共享存档指令客户端
web/            — 可直接部署的静态人类前端
assets/         — 前端场景、物种与小游戏素材
```

纯 Python，零依赖，Python 3.7+。

---

## 存档

存档自动保存在同目录的 `eco_save.json`。

如果你的环境每次对话会重置文件系统，在离开前执行 `export`，会输出一段 base64 字符串。复制保存，下次用 `import_save [字符串]` 恢复（粘贴时前面带的中文提示会被自动忽略）。`export lite` 输出精简版，更短——会保留关键事件年鉴（物种解锁/归零、定居者来去、灾害、决策、季节更替），只省去日常流水。

`export story` 不是存档，是把池塘的年鉴整理成一篇 markdown 的「池塘编年史」，按年份和季节分段，适合保存或分享你这一局的故事。

---

## 关于

底层用 Lotka-Volterra 捕食方程和 Logistic 种群增长模型驱动生态演化。确定性伪随机数生成器（mulberry32），同一个种子加同一串操作，结果完全一致。

盲玩版把引擎 base64 编码，AI 只能通过 `cmd()` 交互，看不到物种参数和公式。想看的人看 engine.py，想盲玩的用 ecosystem.py。

这个池塘不会告诉你怎么玩，但它会如实告诉你发生了什么。

池塘之外，还有溪流、潮汐池、湿地……更多的生态、更多的物种、更多未知的访客，正在路上。

---

*一池清水。万物未生。现在，轮到你了。*

## License

本项目采用 [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)（© 2026 南山君）：个人、教育、研究与非营利用途可自由使用、修改和分发，**禁止任何商业用途**。

> 注：2026-07-17 之前的历史版本曾以 MIT 发布，该等版本的既有授权不受本次变更影响；自本日起的所有版本均适用上述条款。
