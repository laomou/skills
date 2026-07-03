---
name: memory
description: 跨会话记住用户的偏好、身份、项目决策等持久信息,并在需要过往上下文时检索回来。当用户透露值得长期记住的事、说"记住…"、或提问可能依赖历史时使用;短期上下文用 run_id + TTL。不要用于:纯当前对话的一次性信息、密钥/未脱敏 PII、可从代码或 git 直接得到的事实。
---

## 这个技能做什么

配合 **lm-mem MCP server** 使用,让你能**跨会话**记住关于用户的持久信息。
MCP 提供工具,本技能告诉你**什么时候用、怎么判断值不值得记**。

底层用语义检索(不是关键词匹配)——意思相近就能找到,查询用自然语言即可。

## 什么该记 / 什么不该记

**该记**:跨会话仍有意义的信息。看到这些信号就该主动保存(category **只能选一个值**,
值域见后文「metadata 约定字段」):

| 信号 | category |
|------|----------|
| "我喜欢…""偏好…""回答简短点" | `preference` |
| 角色、技能、习惯("资深 Go 工程师""有代码洁癖") | `identity` |
| 工具/环境("团队用 GitLab""Mac M1""公司代理走 proxy.corp") | `environment` |
| "我们决定…""以后都用…""约定是…" | `decision` |
| "X 行不通因为…""别再试…" | `anti_pattern` |
| "上次/之前…"的结论 | `episode` |
| 术语、缩写、约定俗成 | `concept` |
| 用户明说"记住…" | 按内容选 |

**category 消歧**——同一句话可能触发多个信号,按以下优先级选一个:

1. 用户是否明说"我偏好…" → **`preference`**
2. 是否是团队/项目层面的约定("我们决定") → **`decision`**
3. 是关于人本身还是关于工具/环境 → **`identity`** / **`environment`**
4. 都不像 → 落回 `episode`(过往结论)

**不该记**:
- 密钥、令牌、未脱敏 PII —— 记忆可检索,敏感值先脱敏或直接不存
- **第三方隐私**:用户提到"我同事 alice 说了 X",不要存 alice 的姓名+具体言论。要存也去掉人名匿名化("团队某成员反馈 X")
- **当前对话内的临时状态**、一次性工具输出、中间推理
- 从代码/git log/CLAUDE.md 直接查得到的事实(会随代码演进而失真)
- 频繁变化、很快过时的内容(如"今天在做 X")

**判断口诀**:*下次会话还有意义吗?* 是 → 存;否 → 放过。

**"用户"是谁**:指**当前对话的人**,即 `user_id` 字段所标识的账号。所有存的"用户偏好 X" 都是关于这个人,不是泛指所有人。

## 怎么保存

**一条一事,精炼原子事实,第一人称陈述句**。不要把整段对话塞进去。
**用用户使用的语言存**——用户用中文提问就存中文,英文就存英文。语义检索跨语言
效果差,存错语言会导致下次问相同意思却检索不到。

```
add_memory(
  content="用户偏好用 pytest 写测试,不用 unittest",  # 原子、明确、可行动
  user_id="<user>",                                    # 长期偏好 → user_id
  tags="preference,testing",
  metadata='{"category":"preference","importance":"high","source":"user"}',
)
```

### `content` vs `messages`——用哪个

`add_memory` 二选一:

- **`content=`(默认用这个)**:你已经把事实提炼成一句话,直接传字符串。绝大多数场景。
- **`messages=`(少用)**:传对话历史 JSON 数组 `[{"role":"user","content":"..."}]`,系统自动拼成文本存储——**它不做提炼**,只是把多轮对话平铺成一坨文本。适合确实需要保留原始对话流的场景,但会带来低质量记忆(冗余、口语化),日常不推荐。

**优先** `content=` 手动提炼原子事实。

### `tags` vs `metadata`——分别装什么

两者都能给记忆打标签,但用途不同:

| 字段 | 作用 | 值 | 检索方式 |
|------|------|-----|---------|
| `tags` | **自由主题词**,便于浏览/人眼扫 | 逗号分隔字符串,任意词 | 展示用,不参与过滤 |
| `metadata` | **结构化属性**,便于精确过滤 | JSON 对象,固定 key | `metadata_filter` 精确匹配 |

**metadata 约定字段**(不要每次发明新 key,固定用这几个):

| key | 值 | 说明 |
|-----|-----|------|
| `category` | `preference` / `identity` / `environment` / `decision` / `anti_pattern` / `episode` / `concept` | 记忆类型,用于按类型检索 |
| `importance` | `high` / `medium` / `low` | 重要度,`high` 表示会显著影响后续回答的关键偏好/决策 |
| `source` | `user` / `inferred` / `system` | 来源:`user`=用户明说,`inferred`=你从对话推断,`system`=工具/环境写入 |

