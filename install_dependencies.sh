#!/usr/bin/env bash
# Install the runtime needed by take_photo.py on Ubuntu/Jetson.

set -euo pipefail

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer supports Ubuntu/Debian systems only." >&2
  exit 1
fi

echo "Installing FaceStalker camera dependencies..."
sudo apt-get update
sudo apt-get install --yes python3 python3-opencv

python3 - <<'PY'
import cv2
print(f"OpenCV {cv2.__version__} is ready.")
PY

echo "Installation complete. Take a photo with: python3 take_photo.py"
