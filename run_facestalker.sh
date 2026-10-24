#!/usr/bin/env bash
set -u
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || exit 1
cd "$project_dir" || exit 1
exec > >(tee "$project_dir/facestalker.log") 2>&1
ds_root=/opt/nvidia/deepstream/deepstream-9.2
export LD_LIBRARY_PATH="$ds_root/lib:${LD_LIBRARY_PATH:-}"
export GST_PLUGIN_PATH="$ds_root/lib/gst-plugins:${GST_PLUGIN_PATH:-}"
"$project_dir/.venv-deepstream/bin/python" facestalker.py "$@"
result=$?
if [[ "$result" -ne 0 && -t 0 ]]; then
  read -r -p 'Ошибка. Нажмите Enter, чтобы закрыть окно…' || true
fi
exit "$result"
