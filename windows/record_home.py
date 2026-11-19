"""Opt-in Enter/save/return/wait workflow around the pinned LeRobot recorder."""
import threading
import time
from unittest.mock import patch

from home_pose import ReturnCancelled, load_home, return_home


class Controls:
    def __init__(self):
        self.events = dict(exit_early=False, rerecord_episode=False, stop_recording=False)
        self.stage = "loading"
        self.next_episode = False
        self.held = set()
        self.lock = threading.Lock()

    def set_stage(self, stage):
        with self.lock:
            self.stage = stage
            self.next_episode = False

    def press(self, name):
        with self.lock:
            if name in self.held:
                return
            self.held.add(name)
            if name in ("esc", "q"):
                self.events.update(stop_recording=True, exit_early=True)
            elif name == "enter":
                if self.stage == "recording":
                    self.events["exit_early"] = True
                elif self.stage == "waiting":
                    self.next_episode = True

    def release(self, name):
        with self.lock:
            self.held.discard(name)

    def take_start(self):
        with self.lock:
            result = self.next_episode
            self.next_episode = False
            return result

    def stopped(self):
        return self.events["stop_recording"]


def start_listener(controls):
    from pynput import keyboard

    def name(key):
        return {keyboard.Key.enter: "enter", keyboard.Key.esc: "esc"}.get(
            key, (getattr(key, "char", "") or "").lower())

    listener = keyboard.Listener(on_press=lambda key: controls.press(name(key)),
                                 on_release=lambda key: controls.release(name(key)))
    listener.start()
    listener.wait()
    return listener


def alignment_errors(robot, teleop):
    follower = robot.bus.sync_read("Present_Position")
    leader = teleop.get_action()
    if set(leader) != {f"{k}.pos" for k in follower}:
        raise ValueError("Leader and follower joints do not match.")
    return {k: round(abs(follower[k] - leader[f"{k}.pos"]), 1)
            for k in follower if abs(follower[k] - leader[f"{k}.pos"]) > (8 if k == "gripper" else 5)}


class Session:
    def __init__(self, controls, home, total):
        self.controls = controls
        self.home = home
        self.total = total
        self.saved = 0
        self.robot = None

    def wait_for_start(self, robot, teleop):
        self.controls.set_stage("waiting")
        print("\n[WAIT] 리더를 팔로워와 비슷한 자세로 맞추세요. Enter: 녹화 시작 / Q: 종료", flush=True)
        while not self.controls.stopped():
            if self.controls.take_start():
                errors = alignment_errors(robot, teleop)
                if errors:
                    print(f"자세 차이가 큽니다 (몸통 5도 / 그리퍼 8% 이내 필요): {errors}\n"
                          "리더를 맞춘 뒤 Enter를 다시 누르세요.", flush=True)
                else:
                    return
            time.sleep(0.03)
        raise KeyboardInterrupt

    def loop(self, original, **kwargs):
        if kwargs.get("dataset") is None:
            return  # Replace stock timed reset/teleop with holding at home.
        self.robot = kwargs["robot"]
        self.wait_for_start(self.robot, kwargs["teleop"])
        self.controls.events["exit_early"] = False
        self.controls.set_stage("starting")
        if self.controls.stopped():
            raise KeyboardInterrupt
        print("[RECORDING] Enter: 에피소드 저장 후 초기 자세 복귀 / Q: 저장 후 종료", flush=True)
        dataset = kwargs["dataset"]
        add_frame = dataset.add_frame

        def append(frame):
            result = add_frame(frame)
            if self.controls.stage == "starting":
                self.controls.set_stage("recording")
            return result

        try:
            with patch.object(dataset, "add_frame", append):
                return original(**kwargs)
        finally:
            self.controls.set_stage("saving")

    def after_save(self):
        self.saved += 1
        print(f"[SAVED] {self.saved}/{self.total} 에피소드 저장 완료", flush=True)
        if self.controls.stopped():
            return
        self.controls.set_stage("returning")
        print("[RETURN] 초기 자세로 천천히 복귀 중. Q/Esc: 복귀 중단 및 종료", flush=True)
        try:
            return_home(self.robot.bus, self.home, self.controls.stopped)
        except ReturnCancelled:
            return
        print("[HOME] 초기 자세 도착. 팔로워 자세를 유지합니다.", flush=True)
        if self.saved >= self.total:
            self.controls.set_stage("done")
            print("모든 에피소드 완료. 팔을 받친 뒤 Q/Esc를 누르면 토크를 해제하고 종료합니다.", flush=True)
            while not self.controls.stopped():
                time.sleep(0.03)


