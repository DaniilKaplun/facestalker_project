#!/usr/bin/env python3
"""Camera-free servo diagnostic: slow ramp or individual position commands."""
import argparse
import csv
import math
from pathlib import Path
import signal
import time

from servo_calibration import load_calibration


def ramp(start, end, speed, interval):
    """Include the exact endpoint; never exceed speed * interval per step."""
    steps = max(1, math.ceil(abs(end - start) / (speed * interval)))
    for index in range(1, steps + 1):
        yield start + (end - start) * index / steps


def run(args, servo=None):
    calibration = load_calibration()
    low, high = 1500 - args.span, 1500 + args.span
    if args.mode == 'ramp' and (low < calibration.min_pulse_us or high > calibration.max_pulse_us):
        raise ValueError('Test range exceeds saved calibration; reduce --span.')
    angles = (0, 180, 90, 45, 135, 0, 180)
    position_targets = [(angle, calibration.pulse_for_angle(angle)) for angle in angles] if args.mode == 'positions' else []
    pwm_path = next((chip / 'pwm0' / 'duty_cycle'
                     for chip in Path('/sys/class/pwm').glob('pwmchip*')
                     if '3280000.pwm' in str(chip.resolve())), None)
    if args.mode == 'positions':
        print('Individual angle targets: ' + ' -> '.join(f'{a} deg' for a in angles) + '; '
              f'hold each target for {args.hold:g} seconds.', flush=True)
        print(f'Angle scale: {"measured" if calibration.angle_measured else "nominal, not measured"}; '
              f'calibrated travel: {calibration.travel_degrees:g} deg.', flush=True)
        if args.angle_speed:
            print(f'Target ramp: {args.angle_speed:g} deg/s; first positioning is direct. '
                  'Actual shaft speed is not measured.', flush=True)
    else:
        print(f'Range: {low:g}..{high:g} us; speed: {args.speed:g} us/s; '
              f'update interval: {args.interval * 1000:g} ms.', flush=True)
        print('Initial command: 1500 us (may move abruptly from the current position). '
              'Then hold before the test.', flush=True)
    print(f'CSV: {args.log.resolve()} | Ctrl+C stops and releases PWM.', flush=True)
    intervals = []
    largest_step = 0
    with args.log.open('w', newline='', encoding='utf-8') as output:
        writer = csv.writer(output)
        writer.writerow(('elapsed_s', 'interval_ms', 'command_us', 'step_us',
                         'write_ms', 'sysfs_duty_ns', 'angle_deg'))
        beginning = time.monotonic()
        previous_time = None
        previous_pulse = None

        def command(pulse, angle=''):
            nonlocal previous_time, previous_pulse, largest_step
            now = time.monotonic()
            if servo is not None:
                servo.set_pulse_us(pulse)
            finished = time.monotonic()
            actual = ''
            if servo is not None and pwm_path is not None:
                actual = pwm_path.read_text().strip()
            delta = (now - previous_time) * 1000 if previous_time is not None else 0
            step = pulse - previous_pulse if previous_pulse is not None else 0
            if previous_time is not None:
                intervals.append(delta)
                largest_step = max(largest_step, abs(step))
            writer.writerow((f'{now-beginning:.6f}', f'{delta:.3f}', f'{pulse:.6f}',
                             f'{step:.6f}', f'{(finished-now)*1000:.3f}', actual, angle))
            previous_time, previous_pulse = now, pulse

        if args.mode == 'ramp':
            command(1500)
            time.sleep(2)
        # Exclude the deliberate startup hold from timing statistics.
        previous_time = None
        current = 1500
        current_angle = None
        for cycle in range(args.cycles):
            targets = position_targets if args.mode == 'positions' else [('', p) for p in (high, low, 1500)]
            for angle, target in targets:
                if args.mode == 'positions':
                    print(f'Cycle {cycle+1}: angle {angle:g} deg -> {target:g} us', flush=True)
                    if args.angle_speed and current_angle is not None:
                        for intermediate in ramp(current_angle, angle, args.angle_speed, args.interval):
                            deadline = time.monotonic() + args.interval
                            command(calibration.pulse_for_angle(intermediate), intermediate)
                            time.sleep(max(0, deadline - time.monotonic()))
                    else:
                        command(target, angle)
                    current_angle = angle
                    # Hardware PWM continues at 50 Hz during the hold.
                    output.flush()
                    time.sleep(args.hold)
                else:
                    print(f'Cycle {cycle+1}: {current:g} -> {target:g} us', flush=True)
                    for pulse in ramp(current, target, args.speed, args.interval):
                        # Do not catch up with a burst of writes after a delay.
                        deadline = time.monotonic() + args.interval
                        command(pulse)
                        time.sleep(max(0, deadline - time.monotonic()))
                current = target
                output.flush()
    if intervals:
        import statistics
        print(f'Command intervals: median {statistics.median(intervals):.2f} ms, '
              f'max {max(intervals):.2f} ms; largest step {largest_step:.3f} us.', flush=True)
    print('CSV records software commands and sysfs values, not measured shaft position.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('ramp', 'positions'), default='ramp')
    parser.add_argument('--hold', type=float, default=2,
                        help='Seconds at each target in positions mode (default: 2).')
    parser.add_argument('--angle-speed', type=float, default=0,
                        help='Positions mode: target ramp in deg/s; 0 sends direct targets.')
    parser.add_argument('--span', type=float, default=150,
                        help='Microseconds either side of 1500 (default: 150).')
    parser.add_argument('--speed', type=float, default=100,
                        help='Pulse change in us/second (default: 100).')
    parser.add_argument('--interval', type=float, default=0.02)
    parser.add_argument('--cycles', type=int, default=1)
    parser.add_argument('--log', type=Path)
    parser.add_argument('--dry-run', action='store_true', help='Simulate without accessing GPIO.')
    args = parser.parse_args()
    if args.log is None:
        name = 'servo-positions.csv' if args.mode == 'positions' else 'servo-smooth.csv'
        args.log = Path(__file__).with_name(name)
    if (any(not math.isfinite(v) or v <= 0 for v in (args.span, args.speed, args.interval))
            or args.interval < 0.01 or args.speed > 300 or args.cycles < 1):
        parser.error('Require positive span, speed <= 300 us/s, interval >= 0.01 s, cycles >= 1.')
    if not math.isfinite(args.hold) or args.hold < 0.5:
        parser.error('Hold must be finite and at least 0.5 seconds.')
    if not math.isfinite(args.angle_speed) or args.angle_speed < 0:
        parser.error('Angle speed must be finite and nonnegative.')

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, stop)
    try:
        if args.dry_run:
            run(args)
        else:
            from servo_control import ServoController
            with ServoController() as servo:
                run(args, servo)
    except KeyboardInterrupt:
        print('Stopped by user.', flush=True)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
