# laomou-skills

Claude Code 插件市场,当前收录一个插件:**lm-mem** —— 本地语义(向量)记忆。

## 目录结构

```
.
├── .claude-plugin/
│   └── marketplace.json         # Claude 市场清单(name: laomou-skills)
├── .codex-plugin/
│   └── marketplace.json         # Codex 市场清单(name: laomou-skills)
└── plugins/
    └── lm-mem/                  # 插件:本地语义记忆
        ├── .claude-plugin/
        │   └── plugin.json      # Claude 插件清单
        ├── .codex-plugin/
        │   └── plugin.json      # Codex 插件清单(skills/mcpServers 字段指向资源)
        ├── .mcp.json            # Claude 的 MCP 注册(${CLAUDE_PLUGIN_ROOT})
        ├── .codex-mcp.json      # Codex 的 MCP 注册(${CODEX_PLUGIN_ROOT})
        ├── server.py            # MCP server:语义记忆接口(两端共用)
        ├── pyproject.toml       # Python 依赖
        └── skills/
            └── memory/
                └── SKILL.md     # 技能:告诉助手何时存/取记忆(两端共用)
```

## 插件:lm-mem

让 Claude 跨会话保存与检索记忆,语义检索(意思相近即可命中),记忆本地存储。
每条记忆可绑定 `user_id` / `agent_id` / `app_id` / `run_id` 作用域,做多用户/场景隔离。

### MCP 工具(12 个)

| 工具 | 用途 |
|------|------|
| `add_memory` | 保存一条记忆(支持 content/messages、metadata、TTL,默认自动查重) |
| `search_memories` | 语义检索(可按作用域 / metadata 过滤) |
| `get_memories` | 列出记忆(分页 + 作用域 / metadata 过滤) |
| `get_memory` | 按 id 获取单条 |
| `update_memory` | 按 id 更新文本 / metadata / 标签 |
| `delete_memory` | 按 id 删除单条 |
| `delete_all_memories` | 批量删除某作用域内全部记忆 |
| `delete_entities` | 删除某实体及其记忆 |
| `list_entities` | 列出已存的 user/agent/app/run |
| `memory_stats` | 统计总数、按作用域/标签/分类聚合、过期数 |
| `export_memories` | 批量导出记忆(JSON / CSV) |
| `purge_expired` | 清理已过期(TTL)的记忆 |

配套技能 `/lm-mem:memory` 负责告诉 Claude **何时**调用这些工具(何时该记、何时该查)。

## 安装

### Claude Code

```shell
# 添加市场(GitHub 仓库路径 owner/repo)
/plugin marketplace add laomou/skills

# 安装插件(插件名@市场名)
/plugin install lm-mem@laomou-skills
```

装完后,MCP 工具自动可用,技能通过 `/lm-mem:memory` 调用。

> 本地开发验证也可直接用本地目录:
> `/plugin marketplace add /path/to/skills`

### Codex

Codex 复用同一份 `server.py` 与 `skills/`,通过 `.codex-plugin` / `.codex-mcp.json`
接入。在 Codex 里添加本仓库为插件市场并安装 `lm-mem` 即可(顶层
`.codex-plugin/marketplace.json` 已声明该插件)。MCP server 用 `${CODEX_PLUGIN_ROOT}`
定位,由 `uv` 自动拉起、管理依赖,与 Claude 端行为一致。

## 依赖

lm-mem 的 MCP server 用 Python 编写,依赖见 `plugins/lm-mem/pyproject.toml`。
`.mcp.json` 通过 [`uv`](https://github.com/astral-sh/uv) 拉起 server 并自动管理依赖,
首次运行会初始化本地语义模型。

## 测试

```shell
cd plugins/lm-mem
uv run --group dev pytest
```

测试使用临时目录作为记忆库,不会影响真实数据。
