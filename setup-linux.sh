#!/usr/bin/env bash
# Run from the extracted release folder; no administrator access required.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$project_dir"
desktop='ask'
case "${1:-}" in
  --desktop-icon) desktop='yes' ;;
  --no-desktop-icon) desktop='no' ;;
  '') ;;
  *) echo 'Usage: bash setup-linux.sh [--desktop-icon|--no-desktop-icon]' >&2; exit 2 ;;
esac
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10 or newer is required.")'
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
if ! .venv/bin/python -c 'import switcheroo; import sys; sys.exit(0 if (switcheroo.state_root() / "config.json").is_file() else 1)'; then
  bash ./switcheroo.sh init
fi
if [[ "$desktop" == ask ]]; then
  answer=''
  read -r -p 'Create an application menu entry and desktop icon? [y/N] ' answer || true
  case "$answer" in y|Y|yes|YES) desktop='yes' ;; *) desktop='no' ;; esac
fi
if [[ "$desktop" == yes ]]; then
  .venv/bin/python install-desktop.py
fi
printf 'Setup complete. Start with: bash "%s/switcheroo.sh"\n' "$project_dir"
