"""Shared hardware PWM control for the servo on physical pin 15."""
from __future__ import annotations

import fcntl
import importlib
import math
import os
from pathlib import Path
from servo_calibration import Calibration, PULSE_MIN_US, PULSE_MAX_US, load_calibration

SERVO_PIN = 15
FREQUENCY_HZ = 50


def angle_to_duty_cycle(angle: float) -> float:
    return load_calibration().pulse_for_angle(angle) / 20000 * 100


class ServoController:
    def __init__(self, use_saved_calibration=True):
        self.use_saved_calibration = use_saved_calibration

    def __enter__(self):
        self.pwm = None
        self.gpio = None
        lock_path = '/tmp/facestalker-servo.lock'
        try:
            self.lock = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            try:
                self.lock = os.open(lock_path, os.O_RDONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            except FileExistsError:
                self.lock = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.calibration = load_calibration() if self.use_saved_calibration else Calibration()
            self.gpio = importlib.import_module('Jetson.GPIO')
            self.gpio.setmode(self.gpio.BOARD)
            # Keep pin 15 routed to hardware PWM; do not request it as GPIO.
            self.pwm = self.gpio.PWM(SERVO_PIN, FREQUENCY_HZ)
            self.started = False
            return self
        except BaseException:
            os.close(self.lock)
            raise

    def set_angle(self, angle: float):
        pulse = self.calibration.pulse_for_angle(angle)
        self.set_pulse_us(pulse)
        print(f'Pin 15: target={angle:g} deg, pulse={pulse:.0f} us, 50 Hz', flush=True)
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
        for chip in Path('/sys/class/pwm').glob('pwmchip*'):
            if '3280000.pwm' in str(chip.resolve()):
                state = chip / 'pwm0'
                print('PWM1: ' + ', '.join(
                    f'{name}={(state / name).read_text().strip()}'
                    for name in ('period', 'duty_cycle', 'enable')), flush=True)

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            try:
                if self.pwm is not None:
                    self.pwm.stop()
            finally:
                if self.gpio is not None:
                    self.gpio.cleanup(SERVO_PIN)
        finally:
            os.close(self.lock)
        print('PWM stopped and released.', flush=True)
