"""Saved follower pose and bounded return motion for the Windows recorder."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time

HOME = Path(__file__).with_name("home-pose.json")


def identity(robot):
    from serial.tools.list_ports import comports
    port = next((p for p in comports() if p.device.upper() == robot.config.port.upper()), None)
    if port is None or not port.serial_number:
        raise ValueError("Cannot identify follower USB serial number. Check the COM port.")
    return {"id": robot.config.id, "usb_serial": port.serial_number,
            "vid": port.vid, "pid": port.pid, "use_degrees": robot.config.use_degrees,
            "calibration": {k: asdict(v) for k, v in robot.calibration.items()}}


def validate_positions(bus, positions):
    if set(positions) != set(bus.motors) or not bus.calibration:
        raise ValueError("Home pose must contain all six calibrated motors.")
    for name, value in positions.items():
        cal = bus.calibration[name]
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Invalid position: {name}")
        if not cal.range_min <= value <= cal.range_max:
            raise ValueError(f"{name} is outside its calibrated range. Reposition and save again.")


def load_home(robot, path=HOME):
    if not path.exists():
        raise ValueError("Save the initial pose first: .\\so-arm.cmd save-home")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or data.get("identity") != identity(robot):
        raise ValueError("Follower or calibration changed. Run save-home again for this arm.")
    validate_positions(robot.bus, data["positions_raw"])
    return data["positions_raw"]


def save_home(config, path=HOME):
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
    robot = SO101Follower(SO101FollowerConfig(port=config["follower_port"],
                                             id=config["follower_id"], cameras={}))
    arm_identity = identity(robot)
    bus = robot.bus
    try:
        bus.connect()  # Read-only handshake; do not call robot.connect/configure.
        if not bus.is_calibrated:
            raise ValueError("Follower calibration does not match the motors. Calibrate first.")
        first = bus.sync_read("Present_Position", normalize=False)
        time.sleep(0.25)
        positions = bus.sync_read("Present_Position", normalize=False)
        validate_positions(bus, positions)
        if any(abs(positions[k] - first[k]) > 8 for k in positions):
            raise ValueError("Arm moved while saving. Hold it still and run save-home again.")
        data = {"version": 1, "saved_at": datetime.now(timezone.utc).isoformat(),
                "identity": arm_identity, "positions_raw": positions}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(path)
        print(f"Initial pose saved: {path}\nNo motor commands or torque changes were sent.", flush=True)
    finally:
        if bus.is_connected:
            bus.disconnect(disable_torque=False)


class ReturnCancelled(Exception):
    pass


def return_home(bus, target, cancelled, *, clock=time.monotonic, sleep=time.sleep):
    """Raw encoder trajectory: <=180 ticks/s (~16 deg/s), measured following error guard.

    Never enables torque. Each command advances by at most 6 encoder ticks,
    even after a Windows scheduling delay. This is joint interpolation, not
    collision avoidance; the user must leave the return path unobstructed.
    """
    validate_positions(bus, target)
    torque = bus.sync_read("Torque_Enable", normalize=False)
    if set(torque) != set(target) or any(v != 1 for v in torque.values()):
        raise ValueError("Return requires all follower motors already holding position.")
    start = bus.sync_read("Present_Position", normalize=False)
    validate_positions(bus, start)
    distance = max(abs(target[k] - start[k]) for k in target)
    duration = max(3.0, 1.5 * distance / 180.0)
    deadline = clock() + duration + 8.0
    elapsed = 0.0
    previous_time = clock()
    previous = dict(start)
    stable = 0
    while True:
        if cancelled():
            # Freeze the measured pose before handing control to normal disconnect.
            present = bus.sync_read("Present_Position", normalize=False)
            bus.sync_write("Goal_Position", present, normalize=False)
            raise ReturnCancelled()
        present = bus.sync_read("Present_Position", normalize=False)
        validate_positions(bus, present)
        if any(abs(present[k] - previous[k]) > 170 for k in target):
            bus.sync_write("Goal_Position", present, normalize=False)
            raise RuntimeError("Return stopped: follower is not tracking the return trajectory.")
        now = clock()
        if now > deadline:
            bus.sync_write("Goal_Position", present, normalize=False)
            raise TimeoutError("Return stopped: initial pose was not reached in time.")
        elapsed += min(max(now - previous_time, 0), 1 / 30)
        previous_time = now
        fraction = min(elapsed / duration, 1.0)
        blend = fraction * fraction * (3 - 2 * fraction)
        goal = {k: round(start[k] + (target[k] - start[k]) * blend) for k in target}
        # Check again immediately before writing, including cancellation during a read.
        if cancelled():
            bus.sync_write("Goal_Position", present, normalize=False)
            raise ReturnCancelled()
        bus.sync_write("Goal_Position", goal, normalize=False)
        previous = goal
        stable = stable + 1 if fraction == 1 and all(abs(present[k] - target[k]) <= 20 for k in target) else 0
        if stable >= 5:
            return
        sleep(1 / 30)
