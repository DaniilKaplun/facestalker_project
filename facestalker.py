#!/usr/bin/env python3
"""DeepStream live face following on the calibrated pan servo. Q/Esc exits, R reverses."""
import os
import sys
import time

from face_tracking import FaceTracker
from servo_control import ServoController
from view_camera_deepstream import DeepStreamPreview, build_parser, GLib, Gst, cv2


class FaceStalker(DeepStreamPreview):
    def __init__(self, args, servo):
        self.servo = servo
        self.tracker = FaceTracker(servo.calibration, args.servo_direction)
        self.faces = []
        self.frame_time = None
        self.tick_time = time.monotonic()
        super().__init__(args)
        self.window = 'FaceStalker (Q / Esc: exit, R: reverse)'

    def process_faces(self, faces):
        with self.lock:
            self.faces = faces
            self.frame_time = time.monotonic()

    def annotate(self, image, faces):
        height, width = image.shape[:2]
        cv2.line(image, (width // 2, 0), (width // 2, height), (255, 255, 0), 1)
        target = max(faces, key=lambda f: f[2] * f[3], default=None)
        if target:
            x, y, w, h = target
            cv2.rectangle(image, (x, y), (x+w, y+h), (0, 255, 0), 3)
            cv2.circle(image, (x+w//2, y+h//2), 5, (0, 255, 0), -1)
        cv2.putText(image, f'Pan {self.tracker.pulse:.0f} us | direction {self.tracker.direction:+d} | R: reverse',
                    (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)

    def handle_key(self, key):
        if key in (ord('r'), ord('R')):
            self.tracker.direction *= -1
            print(f'Servo direction: {self.tracker.direction:+d}', flush=True)

    def tick(self):
        now = time.monotonic()
        dt, self.tick_time = now - self.tick_time, now
        with self.lock:
            faces, frame_time = self.faces, self.frame_time
        if frame_time is None:
            return True
        if now - frame_time > 2:
            self.error = 'Camera frames stopped; stopping FaceStalker.'
            self.loop.quit()
            return False
        if now - frame_time > 0.2:
            return True
        if not self.servo.started:
            try:
                self.servo.set_pulse_us(self.tracker.pulse)
            except Exception as error:
                self.error = f'Servo: {error}'
                self.loop.quit()
                return False
            return True
        previous = self.tracker.pulse
        self.tracker.update(faces, self.args.width, dt)
        if abs(self.tracker.pulse - previous) > 0.01:
            try:
                self.servo.set_pulse_us(self.tracker.pulse)
            except Exception as error:
                self.error = f'Servo: {error}'
                self.loop.quit()
                return False
        return True

    def run(self):
        # Enable at neutral only after the first valid camera frame.
        self.tick_time = time.monotonic()
        timer = GLib.timeout_add(20, self.tick)
        try:
            super().run()
        finally:
            if GLib.MainContext.default().find_source_by_id(timer):
                GLib.source_remove(timer)


def main():
    parser = build_parser()
    parser.description = __doc__
    parser.add_argument('--servo-direction', type=int, choices=(-1, 1), default=-1)
    args = parser.parse_args()
    if min(args.width, args.height, args.fps, args.timeout) < 1 or min(args.check_frames, args.face_class_id) < 0:
        parser.error('Invalid camera or detection settings')
    if not args.check_frames and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        parser.error('Запустите ярлык FaceStalker на рабочем столе Jetson.')
    Gst.init(None)
    try:
        with ServoController() as servo:
            FaceStalker(args, servo).run()
    except (RuntimeError, OSError, ValueError, cv2.error) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
