# laomou-skills

Claude Code / Codex 插件市场。

## 安装

添加市场：

```shell
/plugin marketplace add laomou/skills
```

## 插件列表

### lm-mem

跨会话语义记忆，让 Claude 跨会话保存与检索记忆。每条记忆可绑定作用域，做多用户/场景隔离。

安装：

```shell
/plugin install lm-mem@laomou-skills
```

底层核心：[lm-mem](https://github.com/laomou/lm-mem) 独立 PyPI 包，本插件为 Claude Code 集成壳。

MCP 工具：增删改查、语义检索、导入导出

技能：`/lm-mem:memory` —— 告诉 Claude 何时调用工具
