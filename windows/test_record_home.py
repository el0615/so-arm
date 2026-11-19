"""Hardware-free checks: python windows/test_record_home.py."""
from types import SimpleNamespace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from home_pose import ReturnCancelled, load_home, return_home
from record_home import Controls, Session


class Clock:
    now = 0.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Bus:
    def __init__(self, jam=False):
        self.motors = {"joint": object()}
        self.calibration = {"joint": SimpleNamespace(range_min=0, range_max=4095)}
        self.position = {"joint": 1000}
        self.writes = []
        self.jam = jam
        self.torque = 1

    def sync_read(self, register, normalize=False):
        return {"joint": self.torque} if register == "Torque_Enable" else dict(self.position)

    def sync_write(self, register, values, normalize=False):
        assert register == "Goal_Position" and normalize is False
        self.writes.append(dict(values))
        if not self.jam:
            self.position = dict(values)


class ReturnTests(unittest.TestCase):
    def run_return(self, bus, target=2000, cancelled=lambda: False, clock=None):
        clock = clock or Clock()
        return_home(bus, {"joint": target}, cancelled, clock=clock.clock, sleep=clock.sleep)

    def test_reaches_home_with_bounded_steps(self):
        bus = Bus()
        self.run_return(bus)
        values = [1000] + [w["joint"] for w in bus.writes]
        self.assertEqual(values[-1], 2000)
        self.assertLessEqual(max(abs(a-b) for a, b in zip(values, values[1:])), 6)

    def test_windows_scheduling_delay_does_not_jump(self):
        class SlowClock(Clock):
            def sleep(self, seconds):
                self.now += 0.12
        bus = Bus()
        with self.assertRaises(TimeoutError):
            self.run_return(bus, clock=SlowClock())
        values = [1000] + [w["joint"] for w in bus.writes]
        self.assertLessEqual(max(abs(a-b) for a, b in zip(values, values[1:])), 6)

    def test_jam_stops_and_holds_measured_pose(self):
        bus = Bus(jam=True)
        with self.assertRaisesRegex(RuntimeError, "not tracking"):
            self.run_return(bus)
        self.assertLess(max(w["joint"] for w in bus.writes), 1180)
        self.assertEqual(bus.writes[-1], {"joint": 1000})

    def test_cancel_never_commands_home(self):
        bus = Bus()
        with self.assertRaises(ReturnCancelled):
            self.run_return(bus, cancelled=lambda: True)
        self.assertEqual(bus.writes, [{"joint": 1000}])

    def test_torque_off_and_bad_target_rejected_before_writes(self):
        bus = Bus()
        bus.torque = 0
        with self.assertRaises(ValueError):
            self.run_return(bus)
        bus.torque = 1
        with self.assertRaises(ValueError):
            self.run_return(bus, target=5000)
        self.assertEqual(bus.writes, [])

    def test_identity_or_calibration_mismatch_rejected(self):
        robot = SimpleNamespace(bus=Bus())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "home.json"
            path.write_text(json.dumps(dict(version=1, identity={"calibration": "old"},
                                            positions_raw={"joint": 2000})))
            with patch("home_pose.identity", return_value={"calibration": "new"}):
                with self.assertRaisesRegex(ValueError, "changed"):
                    load_home(robot, path)


class SessionTests(unittest.TestCase):
    def test_enter_stops_only_episode_and_held_key_cannot_restart(self):
        controls = Controls()
        controls.set_stage("recording")
        controls.press("enter")
        self.assertTrue(controls.events["exit_early"])
        self.assertFalse(controls.stopped())
        controls.set_stage("waiting")
        controls.press("enter")
        self.assertFalse(controls.take_start())
        controls.release("enter")
        controls.press("enter")
        self.assertTrue(controls.take_start())

    def test_return_and_saving_ignore_enter(self):
        controls = Controls()
        for stage in ("saving", "returning", "done"):
            controls.set_stage(stage)
            controls.press("enter")
            controls.release("enter")
            self.assertFalse(controls.take_start())
        controls.press("q")
        self.assertTrue(controls.stopped())

    def test_reset_never_calls_teleop(self):
        session = Session(Controls(), {}, 3)
        original = Mock()
        session.loop(original, robot=object(), dataset=None)
        original.assert_not_called()

    def test_camera_failure_does_not_return_and_restores_add_frame(self):
        session = Session(Controls(), {}, 3)
        original = Mock(side_effect=TimeoutError("camera stale"))
        dataset = SimpleNamespace(add_frame=Mock())
        add = dataset.add_frame
        with patch.object(session, "wait_for_start"), patch("record_home.return_home") as motion:
            with self.assertRaises(TimeoutError):
                session.loop(original, robot=object(), teleop=object(), dataset=dataset)
            motion.assert_not_called()
        self.assertIs(dataset.add_frame, add)

    def test_first_frame_enables_enter_and_return_is_outside_record_loop(self):
        controls = Controls()
        session = Session(controls, {"joint": 2000}, 3)
        dataset = SimpleNamespace(add_frame=Mock())
        robot = SimpleNamespace(bus=Bus())

        def loop(**kwargs):
            self.assertEqual(controls.stage, "starting")
            kwargs["dataset"].add_frame({"test": 1})
            self.assertEqual(controls.stage, "recording")
            controls.press("enter")
            self.assertTrue(controls.events["exit_early"])

        with patch.object(session, "wait_for_start"), patch("record_home.return_home") as motion:
            session.loop(loop, robot=robot, teleop=object(), dataset=dataset)
            motion.assert_not_called()
            session.after_save()
            motion.assert_called_once()
        dataset.add_frame.assert_called_once_with({"test": 1})
        self.assertEqual(session.saved, 1)

    def test_quit_skips_return(self):
        controls = Controls()
        session = Session(controls, {}, 3)
        controls.press("q")
        with patch("record_home.return_home") as motion:
            session.after_save()
            motion.assert_not_called()


if __name__ == "__main__":
    unittest.main()
