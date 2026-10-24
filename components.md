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
device or desired resolution differs. Each saved photo has green boxes drawn
around faces detected by OpenCV's frontal-face classifier. If needed, tune
the detector with `--face-scale-factor` (default `1.1`) and
`--face-min-neighbors` (default `5`).

The included installer installs the `opencv-data` package that contains the
face-detector model. Always install or update FaceStalker dependencies by
running `./install_dependencies.sh`; do not run `apt-get install` directly.
When a new feature needs another package, add it to the installer first.

## Live camera preview

## FaceStalker servo following

Launch "FaceStalker — слежение за лицом" on the Jetson Desktop, or run
`bash run_facestalker.sh`. Close other camera applications first.
DeepStream draws pink face boxes; the largest by area is highlighted green.
The servo follows its horizontal centre toward the cyan vertical centre line.
It uses the saved calibration, a 4% frame-width dead zone and a maximum
300 us/second pulse change. Without a face it holds its position; stale
frames suspend movement, and a two-second camera stall exits and disables PWM.
Q/Esc or closing the window releases the camera and disables PWM.
R reverses the servo direction for the current run; to choose it at launch,
use `bash run_facestalker.sh --servo-direction 1` (default: -1).
The servo initially commands 1500 us after the first frame; its physical
starting position cannot be sensed. Logs: `facestalker.log`.
No new dependencies are required. `--check-frames 120` runs a finite headless
check including servo movement.

## Camera preview without servo following

The Desktop shortcut "Камера — прямой эфир" now starts
`bash run_camera_deepstream.sh`: YuNet runs through DeepStream nvinfer/TensorRT,
and all detected faces receive pink (#FF69B4) boxes. Q, Esc, or closing the
window stops the preview. Logs are saved to `camera-deepstream.log`.
The wrapper uses the same installed model, parser and Python environment as
DeepStream photo capture. No additional dependencies are needed.
Deploy `view_camera_deepstream.py` and `run_camera_deepstream.sh` alongside
`take_photo_deepstream.py`, and update `view-camera.desktop` on the Desktop.
Use `bash run_camera_deepstream.sh --check-frames 120` for a headless inference
check with measured processing FPS and the maximum detected face count.

### Legacy OpenCV preview

The optional `view_camera.py` script shows
the UGREEN camera in a window on the Jetson desktop. The default is MJPEG,
1280x720 at a requested 30 FPS; the camera may negotiate different settings.
Press Q or Esc, or close the preview window, to release the camera and exit.
Every frame is processed by OpenCV's frontal-face classifier, with green boxes
drawn around detected faces, as in the OpenCV photo capture. The classifier is
loaded once and reused. The preview does not record video.
It uses the OpenCV dependency from the single project installer.

```bash
python3 view_camera.py
```

Override capture settings with `--device`, `--width`, `--height`, or `--fps`.
Tune face detection with `--face-scale-factor` (default `1.1`) and
`--face-min-neighbors` (default `5`), as for photo capture.
Use `python3 view_camera.py --check-frames 10` for a finite camera check
over SSH without a graphical display. An ordinary SSH session does not show
the preview window on Windows; launch the desktop shortcut in Ubuntu to view it.
Close the preview before running a photo capture because they share the camera.

## DeepStream photo capture

The Desktop shortcut "Сделать фото — DeepStream" runs
`run_photo_deepstream.sh`. It uses `face_detector_pgie_config.txt` in the
project directory automatically. No configuration path is requested.
The terminal stays open after capture; output is saved to
`photo-deepstream.log` in the project directory. Deploy the wrapper into
`/home/daniil/facestalker_project` and `take-photo-deepstream.desktop` onto
the Jetson Desktop.

The default model is OpenCV Zoo YuNet (2023mar ONNX, face class ID 0),
executed by NVIDIA DeepStream `nvinfer` / TensorRT on the GPU. The included
`nvdsinfer_yunet.cpp` parser decodes the model's outputs; nvinfer applies NMS.
The installer downloads the pinned model with SHA-256 verification and its
license, installs DeepStream 9.2, builds NVIDIA's pinned Python bindings against
the installed SDK, and builds the parser. This installation profile targets
the current Jetson: Ubuntu 24.04, L4T 39.2 and Python 3.12.

Install all dependencies using the single Desktop shortcut
"Установить зависимости FaceStalker" (requires the Ubuntu sudo password).
It runs `install_dependencies.sh` without options, installs dependencies for
the camera, servo and DeepStream, and logs output to `install-dependencies.log`.
The equivalent terminal command is:

```bash
bash install_dependencies.sh
```

Then use the desktop shortcut or `bash run_photo_deepstream.sh`.
The first capture can take longer while TensorRT builds its engine; the
engine is cached under `models/`, and the default timeout is 300 seconds.
Model, parser binaries, build files and the Python environment are ignored
by Git and reproduced by the single installer. There are no separate
DeepStream installation scripts or installation modes.

Installation references: [NVIDIA DeepStream installation](https://docs.nvidia.com/deepstream/text/DS_Installation),
[NVIDIA Python bindings](https://github.com/NVIDIA-AI-IOT/deepstream_python_apps/tree/8ad0349ed7a496fae35ebb21c350641727070b89/bindings),
and [OpenCV Zoo YuNet](https://github.com/opencv/opencv_zoo/tree/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/face_detection_yunet).

The script reads the detector metadata, draws pink (#FF69B4) boxes around class-0 face
detections, and saves a timestamped `photo-deepstream-*.jpg` in
`~/Desktop/photos`. Change `--face-class-id` when the selected face model uses
a different class ID.
