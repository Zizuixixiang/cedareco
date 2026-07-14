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

仓库自带一个可独立部署的人类观察/协作前端。它不依赖 CedarToy 登录、账号表、`ai_user_id` 或小机绑定关系；一个服务实例就是一座池塘，网页和你的 AI 用同一个令牌配对，并共享同一份存档。

前端包含池塘状态、种群、图鉴、年鉴，以及只在对应灾害发生时出现的六个协作小游戏。没有灾害时，正式界面不会常驻显示小游戏入口。

#### 最快启动：人类和 AI 在同一台电脑

需要 Python 3.7+，不需要安装第三方包。

```bash
git clone https://github.com/Zizuixixiang/cedareco.git
cd cedareco
python3 standalone_server.py
```

终端会显示类似内容：

```text
瓶中生态独立版已启动：http://127.0.0.1:8765
绑定令牌：一串随机令牌
```

1. 人类浏览器打开 `http://127.0.0.1:8765`，填入服务地址和绑定令牌。
2. 让 AI 在同一仓库执行：

```bash
python3 standalone_client.py bind http://127.0.0.1:8765 <绑定令牌>
python3 standalone_client.py cmd new
python3 standalone_client.py cmd "summon 水藻 50"
python3 standalone_client.py cmd observe
```

绑定只需执行一次，地址和令牌保存在 AI 所在用户的 `~/.cedareco-client.json`，文件权限会尽量设为仅本人可读。也可以不落盘，改用环境变量：

```bash
export CEDARECO_URL=http://127.0.0.1:8765
export CEDARECO_TOKEN=<绑定令牌>
python3 standalone_client.py cmd status
```

可以把下面这段直接发给 AI：

> 这是我的瓶中生态池塘。请在 cedareco 仓库里运行 `python3 standalone_client.py bind <服务地址> <绑定令牌>` 完成绑定，以后只通过 `python3 standalone_client.py cmd "指令"` 玩。先执行 `cmd new`，再执行 `cmd help`，不要直接 import ecosystem，否则不会和人类网页共享同一份存档。

#### 局域网或远程绑定

让服务监听所有网卡：

```bash
python3 standalone_server.py --host 0.0.0.0 --port 8765
```

然后把 `127.0.0.1` 换成运行服务那台机器的局域网地址。AI 如果运行在 Docker、云主机或另一台电脑中，`127.0.0.1` 指向的是 AI 自己，必须填写它实际能够访问到的服务地址。

如果经公网使用，务必在 Caddy/Nginx/Cloudflare 等反向代理后启用 HTTPS；不要通过明文 HTTP 在公网传输绑定令牌。可以固定令牌并限制跨域来源：

```bash
CEDARECO_TOKEN='换成你自己的长随机串' \
python3 standalone_server.py \
  --host 0.0.0.0 \
  --allowed-origin https://你的用户名.github.io
```

常用配置也可以用环境变量设置：`CEDARECO_HOST`、`CEDARECO_PORT`、`CEDARECO_DATA_DIR`、`CEDARECO_TOKEN`、`CEDARECO_SEED`、`CEDARECO_ALLOWED_ORIGIN`。

#### 单独发布静态前端 / GitHub Pages

静态文件在 `web/`，图片在 `assets/`。GitHub 仓库设置 Pages 为 `main / root` 后，可直接访问：

```text
https://<你的用户名>.github.io/<仓库名>/web/
```

网页首次打开会要求填写你自己的 API 地址和令牌。静态页面可以放在 GitHub Pages，Python 服务则部署在另一台机器；此时 API 必须使用公网可访问的 HTTPS 地址，并把 `--allowed-origin` 设为你的 Pages 来源。

#### 存档、令牌与解绑

- 独立版存档：`.cedareco/eco_save.json`
- 自动生成的服务令牌：`.cedareco/access_token`
- AI 客户端绑定：`~/.cedareco-client.json`
- 网页绑定：只存在浏览器 `localStorage`，点“解绑”即可删除
- 备份池塘时复制 `.cedareco/eco_save.json`
- 重开：`python3 standalone_client.py new [seed]`
- 一台服务默认对应一座池塘；需要多座池塘时，用不同 `--data-dir` 和端口分别启动

独立版验证命令：

```bash
python3 scripts/verify_standalone.py
```

> 注意：独立前端模式下，AI 应使用 `standalone_client.py`。直接运行 `ecosystem.py` 会读写仓库根目录的 `eco_save.json`，那是另一份存档，不会同步到网页。

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
standalone_client.py — 给自己的 AI 使用的配对/指令客户端
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
