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
        "bash /home/daniil/facestalker_project/install_dependencies.sh"
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
    parser.add_argument(
        "--face-scale-factor",
        type=float,
        default=1.1,
        help="Face-detector image scale factor (default: 1.1)",
    )
    parser.add_argument(
        "--face-min-neighbors",
        type=int,
        default=5,
        help="Face-detector minimum neighbours (default: 5)",
    )
    return parser.parse_args()


def face_cascade_path() -> Path:
    """Locate OpenCV's frontal-face model across pip and Ubuntu packages."""
    filename = "haarcascade_frontalface_default.xml"
    candidates: list[Path] = [
        Path("/usr/share/opencv4/haarcascades") / filename,
        Path("/usr/share/opencv/haarcascades") / filename,
    ]

    opencv_data = getattr(cv2, "data", None)
    haarcascades = getattr(opencv_data, "haarcascades", None)
    if haarcascades:
        candidates.insert(0, Path(haarcascades) / filename)

    cv2_module_path = getattr(cv2, "__file__", None)
    if cv2_module_path:
        candidates.append(
            Path(cv2_module_path).resolve().parent / "data" / "haarcascades" / filename
        )

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    raise RuntimeError(
        "Face-detector data is not installed. On the Jetson run: "
        "bash /home/daniil/facestalker_project/install_dependencies.sh"
    )


def load_face_detector():
    """Load the classifier once so live capture can reuse it across frames."""
    cascade_path = face_cascade_path()
    detector = cv2.CascadeClassifier(str(cascade_path))
    if detector.empty():
        raise RuntimeError(f"Could not load face detector: {cascade_path}")
    return detector


def draw_face_boxes(
    frame,
    scale_factor: float,
    min_neighbors: int,
    detector=None,
) -> int:
    """Draw green boxes around detected frontal faces and return their count."""
    if detector is None:
        detector = load_face_detector()

    grayscale = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = detector.detectMultiScale(
        grayscale,
        scaleFactor=scale_factor,
        minNeighbors=min_neighbors,
        minSize=(30, 30),
    )
    thickness = max(2, round(min(frame.shape[:2]) / 360))
    for x, y, width, height in faces:
        cv2.rectangle(
            frame,
            (int(x), int(y)),
            (int(x + width), int(y + height)),
            (0, 255, 0),
            thickness,
        )

    return len(faces)


def main() -> int:
    args = parse_args()
    if (
        args.width < 1
        or args.height < 1
        or args.warmup_frames < 0
        or args.face_scale_factor <= 1.0
        or args.face_min_neighbors < 0
    ):
        print(
            "Width, height, warmup frames, and face-detector settings must be valid values.",
            file=sys.stderr,
        )
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

    try:
        face_count = draw_face_boxes(
            frame,
            args.face_scale_factor,
            args.face_min_neighbors,
        )
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    filename = datetime.now().strftime("photo-%Y%m%d-%H%M%S.jpg")
    output_path = args.output_dir / filename

    if not cv2.imwrite(str(output_path), frame):
        print(f"Could not write photo: {output_path}", file=sys.stderr)
        return 1

    print(f"Detected {face_count} face(s).")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
