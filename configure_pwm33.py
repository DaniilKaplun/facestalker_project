#!/usr/bin/env python3
"""Prepare and optionally install a dual-servo boot entry for this Jetson."""
import argparse
import datetime
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


BOOT = Path('/boot/extlinux/extlinux.conf')
BASE_LABEL = 'FaceStalkerServo-20261018-104619'
BASE = Path('/boot/dtb/facestalker-servo-20261018-104619.dtb')
LABEL = 'FaceStalkerServoPins15And33'
DUAL = Path('/boot/dtb/facestalker-servo-pins15-33.dtb')
PINMUX = '/bus@0/pinmux@2430000/exp-header-pinmux'
PWM1, PWM5 = '/bus@0/pwm@3280000', '/bus@0/pwm@32c0000'


def run(*args):
    subprocess.run(args, check=True)


def read(*args):
    return subprocess.check_output(args, text=True).strip()


def prepare(out):
    original = BOOT.read_text()
    entries = re.split(r'(?m)(?=^LABEL\s+)', original)
    bases = [entry for entry in entries if entry.splitlines()[0].split() == ['LABEL', BASE_LABEL]]
    if len(bases) != 1 or not re.search(rf'(?m)^\s+FDT\s+{re.escape(str(BASE))}$', bases[0]):
        raise ValueError('Expected working pin-15 boot entry not found.')
    if read('fdtget', '-t', 's', BASE, PINMUX + '/hdr40-pin15', 'nvidia,pins') != 'soc_gpio39_pn1':
        raise ValueError('Unexpected pin-15 mapping in base DTB.')
    clock = read('fdtget', '-t', 'x', BASE, PWM1, 'assigned-clock-parents').split()
    source_rate = read('fdtget', '-t', 'u', BASE, PWM1, 'assigned-clock-rates')
    pwm5_clock = read('fdtget', '-t', 'x', BASE, PWM5, 'clocks').split()
    if (len(clock) != 2 or clock[1] != 'e' or source_rate != '19200000'
            or pwm5_clock != [clock[0], '6d']
            or read('fdtget', '-t', 's', BASE, PWM5, 'status') != 'okay'):
        raise ValueError('Unexpected clock configuration for PWM1 or PWM5.')

    dtb = out / DUAL.name
    shutil.copyfile(BASE, dtb)
    pin33 = PINMUX + '/hdr40-pin33'
    run('fdtput', '-c', dtb, pin33)
    for prop, value in [('nvidia,pins', 'soc_gpio21_ph0'), ('nvidia,function', 'gp')]:
        run('fdtput', '-t', 's', dtb, pin33, prop, value)
    for prop, value in [('nvidia,gpio-mode', '1'), ('nvidia,tristate', '0'), ('nvidia,enable-input', '0')]:
        run('fdtput', '-t', 'u', dtb, pin33, prop, value)
    run('fdtput', '-t', 'x', dtb, PWM5, 'assigned-clocks', *pwm5_clock)
    run('fdtput', '-t', 'x', dtb, PWM5, 'assigned-clock-parents', *clock)
    run('fdtput', '-t', 'u', dtb, PWM5, 'assigned-clock-rates', source_rate)

    # Remove only the planned additions from a copy and compare the entire
    # canonical tree. This also verifies every pin-15 property is untouched.
    check = out / 'without-pwm33.dtb'
    shutil.copyfile(dtb, check)
    run('fdtput', '-r', check, pin33)
    for prop in ('assigned-clocks', 'assigned-clock-parents', 'assigned-clock-rates'):
        run('fdtput', '-d', check, PWM5, prop)
    if read('dtc', '-q', '-s', '-I', 'dtb', '-O', 'dts', BASE) != read('dtc', '-q', '-s', '-I', 'dtb', '-O', 'dts', check):
        raise ValueError('Unexpected differences from the working DTB.')

    entry = re.sub(r'(?m)^\s+MENU LABEL[^\n]*', '\n      MENU LABEL FaceStalker PWM 50 Hz (pins 15 + 33)', bases[0])
    entry = entry.replace(f'LABEL {BASE_LABEL}', f'LABEL {LABEL}', 1).replace(str(BASE), str(DUAL))
    defaults = re.findall(r'(?m)^DEFAULT\s+(\S+)', original)
    if defaults not in ([BASE_LABEL], [LABEL]):
        raise ValueError('Unexpected default boot entry; refusing to replace it.')
    if DUAL.exists() and DUAL.read_bytes() != dtb.read_bytes():
        raise ValueError('An existing dual-servo DTB differs; inspect it manually.')
    if any(item.startswith(f'LABEL {LABEL}\n') for item in entries):
        if not DUAL.is_file():
            raise ValueError('Dual-servo boot entry exists but its DTB is missing.')
        updated = original
    else:
        updated = original.rstrip() + '\n\n' + entry.rstrip() + '\n'
    updated = re.sub(rf'(?m)^DEFAULT\s+{re.escape(BASE_LABEL)}$', f'DEFAULT {LABEL}', updated)
    config = out / BOOT.name
    config.write_text(updated)
    print('Verified DTB: only the pin-33 pinmux and PWM5 clock were added.', flush=True)
    print(f'New boot entry: {LABEL}; previous entry stays available: {BASE_LABEL}.', flush=True)
    return dtb, config, original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='facestalker-pwm33-') as directory:
        dtb, config, original = prepare(Path(directory))
        if not args.install:
            print('Preparation check only. Nothing written to /boot.')
            return
        if config.read_text() == original:
            print('Already installed.')
            return
        run('sudo', '-v')
        if BOOT.read_text() != original:
            raise ValueError('Boot configuration changed during preparation. Run again.')
        suffix = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        backup = BOOT.with_name(f'{BOOT.name}.before-pwm33-{suffix}')
        staged = BOOT.with_name(f'.{BOOT.name}.pwm33-{suffix}')
        run('sudo', 'cp', '-p', '--', BOOT, backup)
        run('sudo', 'install', '-m', '644', '--', dtb, DUAL)
        if DUAL.read_bytes() != dtb.read_bytes():
            raise ValueError('Installed DTB differs from the verified file.')
        run('sudo', 'install', '-m', '644', '--', config, staged)
        run('sudo', 'mv', '-T', '--', staged, BOOT)
        print(f'Installed. Reboot manually to activate. Backup: {backup}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'PWM setup failed: {error}')
