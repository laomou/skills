# laomou-skills

Claude Code 插件市场,当前收录一个插件:**lm-mem** —— 跨会话语义记忆。

## 目录结构

```
.
├── .claude-plugin/
│   └── marketplace.json          # Claude 市场清单
├── .codex-plugin/
│   └── marketplace.json          # Codex 市场清单
└── plugins/
    └── lm-mem/                   # 插件:语义记忆
        ├── .mcp.json             # MCP 注册:uvx lm-mem-mcp
        ├── .codex-mcp.json       # Codex MCP 注册
        ├── README.md             # 简短说明
        └── skills/
            └── memory/
                └── SKILL.md      # 技能:何时存/取记忆
```

## 插件:lm-mem

让 Claude 跨会话保存与检索记忆。每条记忆可绑定作用域,做多用户/场景隔离。

> 底层核心包 [`lm-mem`](https://github.com/laomou/lm-mem) 独立在 PyPI 发布,
> 本插件是 Claude Code 集成壳。`uvx lm-mem-mcp` 自动拉取最新版本。

### MCP 工具(14 个)

| 工具 | 用途 |
|------|------|
| `add_memory` | 保存一条记忆(content/messages、metadata、TTL,自动查重) |
| `search_memories` | 语义检索(按作用域 / metadata 过滤) |
| `get_memories` | 列出记忆(分页 + 过滤) |
| `get_memory` | 按 id 获取单条 |
| `update_memory` | 更新文本 / metadata / 标签 |
| `delete_memory` | 删除单条 |
| `delete_all_memories` | 批量删除某作用域内全部记忆 |
| `delete_entities` | 删除某实体及其记忆 |
| `list_entities` | 列出已存的实体 |
| `memory_stats` | 统计总数、聚合、过期数 |
| `export_memories` | 导出(JSON / CSV) |
| `import_memories` | 导入(JSON / CSV) |
| `purge_expired` | 清理过期记忆 |
| `get_user_context` | 获取用户长期属性 |

配套技能 `/lm-mem:memory` 负责告诉 Claude **何时**调用这些工具。

## 安装

```shell
/plugin marketplace add laomou/skills
/plugin install lm-mem@laomou-skills
```

装完后 MCP 工具自动可用,技能通过 `/lm-mem:memory` 调用。

## Web UI

自带只读 Web 界面,浏览器查看/检索记忆:

```shell
pip install lm-mem
lm-mem web start   # http://127.0.0.1:7531
# 或
uvx lm-mem web start
```

## 环境变量

由 `lm-mem` 包处理,详见 [lm-mem README](https://github.com/laomou/lm-mem)。