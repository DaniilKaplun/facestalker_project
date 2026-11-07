#!/usr/bin/env python3
"""DeepStream face following on pan (pin 15) and tilt (pin 33). Q/Esc exits."""
from contextlib import ExitStack
import os
from queue import Empty, SimpleQueue
import sys
from threading import Event, Thread
import time

from face_tracking import (FaceTracker, select_face, TRACKING_SPEED_DEG_S, CONTROL_INTERVAL_MS,
                           PID_KP, PID_KI, PID_KD)
from servo_control import ServoController
from view_camera_deepstream import DeepStreamPreview, build_parser, GLib, Gst, cv2


class FaceStalker(DeepStreamPreview):
    def __init__(self, args, pan, tilt):
        self.servos = (pan, tilt)
        self.trackers = tuple(FaceTracker(servo.calibration, direction,
                                          args.pid_kp, args.pid_ki, args.pid_kd)
                              for servo, direction in zip(self.servos,
                                                          (args.servo_direction, args.tilt_direction)))
        self.target = None
        self.pid_enabled = True
        self.control_keys = SimpleQueue()
        self.frame_time = None
        self.tick_time = time.monotonic()
        super().__init__(args)
        self.window = 'FaceStalker (F: fullscreen, P / Space: tracking mode, R: pan, T: tilt, Q / Esc: exit)'

    def process_faces(self, faces):
        with self.lock:
            self.target = select_face(faces)
            self.frame_time = time.monotonic()

    def annotate(self, image, faces):
        height, width = image.shape[:2]
        cv2.line(image, (width // 2, 0), (width // 2, height), (255, 255, 0), 1)
        cv2.line(image, (0, height // 2), (width, height // 2), (255, 255, 0), 1)
        target = select_face(faces)
        if target:
            x, y, w, h = target
            cv2.rectangle(image, (x, y), (x+w, y+h), (0, 255, 0), 3)
            cv2.circle(image, (x+w//2, y+h//2), 5, (0, 255, 0), -1)
        pan, tilt = self.trackers
        cv2.putText(image, f'Pan {pan.pulse:.0f} us ({pan.direction:+d}) [R] | Tilt {tilt.pulse:.0f} us ({tilt.direction:+d}) [T]',
                    (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        status = 'PID ON' if self.pid_enabled else 'PID OFF - simple tracking'
        color = (0, 255, 0) if self.pid_enabled else (0, 180, 255)
        cv2.putText(image, f'{status} [P / Space]', (15, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)

    def handle_key(self, key):
        if key in (ord('f'), ord('F')):
            fullscreen = cv2.getWindowProperty(self.window, cv2.WND_PROP_FULLSCREEN)
            mode = cv2.WINDOW_NORMAL if fullscreen == cv2.WINDOW_FULLSCREEN else cv2.WINDOW_FULLSCREEN
            cv2.setWindowProperty(self.window, cv2.WND_PROP_FULLSCREEN, mode)
            return
        if key in (ord('p'), ord('P'), ord(' '), ord('r'), ord('R'), ord('t'), ord('T')):
            self.control_keys.put(key)

    def apply_control_key(self, key):
        if key in (ord('p'), ord('P'), ord(' ')):
            self.pid_enabled = not self.pid_enabled
            for tracker in self.trackers:
                tracker.reset()
            print('PID tracking' if self.pid_enabled else 'Simple tracking (PID off)', flush=True)
            return
        if key in (ord('r'), ord('R')):
            axis = 0
        elif key in (ord('t'), ord('T')):
            axis = 1
        else:
            return
        tracker = self.trackers[axis]
        tracker.direction *= -1
        tracker.reset()
        print(f'Pin {self.servos[axis].pin} direction: {tracker.direction:+d}', flush=True)

    def tick(self):
        now = time.monotonic()
        dt, self.tick_time = now - self.tick_time, now
        with self.lock:
            target, frame_time = self.target, self.frame_time
        if frame_time is None:
            return
        if now - frame_time > 2:
            raise RuntimeError('Camera frames stopped; stopping FaceStalker.')
        if now - frame_time > 0.2:
            for tracker in self.trackers:
                tracker.reset()
            return
        for axis, (servo, tracker, extent) in enumerate(zip(
                self.servos, self.trackers, (self.args.width, self.args.height))):
            try:
                if not servo.started:
                    servo.set_pulse_us(tracker.pulse)
                    continue
                previous = tracker.pulse
                tracker.update_target(target, extent, dt, frame_time, axis=axis,
                                      use_pid=self.pid_enabled)
                if abs(tracker.pulse - previous) > 0.01:
                    servo.set_pulse_us(tracker.pulse)
            except Exception as error:
                raise RuntimeError(f'Servo on pin {servo.pin}: {error}') from error
    def control_loop(self, stop):
        interval = CONTROL_INTERVAL_MS / 1000
        self.tick_time = time.monotonic()
        try:
            while not stop.is_set() and not self.finished:
                deadline = time.monotonic() + interval
                while not stop.is_set():
                    try:
                        key = self.control_keys.get_nowait()
                    except Empty:
                        break
                    self.apply_control_key(key)
                if stop.is_set():
                    break
                self.tick()
                stop.wait(max(0, deadline - time.monotonic()))
        except Exception as error:
            self.error = str(error)
            GLib.idle_add(self.loop.quit)

    def run(self):
        print(f'Tracking: max {TRACKING_SPEED_DEG_S:g} nominal deg/s with braking near centre, '
              f'{CONTROL_INTERVAL_MS} ms target updates, 50 Hz hardware PWM.', flush=True)
        for servo, tracker in zip(self.servos, self.trackers):
            print(f'Pin {servo.pin}: {tracker.minimum:g}–{tracker.maximum:g} us, '
                  f'direction {tracker.direction:+d}; '
                  f'PID Kp={tracker.kp:g}, Ki={tracker.ki:g}, Kd={tracker.kd:g}', flush=True)
        stop = Event()
        worker = Thread(target=self.control_loop, args=(stop,), name='servo-control')
        worker.start()
        try:
            super().run()
        finally:
            stop.set()
            worker.join()


def main(app_class=FaceStalker):
    parser = build_parser()
    parser.description = __doc__
    parser.set_defaults(width=640, height=360)
    parser.add_argument('--servo-direction', type=int, choices=(-1, 1), default=-1,
                        help='Pan direction on pin 15 (default: -1).')
    parser.add_argument('--tilt-direction', type=int, choices=(-1, 1), default=-1,
                        help='Tilt direction on pin 33 (default: -1).')
    parser.add_argument('--pid-kp', type=float, default=PID_KP)
    parser.add_argument('--pid-ki', type=float, default=PID_KI)
    parser.add_argument('--pid-kd', type=float, default=PID_KD)
    args = parser.parse_args()
    if min(args.width, args.height, args.fps, args.timeout) < 1 or min(args.check_frames, args.face_class_id) < 0:
        parser.error('Invalid camera or detection settings')
    if not args.check_frames and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        parser.error('Запустите ярлык FaceStalker на рабочем столе Jetson.')
    Gst.init(None)
    try:
        with ExitStack() as stack:
            pan = stack.enter_context(ServoController(pin=15))
            tilt = stack.enter_context(ServoController(pin=33))
            app_class(args, pan, tilt).run()
    except (RuntimeError, OSError, ValueError, cv2.error) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
