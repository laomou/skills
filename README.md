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
        ├── .mcp.json             # MCP 注册:uvx lm-mem mcp
        ├── .codex-mcp.json       # Codex MCP 注册
        └── skills/
            └── memory/
                └── SKILL.md      # 技能:何时存/取记忆
```

## 插件:lm-mem

让 Claude 跨会话保存与检索记忆。每条记忆可绑定作用域,做多用户/场景隔离。

> 底层核心包 [`lm-mem`](https://github.com/laomou/lm-mem) 独立在 PyPI 发布,
> 本插件是 Claude Code 集成壳。`uvx lm-mem mcp` 自动拉取最新版本。

插件暴露记忆的增删改查、语义检索、导入导出等 MCP 工具,完整清单见 lm-mem 仓库;
配套技能 `/lm-mem:memory` 负责告诉 Claude **何时**调用这些工具。

## 安装

```shell
/plugin marketplace add laomou/skills
/plugin install lm-mem@laomou-skills
```

装完后 MCP 工具自动可用,技能通过 `/lm-mem:memory` 调用。
