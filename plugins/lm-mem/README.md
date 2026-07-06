# lm-mem

**跨会话记忆的 Claude Code MCP 插件** — 让 Claude 记住你的偏好、身份、项目决策等长期信息,下次自动检索使用。

数据全部本机存储,不上传云端。语义检索(意思相近就能找到,不必字面匹配)。

## 特性

- **语义检索**:意思相近就能查到,不必字面匹配
- **多作用域**:`user_id` / `agent_id` / `app_id` / `run_id` 隔离不同来源
- **自动去重**:相似度 ≥0.85 提示,避免同一事实入库多次
- **TTL 过期**:临时便签自动清理,长期偏好永不过期
- **结构化 metadata**:`category` / `importance` / `source` 三个约定字段,便于过滤
- **Web UI**:`http://127.0.0.1:7531` 浏览/删除记忆(表格 + 抽屉详情)
- **JSON 导入导出**:一键备份还原

## 快速开始

```bash
git clone <this-repo>
cd plugins/lm-mem
./setup.sh
```

`setup.sh` 会:
1. `uv sync` 装依赖
2. 起后端(8901)
3. 起 Web UI(7531)

然后在 Claude Code 里:
```
/plugin marketplace add <path-to-repo>
/plugin install lm-mem@<marketplace-name>
```

或者手动在 `.mcp.json`(用户级 `~/.claude.json` 或项目级 `<project>/.mcp.json`)加:
```json
{
  "mcpServers": {
    "memory": {
      "command": "uv",
      "args": ["run", "--project", "<abs-path-to-plugins/lm-mem>",
               "python", "<abs-path>/manage.py", "mcp"]
    }
  }
}
```

重启 Claude Code,它会自动调用 `add_memory` / `search_memories` 等工具。

## 日常用法

**LLM 自动用**——正常聊天时 Claude 会根据 `SKILL.md` 的指引自主保存/检索,你不用管。

**手动管理**:
```bash
./manage.py backend status     # 后端在跑吗?
./manage.py web restart        # 重启 Web UI
./manage.py backend stop       # 停后端
./manage.py mcp                # 前台跑 MCP(调试用)
```

**Web UI**:浏览器打开 `http://127.0.0.1:7531` — 表格列记忆,点行进抽屉,可删除。

**备份**:调 `export_memories(fmt="json")` 或 `export_memories(fmt="csv")`,把 JSON 输出保存到文件。恢复:`import_memories(data=<json-string>)`。

## MCP 工具速查

| 工具 | 用途 |
|------|------|
| `get_user_context(user_id?, limit=10)` | 新会话冷启动,一次拉核心偏好 |
| `add_memory(content, user_id?, tags?, metadata?, ttl_seconds?)` | 保存(默认查重) |
| `search_memories(query, user_id?, metadata_filter?, limit?)` | 语义检索 |
| `get_memory(mem_id)` | 按 id 取单条 |
| `get_memories(user_id?, ...)` | 分页列 |
| `update_memory(mem_id, ...)` | 原地更新 |
| `delete_memory(mem_id)` | 删单条 |
| `delete_all_memories(user_id, ...)` | 删作用域内全部(至少给一个作用域) |
| `delete_entities(entity_type, entity_id)` | 删某实体所有记忆 |
| `list_entities(entity_type?)` | 列已有作用域实例 |
| `memory_stats(user_id?, ...)` | 统计:总数/过期/标签分布/分类分布 |
| `export_memories(fmt="json"|"csv")` | 导出 |
| `import_memories(data, fmt?)` | 导入(对称 export) |
| `purge_expired()` | 清过期项 |

所有工具返回 **JSON 字符串**(MCP-native):
- 成功 → 业务数据(如 `{"id": "..."}`)
- 失败 → 抛异常(MCP 协议层自动 `isError:true`)
- 业务分支(add_memory 查重命中) → `{"duplicate_id": ..., "similarity": ...}`

## 目录结构

```
lm-mem/
├── mcp_tools.py       # MCP 工具实现(14 个工具)
├── backend.py         # 存储层客户端
├── memory_utils.py    # 纯函数层(scope/metadata/序列化)
├── web.py             # Web UI(独立进程)
├── manage.py          # 命令行管理:backend/web/mcp
├── setup.sh           # 一键安装
├── test_mcp_tools.py  # 28 项测试
├── skills/memory/SKILL.md  # LLM 决策指南
└── .venv/             # uv 生成
```

## 数据位置

- `~/.lm-mem/` — 记忆数据 + 日志 + pid
- 备份整个 `~/.lm-mem/` 目录即可迁移到另一台机器
- 路径不受特定 AI 客户端(Claude Code/Codex/Cursor 等)绑定,可跨客户端共享同一份记忆

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `LM_MEM_BACKEND_URL` | `http://127.0.0.1:8901` | 后端连接地址 |
| `LM_MEM_DATA_DIR` | `~/.lm-mem` | 数据根目录 |
| `LM_MEM_DB_PATH` | `~/.lm-mem/chroma` | 数据存储子路径(优先于 `LM_MEM_DATA_DIR`) |
| `LM_MEM_WEB_HOST` | `127.0.0.1` | Web UI 绑定 host |
| `LM_MEM_WEB_PORT` | `7531` | Web UI 端口 |

## 开发

```bash
# 测试
uv run pytest -q

# 前台 MCP(用于本地手动测试或调试)
./manage.py mcp
```

## 常见问题

**Q: MCP 连不上,`/mcp` 报错**
A: 检查 `./manage.py backend status`——后端要先起。

**Q: 想暂停记忆功能**
A: `./manage.py backend stop`——MCP 连不上会直接返回错,不影响其他工具。

**Q: 想彻底清空记忆库**
A: `./manage.py backend stop && rm -rf ~/.lm-mem/ && ./manage.py backend start`

**Q: 备份 & 迁移到另一台机器**
A: 目标机器上 `import_memories(data=<导出的 JSON>)`;或者直接把 `~/.lm-mem/` 打包过去。

## License

MIT
