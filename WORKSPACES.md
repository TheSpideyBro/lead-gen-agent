# Multi-Agent Workspaces

This repo is worked on by more than one AI agent at a time. To stop agents from
overwriting each other's files, **every agent gets its own isolated, dedicated
workspace** — a separate directory on its own branch, all backed by one shared
Git history.

This replaces the old `.mcp/` advisory-lock scheme (which relied on every agent
voluntarily checking lock files — they didn't). Isolation is now enforced by the
filesystem, not by cooperation.

## How it works

```
lead-gen-agent/                 # main repo — branch `main` (integration branch)
├── .git/                       # ONE shared git dir + ONE shared set of hooks
├── scripts/
│   ├── agent_workspace.sh      # create / list / remove agent workspaces
│   └── precommit_check.py      # sanity gate run by the shared pre-commit hook
└── worktrees/                  # gitignored — agent workspaces live here
    ├── alice/                  # branch agent/alice   (Alice's files only)
    └── bob/                    # branch agent/bob     (Bob's files only)
```

Each workspace is a **Git worktree**: a full working copy on its own branch that
shares the single `.git` directory. Two consequences:

- **No collisions.** Each agent edits files in its own directory. Nothing one
  agent saves can clobber another agent's uncommitted work.
- **Shared safety net.** All worktrees share `.git/hooks`, so the pre-commit
  gate (`py_compile` + `pyflakes` undefined-name check) runs on **every** agent's
  commits automatically — no per-workspace setup.

## Quick start

```bash
# Create a workspace for an agent named "alice"
scripts/agent_workspace.sh new alice
# → creates branch agent/alice off the latest main, checks it out at
#   worktrees/alice/, and copies .env in so it can run.

# Launch that agent with worktrees/alice as its working directory.

# See every workspace
scripts/agent_workspace.sh list

# Tear one down when the agent is finished (its branch is kept)
scripts/agent_workspace.sh remove alice
```

## Branch & integration convention

| Branch          | Purpose                                             |
|-----------------|-----------------------------------------------------|
| `main`          | Integration branch — always working, always green.  |
| `agent/<name>`  | One agent's work-in-progress.                        |

Agents commit on their own `agent/<name>` branch, push, and open a **pull
request into `main`**. Merging through PRs gives:

- **Clean attribution** — every commit carries its real author and branch.
- **No mid-air clobbering** — Git merges changes; it never silently overwrites.
- **A review gate** — conflicts surface as PR conflicts, not corrupted files.

## Notes

- `worktrees/` is gitignored — the workspaces themselves are never committed.
- Each workspace gets its own copy of `.env` (gitignored). Update credentials in
  the root `.env`; new workspaces inherit it at creation time.
- `data/` (the SQLite DB) is per-workspace by default. For a shared lead
  database across agents, set `LEAD_DB_PATH` to one absolute path in each `.env`.
- `venv/` is not copied. Either create a venv per workspace, or reuse the root
  one (`source ../../venv/Scripts/activate` on Windows) since deps are identical.
- The pre-commit gate applies everywhere automatically. Override a false
  positive with `git commit --no-verify`. On a fresh clone the hook must be
  reinstalled once (it lives in `.git/hooks/`, which Git never tracks).
