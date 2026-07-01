---
name: hello-script
description: A skill with bundled scripts — greets the user by running a helper script for platform-aware output
---

## What It Does

Same greeting concept as `hello-world`, but runs a real shell script (`scripts/greet.sh`)
to produce the output. This pattern is useful when your skill needs to:

- Run local tooling (compilers, linters, package managers)
- Execute platform-specific logic (OS detection, path resolution)
- Keep complex logic out of the markdown instructions

## When to Use

- You need a reference for skills that bundle executable scripts
- The user asks for system information alongside a greeting
- Demonstrating the "skill with scripts" pattern

## Requirements

- `bash` (any modern Linux/macOS/WSL environment)

## How to Use

Run the bundled script:

```bash
bash skills/hello-script/scripts/greet.sh
```

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/greet.sh` | Prints OS, hostname, date, and a greeting |

## Examples

```bash
$ bash skills/hello-script/scripts/greet.sh
Hello from hello-script!
  OS:       Linux
  Hostname: dev-machine
  Date:     Wed Jul  1 16:58:00 CST 2026
```
