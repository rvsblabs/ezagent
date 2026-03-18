# Git worktrees in ezagent

Use a **worktree** when you want a second checkout of the same repo (e.g. another branch or parallel agent work) without cloning again. Paths under `.worktree/` are conventional in this repo; they stay out of the main tree and avoid socket/PID collisions if you use different project dirs per worktree.

## Prerequisites

- Run all commands from your **primary clone** (the one that already has `origin`), unless noted.
- Replace `<branch>`, `<path>`, and remote names to match your setup.

## Create a worktree

**New local branch from current `HEAD`:**

```bash
cd /path/to/ezagent   # main clone root
git worktree add .worktree/<short-name> -b <branch>
```

**Track an existing remote branch:**

```bash
git fetch origin
git worktree add .worktree/<short-name> origin/<branch>
```

**Detached HEAD (e.g. specific commit) — rarely needed:**

```bash
git worktree add .worktree/<short-name> <commit-sha>
```

Then install and work:

```bash
cd .worktree/<short-name>
uv sync
uv sync --group dev          # if running tests
uv sync --extra serve        # if integration tests or ez serve
```

## List and remove

```bash
git worktree list
git worktree remove .worktree/<short-name>   # from any worktree in the repo; dir must be clean or use --force
```

Remove the branch separately if you no longer need it: `git branch -d <branch>`.

## Gotchas

| Issue | What to do |
|-------|------------|
| **Daemon/socket** | Each worktree is a different directory → different `/tmp/ezagent_<md5>.sock`. Run `ez start` only in the tree you intend, or `ez stop` before switching. |
| **Uncommitted work** | Commit, stash, or discard before `git worktree remove` (or use `git worktree remove --force` if you accept losing local changes in that tree). |
| **Same branch in two trees** | Git allows it but is confusing; prefer one worktree per branch. |

## Docs map (don’t guess)

| Doc | Purpose |
|-----|---------|
| **AGENTS.md** (repo root) | Agent/CI context: commands, tests, integration env vars. |
| **CLAUDE.md** (repo root) | Deeper ezagent internals for Claude Code. |
| **README.md** | User-facing CLI and product overview. |
| **This folder** | Worktree workflow; extend here if you add more shared agent-only notes. |

When you add behavior that agents must follow, update **AGENTS.md** and/or **CLAUDE.md** in the **main clone** and merge as usual—worktrees share one Git history.
