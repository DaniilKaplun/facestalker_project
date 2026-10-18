#!/usr/bin/env python3
"""Sweep nominal 0..180..0 degrees, 10 degrees per second, until Ctrl+C."""
import argparse
import math
import signal
import time
from servo_control import ServoController


def sweep_positions():
    return list(range(0, 181, 10)) + list(range(170, -1, -10))


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
    print('Sweep 0 -> 180 -> 0, step 10 degrees. Ctrl+C stops PWM.', flush=True)
    print('Nominal positions use 1–2 ms pulses; shaft angles are not measured.', flush=True)
    try:
        with ServoController() as servo:
            cycle = 0
            while args.cycles == 0 or cycle < args.cycles:
                for angle in sweep_positions()[0 if cycle == 0 else 1:]:
                    servo.set_angle(angle)
                    time.sleep(args.interval)
                cycle += 1
    except KeyboardInterrupt:
        print('Stopped by user.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
