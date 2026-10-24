#!/usr/bin/env python3
"""Sweep nominal 0..180..0 degrees, 10 degrees per second, until Ctrl+C."""
import argparse
import math
import signal
import time
from servo_control import ServoController
from servo_calibration import load_calibration


def sweep_positions(travel=180):
    forward = list(range(0, math.ceil(travel), 10))
    if not forward or forward[-1] != travel:
        forward.append(travel)
    return forward + forward[-2::-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=0,
                        help='Round trips; 0 repeats until Ctrl+C (default).')
    parser.add_argument('--interval', type=float, default=1,
                        help='Seconds between target changes (default: 1).')
    args = parser.parse_args()
    if args.cycles < 0 or not math.isfinite(args.interval) or args.interval < 0.1:
        parser.error('Cycles must be nonnegative; interval must be finite and at least 0.1 seconds.')
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)
    calibration = load_calibration()
    print(f'Sweep 0 -> {calibration.travel_degrees:g} -> 0, step 10 degrees. Ctrl+C stops PWM.', flush=True)
    print(f'Pulse range: {calibration.min_pulse_us:g}–{calibration.max_pulse_us:g} us; '
          f'angle scale: {"measured" if calibration.angle_measured else "nominal, not measured"}.', flush=True)
    try:
        with ServoController() as servo:
            cycle = 0
            while args.cycles == 0 or cycle < args.cycles:
                for angle in sweep_positions(calibration.travel_degrees)[0 if cycle == 0 else 1:]:
                    servo.set_angle(angle)
                    time.sleep(args.interval)
                cycle += 1
    except KeyboardInterrupt:
        print('Stopped by user.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
