# facestalker_project
jetson orin nano, keybord mouse, cabels
micro servo mg90s
camera
wireing
camera ugreen cm831

## Servo sweep on the Jetson

Connect the servo signal wire to physical header pin 15, connect its ground to
physical pin 6, and power the servo from its external supply. The external
supply ground and the Jetson ground must remain connected together.

The current Jetson already has the working boot configuration: physical pin
15 is routed to PWM1 (pinmux register `0x02440020` reads `0x00000404`) and
PWM1 uses CLK_M at 19.2 MHz for 50 Hz output. Preserve that configuration in
`/boot`; the runtime scripts do not configure pinmux or the source clock.

The desktop shortcut "Серва — шаг 10 градусов" starts `sweep_servo.py`:
0 -> calibrated travel -> 0 degrees, 10 degrees per second, repeating until Ctrl+C
or the terminal closes. A single round trip is:

```bash
python3 sweep_servo.py --cycles 1
```

The sweep uses `servo_control.py`, physical pin 15, 50 Hz, and saved per-device
limits. Without calibration it uses a nominal 1–2 ms pulse mapping and a
nominal 180-degree scale. These scripts cannot sense the servo's position.
A process lock prevents concurrent
servo commands. The sweep log is `servo-sweep.log` (ignored by Git).

Deploy `sweep_servo.py`, `servo_control.py`, `servo_calibration.py`, and `run_servo_sweep.sh` into
`/home/daniil/facestalker_project`. Copy `sweep-servo.desktop` to the Jetson's
Desktop and mark the launcher executable. No sudo is needed to run the sweep
when the user belongs to the `gpio` group.

## Interactive servo calibration

The desktop shortcut "Калибровка сервы" launches `calibrate_servo.py` (Tkinter).
It starts with PWM off. Stop the sweep before enabling calibration.

1. Click "Включить: 1500 мкс" to command neutral.
2. Use the slider or Left/Right (5 us); Shift+Left/Right uses 25 us.
   The slider range 500–2500 us is a generator limit, not a guaranteed safe
   mechanical range. Approach each limit slowly and retreat if the servo
   meets a stop or starts straining; never leave it pushing against a stop.
3. Record the lower and upper pulse boundaries. After each record the servo
   retreats by the selected margin (default 50 us). Saving shrinks both
   recorded limits by that margin.
4. Optionally measure the travel between the safe limits with a protractor,
   tick the measured-travel checkbox, and enter the measured angle. Otherwise
   the degree scale stays explicitly nominal, even after pulse calibration.
5. Save. PWM turns off. Restart the sweep to load the new safe range.

Esc or Space immediately disables PWM. Closing the window also disables it;
30 seconds without interaction triggers an inactivity stop. Slider jumps are
limited to 10 us per 20 ms tick. Calibration is saved atomically next to the
scripts as `servo_calibration.json`, which is intentionally ignored by Git.
Calibration changes do not modify `/boot` and do not need sudo or reboot.

## Taking a photo on the Jetson

The UGREEN Camera 4K is available as `/dev/video0`. Install the dependencies
once (the command prompts for the Ubuntu password):

```bash
./install_dependencies.sh
```

Then take a photo:

```bash
python3 take_photo.py
```

Photos are saved as timestamped JPEG files in `~/Desktop/photos`. Use
`--device /dev/video1`, `--width`, or `--height` if the camera's active V4L2
device or desired resolution differs.
