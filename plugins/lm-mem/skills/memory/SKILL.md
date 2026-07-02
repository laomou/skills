---
name: memory
description: 跨会话记住用户的偏好、身份、项目决策等持久信息,并在需要过往上下文时检索回来。当用户透露值得长期记住的事、说"记住…"、或提问可能依赖历史时使用;短期上下文用 run_id + TTL。
---

## 作用

这个技能配合 **lm-mem MCP server** 使用,让你能跨会话记住信息。MCP 提供工具,
本技能告诉你**什么时候**该用它们。

可用的 MCP 工具:

| 工具 | 用途 |
|------|------|
| `add_memory(content?, messages?, user_id?, tags?, metadata?, ttl_seconds?, force?)` | 保存一条记忆(默认自动查重) |
| `search_memories(query, limit?, user_id?, metadata_filter?, ...)` | 按语义相似度检索(可按作用域/元数据过滤) |
| `get_memories(limit?, offset?, user_id?, metadata_filter?, ...)` | 列出记忆(支持分页、作用域/元数据过滤) |
| `get_memory(mem_id)` | 按 id 获取单条 |
| `update_memory(mem_id, content?, metadata?, tags?, ttl_seconds?)` | 按 id 更新文本/元数据/标签/过期时间 |
| `delete_memory(mem_id)` | 按 id 删除单条 |
| `delete_all_memories(user_id?, ...)` | 批量删除某作用域内全部记忆 |
| `delete_entities(entity_type, entity_id)` | 删除某实体及其记忆 |
| `list_entities(entity_type?)` | 列出已存的 user/agent/app/run |
| `memory_stats(user_id?, ...)` | 统计总数、按作用域/标签/分类聚合、过期数 |
| `export_memories(fmt=json\|csv, user_id?, ...)` | 批量导出记忆 |
| `purge_expired()` | 清理已过期(超过 TTL)的记忆 |

## 作用域与记忆分层(scope)

每条记忆可归属到 `user_id` / `agent_id` / `app_id` / `run_id`。保存时带上作用域,
检索和列举时用同样的作用域过滤,可以把不同用户/场景的记忆隔开。多数单用户场景
留空即可。

参考记忆分层的思路,按**存活时长**选作用域与 TTL:

| 层次 | 存活 | 用什么 | 适合 |
|------|------|--------|------|
| 会话/短期 | 分钟~小时 | `run_id` + `ttl_seconds` | 多步任务的中间状态、临时上下文 |
| 用户/长期 | 数周~永久 | `user_id` | 个人偏好、身份、长期决策 |

短期上下文用 `run_id` 隔离、配 `ttl_seconds` 让它自动过期;真正要长期个性化的信息
才落到 `user_id`。

## 何时保存(add_memory)

当用户透露了**下次会话仍然有用**的持久信息时,主动保存。可对照三类长期记忆:

- **事实型(factual)**:偏好、身份、账号/环境状态 —— "我喜欢用 TypeScript""回答简短一点""团队用 GitLab"
- **情节型(episodic)**:过往交互的结论/决策摘要 —— "上次定了用 PostgreSQL 而非 Mongo"
- **语义型(semantic)**:概念间的关系/约定 —— "本项目里 `svc` 指订单服务"
- 用户明确说"记住……"

保存要点:

- **存精炼后的原子事实,一条一事**,用第一人称陈述,而不是整段原始对话。
- 保存前判断:**下次会话还有意义吗**?是 → 存;只对当前对话有用 → 不存。

一个把作用域、标签、元数据串起来的完整例子:

```
add_memory(
  content="用户偏好用 pytest 写测试,不用 unittest",
  user_id="mourui",                         # 长期偏好 → 落到 user
  tags="preference,testing",
  metadata='{"category":"pref","importance":"high"}',
)
# 之后按语义 + 元数据检索:
search_memories(query="怎么写测试", user_id="mourui",
                metadata_filter='{"category":"pref"}')
```

`add_memory` 默认会先自动查重(见下文「更新与去重」),同一事实反复说不会重复入库。

### 不该存

- **密钥、令牌、未脱敏的 PII**:记忆按设计是可检索的,敏感值先脱敏/不存。
- 纯瞬时信息(当前这轮的中间推理、一次性工具输出)。真要临时留存,用 `run_id` + 短 `ttl_seconds`。
- 会频繁变化、很快过时的内容。

## 何时检索(search_memories)

- 用户提到过去的事("上次我们说的那个方案")
- 回答前可能需要用户的偏好/背景
- 用户直接问"你还记得……吗"

检索用自然语言 query 即可,靠语义匹配,不必和原文逐字一致。

## 元数据(metadata)

保存时可带 `metadata`(JSON 对象字符串),附加 `category` / `importance` / `source`
等自定义字段;检索/列举时用 `metadata_filter`(同为 JSON 对象)按这些字段精确过滤。
适合做分类、优先级、来源标记。

## 输入格式

`add_memory` 二选一:直接传 `content` 文本;或传 `messages`(对话历史 JSON 数组,
如 `[{"role":"user","content":"..."}]`),系统会自动拼成文本存储。

## 更新与去重(自动)

- `add_memory` **默认自动查重**:插入前在同作用域内做语义相似度检索,命中高相似度
  (≥0.85)时不插入,直接返回疑似重复项,并提示你决策:内容有变化 → `update_memory`
  覆盖;已足够 → 跳过;确需新增 → `add_memory(..., force=True)`。
- 事实变化时优先 `update_memory` 原地更新(文本/标签/元数据/`ttl_seconds` 均可单独改),而非另存一条。

## 管理与治理

- `memory_stats`:查看记忆库规模、按作用域/标签/分类的分布、待清理的过期数量。
- `export_memories`:导出为 JSON 或 CSV,便于备份/迁移/审计。
- TTL:`add_memory(..., ttl_seconds=N)` 让记忆 N 秒后过期;过期项检索时自动忽略,
  用 `purge_expired` 物理清理。适合临时便签、会话级上下文。

## 注意

- 记忆本地存储,不上传云端。
- 首次检索时会在本地初始化语义模型,可能稍慢,之后即快。
