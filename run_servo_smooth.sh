#!/usr/bin/env bash
set -uo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" || exit 1
python3 -u test_servo_smooth.py "$@" 2>&1 | tee servo-smooth.log
result=${PIPESTATUS[0]}
if [[ -t 0 ]]; then
  read -r -p 'Тест завершён. Нажмите Enter, чтобы закрыть окно…' || true
fi
exit "$result"
