"""Read motor IDs, calibration registers and position; never write motor registers."""
import dataclasses
import datetime
import json
from pathlib import Path

from lerobot.motors import Motor, MotorNormMode, SerialMotorsBus

ROOT = Path(__file__).resolve().parent
NAMES = ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper')


def main():
    config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig'))
    report = {}
    for side in ('leader', 'follower'):
        port = config[f'{side}_port']
        bus = SerialMotorsBus(port, {name: Motor(i, 'sts3215', MotorNormMode.RANGE_0_100)
                                     for i, name in enumerate(NAMES, 1)})
        result = {'port': port}
        try:
            bus.connect()
            result['motor_handshake'] = 'OK: IDs 1-6, models and firmware checked'
            result['calibration_registers'] = {k: dataclasses.asdict(v) for k, v in bus.read_calibration().items()}
            result['positions_raw'] = bus.sync_read('Present_Position', normalize=False)
            result['torque_enabled'] = bus.sync_read('Torque_Enable', normalize=False)
        except Exception as exc:
            result['error'] = f'{type(exc).__name__}: {exc}'
        finally:
            bus.disconnect(disable_torque=False)
        report[side] = result
        print(json.dumps({side: result}, indent=2, ensure_ascii=False), flush=True)
    destination = ROOT / 'diagnostics'
    destination.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    path = destination / f'motor_readback_{stamp}.json'
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Read-only report: {path}')
    if any('error' in item for item in report.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
