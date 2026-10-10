#!/usr/bin/env python3
"""Capture one photo from the UGREEN USB camera on the Jetson."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import cv2
except ModuleNotFoundError:
    sys.exit(
        "OpenCV is not installed. On the Jetson run: "
        "sudo apt-get install python3-opencv"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Take one photo from a USB camera and save it on the Desktop."
    )
    parser.add_argument(
        "--device",
        default="/dev/video0",
        help="V4L2 camera device (default: /dev/video0)",
    )
    parser.add_argument("--width", type=int, default=1920, help="Photo width")
    parser.add_argument("--height", type=int, default=1080, help="Photo height")
    parser.add_argument(
        "--warmup-frames",
        type=int,
        default=15,
        help="Frames to discard while the camera adjusts exposure (default: 15)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / "Desktop" / "photos",
        help="Directory for saved images (default: ~/Desktop/photos)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.width < 1 or args.height < 1 or args.warmup_frames < 0:
        print("Width, height, and warmup frames must be valid values.", file=sys.stderr)
        return 2

    camera = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
    if not camera.isOpened():
        print(f"Cannot open camera: {args.device}", file=sys.stderr)
        return 1

    try:
        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

        frame = None
        for _ in range(args.warmup_frames + 1):
            success, frame = camera.read()
            if not success:
                print("The camera did not provide a frame.", file=sys.stderr)
                return 1
            time.sleep(0.03)
    finally:
        camera.release()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    filename = datetime.now().strftime("photo-%Y%m%d-%H%M%S.jpg")
    output_path = args.output_dir / filename

    if not cv2.imwrite(str(output_path), frame):
        print(f"Could not write photo: {output_path}", file=sys.stderr)
        return 1

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
