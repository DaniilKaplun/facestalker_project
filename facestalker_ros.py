"""ROS 2 transport for the FaceStalker camera and pan/tilt controller."""
from contextlib import ExitStack
from queue import Empty
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import Int64MultiArray

from facestalker import FaceStalker, GLib, CONTROL_INTERVAL_MS, select_face


class RosFaceStalker(FaceStalker):
    def process_faces(self, faces):
        # Called by the GStreamer streaming thread. Publish once per frame,
        # even without a face, so the controller can tell the camera is alive.
        target = select_face(faces)
        # Wire format: capture timestamp in monotonic ns, then optional x/y/w/h
        # in preview pixels. The timestamp is shared by nodes on this Jetson.
        data = [time.monotonic_ns(), *(target or ())]
        self.target_publisher.publish(Int64MultiArray(data=data))

    def receive_target(self, message):
        data = message.data
        if len(data) not in (1, 5) or not 0 < data[0] <= time.monotonic_ns():
            return
        # Use frame time instead of receive time so delayed messages stay stale.
        frame_time = data[0] / 1_000_000_000
        with self.lock:
            if self.frame_time is None or frame_time > self.frame_time:
                self.frame_time = frame_time
                self.target = tuple(data[1:]) or None

    def control_tick(self):
        # The timer and target subscription run serially on the control thread.
        # Handle preview key presses here so only this thread changes the PID.
        while True:
            try:
                key = self.control_keys.get_nowait()
            except Empty:
                break
            self.apply_control_key(key)
        if self.frame_time is None and self.started is not None:
            if time.monotonic() - self.started > 2:
                raise RuntimeError('Camera is running but no ROS 2 targets arrived.')
        self.tick()

    def control_loop(self, stop):
        self.tick_time = time.monotonic()
        try:
            while not stop.is_set() and not self.finished:
                self.executor.spin_once(timeout_sec=CONTROL_INTERVAL_MS / 1000)
        except Exception as error:
            self.error = str(error)
            GLib.idle_add(self.loop.quit)

    def run(self):
        topic = '/facestalker/target'
        # Only the latest frame matters for steering. Avoid a backlog of targets.
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        with ExitStack() as stack:
            rclpy.init(args=[], signal_handler_options=SignalHandlerOptions.NO)
            stack.callback(rclpy.shutdown)
            camera = rclpy.create_node('facestalker_camera')
            stack.callback(camera.destroy_node)
            controller = rclpy.create_node('facestalker_pan_tilt')
            stack.callback(controller.destroy_node)
            self.executor = SingleThreadedExecutor()
            stack.callback(self.executor.shutdown)
            self.target_publisher = camera.create_publisher(Int64MultiArray, topic, qos)
            controller.create_subscription(Int64MultiArray, topic, self.receive_target, qos)
            controller.create_timer(CONTROL_INTERVAL_MS / 1000, self.control_tick)
            # The camera node only publishes from the frame callback. Only the
            # pan/tilt node has callbacks that need to be spun by the executor.
            self.executor.add_node(controller)
            super().run()


if __name__ == '__main__':
    from facestalker import main

    raise SystemExit(main(app_class=RosFaceStalker))
