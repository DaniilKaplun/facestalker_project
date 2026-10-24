#!/usr/bin/env bash
# Keep the capture result visible when launched from the Desktop.
set -u

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)" || exit 1
cd "$project_dir" || exit 1
exec > >(tee "$project_dir/photo-deepstream.log") 2>&1

ds_root=/opt/nvidia/deepstream/deepstream-9.2
export LD_LIBRARY_PATH="$ds_root/lib:${LD_LIBRARY_PATH:-}"
export GST_PLUGIN_PATH="$ds_root/lib/gst-plugins:${GST_PLUGIN_PATH:-}"

config="${DEEPSTREAM_FACE_CONFIG:-$project_dir/face_detector_pgie_config.txt}"
python="$project_dir/.venv-deepstream/bin/python"

if [[ ! -f "$config" ]]; then
  echo "Конфигурация не найдена: $config"
  result=1
elif [[ ! -x "$python" || ! -f "$project_dir/models/yunet.onnx" || ! -f "$project_dir/lib/libnvdsinfer_yunet.so" ]]; then
  echo "Запустите ярлык «Установить зависимости FaceStalker»."
  result=1
else
  "$python" take_photo_deepstream.py --pgie-config "$config" "$@"
  result=$?
fi

if [[ "$result" -ne 0 ]]; then
  echo "Съёмка завершилась с ошибкой (код $result)."
  echo "Для установки зависимостей используйте ярлык «Установить зависимости FaceStalker»."
fi
read -r -p "Нажмите Enter, чтобы закрыть окно…" || true
exit "$result"
