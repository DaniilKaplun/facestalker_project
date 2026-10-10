# facestalker_project
jetson orin nano, keybord mouse, cabels
micro servo mg90s
camera
wireing
camera ugreen cm831

## Taking a photo on the Jetson

The UGREEN Camera 4K is available as `/dev/video0`. Install OpenCV once:

```bash
sudo apt-get install python3-opencv
```

Then take a photo:

```bash
python3 take_photo.py
```

Photos are saved as timestamped JPEG files in `~/Desktop/photos`. Use
`--device /dev/video1`, `--width`, or `--height` if the camera's active V4L2
device or desired resolution differs.
