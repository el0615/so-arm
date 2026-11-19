"""Exercise the installed LeRobot outer recording loop with simulated devices only."""
import contextlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import so_arm
so_arm.environment()
import record_home
from lerobot.scripts import lerobot_record as upstream


class RecorderIntegration(unittest.TestCase):
    def test_save_home_is_read_only(self):
        import home_pose
        from lerobot.robots import so_follower
        bus = Mock(is_connected=True, is_calibrated=True)
        bus.motors = {"joint": object()}
        bus.calibration = {"joint": SimpleNamespace(range_min=0, range_max=4095)}
        bus.sync_read.return_value = {"joint": 1000}
        robot = SimpleNamespace(bus=bus)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(so_follower, "SO101Follower", return_value=robot), \
             patch.object(home_pose, "identity", return_value={"test": "mock"}), \
             patch.object(home_pose.time, "sleep"):
            path = Path(directory) / "home.json"
            home_pose.save_home({"follower_port": "COM8", "follower_id": "windows_follower"}, path)
            self.assertTrue(path.exists())
        bus.sync_write.assert_not_called()
        bus.enable_torque.assert_not_called()
        bus.disable_torque.assert_not_called()
        bus.disconnect.assert_called_once_with(disable_torque=False)

    def test_save_return_wait_order_and_no_reset_teleop(self):
        order = []
        controls = record_home.Controls()
        bus = Mock(is_connected=True, is_calibrated=True)
        robot = SimpleNamespace(bus=bus, connect=Mock(), disconnect=Mock(), is_connected=True,
                                cameras={}, observation_features={}, action_features={}, robot_type="so101")
        teleop = Mock(is_connected=True, action_features={})

        class Dataset:
            num_episodes = 0
            frames = 0

            @classmethod
            def create(cls, *a, **kw):
                return cls()

            def add_frame(self, frame):
                self.frames += 1

            def save_episode(self):
                self_test.assertEqual(self.frames, 1)
                self.frames = 0
                self.num_episodes += 1
                order.append("save")

            def finalize(self):
                order.append("finalize")

        self_test = self

        def loop(**kw):
            order.append("record")
            kw["dataset"].add_frame({})
            controls.press("enter")
            self.assertTrue(kw["events"]["exit_early"])
            controls.release("enter")

        def wait(*a):
            order.append("wait")

        def motion(*a):
            self.assertEqual(order[-1], "save")
            order.append("return")
            if order.count("return") == 2:
                controls.press("q")

        with contextlib.ExitStack() as stack:
            for obj, name, value in [
                (upstream, "make_robot_from_config", Mock(return_value=robot)),
                (upstream, "make_teleoperator_from_config", Mock(return_value=teleop)),
                (upstream, "check_control_rate", Mock()),
                (upstream, "make_default_processors", Mock(return_value=(None, None, None))),
                (upstream, "aggregate_pipeline_dataset_features", Mock(return_value={})),
                (upstream, "start_episode", Mock()),
                (upstream, "log_say", Mock()),
                (upstream, "LeRobotDataset", Dataset),
                (upstream, "VideoEncodingManager", lambda dataset: contextlib.nullcontext()),
                (upstream, "record_loop", loop),
                (record_home, "load_home", Mock(return_value={"joint": 1000})),
                (record_home, "Controls", Mock(return_value=controls)),
                (record_home, "start_listener", Mock(return_value=Mock())),
                (record_home, "return_home", motion),
                (record_home.Session, "wait_for_start", wait),
            ]:
                stack.enter_context(patch.object(obj, name, value))
            record_home.record([
                "--robot.type=so101_follower", "--robot.port=COM8", "--robot.id=windows_follower",
                "--teleop.type=so101_leader", "--teleop.port=COM7", "--teleop.id=windows_leader",
                "--dataset.repo_id=local/mock_only", "--dataset.single_task=test",
                "--dataset.num_episodes=2", "--dataset.push_to_hub=false",
            ])
        self.assertEqual(order, ["wait", "record", "save", "return",
                                 "wait", "record", "save", "return", "finalize"])
        robot.disconnect.assert_called_once()
        teleop.disconnect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
