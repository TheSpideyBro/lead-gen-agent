#!/usr/bin/env bash
#
# agent_workspace.sh — give each agent its own isolated, dedicated workspace.
#
# Every agent works in a separate directory on its own branch (agent/<name>),
# all sharing one .git (and therefore one set of hooks, including the pre-commit
# sanity gate). Because each agent has a distinct working directory, they can
# NEVER clobber each other's files. Work integrates to the default branch via
# merge / pull request.
#
# Usage:
#   scripts/agent_workspace.sh new <name>      Create workspace + branch agent/<name>
#   scripts/agent_workspace.sh list            List all workspaces
#   scripts/agent_workspace.sh remove <name>   Remove the workspace (branch kept)
#   scripts/agent_workspace.sh path <name>     Print the workspace directory
#
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_DIR="$REPO_ROOT/worktrees"
BRANCH_PREFIX="agent/"
DEFAULT_BRANCH="$(git -C "$REPO_ROOT" symbolic-ref --short HEAD 2>/dev/null || echo main)"

die() { echo "error: $*" >&2; exit 1; }

usage() {
  grep '^#' "$0" | grep -E '^#( |$)' | sed 's/^# \{0,1\}//' | sed -n '1,16p'
}

cmd_new() {
  local name="${1:-}"
  [ -n "$name" ] || die "agent name required:  agent_workspace.sh new <name>"
  echo "$name" | grep -qE '^[A-Za-z0-9._-]+$' || die "invalid name '$name' (use letters, digits, . _ -)"

  local branch="${BRANCH_PREFIX}${name}"
  local path="$WORKTREE_DIR/$name"
  [ -e "$path" ] && die "workspace already exists: $path"

  # Branch from the freshest default branch available.
  local base="$DEFAULT_BRANCH"
  if git -C "$REPO_ROOT" remote get-url origin >/dev/null 2>&1; then
    git -C "$REPO_ROOT" fetch origin "$DEFAULT_BRANCH" --quiet 2>/dev/null || true
    git -C "$REPO_ROOT" rev-parse --verify --quiet "origin/$DEFAULT_BRANCH" >/dev/null \
      && base="origin/$DEFAULT_BRANCH"
  fi

  mkdir -p "$WORKTREE_DIR"
  if git -C "$REPO_ROOT" rev-parse --verify --quiet "$branch" >/dev/null; then
    git -C "$REPO_ROOT" worktree add "$path" "$branch"          # branch exists → attach
  else
    git -C "$REPO_ROOT" worktree add -b "$branch" "$path" "$base"  # create branch
  fi

  # Seed the workspace with credentials so the agent can actually run.
  # .env is gitignored, so a fresh worktree won't have it.
  if [ -f "$REPO_ROOT/.env" ] && [ ! -f "$path/.env" ]; then
    cp "$REPO_ROOT/.env" "$path/.env"
    echo "  copied .env into the workspace"
  fi

  cat <<EOF

Workspace ready:
  agent:  $name
  branch: $branch  (based on $base)
  path:   $path

Point the agent at that directory as its working dir. It shares this repo's
.git and pre-commit hook, but has its own files — no collisions with other agents.
When done:  cd into it, commit, push, open a PR into '$DEFAULT_BRANCH'.
EOF
}

cmd_list() {
  echo "Workspaces (git worktrees):"
  git -C "$REPO_ROOT" worktree list
}

cmd_remove() {
  local name="${1:-}"
  [ -n "$name" ] || die "agent name required:  agent_workspace.sh remove <name>"
  local path="$WORKTREE_DIR/$name"
  git -C "$REPO_ROOT" worktree remove "$path"
  echo "Removed workspace: $path"
  echo "(branch ${BRANCH_PREFIX}${name} kept — delete with: git branch -D ${BRANCH_PREFIX}${name})"
}

cmd_path() {
  local name="${1:-}"
  [ -n "$name" ] || die "agent name required"
  echo "$WORKTREE_DIR/$name"
}

case "${1:-}" in
  new)        shift; cmd_new "$@" ;;
  list|ls)    shift; cmd_list "$@" ;;
  remove|rm)  shift; cmd_remove "$@" ;;
  path)       shift; cmd_path "$@" ;;
  ""|-h|--help|help) usage ;;
  *) die "unknown command '$1' (try: new | list | remove | path)" ;;
esac