def record(args, *, check=False):
    print("Loading Enter/home recording...", flush=True)
    import draccus
    from lerobot.scripts import lerobot_record as upstream
    from lerobot.robots.so_follower import SO101FollowerConfig
    from lerobot.teleoperators.so_leader import SO101LeaderConfig

    cfg = draccus.parse(upstream.RecordConfig, args=args)
    # SO100 and SO101 names are aliases of the same config class in this pin.
    if not isinstance(cfg.robot, SO101FollowerConfig) or not isinstance(cfg.teleop, SO101LeaderConfig):
        raise ValueError("Enter/home recording supports one SO101 follower and leader.")
    if not cfg.robot.use_degrees or not cfg.teleop.use_degrees:
        raise ValueError("Enter/home recording requires use_degrees=true on both arms.")
    if cfg.robot.port.upper() == cfg.teleop.port.upper():
        raise ValueError("Leader and follower must use different COM ports.")
    if cfg.dataset.num_episodes < 1:
        raise ValueError("num_episodes must be positive.")
    if not cfg.robot.disable_torque_on_disconnect:
        raise ValueError("Enter/home recording requires disable_torque_on_disconnect=true.")
    robot = upstream.make_robot_from_config(cfg.robot)
    home = load_home(robot)  # Refuse missing/stale pose before opening devices.
    if check:
        print("Configuration and saved home pose OK. No devices opened.", flush=True)
        return
    controls = Controls()
    session = Session(controls, home, cfg.dataset.num_episodes)
    listener = start_listener(controls)
    original_connect = robot.connect
    original_enable = robot.bus.enable_torque

    def connect():
        # Check stored calibration against hardware before any configuration writes.
        try:
            robot.bus.connect()
            if not robot.bus.is_calibrated:
                raise ValueError("Motor calibration changed. Calibrate and save-home again.")
        finally:
            if robot.bus.is_connected:
                robot.bus.disconnect(disable_torque=False)
        if controls.stopped():
            raise KeyboardInterrupt
        original_connect(calibrate=False)

    def enable(*a, **kw):
        # configure() enables torque. Seed the present pose to avoid an old goal
        # from a prior session pulling the arm before the first Enter.
        if controls.stopped():
            raise KeyboardInterrupt
        present = robot.bus.sync_read("Present_Position", normalize=False)
        robot.bus.sync_write("Goal_Position", present, normalize=False)
        return original_enable(*a, **kw)

    original_loop = upstream.record_loop
    original_save = upstream.LeRobotDataset.save_episode

    def save(dataset, *a, **kw):
        if controls.stopped() and not dataset.has_pending_frames():
            return  # Q during the first frame must not attempt an empty episode.
        result = original_save(dataset, *a, **kw)
        session.after_save()  # Saving finishes before any return commands.
        return result

    cfg.dataset.reset_time_s = 0
    cfg.play_sounds = False
    try:
        with patch.object(upstream, "make_robot_from_config", return_value=robot), \
             patch.object(robot, "connect", connect), \
             patch.object(robot.bus, "enable_torque", enable), \
             patch.object(upstream, "init_keyboard_listener", return_value=(listener, controls.events)), \
             patch.object(upstream, "record_loop", lambda **kw: session.loop(original_loop, **kw)), \
             patch.object(upstream.LeRobotDataset, "save_episode", save):
            upstream.record(cfg)
    except KeyboardInterrupt:
        print("Recording stopped. No automatic return on Ctrl+C or while waiting.", flush=True)
    finally:
        listener.stop()
        # Also clean up partial camera connections or failures in dataset.finalize().
        if robot.bus.is_connected:
            robot.bus.disconnect(disable_torque=True)
        for camera in robot.cameras.values():
            if camera.is_connected:
                camera.disconnect()
