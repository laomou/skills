---
name: hello-world
description: A minimal example skill that greets the user and shows the basic SKILL.md structure
---

## What It Does

Prints a friendly greeting to the user. This skill exists to demonstrate the
minimum viable structure of a skill: just a `SKILL.md` file with YAML frontmatter
and markdown body content.

## When to Use

- The user asks for a greeting or says hello
- You need a starting point / template for creating a new skill
- Demonstrating the `.claude-plugin` skill pattern to someone

## Requirements

None. This is a pure-agent skill — no external tools or dependencies needed.

## How to Use

When this skill is active, respond to greeting requests by saying:

```
Hello from the hello-world skill! 👋
```

## Examples

| User says | Agent responds |
|-----------|---------------|
| "say hello" | "Hello from the hello-world skill! 👋" |
| "greet me" | "Hello from the hello-world skill! 👋" |
