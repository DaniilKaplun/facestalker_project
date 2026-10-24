"""Hardware-independent horizontal face-following controller."""
import math


class FaceTracker:
    def __init__(self, calibration, direction=-1):
        self.minimum = calibration.min_pulse_us
        self.maximum = calibration.max_pulse_us
        self.pulse = 1500.0
        self.direction = direction

    def update(self, faces, width, dt):
        target = max((f for f in faces if f[2] > 0 and f[3] > 0),
                     key=lambda f: f[2] * f[3], default=None)
        if target is None:
            return None
        error = (target[0] + target[2] / 2 - width / 2) / (width / 2)
        if not math.isfinite(error):
            return None
        # 4% of frame width either side of centre prevents hunting.
        if abs(error) > 0.08:
            velocity = self.direction * max(-300.0, min(300.0, error * 600.0))
            self.pulse = max(self.minimum, min(self.maximum,
                             self.pulse + velocity * max(0, min(dt, 0.05))))
        return target