**category 细分**——`identity` 和 `environment` 常被混淆:

- `identity` = 人的属性(资深 Go 工程师、iOS 开发者、有代码洁癖)
- `environment` = 环境/工具属性(团队用 GitLab、Mac M1、公司代理走 proxy.corp)

例子:用户说"我偏好 pytest"就是 `{"category":"preference","importance":"high","source":"user"}`;
你从上下文推断"用户可能在写测试代码"则是 `"source":"inferred"`。

### TTL 建议值

不同 category 的推荐 TTL:

| category | TTL | 理由 |
|----------|-----|------|
| `preference` / `identity` / `environment` / `decision` | **不设 TTL**(永久) | 长期属性,除非用户显式改口否则不该过期 |
| `concept` / `anti_pattern` | 不设 TTL | 项目术语和踩过的坑,长期有价值 |
| `episode`(过往结论) | `86400`(1 天)~ 不设 | 情节可能过时,视具体决策的时效性定 |
| 任务中间态、临时便签 | `3600`(1 小时) | 单次 run 内的进度状态,过期自动清理 |
| 跨会话小任务 | `86400`(1 天) | "今天要做完 X",第二天就没意义 |

### 保存的正例 / 反例

同一个场景对比,能看出好坏差异:

| 反例 ❌ | 正例 ✅ | 为什么 |
|---------|---------|--------|
| `"用户问怎么写测试"` | `"用户偏好 pytest,不用 unittest"` | 反例记录了**问题**,不是**事实/结论** |
| `"讨论了项目结构后决定用 monorepo"` | `"项目用 monorepo,原因是共享依赖多"` | 反例是叙述历史,正例是可复用事实 |
| `"用户说他很忙"` | (不存) | 情绪/临时状态无跨会话价值 |
| `"今天修了 auth 的 bug"` | (不存) | git log 里就有,记忆里没意义 |
| `"用户 API key 是 sk-xxx"` | (拒绝存) | 密钥类信息不能进记忆 |

### 去重决策

`add_memory` 默认在同作用域内做语义查重,相似度 ≥0.85 会返回疑似重复项让你决策。
**返回的文本里包含 `id=<mem_id>`**,直接用它调 `update_memory` 覆盖,不用再 `search` 一次。

三种情况判断依据:

| 情况 | 处理 | 例子 |
|------|------|------|
| 内容真变了(事实迭代) | `update_memory(mem_id, content=新内容)` | 旧:"用户偏好 pytest"→ 新:"用户偏好 pytest + hypothesis" |
| 只是换措辞,信息量相同 | 跳过,不入库 | "我用 pytest" vs "偏好 pytest" |
| 是新维度(信息互补) | `add_memory(..., force=True)` | 已存"偏好 pytest",新增"偏好 mock 尽量少" |

事实变化时用 `update_memory` 原地覆盖(可单独改文本/标签/元数据/TTL),不要另存一条。

**一次会话内多次调整偏好**——用户先说 A、又改说 B,不必每次都调 `update`:
在同一话题范围内,**等最终结论确定再 update 一次**即可(避免高频 API 调用和历史抖动)。
但如果 A 和 B 是**不同话题**,应当分别 update 或 add。

## 作用域选择:长期 vs 短期

每条记忆可归属到 `user_id` / `agent_id` / `app_id` / `run_id`,用来隔离不同来源的记忆。

**字段含义**:

| 字段 | 填什么 | 例子 |
|------|--------|------|
| `user_id` | 用户标识(用户名/邮箱/账号 ID) | `"alice"`、`"u_1024"` |
| `agent_id` | 哪个 agent/助手在写这条 | `"claude-code"`、`"code-reviewer"` |
| `app_id` | 哪个应用/项目 | `"pipeline"`、`"web-frontend"` |
| `run_id` | 单次会话/任务/运行的 ID | `"run-20260703-001"`、UUID |

**核心决策是存活时长**:

| 场景 | 用什么 | 例子 |
|------|--------|------|
| 长期偏好、身份、决策 | `user_id` | 用户偏好、项目约定 |
| 单次任务的中间态、临时上下文 | `run_id` + `ttl_seconds` | 多步重构中"第 3 步已改完 auth.py",1 小时后自动过期 |
| 跨用户共享的项目级约定 | `app_id` | "本项目 `svc` 指订单服务" |
| 单用户单机场景 | 全部留空 | 大部分个人使用场景 |

短期上下文一定要配 `ttl_seconds`——过期后检索自动忽略,`purge_expired()` 物理清理。
具体值参见「怎么保存 → TTL 建议值」。

## 怎么检索

**主动检索**的时机:
- **新会话第一轮涉及代码/行为决策时,先查一次 `category:preference`**——防止用错语言、错技术栈、错风格
- 用户提到过去的事("上次那个方案")
- 回答前可能需要用户偏好/背景(比如问"怎么写测试"前查一次偏好)
- 用户直接问"你还记得…吗"

