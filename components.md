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
nominal 0 -> 180 -> 0 degrees, 10 degrees per second, repeating until Ctrl+C
or the terminal closes. A single round trip is:

```bash
python3 sweep_servo.py --cycles 1
```

The sweep uses `servo_control.py`, physical pin 15, 50 Hz, and a nominal
1–2 ms pulse mapping. Actual
shaft angle and mechanical endpoints require calibration; these scripts
cannot sense the servo's position. A process lock prevents concurrent
servo commands. The sweep log is `servo-sweep.log` (ignored by Git).

Deploy `sweep_servo.py`, `servo_control.py`, and `run_servo_sweep.sh` into
`/home/daniil/facestalker_project`. Copy `sweep-servo.desktop` to the Jetson's
Desktop and mark the launcher executable. No sudo is needed to run the sweep
when the user belongs to the `gpio` group.

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
