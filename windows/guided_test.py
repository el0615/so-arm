"""Interactive calibration of both arms, then a short supervised teleoperation."""
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'windows' / 'so_arm.py'
STATUS = ROOT / 'windows' / 'guided-test-status.json'


def status(stage, **details):
    STATUS.write_text(json.dumps({'stage': stage, **details}, ensure_ascii=False, indent=2), encoding='utf-8')


def run(*args):
    result = subprocess.run([sys.executable, str(LAUNCHER), *args], cwd=ROOT)
    if result.returncode:
        status('failed', command=list(args), exit_code=result.returncode)
        raise RuntimeError(f'명령이 종료 코드 {result.returncode}로 중단되었습니다. 다음 단계는 실행하지 않습니다.')


def main():
    cfg = json.loads((ROOT / 'windows/config.json').read_text(encoding='utf-8-sig'))
    backup = ROOT / 'windows/calibration/backup' / datetime.datetime.now().strftime('guided_%Y%m%d_%H%M%S')
    backup.mkdir(parents=True)
    for side, folder in [('leader', 'teleoperators/so_leader'), ('follower', 'robots/so_follower')]:
        path = ROOT / 'windows/calibration' / folder / (cfg[side + '_id'] + '.json')
        if path.exists():
            shutil.copy2(path, backup / path.name)
    print('SO-ARM101: 리더 보정 → 팔로워 보정 → 30초 텔레옵', flush=True)
    print(f'기존 보정 백업: {backup}', flush=True)
    for side, label in [('leader', '리더(손으로 조작하는 팔)'), ('follower', '팔로워(따라 움직이는 팔)')]:
        status('waiting_for_calibration', arm=side)
        print(f'\n=== {label} 보정 ===')
        print('1. 팔을 받쳐 주세요. 보정 중 모터 힘이 풀립니다.')
        print('2. 기존 보정 사용 여부를 물으면 c를 입력하고 Enter를 누르세요.')
        print('3. 그림에 맞춰 관절을 가동 범위의 가운데 자세로 놓고 Enter를 누르세요.')
        print('4. 수치 표가 나오면 어깨 회전·어깨 들기·팔꿈치·손목 굽힘·그리퍼를')
        print('   각각 무리 없이 움직일 수 있는 전체 범위로 천천히 움직이세요.')
        print('   손목 회전(wrist_roll)은 범위 기록에서 제외됩니다.')
        print('5. 모든 관절 범위를 기록한 뒤 Enter를 눌러 저장하세요.')
        input('팔을 받치고 준비되면 Enter: ')
        status('calibrating', arm=side)
        run('calibrate', side)
        print(f'{label} 보정 명령 정상 종료.', flush=True)
    status('waiting_for_teleop')
    print('\n=== 30초 텔레옵 테스트 ===')
    print('두 팔을 비슷한 자세로 놓고 주변 물건과 손을 팔로워 이동 경로에서 치워 주세요.')
    print('시작하면 팔로워가 움직입니다. 리더를 조금씩 천천히 움직여 방향을 확인하세요.')
    print('10 Hz, 한 제어 주기당 목표 변화 제한 1 (관절 1도 / 그리퍼 1%).')
    print('중단: 이 창에서 Ctrl+C. 종료 시 팔로워의 힘이 풀리므로 받칠 준비를 하세요.')
    if input('준비가 되면 START를 입력하고 Enter (그 외 입력은 종료): ').strip() != 'START':
        status('calibrated_teleop_skipped')
        return
    status('teleop_running')
    run('teleop', '--fps=10', '--teleop_time_s=30', '--robot.max_relative_target=1')
    status('finished', note='Calibration and teleop commands exited successfully; user must confirm physical tracking.')
    print('\n두 팔 보정과 30초 텔레옵 명령이 정상 종료됐습니다. 실제로 잘 따라왔는지 채팅으로 알려주세요.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        status('interrupted')
        print('\n사용자가 중단했습니다. 보정 중 중단했다면 다시 보정을 완료한 뒤 텔레옵을 실행하세요.')
    except Exception as exc:
        status('failed', error=str(exc))
        print(f'\n오류: {exc}')
    finally:
        input('\n결과를 확인한 뒤 Enter를 누르면 종료합니다: ')
