---
name: memory
description: 跨会话记忆。当用户分享值得长期记住的信息(偏好、事实、项目决策),或提问可能依赖过往上下文时使用。通过 lm-mem MCP 的工具保存与检索。
---

## 作用

这个技能配合 **lm-mem MCP server** 使用,让你能跨会话记住信息。MCP 提供工具,
本技能告诉你**什么时候**该用它们。

可用的 MCP 工具:

| 工具 | 用途 |
|------|------|
| `add_memory(content, user_id?, agent_id?, tags?)` | 保存一条记忆 |
| `search_memories(query, limit?, user_id?, ...)` | 按语义相似度检索(可按作用域过滤) |
| `get_memories(limit?, offset?, user_id?, ...)` | 列出记忆(支持分页、作用域过滤) |
| `get_memory(mem_id)` | 按 id 获取单条 |
| `update_memory(mem_id, content)` | 按 id 覆盖记忆文本 |
| `delete_memory(mem_id)` | 按 id 删除单条 |
| `delete_all_memories(user_id?, ...)` | 批量删除某作用域内全部记忆 |
| `delete_entities(entity_type, entity_id)` | 删除某实体及其记忆 |
| `list_entities(entity_type?)` | 列出已存的 user/agent/app/run |

## 作用域(scope)

每条记忆可归属到 `user_id` / `agent_id` / `app_id` / `run_id`。保存时带上作用域,
检索和列举时用同样的作用域过滤,可以把不同用户/场景的记忆隔开。多数单用户场景
留空即可。

## 何时保存(add_memory)

当用户透露了以后会用得上的持久信息时,主动保存:

- **偏好**:"我喜欢用 TypeScript"、"回答简短一点"
- **事实/身份**:角色、团队、常用技术栈
- **项目决策**:架构选择、约定、待办
- 用户明确说"记住……"

保存前先判断:这条信息**下次会话还有意义吗**?是 → 存;只对当前对话有用 → 不存。

## 何时检索(search_memories)

- 用户提到过去的事("上次我们说的那个方案")
- 回答前可能需要用户的偏好/背景
- 用户直接问"你还记得……吗"

检索用自然语言 query 即可,靠语义匹配,不必和原文逐字一致。

## 更新与去重

- 保存前可先 `search_memories` 看是否已有高度相似的记忆,避免同一事实反复写入。
- 已有记忆内容变化时,用 `update_memory` 覆盖,而不是新增一条。

## 注意

- 记忆本地存储,不上传云端。
- 首次检索时会在本地初始化语义模型,可能稍慢,之后即快。
