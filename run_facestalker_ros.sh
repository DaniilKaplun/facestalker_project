#!/usr/bin/env bash
set -u
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || exit 1
cd "$project_dir" || exit 1
exec > >(tee "$project_dir/facestalker-ros.log") 2>&1
ds_root=/opt/nvidia/deepstream/deepstream-9.2
export LD_LIBRARY_PATH="$ds_root/lib:${LD_LIBRARY_PATH:-}"
export GST_PLUGIN_PATH="$ds_root/lib/gst-plugins:${GST_PLUGIN_PATH:-}"
if [[ ! -r /opt/ros/jazzy/setup.bash ]]; then
  echo 'ROS 2 Jazzy is missing. Run the FaceStalker dependency installer.'
  result=1
else
  export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
  # ROS environment hooks may read unset variables.
  set +u
  source /opt/ros/jazzy/setup.bash &&
    "$project_dir/.venv-deepstream/bin/python" facestalker_ros.py "$@"
  result=$?
fi
if [[ "$result" -ne 0 && ! -t 0 ]] && command -v zenity >/dev/null &&
   [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
  zenity --error --title='FaceStalker ROS 2' \
    --text="FaceStalker ROS 2 не запустился. Журнал: $project_dir/facestalker-ros.log" || true
elif [[ "$result" -ne 0 && -t 0 ]]; then
  read -r -p 'Ошибка. Нажмите Enter, чтобы закрыть окно…' || true
fi
exit "$result"
