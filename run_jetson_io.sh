#!/usr/bin/env bash
set -u
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || exit 1
log="$project_dir/jetson-io.log"
umask 077

# Capture output only, preserving the pseudo-terminal required by curses.
script --quiet --return --command 'sudo /opt/nvidia/jetson-io/jetson-io.py' "$log"
status=$?
if (( status != 0 )); then
  printf '\nJetson-IO завершилась с кодом %s. Журнал: %s\n' "$status" "$log"
  read -r -p 'Нажмите Enter, чтобы закрыть окно…' || true
fi
exit "$status"
