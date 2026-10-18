#!/usr/bin/env bash
set -uo pipefail
cd /home/daniil/facestalker_project || exit 1
python3 -u sweep_servo.py 2>&1 | tee servo-sweep.log
result=${PIPESTATUS[0]}
echo "Exit code: $result"
read -r -p 'Press Enter to close...' answer
exit "$result"
