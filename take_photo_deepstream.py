#!/usr/bin/env python3
"""Capture one USB-camera photo with NVIDIA DeepStream face detections.

This script needs a DeepStream face-detector nvinfer configuration, including
the model or TensorRT engine it refers to. It deliberately does not fall back
to the OpenCV Haar detector: every pink box comes from DeepStream metadata.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import cv2
    import numpy as np
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst
    import pyds
except (ImportError, ValueError) as error:
    sys.exit(
        "NVIDIA DeepStream Python bindings are required. Install a DeepStream "
        "release that matches the Jetson's JetPack version and its pyds bindings. "
        f"({error})"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture a USB-camera photo using a DeepStream face detector."
    )
    parser.add_argument("--device", default="/dev/video0", help="V4L2 camera device")
    parser.add_argument("--width", type=int, default=1920, help="Camera width")
    parser.add_argument("--height", type=int, default=1080, help="Camera height")
    parser.add_argument("--fps", type=int, default=30, help="Camera frame rate")
    parser.add_argument(
        "--warmup-frames",
        type=int,
        default=15,
        help="Frames to discard while camera exposure and inference warm up",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for a frame before failing",
    )
    parser.add_argument(
        "--pgie-config",
        type=Path,
        default=Path(__file__).resolve().parent / "face_detector_pgie_config.txt",
        help="DeepStream nvinfer config for a face detector",
    )
    parser.add_argument(
        "--face-class-id",
        type=int,
        default=0,
        help="Class ID used for faces by the nvinfer model (default: 0)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / "Desktop" / "photos",
        help="Directory for saved images (default: ~/Desktop/photos)",
    )
    return parser.parse_args()


def make_element(factory: str, name: str) -> Gst.Element:
    element = Gst.ElementFactory.make(factory, name)
    if element is None:
        raise RuntimeError(
            f"Cannot create GStreamer element '{factory}'. Is DeepStream installed?"
        )
    return element


def link_elements(*elements: Gst.Element) -> None:
    for source, destination in zip(elements, elements[1:]):
        if not source.link(destination):
            raise RuntimeError(
                f"Cannot link DeepStream elements '{source.get_name()}' and "
                f"'{destination.get_name()}'."
            )


class DeepStreamPhotoCapture:
    """Run a one-frame DeepStream pipeline and save annotated RGB output."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.loop = GLib.MainLoop()
        self.pipeline = Gst.Pipeline.new("face-photo-pipeline")
        if self.pipeline is None:
            raise RuntimeError("Cannot create the DeepStream pipeline.")

        self.frames_seen = 0
        self.finished = False
        self.error: str | None = None
        self.output_path: Path | None = None
        self.streammux: Gst.Element | None = None
        self.streammux_sink_pad: Gst.Pad | None = None
        self.post_infer_convert: Gst.Element | None = None
        self._build_pipeline()

    def _caps_filter(self, name: str, caps: str) -> Gst.Element:
        element = make_element("capsfilter", name)
        element.set_property("caps", Gst.Caps.from_string(caps))
        return element

    def _build_pipeline(self) -> None:
        source = make_element("v4l2src", "camera-source")
        source.set_property("device", self.args.device)
        camera_caps = self._caps_filter(
            "camera-mjpeg-caps",
            "image/jpeg,"
            f"width=(int){self.args.width},height=(int){self.args.height},"
            f"framerate=(fraction){self.args.fps}/1",
        )
        jpeg_decoder = make_element("jpegdec", "jpeg-decoder")
        cpu_convert = make_element("videoconvert", "cpu-convert")
        pre_infer_convert = make_element("nvvideoconvert", "pre-infer-convert")
        nv12_caps = self._caps_filter(
            "nv12-nvmm-caps", "video/x-raw(memory:NVMM),format=NV12"
        )
        streammux = make_element("nvstreammux", "stream-muxer")
        streammux.set_property("width", self.args.width)
        streammux.set_property("height", self.args.height)
        streammux.set_property("batch-size", 1)
        streammux.set_property("live-source", True)
        streammux.set_property("batched-push-timeout", 4_000_000)

        pgie = make_element("nvinfer", "face-detector")
        pgie.set_property("config-file-path", str(self.args.pgie_config))
        post_infer_convert = make_element("nvvideoconvert", "post-infer-convert")
        rgba_caps = self._caps_filter(
            "rgba-nvmm-caps", "video/x-raw(memory:NVMM),format=RGBA"
        )
        sink = make_element("fakesink", "frame-sink")
        sink.set_property("sync", False)
        sink.set_property("enable-last-sample", False)

        for element in (
            source,
            camera_caps,
            jpeg_decoder,
            cpu_convert,
            pre_infer_convert,
            nv12_caps,
            streammux,
            pgie,
            post_infer_convert,
            rgba_caps,
            sink,
        ):
            self.pipeline.add(element)

        link_elements(
            source,
            camera_caps,
            jpeg_decoder,
            cpu_convert,
            pre_infer_convert,
            nv12_caps,
        )
        source_pad = nv12_caps.get_static_pad("src")
        if source_pad is None:
            raise RuntimeError("Cannot get the camera pipeline source pad.")

        try:
            request_pad = streammux.request_pad_simple("sink_0")
        except AttributeError:
            # DeepStream releases based on older GStreamer expose the
            # deprecated method only.
            request_pad = streammux.get_request_pad("sink_0")
        if request_pad is None:
            raise RuntimeError("Cannot request nvstreammux sink_0 pad.")
        if source_pad.link(request_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError("Cannot link camera output to nvstreammux.")

        link_elements(streammux, pgie, post_infer_convert, rgba_caps, sink)
        output_pad = rgba_caps.get_static_pad("src")
        if output_pad is None:
            raise RuntimeError("Cannot get the annotated-frame pad.")
        output_pad.add_probe(Gst.PadProbeType.BUFFER, self._on_frame, None)

        self.streammux = streammux
        self.streammux_sink_pad = request_pad
        self.post_infer_convert = post_infer_convert

    def _on_bus_message(self, _bus: Gst.Bus, message: Gst.Message) -> bool:
        if message.type == Gst.MessageType.ERROR:
            error, details = message.parse_error()
            self.error = f"DeepStream pipeline error: {error.message} ({details or 'no details'})"
            GLib.idle_add(self.loop.quit)
        elif message.type == Gst.MessageType.EOS and not self.finished:
            self.error = "The DeepStream pipeline reached end-of-stream before a photo was saved."
            GLib.idle_add(self.loop.quit)
        return True

    def _on_timeout(self) -> bool:
        if not self.finished:
            self.error = f"Timed out after {self.args.timeout} seconds waiting for a camera frame."
            self.loop.quit()
        return False

    def _objects_for_frame(self, frame_meta: Any) -> list[tuple[int, int, int, int]]:
        faces: list[tuple[int, int, int, int]] = []
        object_list = frame_meta.obj_meta_list
        while object_list is not None:
            try:
                object_meta = pyds.NvDsObjectMeta.cast(object_list.data)
            except StopIteration:
                break

            if int(object_meta.class_id) == self.args.face_class_id:
                rect = object_meta.rect_params
                faces.append(
                    (
                        max(0, int(rect.left)),
                        max(0, int(rect.top)),
                        max(0, int(rect.width)),
                        max(0, int(rect.height)),
                    )
                )

            try:
                object_list = object_list.next
            except StopIteration:
                break
        return faces

    def _on_frame(
        self,
        _pad: Gst.Pad,
        info: Gst.PadProbeInfo,
        _user_data: Any,
    ) -> Gst.PadProbeReturn:
        if self.finished:
            return Gst.PadProbeReturn.OK

        gst_buffer = info.get_buffer()
        if gst_buffer is None:
            self.error = "DeepStream delivered an empty buffer."
            self.finished = True
            GLib.idle_add(self.loop.quit)
            return Gst.PadProbeReturn.OK

        batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
        if batch_meta is None:
            return Gst.PadProbeReturn.OK

        frame_list = batch_meta.frame_meta_list
        while frame_list is not None and not self.finished:
            try:
                frame_meta = pyds.NvDsFrameMeta.cast(frame_list.data)
            except StopIteration:
                break

            self.frames_seen += 1
            if self.frames_seen > self.args.warmup_frames:
                try:
                    surface = pyds.get_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)
                    try:
                        rgba = np.array(surface, copy=True, order="C")
                    finally:
                        pyds.unmap_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)
                    image = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)
                    faces = self._objects_for_frame(frame_meta)
                    thickness = max(2, round(min(image.shape[:2]) / 360))
                    for x, y, width, height in faces:
                        cv2.rectangle(
                            image,
                            (x, y),
                            (x + width, y + height),
                            (180, 105, 255),  # Hot pink (#FF69B4), in BGR order.
                            thickness,
                        )

                    filename = datetime.now().strftime("photo-deepstream-%Y%m%d-%H%M%S.jpg")
                    self.output_path = self.args.output_dir / filename
                    if not cv2.imwrite(str(self.output_path), image):
                        raise RuntimeError(f"Could not write photo: {self.output_path}")
                    print(f"Detected {len(faces)} face(s).")
                    print(self.output_path)
                except Exception as error:  # reported after the main loop exits
                    self.error = str(error)
                self.finished = True
                GLib.idle_add(self.loop.quit)

            try:
                frame_list = frame_list.next
            except StopIteration:
                break
        return Gst.PadProbeReturn.OK

    def run(self) -> Path:
        self.args.output_dir.mkdir(parents=True, exist_ok=True)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        GLib.timeout_add_seconds(self.args.timeout, self._on_timeout)

        try:
            if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("Cannot start the DeepStream pipeline.")
            self.loop.run()
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            if self.streammux is not None and self.streammux_sink_pad is not None:
                self.streammux.release_request_pad(self.streammux_sink_pad)

        if self.error:
            raise RuntimeError(self.error)
        if self.output_path is None:
            raise RuntimeError("DeepStream ended without saving a photo.")
        return self.output_path


def main() -> int:
    args = parse_args()
    if (
        args.width < 1
        or args.height < 1
        or args.fps < 1
        or args.warmup_frames < 0
        or args.timeout < 1
        or args.face_class_id < 0
    ):
        print("Camera and inference settings must be valid values.", file=sys.stderr)
        return 2
    if not args.pgie_config.is_file():
        print(f"Face-detector config not found: {args.pgie_config}", file=sys.stderr)
        return 2

    Gst.init(None)
    try:
        DeepStreamPhotoCapture(args).run()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
