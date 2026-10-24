"""Per-device servo pulse calibration; no GPIO access."""
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path

CALIBRATION_PATH = Path(__file__).with_name('servo_calibration.json')
PULSE_MIN_US = 500
PULSE_MAX_US = 2500


@dataclass(frozen=True)
class Calibration:
    endpoint_min_us: float = 1000
    endpoint_max_us: float = 2000
    margin_us: float = 0
    travel_degrees: float = 180
    angle_measured: bool = False

    def __post_init__(self):
        numbers = (self.endpoint_min_us, self.endpoint_max_us,
                   self.margin_us, self.travel_degrees)
        if any(isinstance(x, bool) or not isinstance(x, (int, float))
               or not math.isfinite(x) for x in numbers):
            raise ValueError('Calibration values must be finite numbers.')
        if not PULSE_MIN_US <= self.endpoint_min_us < self.endpoint_max_us <= PULSE_MAX_US:
            raise ValueError('Endpoint pulses must be ordered and within 500–2500 us.')
        if not 0 <= self.margin_us <= 200:
            raise ValueError('Safety margin must be between 0 and 200 us.')
        if not self.min_pulse_us < 1500 < self.max_pulse_us:
            raise ValueError('Safe limits must bracket the 1500 us neutral pulse.')
        if not 0 < self.travel_degrees <= 270:
            raise ValueError('Travel must be greater than 0 and at most 270 degrees.')
        if not isinstance(self.angle_measured, bool):
            raise ValueError('angle_measured must be boolean.')

    @property
    def min_pulse_us(self):
        return self.endpoint_min_us + self.margin_us

    @property
    def max_pulse_us(self):
        return self.endpoint_max_us - self.margin_us

    def pulse_for_angle(self, angle):
        if not math.isfinite(angle) or not 0 <= angle <= self.travel_degrees:
            raise ValueError(f'Angle must be between 0 and {self.travel_degrees:g}.')
        return self.min_pulse_us + angle / self.travel_degrees * (self.max_pulse_us - self.min_pulse_us)


def load_calibration(path=CALIBRATION_PATH):
    try:
        data = Path(path).read_text(encoding='utf-8')
    except FileNotFoundError:
        return Calibration()
    return Calibration(**json.loads(data))


def save_calibration(calibration, path=CALIBRATION_PATH):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(asdict(calibration), stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
