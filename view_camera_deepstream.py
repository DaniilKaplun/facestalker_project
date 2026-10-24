#!/usr/bin/env python3
"""Live DeepStream face detections with pink boxes; Q/Esc closes preview."""
import argparse
import os
from pathlib import Path
import sys
import threading
import time

from take_photo_deepstream import DeepStreamPhotoCapture, GLib, Gst, cv2, np, pyds


class DeepStreamPreview(DeepStreamPhotoCapture):
    def __init__(self, args):
        self.lock = threading.Lock()
        self.latest = None
        self.max_faces = 0
        self.started = None
        self.window = "FaceStalker - DeepStream (Q / Esc)"
        super().__init__(args)
        self.streammux.set_property("batched-push-timeout", 33333)

    def _on_frame(self, _pad, info, _user_data):
        try:
            buffer = info.get_buffer()
            if buffer is None:
                return Gst.PadProbeReturn.OK
            batch = pyds.gst_buffer_get_nvds_batch_meta(hash(buffer))
            node = batch.frame_meta_list if batch else None
            while node is not None:
                meta = pyds.NvDsFrameMeta.cast(node.data)
                faces = self._objects_for_frame(meta)
                if self.started is None:
                    self.started = time.monotonic()
                self.frames_seen += 1
                self.max_faces = max(self.max_faces, len(faces))
                if not self.args.check_frames:
                    surface = pyds.get_nvds_buf_surface(hash(buffer), meta.batch_id)
                    try:
                        image = cv2.cvtColor(np.array(surface, copy=True), cv2.COLOR_RGBA2BGR)
                    finally:
                        pyds.unmap_nvds_buf_surface(hash(buffer), meta.batch_id)
                    for x, y, w, h in faces:
                        cv2.rectangle(image, (x, y), (x+w, y+h), (180, 105, 255), 2)
                    with self.lock:
                        self.latest = image
                elif self.frames_seen >= self.args.check_frames:
                    self.finished = True
                    GLib.idle_add(self.loop.quit)
                try:
                    node = node.next
                except StopIteration:
                    break
        except Exception as error:
            self.error = str(error)
            GLib.idle_add(self.loop.quit)
        return Gst.PadProbeReturn.OK

    def _show(self):
        with self.lock:
            image, self.latest = self.latest, None
        if image is not None:
            cv2.imshow(self.window, image)
        if cv2.waitKey(1) & 255 in (27, ord('q'), ord('Q')) or cv2.getWindowProperty(self.window, cv2.WND_PROP_VISIBLE) < 1:
            self.finished = True
            self.loop.quit()
            return False
        return True

    def _watchdog(self):
        if self.frames_seen == 0:
            self.error = "DeepStream did not deliver frames before startup timeout."
            self.loop.quit()
        return False

    def run(self):
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        timers = [GLib.timeout_add_seconds(self.args.timeout, self._watchdog)]
        if self.args.check_frames:
            timers.append(GLib.timeout_add_seconds(self.args.timeout, self._on_timeout))
        else:
            cv2.namedWindow(self.window, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.window, self.args.width, self.args.height)
            timers.append(GLib.timeout_add(10, self._show))
        try:
            if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("Cannot start DeepStream preview.")
            self.loop.run()
        except KeyboardInterrupt:
            pass
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            for timer in timers:
                if GLib.MainContext.default().find_source_by_id(timer):
                    GLib.source_remove(timer)
            self.streammux.release_request_pad(self.streammux_sink_pad)
            bus.remove_signal_watch()
            if not self.args.check_frames:
                cv2.destroyAllWindows()
        if self.error:
            raise RuntimeError(self.error)
        elapsed = time.monotonic() - self.started if self.started else 0
        print(f"DeepStream: {self.frames_seen} frames; max faces: {self.max_faces}; "
              f"processing FPS: {max(0, self.frames_seen-1)/elapsed if elapsed else 0:.1f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default='/dev/video0')
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--check-frames', type=int, default=0)
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--face-class-id', type=int, default=0)
    parser.add_argument('--pgie-config', type=Path, default=Path(__file__).resolve().parent / 'face_detector_pgie_config.txt')
    args = parser.parse_args()
    if min(args.width, args.height, args.fps, args.timeout) < 1 or min(args.check_frames, args.face_class_id) < 0:
        parser.error('Invalid camera or detection settings')
    if not args.check_frames and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        parser.error('Запустите ярлык камеры на рабочем столе Jetson.')
    Gst.init(None)
    try:
        DeepStreamPreview(args).run()
    except (RuntimeError, cv2.error) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
