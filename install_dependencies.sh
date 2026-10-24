#!/usr/bin/env bash
# Single installer for all FaceStalker dependencies: camera, servo and DeepStream.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"
if [[ $# -ne 0 ]]; then
  echo "Usage: bash install_dependencies.sh" >&2
  exit 2
fi
if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer supports Ubuntu/Jetson only." >&2
  exit 1
fi

# The model and its config can be prepared without sudo or a running camera.
python3 - "$project_dir" <<'PY'
import hashlib
from pathlib import Path
import sys
import urllib.request

root = Path(sys.argv[1])
model_dir = root / 'models'
model_dir.mkdir(exist_ok=True)
revision = '48b10fa505aeb51fbd127fc60a5c660040e823b7'
expected = '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'
model = model_dir / 'yunet.onnx'
if not model.is_file() or hashlib.sha256(model.read_bytes()).hexdigest() != expected:
    url = ('https://media.githubusercontent.com/media/opencv/opencv_zoo/' + revision +
           '/models/face_detection_yunet/face_detection_yunet_2023mar.onnx')
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit('YuNet download checksum mismatch; installation stopped.')
    temporary = model.with_suffix('.onnx.tmp')
    temporary.write_bytes(data)
    temporary.replace(model)
license_path = model_dir / 'YuNet-LICENSE'
if not license_path.is_file():
    url = ('https://raw.githubusercontent.com/opencv/opencv_zoo/' + revision +
           '/models/face_detection_yunet/LICENSE')
    with urllib.request.urlopen(url, timeout=60) as response:
        license_path.write_bytes(response.read())
print('YuNet model verified:', model)
PY

# This profile matches the actual Jetson: Ubuntu 24.04 / L4T R39.2 / Python 3.12.
# Stop rather than install an incompatible SDK on another JetPack release.
if [[ "$(dpkg --print-architecture)" != arm64 ]] ||
   ! grep -q '^# R39 .*REVISION: 2\.' /etc/nv_tegra_release ||
   ! python3 -c 'import sys; assert sys.version_info[:2] == (3, 12)'; then
  echo "This DeepStream profile requires Jetson L4T 39.2 and Python 3.12." >&2
  exit 1
fi
if [[ -z "$(apt-cache policy deepstream-9.2 | sed -n 's/.*Candidate: //p')" ]] ||
   apt-cache policy deepstream-9.2 | grep -q 'Candidate: (none)'; then
  echo "NVIDIA repository has no deepstream-9.2 candidate for this Jetson." >&2
  exit 1
fi

packages=(deepstream-9.2 python3-opencv opencv-data python3-tk python3-jetson-gpio python3-numpy
  python3-venv python3-dev python3-gi python3-gst-1.0 \
  gir1.2-gstreamer-1.0 gstreamer1.0-tools gstreamer1.0-plugins-good \
  libgstreamer1.0-dev libglib2.0-dev cmake build-essential git)
missing_packages=()
for package in "${packages[@]}"; do
  if [[ "$(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true)" != installed ]]; then
    missing_packages+=("$package")
  fi
done
if [[ ${#missing_packages[@]} -gt 0 ]]; then
  sudo apt-get update
  sudo apt-get install --yes "${missing_packages[@]}"
else
  echo "System dependencies already installed; resuming build without sudo."
fi

ds_root=/opt/nvidia/deepstream/deepstream-9.2
ds_include="$ds_root/includes"
if [[ ! -f "$ds_include/gstnvdsmeta.h" ]]; then
  ds_include="$ds_root/sources/includes"
fi
if [[ ! -f "$ds_include/gstnvdsmeta.h" ]]; then
  echo "DeepStream SDK headers not found under $ds_root." >&2
  exit 1
fi
export LD_LIBRARY_PATH="$ds_root/lib:${LD_LIBRARY_PATH:-}"
export GST_PLUGIN_PATH="$ds_root/lib/gst-plugins:${GST_PLUGIN_PATH:-}"
for plugin in nvinfer nvstreammux nvvideoconvert; do
  gst-inspect-1.0 "$plugin" >/dev/null
done

mkdir -p "$project_dir/.deepstream-build" "$project_dir/lib"
python3 -m venv --system-site-packages "$project_dir/.venv-deepstream"
python="$project_dir/.venv-deepstream/bin/python"
bindings="$project_dir/.deepstream-build/deepstream_python_apps"
revision=8ad0349ed7a496fae35ebb21c350641727070b89
if [[ ! -d "$bindings/.git" ]]; then
  git clone --no-checkout https://github.com/NVIDIA-AI-IOT/deepstream_python_apps.git "$bindings"
fi
git -C "$bindings" checkout --detach "$revision"
git -C "$bindings" submodule update --init --depth 1 bindings/3rdparty/pybind11
# Build the NVIDIA CMake target directly against the installed SDK headers.
# pyds has no matching prebuilt wheel for DeepStream 9.2.
cmake -S "$bindings/bindings" -B "$project_dir/.deepstream-build/pyds" \
  -DDS_PATH="$ds_root" -DPYTHON_MAJOR_VERSION=3 -DPYTHON_MINOR_VERSION=12 \
  -DCMAKE_CXX_FLAGS="-I$ds_include"
cmake --build "$project_dir/.deepstream-build/pyds" --parallel 2
site_packages="$("$python" -c 'import sysconfig; print(sysconfig.get_path("platlib"))')"
install -m 644 "$project_dir/.deepstream-build/pyds/pyds.so" "$site_packages/pyds.so"

cuda_include=""
for candidate in /usr/local/cuda/include /usr/local/cuda/targets/sbsa-linux/include /usr/local/cuda/targets/aarch64-linux/include; do
  if [[ -f "$candidate/cuda_runtime_api.h" ]]; then
    cuda_include="$candidate"
    break
  fi
done
if [[ -z "$cuda_include" ]]; then
  echo "CUDA development headers were not found; check the DeepStream SDK installation." >&2
  exit 1
fi
cuda_crt_flags=()
if [[ ! -f "$cuda_include/crt/host_defines.h" ]]; then
  # cuda-cudart-dev does not pull in CUDA's compiler headers on this image.
  # Only these headers are needed: unpack the official package locally,
  # without installing a compiler or changing system directories.
  cuda_crt_root="$project_dir/.deepstream-build/cuda-crt"
  mkdir -p "$cuda_crt_root"
  if [[ ! -f "$cuda_crt_root/usr/local/cuda-13.2/targets/sbsa-linux/include/crt/host_defines.h" ]]; then
    (
      cd "$cuda_crt_root"
      apt-get download cuda-crt-13-2
      for archive in cuda-crt-13-2_*.deb; do
        dpkg-deb -x "$archive" "$cuda_crt_root"
      done
    )
  fi
  crt_include="$cuda_crt_root/usr/local/cuda-13.2/targets/sbsa-linux/include"
  test -f "$crt_include/crt/host_defines.h"
  cuda_crt_flags=(-I"$crt_include")
fi
g++ -std=c++17 -O2 -shared -fPIC \
  -I"$ds_include" -I"$cuda_include" "${cuda_crt_flags[@]}" "$project_dir/nvdsinfer_yunet.cpp" \
  -o "$project_dir/lib/libnvdsinfer_yunet.so"
"$python" - <<'PY'
import ctypes
import cv2
import gi
import numpy as np
import pyds
import tkinter
import Jetson.GPIO
gi.require_version('Gst', '1.0')
from gi.repository import Gst
Gst.init(None)
for name in ('nvinfer', 'nvstreammux', 'nvvideoconvert'):
    assert Gst.ElementFactory.find(name), f'Missing DeepStream plugin: {name}'
assert np.__version__.split('.')[0] == '1', 'pyds requires NumPy 1.x'
parser = ctypes.CDLL('./lib/libnvdsinfer_yunet.so')
assert parser.NvDsInferParseYuNet
print('Camera, servo, DeepStream, Python bindings and YuNet parser verified.')
PY
echo "All FaceStalker dependencies installed and verified. Launch: bash $project_dir/run_photo_deepstream.sh"
