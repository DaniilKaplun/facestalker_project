"""Hardware-independent horizontal face-following controller."""
import math

# User-selected settings, confirmed with the angle-sequence test.
TRACKING_SPEED_DEG_S = 150.0
CONTROL_INTERVAL_MS = 10
STOP_ERROR = 0.08       # 4% of frame width either side of centre.
RESUME_ERROR = 0.12     # Restart only outside 6%, to ignore box jitter.
PID_KP = 180.0          # deg/s per normalized image error.
PID_KI = 20.0           # deg/s per integrated error-second.
PID_KD = 15.0           # deg/s per error/second.
DERIVATIVE_FILTER_S = 0.10
MAX_INTEGRAL_SPEED = 20.0


class FaceTracker:
    def __init__(self, calibration, direction=-1, kp=PID_KP, ki=PID_KI, kd=PID_KD):
        if any(not math.isfinite(v) or v < 0 for v in (kp, ki, kd)):
            raise ValueError('PID gains must be finite and nonnegative.')
        if direction not in (-1, 1):
            raise ValueError('Servo direction must be -1 or 1.')
        self.kp, self.ki, self.kd = kp, ki, kd
        self.minimum = calibration.min_pulse_us
        self.maximum = calibration.max_pulse_us
        self.pulse = 1500.0
        self.direction = direction
        self.us_per_degree = (self.maximum - self.minimum) / calibration.travel_degrees
        self.clock = 0.0
        self.reset()

    def reset(self):
        """Discard PID history while holding the current commanded position."""
        self.moving = False
        self.integral = 0.0
        self.derivative = 0.0
        self.last_error = None
        self.last_sample_time = None
        self.velocity_deg_s = 0.0

    def update(self, faces, width, dt, sample_time=None):
        if not math.isfinite(dt) or dt < 0 or not math.isfinite(width) or width <= 0:
            self.reset()
            return None
        self.clock += dt
        sample_time = self.clock if sample_time is None else sample_time
        if not math.isfinite(sample_time):
            self.reset()
            return None
        target = max((f for f in faces if f[2] > 0 and f[3] > 0),
                     key=lambda f: f[2] * f[3], default=None)
        if target is None:
            self.reset()
            return None
        error = (target[0] + target[2] / 2 - width / 2) / (width / 2)
        if not math.isfinite(error):
            self.reset()
            return None
        # Repeated 10 ms ticks reuse the last PID output; I and D advance only
        # when inference supplies a new frame timestamp.
        if self.last_sample_time is None or sample_time != self.last_sample_time:
            sample_dt = sample_time - self.last_sample_time if self.last_sample_time is not None else 0
            if (sample_dt <= 0 or sample_dt > 0.2
                    or (self.last_error is not None and abs(error - self.last_error) > 0.5)):
                # Reacquisition, delayed frames or a large target jump: no D kick.
                self.reset()
                sample_dt = 0
            magnitude = abs(error)
            if magnitude <= STOP_ERROR:
                self.reset()
            elif magnitude >= RESUME_ERROR:
                self.moving = True
            if self.moving:
                if sample_dt > 0 and self.last_error is not None:
                    slope = (error - self.last_error) / sample_dt
                    alpha = sample_dt / (DERIVATIVE_FILTER_S + sample_dt)
                    self.derivative += alpha * (slope - self.derivative)
                effective_error = math.copysign(max(0, magnitude - STOP_ERROR), error)
                candidate = self.integral
                if self.ki > 0:
                    bound = MAX_INTEGRAL_SPEED / self.ki
                    candidate = max(-bound, min(bound, candidate + effective_error * sample_dt))
                p_d = self.kp * effective_error + self.kd * self.derivative
                proposed = p_d + self.ki * candidate
                pulse_direction = self.direction * proposed
                at_limit = ((self.pulse <= self.minimum and pulse_direction < 0)
                            or (self.pulse >= self.maximum and pulse_direction > 0))
                # Conditional integration prevents windup at speed/position limits.
                unwinding = effective_error * proposed < 0
                if not at_limit and (abs(proposed) <= TRACKING_SPEED_DEG_S or unwinding):
                    self.integral = candidate
                raw = p_d + self.ki * self.integral
                # D brakes motion but must not drive away from the target.
                self.velocity_deg_s = (max(-TRACKING_SPEED_DEG_S, min(TRACKING_SPEED_DEG_S, raw))
                                       if raw * error > 0 else 0.0)
            self.last_error = error
            self.last_sample_time = sample_time
        velocity = self.direction * self.velocity_deg_s * self.us_per_degree
        # Never catch up with a large step after a delayed control tick.
        self.pulse = max(self.minimum, min(self.maximum,
                         self.pulse + velocity * min(dt, CONTROL_INTERVAL_MS / 1000)))
        return target
