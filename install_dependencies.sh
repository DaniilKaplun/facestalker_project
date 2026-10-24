#!/usr/bin/env bash
# Install camera and servo GUI runtimes on Ubuntu/Jetson.

set -euo pipefail

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer supports Ubuntu/Debian systems only." >&2
  exit 1
fi

echo "Installing FaceStalker camera and servo dependencies..."
sudo apt-get update
sudo apt-get install --yes python3 python3-opencv opencv-data python3-tk python3-jetson-gpio

python3 - <<'PY'
import cv2
import tkinter
import Jetson.GPIO
print(f"OpenCV {cv2.__version__} is ready.")
print(f"Tk {tkinter.TkVersion} and Jetson.GPIO are ready.")
PY

echo "Installation complete. Take a photo with: python3 take_photo.py"