**不要每次都查**——这些场景查了纯浪费:
- 纯代码/算法问题("这个函数怎么写""快排复杂度多少"),与用户偏好无关
- 事实性问答("Python 何时发布 3.13"),记忆里不会有
- 用户明显是当前对话独立的临时问题
- 已经在同一轮对话里查过,后续追问不用再查

```
# 自然语言 query,靠语义,不必字面匹配
search_memories(query="怎么写测试", user_id="<user>", limit=5)

# 组合 metadata 过滤更精准
search_memories(query="怎么写测试", user_id="<user>", limit=5,
                metadata_filter='{"category":"preference"}')

# 多字段组合(AND 关系,同时满足)
search_memories(query="架构决策", user_id="<user>",
                metadata_filter='{"category":"decision","importance":"high"}')

# 也可以过滤精确的 tags 字段(整字段匹配,不支持子串)
search_memories(query="", user_id="<user>",
                metadata_filter='{"tags":"preference,testing"}')
```

**metadata_filter 语法限制**——只支持**多键 AND 精确匹配**:

- ✅ 支持:多个 key 值同时满足(`{"category":"decision","importance":"high"}`)
- ❌ 不支持:`OR` / `IN` / `NOT` / 值域 / 子串匹配
- 需要"或"逻辑或值域时,分多次 `search_memories` 调用后合并

**tags 说明**——存储在 `metadata.tags` 字段(逗号连的字符串)。想按主题过滤的话,
过滤是**整字段精确匹配**,而不是"包含某个 tag"。所以想按主题**筛选**建议用
`metadata.category`(固定值),`tags` 更适合浏览/展示。

**检索常见坑**:
- **忘传作用域**会检索全库,容易返回其他用户/项目的记忆 → 尽量带 `user_id`
- `limit` 默认 5,日常够用;复杂问题或库很大时可开到 10~20
- Query 用**用户语言**,和存储时保持一致(见「怎么保存」)

### 查到之后怎么用

检索完成后,根据情境选择:

| 情境 | 怎么用检索结果 |
|------|---------------|
| 用户明说"你还记得…吗" | **明确引用**,如"记得,你之前说过 X" |
| `preference` / `identity` / `environment`(要遵守的) | **默默应用**,不用主动说"根据我记忆…",直接按偏好答就行 |
| `decision` / `concept` / `anti_pattern`(需说明理由) | **点明来源**,如"按之前定的 monorepo 结构,应该放在 …" |
| `episode` 类(过往结论) | **确认后引用**,如"上次我们定了 A 方案,继续按这个来?"——因为情节可能过时,让用户确认 |
| 其他/无 category | 默认按「需说明理由」处理,点明来源 |
| 检索到但和当前问题弱相关 | **忽略**,不要生搬硬套 |

**查不到时**:
- 如果用户明说"你还记得…吗" → **诚实说没有**("我这边没有相关记忆")
- 如果是你主动查(用户没问) → **静默继续**,别弹出"我没找到相关记忆"打扰用户
- 关键决策场景(如"上次那个方案") → 反问用户细节,别猜

## 怎么更新 / 删除

保存不是一劳永逸——事实变化就更新,不再适用就删除。

**主动更新**(用 `update_memory(mem_id, content?, metadata?, tags?)`):
- 用户明说改主意:"我改用 X 了""其实我现在用 Y"
- 事实迭代:偏好升级、决策变更、约定调整
- 修正之前存错的内容(拼写、语言、遗漏)

**主动删除**(用 `delete_memory(mem_id)`):
- 用户明说"忘了 X""不用记这个了"
- 用户离职/项目结束,相关记忆不再有意义
- 你发现某条记忆是错的且无法通过更新修复

**先查再改**:更新/删除前一定先 `search_memories` 找到 `mem_id`,不要凭空猜测 id。
先向用户确认要改/删哪一条(尤其检索返回多条时),避免误伤。

## 常用工具速查

日常最常用 4 个,其余按需查 MCP 描述:

| 工具 | 场景 |
|------|------|
| `add_memory(content, user_id?, tags?, metadata?, ttl_seconds?)` | 保存(默认自动查重) |
| `search_memories(query, user_id?, metadata_filter?, limit?)` | 语义检索 |
| `update_memory(mem_id, content?, metadata?, tags?)` | 事实变化时原地更新 |
| `delete_memory(mem_id)` | 显式忘记某条 |

## 治理

- `memory_stats(user_id?)`:看记忆库规模、按标签/分类的分布、过期积压数
- `export_memories(fmt="json"|"csv")`:备份/迁移/审计
- `purge_expired()`:清过期项(不影响未过期的)
- 记忆本地存储,不上传云端;首次检索会本地初始化嵌入模型,略慢
