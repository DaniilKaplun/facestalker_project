#!/usr/bin/env python3
"""Show live UGREEN video with green OpenCV face boxes on the Jetson."""

from __future__ import annotations

import argparse
import os
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Live camera preview. Press Q, Esc, or close the window to stop."
    )
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--face-scale-factor", type=float, default=1.1)
    parser.add_argument("--face-min-neighbors", type=int, default=5)
    parser.add_argument(
        "--check-frames",
        type=int,
        default=0,
        help="Read this many frames without a window, then exit (SSH diagnostic)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if min(args.width, args.height, args.fps) < 1 or args.check_frames < 0:
        print("Width, height and FPS must be positive; check-frames cannot be negative.", file=sys.stderr)
        return 2
    if not args.face_scale_factor > 1.0 or args.face_min_neighbors < 0:
        print("Face scale factor must exceed 1; minimum neighbours cannot be negative.", file=sys.stderr)
        return 2

    try:
        import cv2
    except ImportError:
        print("Запустите ярлык «Установить зависимости FaceStalker».", file=sys.stderr)
        return 1

    if not args.check_frames and sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        print(
            "Нет графического сеанса. Запустите ярлык камеры на рабочем столе Ubuntu. "
            "Для проверки по SSH используйте --check-frames 10.",
            file=sys.stderr,
        )
        return 1

    from take_photo import draw_face_boxes, load_face_detector

    try:
        detector = load_face_detector()
    except (RuntimeError, cv2.error) as error:
        print(f"Ошибка детектора лиц: {error}", file=sys.stderr)
        return 1

    window_name = "FaceStalker - Live faces (Q / Esc to exit)"
    camera = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
    window_created = False
    frames = 0
    try:
        if not camera.isOpened():
            print(f"Не удалось открыть камеру {args.device}. Закройте другие приложения камеры.", file=sys.stderr)
            return 1

        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        camera.set(cv2.CAP_PROP_FPS, args.fps)
        # Ask V4L2 for a short capture queue to reduce preview latency.
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not args.check_frames:
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
            window_created = True
            cv2.resizeWindow(window_name, args.width, args.height)

        while True:
            success, frame = camera.read()
            if not success or frame is None:
                print("Камера перестала передавать кадры.", file=sys.stderr)
                return 1
            frames += 1
            if frames == 1:
                height, width = frame.shape[:2]
                print(
                    f"Camera: {args.device}; {width}x{height}; "
                    f"configured FPS: {camera.get(cv2.CAP_PROP_FPS):g}",
                    flush=True,
                )

            face_count = draw_face_boxes(
                frame, args.face_scale_factor, args.face_min_neighbors, detector
            )

            if args.check_frames:
                if frames >= args.check_frames:
                    print(f"OK: processed {frames} frames; faces in last frame: {face_count}.")
                    return 0
                continue

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q"), ord("Q")):
                return 0
            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                return 0
    except KeyboardInterrupt:
        return 0
    except cv2.error as error:
        print(f"Ошибка просмотра камеры: {error}", file=sys.stderr)
        return 1
    finally:
        camera.release()
        if window_created:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())
