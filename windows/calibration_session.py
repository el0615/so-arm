"""SO-101 calibration without the follower's torque-enabling configure step."""
from datetime import datetime
import shutil


def run_device_calibration(device):
    path = device.calibration_fpath
    if path.is_file():
        backup = path.parent / 'backup' / (path.stem + '_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        print(f'Calibration backup: {backup}', flush=True)
    # device.connect() calls SOFollower.configure(), which re-enables torque.
    # Calibration only needs the serial bus, not robot runtime configuration.
    try:
        device.bus.connect()
        device.bus.disable_torque()
        torque = device.bus.sync_read('Torque_Enable', normalize=False)
        if set(torque) != set(device.bus.motors) or any(value != 0 for value in torque.values()):
            raise RuntimeError(f'Torque-off verification failed: {torque}. Do not force the joints.')
        print('All 6 motors: torque OFF. Type c at the next prompt to perform NEW calibration.', flush=True)
        device.calibrate()
        if not device.bus.is_calibrated:
            raise RuntimeError('Saved calibration does not match the motor registers.')
        print('Calibration matches motor registers.', flush=True)
    finally:
        device.bus.disconnect(disable_torque=True)


def calibrate(args):
    print('Loading SO-101 calibration tools; please wait...', flush=True)
    import draccus
    from lerobot.scripts.lerobot_calibrate import CalibrateConfig
    from lerobot.robots import make_robot_from_config
    from lerobot.teleoperators import make_teleoperator_from_config
    cfg = draccus.parse(CalibrateConfig, args=args)
    device = make_robot_from_config(cfg.robot) if cfg.robot else make_teleoperator_from_config(cfg.teleop)
    if device.name not in ('so_follower', 'so_leader'):
        raise ValueError('This Windows calibration entry point supports SO-100/101 arms only.')
    run_device_calibration(device)
