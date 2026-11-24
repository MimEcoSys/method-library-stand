#!/bin/bash
# Run stand scenarios with the OpenRouter key read from a file kept outside the repository.
# Usage: ./run_stand.sh <scenario_id|all> [--repeats N] [--tag TAG]   (key file: $STAND_KEY_FILE, default ~/.config/iwe/openrouter-stand-key)
set -euo pipefail
KEY_FILE="${STAND_KEY_FILE:-$HOME/.config/iwe/openrouter-stand-key}"
[ -r "${KEY_FILE}" ] || { echo "key file not found: ${KEY_FILE}" >&2; exit 1; }
OPENROUTER_API_KEY="$(tr -d '[:space:]' < "${KEY_FILE}")"
case "${OPENROUTER_API_KEY}" in sk-or-*) ;; *) echo "key file does not hold an OpenRouter key" >&2; exit 1;; esac
export OPENROUTER_API_KEY
exec python3 "$(dirname "$0")/run_scenario.py" "$@"
