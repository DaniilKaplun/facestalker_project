"""Hardware PWM control for a servo on physical pin 15 or 33."""
from __future__ import annotations

import fcntl
import importlib
import math
import os
from pathlib import Path
from servo_calibration import (Calibration, PULSE_MIN_US, PULSE_MAX_US,
                               SERVO_CALIBRATION_PATHS, load_calibration)

SERVO_PIN = 15
FREQUENCY_HZ = 50
PWM_CONTROLLERS = {15: ('PWM1', '3280000.pwm'), 33: ('PWM5', '32c0000.pwm')}


def angle_to_duty_cycle(angle: float) -> float:
    return load_calibration().pulse_for_angle(angle) / 20000 * 100


class ServoController:
    def __init__(self, use_saved_calibration=True, *, pin=SERVO_PIN):
        if pin not in PWM_CONTROLLERS:
            raise ValueError('Servo pin must be 15 or 33.')
        self.use_saved_calibration = use_saved_calibration
        self.pin = pin

    def __enter__(self):
        self.pwm = None
        self.gpio = None
        # Keep the legacy lock for pin 15; each PWM channel has one owner.
        lock_path = ('/tmp/facestalker-servo.lock' if self.pin == 15
                     else '/tmp/facestalker-servo-pin33.lock')
        try:
            self.lock = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            try:
                self.lock = os.open(lock_path, os.O_RDONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            except FileExistsError:
                self.lock = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.calibration = (load_calibration(SERVO_CALIBRATION_PATHS[self.pin])
                                if self.use_saved_calibration else Calibration())
            if self.pin == 33:
                pinmux = Path('/proc/device-tree/bus@0/pinmux@2430000/exp-header-pinmux/hdr40-pin33')
                if not pinmux.is_dir():
                    raise RuntimeError('Сначала включи PWM на пине 33 ярлыком FaceStalker и перезагрузи Jetson.')
            self.gpio = importlib.import_module('Jetson.GPIO')
            self.gpio.setmode(self.gpio.BOARD)
            # Keep the pin routed to hardware PWM; do not request it as GPIO.
            self.pwm = self.gpio.PWM(self.pin, FREQUENCY_HZ)
            self.started = False
            return self
        except BaseException:
            os.close(self.lock)
            raise

    def set_angle(self, angle: float):
        pulse = self.calibration.pulse_for_angle(angle)
        self.set_pulse_us(pulse)
        print(f'Pin {self.pin}: target={angle:g} deg, pulse={pulse:.0f} us, 50 Hz', flush=True)
        self.print_state()

    def set_pulse_us(self, pulse: float):
        if not math.isfinite(pulse) or not PULSE_MIN_US <= pulse <= PULSE_MAX_US:
            raise ValueError('Pulse must be between 500 and 2500 us.')
        duty = pulse / 20000 * 100
        if self.started:
            self.pwm.ChangeDutyCycle(duty)
        else:
            self.pwm.start(duty)
            self.started = True

    def print_state(self):
        label, address = PWM_CONTROLLERS[self.pin]
        for chip in Path('/sys/class/pwm').glob('pwmchip*'):
            if address in chip.resolve().parts:
                state = chip / 'pwm0'
                print(f'{label}: ' + ', '.join(
                    f'{name}={(state / name).read_text().strip()}'
                    for name in ('period', 'duty_cycle', 'enable')), flush=True)

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            try:
                if self.pwm is not None:
                    self.pwm.stop()
            finally:
                if self.gpio is not None:
                    self.gpio.cleanup(self.pin)
        finally:
            os.close(self.lock)
        print('PWM stopped and released.', flush=True)
