#!/usr/bin/env bash
# Update the checkout before opening the terminal account picker.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$project_dir"

warn() { printf 'Switcheroo: %s\n' "$*" >&2; }
export GIT_TERMINAL_PROMPT=0
export GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=10'

if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
  warn 'No Git history is configured; opening the local copy.'
elif ! upstream=$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null); then
  warn 'No upstream branch is configured; opening the local copy.'
else
  branch=$(git symbolic-ref --short HEAD)
  remote=$(git config --get "branch.$branch.remote")
  if ! timeout 45s git fetch -- "$remote"; then
    warn 'GitHub update check failed; opening the local copy.'
  elif [[ -n "$(git status --porcelain)" ]]; then
    warn 'Local changes exist; skipping pull and opening the local copy.'
  else
    old_head=$(git rev-parse HEAD)
    old_requirements=$(git hash-object requirements.txt)
    if ! git merge-base --is-ancestor HEAD "$upstream"; then
      warn 'Local history is ahead or diverged; skipping pull.'
    elif ! timeout 45s git pull --ff-only --no-rebase; then
      warn 'Pull failed; opening the local copy.'
    elif [[ "$old_head" != "$(git rev-parse HEAD)" ]]; then
      warn 'Updated from GitHub.'
      if [[ "$old_requirements" != "$(git hash-object requirements.txt)" ]]; then
        "$project_dir/.venv/bin/python" -m pip install -r requirements.txt
      fi
    fi
  fi
fi

exec bash "$project_dir/switcheroo.sh" "$@"
