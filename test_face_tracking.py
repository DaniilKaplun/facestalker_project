"""Controller checks without GPIO, camera or DeepStream."""
from collections import deque
import math
import unittest

from face_tracking import FaceTracker
from servo_calibration import Calibration


def faces(error):
    return [((1 + error) * 640 - 50, 100, 100, 100)]


class PIDTests(unittest.TestCase):
    def setUp(self):
        self.calibration = Calibration(500, 2500, 50)
        self.tracker = FaceTracker(self.calibration)

    def test_speed_limit_and_delayed_tick(self):
        t = self.tracker
        before = t.pulse
        t.update(faces(1), 1280, 1, sample_time=1)
        self.assertAlmostEqual((before - t.pulse) / t.us_per_degree, 1.5)
        self.assertEqual(t.integral, 0)  # Saturated output cannot wind up.

    def test_duplicate_frame_does_not_update_pid(self):
        t = self.tracker
        t.update(faces(.4), 1280, .01, sample_time=1)
        t.update(faces(.3), 1280, .01, sample_time=1.04)
        history = (t.integral, t.derivative, t.velocity_deg_s)
        for _ in range(3):
            t.update(faces(.3), 1280, .01, sample_time=1.04)
        self.assertEqual(history, (t.integral, t.derivative, t.velocity_deg_s))
        self.assertLess(t.derivative, 0)

    def test_integral_and_derivative_are_active(self):
        t = self.tracker
        t.update(faces(.3), 1280, .01, sample_time=1)
        t.update(faces(.3), 1280, .01, sample_time=1.04)
        self.assertGreater(t.integral, 0)
        t.update(faces(.2), 1280, .01, sample_time=1.08)
        self.assertLess(t.derivative, 0)
        self.assertLess(t.velocity_deg_s, t.kp * (.2 - .08) + t.ki * t.integral)
        self.assertGreaterEqual(t.velocity_deg_s, 0)

    def test_hold_hysteresis_loss_and_reacquisition(self):
        t = self.tracker
        t.update(faces(.3), 1280, .01)
        t.update(faces(.03), 1280, .01)
        position = t.pulse
        for error in (.1, -.1, .11, -.09):
            t.update(faces(error), 1280, .01)
        self.assertEqual(t.pulse, position)
        t.update(faces(.2), 1280, .01)
        self.assertLess(t.pulse, position)
        t.update([], 1280, .01)
        self.assertEqual((t.integral, t.derivative, t.velocity_deg_s), (0, 0, 0))
        t.update(faces(-.4), 1280, .01)
        self.assertEqual(t.derivative, 0)

    def test_limits_and_reverse(self):
        t = self.tracker
        for tick in range(1000):
            t.update(faces(.8), 1280, .01)
        self.assertEqual(t.pulse, t.minimum)
        integral_at_limit = t.integral
        for _ in range(100):
            t.update(faces(.8), 1280, .01)
        self.assertEqual(t.integral, integral_at_limit)
        t.direction = 1
        t.reset()
        t.update(faces(.8), 1280, .01)
        self.assertGreater(t.pulse, t.minimum)

    def test_invalid_gains(self):
        for value in (-1, math.nan, math.inf):
            with self.assertRaises(ValueError):
                FaceTracker(self.calibration, kp=value)

    def test_delayed_camera_simulation(self):
        # Approximate plant only; this does not substitute for tuning real hardware.
        for delay in (0, 10, 20):
            t = FaceTracker(self.calibration)
            history = deque([.6] * (delay + 1), maxlen=delay + 1)
            observed, frame_time = .6, 1.0
            errors = []
            for tick in range(1000):
                actual = .6 + (t.pulse - 1500) / t.us_per_degree / 35
                history.append(actual)
                if tick % 3 == 0:
                    observed, frame_time = history[0], 1 + tick * .01
                t.update(faces(observed), 1280, .01, sample_time=frame_time)
                errors.append(actual)
            self.assertLess(max(abs(e) for e in errors[-100:]), .12, delay)


if __name__ == '__main__':
    unittest.main()
