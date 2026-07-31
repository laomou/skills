# laomou-skills

[中文](README_zh.md)

Plugin marketplace for Claude Code / Codex.

## Install

Add the marketplace:

```shell
/plugin marketplace add laomou/skills
```

## Plugins

### lm-mem

Cross-session semantic memory — let Claude save and retrieve memories across sessions. Each
memory can be bound to a scope for multi-user / multi-context isolation.

Install:

```shell
/plugin install lm-mem@laomou-skills
```

Core: [lm-mem](https://github.com/laomou/lm-mem), a standalone PyPI package; this plugin is the
Claude Code integration shell.

MCP tools: create / read / update / delete, semantic search, import / export

Skill: `/lm-mem:memory` — tells Claude when to call the tools
