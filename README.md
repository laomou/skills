# example-skills

Agent Skills 示例项目，`.claude-plugin` 模式。

## 目录结构

```
.
├── .claude-plugin/
│   ├── plugin.json          # 包清单
│   └── marketplace.json     # Skill 注册表
└── skills/
    ├── hello-world/         # 最简 skill：纯 SKILL.md
    │   └── SKILL.md
    └── hello-script/        # 带脚本的 skill
        ├── SKILL.md
        └── scripts/
            └── greet.sh
```

## Skills

| Skill | 说明 |
|-------|------|
| `hello-world` | 最简示例，纯 markdown 指令 |
| `hello-script` | 带辅助脚本的示例 |

## 使用

在 Claude Code 中安装后，通过 marketplace 激活相应的 skill 即可。
