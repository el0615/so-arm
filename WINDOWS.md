# SO-ARM101 Windows 실행

PowerShell에서 이 폴더를 열고 실행합니다. Ubuntu/WSL은 사용하지 않습니다.

```powershell
.\so-arm.cmd help
.\so-arm.cmd check
```

Python과 패키지는 이 폴더의 `.venv`, `.runtime`에 설치됩니다. 시스템 PATH나 PowerShell 실행 정책을 바꿀 필요가 없습니다. 원본 저장소는 `source/jaemin0319-so-arm101_ws-a21b2ad`에 있습니다. LeRobot은 원본이 지정한 `d490e472a5d1a207cfe0255caaaf74b6d66e4656`의 소스입니다. 이 PC의 Intel Arc GPU에 대한 가속은 구성하지 않았으며 CPU를 기본으로 사용합니다. 학습은 느릴 수 있습니다.

## 장치 설정 (로봇을 사용할 때)

```powershell
.\so-arm.cmd ports
.\so-arm.cmd cameras --help
```

`windows/config.json`의 `follower_port`, `leader_port`를 실제 `COM3`, `COM4` 같은 값으로 설정합니다. 예시 번호를 그대로 사용하면 안 됩니다. `cameras`에는 확인한 카메라 번호만 추가합니다. 예:

```json
"cameras": {
  "front": {"type": "opencv", "index_or_path": 0, "width": 640, "height": 480, "fps": 30, "fourcc": "MJPG", "rotation": 180},
  "wrist": {"type": "opencv", "index_or_path": 1, "width": 640, "height": 480, "fps": 30, "fourcc": "MJPG", "rotation": 0}
}
```

카메라 0/1이 실제 front/wrist인지는 영상으로 확인해야 합니다. 원본의 Linux `/dev/...` 경로는 Windows에서 사용할 수 없습니다. 원본 작성자의 보정 파일 대신 이 PC에서 수행한 보정을 `windows/calibration`에 저장합니다.

```powershell
.\so-arm.cmd calibrate follower
.\so-arm.cmd calibrate leader
.\so-arm.cmd teleop --dry-run
.\so-arm.cmd teleop
.\so-arm.cmd teleop --display
```

보정·모터 설정·텔레옵·추론은 사용자가 실제 장치를 연결하고 위 명령을 실행할 때 시작됩니다. 텔레옵 종료 시 follower 토크가 꺼지므로 팔을 손으로 받칩니다. `setup-motors`는 새 팔이나 모터 교체 때만 사용합니다.

## 녹화·학습·추론

Windows 실행기는 LeRobot 원래 옵션을 받습니다. 원본 `.sh`의 `--name`, `--job` 같은 축약 옵션 대신 아래처럼 사용합니다. `YOUR_HF_USER`는 실제 Hugging Face 사용자 이름으로 바꿉니다.

```powershell
.\so-arm.cmd record --dataset.repo_id=YOUR_HF_USER/ball_v1 --dataset.single_task="Pick up the ball and place it in the bowl" --dataset.num_episodes=10
.\so-arm.cmd train --dataset.repo_id=YOUR_HF_USER/ball_v1 --output_dir=outputs/train/act_ball_v1 --job_name=act_ball_v1 --steps=100000 --batch_size=8
.\so-arm.cmd rollout --policy.path=outputs/train/act_ball_v1/checkpoints/last/pretrained_model --duration=60
.\so-arm.cmd hf auth login
```

녹화·학습은 기본으로 업로드하지 않습니다. 자세한 옵션은 각 명령 뒤에 `--help`를 붙입니다. `cli lerobot-명령`으로 나머지 LeRobot 도구도 실행할 수 있고, `python`으로 프로젝트 Python을 쓸 수 있습니다. 원본의 Linux 전용 `scripts/cameras.py` 대신 Windows용 `cameras` 명령을 사용합니다. 상대 경로의 기준은 원본 저장소 폴더입니다.

## Enter로 에피소드 저장 → 초기 자세 복귀 → 다음 녹화 대기

실행 중인 텔레옵/녹화를 먼저 종료하고 팔로워를 원하는 초기 자세에 놓은 다음, 움직이지 않게 받친 상태에서 저장합니다. 그리퍼 위치도 함께 저장됩니다. 이 명령은 위치만 읽으며 토크를 바꾸거나 팔을 움직이지 않습니다.

```powershell
.\so-arm.cmd save-home
```

`windows/home-pose.json`에 저장됩니다. 같은 명령을 다시 실행하면 초기 자세를 덮어씁니다. 팔 또는 보정을 바꾸면 다시 저장해야 합니다.

```powershell
.\so-arm.cmd record --return-home --display `
  --dataset.repo_id=local/enter_test `
  --dataset.single_task="Pick up the ball and place it in the bowl" `
  --dataset.fps=30 `
  --dataset.num_episodes=3 `
  --dataset.episode_time_s=3600 `
  --dataset.streaming_encoding=true `
  --dataset.encoder_threads=2 `
  --dataset.no_stamp=false `
  --dataset.push_to_hub=false
```

- 연결 후 `[WAIT]`에서 기다립니다. 리더를 팔로워와 비슷한 자세로 맞추고 **Enter**를 눌러 녹화를 시작합니다. 몸통 관절 차이 5도, 그리퍼 차이 8%를 넘으면 시작하지 않고 차이를 표시합니다.
- `[RECORDING]`에서 **Enter**를 누르면 현재 에피소드를 저장하고 초기 자세로 천천히 복귀합니다. 복귀와 대기 중에는 리더를 따라가지 않으며, 이 구간은 데이터셋에 포함하지 않습니다.
- `[HOME]` 이후 다시 `[WAIT]`가 나오면 리더 자세를 맞추고 **Enter**를 눌러 다음 에피소드를 시작합니다. 대기 시간은 무제한이며 `reset_time_s`는 사용하지 않습니다.
- 지정한 에피소드를 모두 수집하면 초기 자세를 유지합니다. **팔을 받친 뒤 Q/Esc**로 토크를 해제하고 종료합니다. 녹화 중 Q/Esc는 현재 에피소드를 저장하고 복귀 없이 종료합니다. 복귀 중 Q/Esc는 복귀를 중단하고 종료합니다.
- Ctrl+C 또는 카메라/통신 오류 시에는 자동 복귀하지 않습니다. 종료할 때 토크가 해제되므로 팔을 받쳐주세요.

키 입력은 Windows 전체에서 감지되므로 수집 중에는 VS Code 터미널 또는 디스플레이 창을 사용하세요. Enter를 길게 누르거나 복귀 중 미리 눌러도 다음 녹화가 자동 시작되지 않습니다. 대기 중 디스플레이는 마지막 녹화 프레임에 머뭅니다.

복귀는 관절별 보간으로 약 16도/초 이하의 목표 속도로 움직입니다. 장애물 회피 기능은 없으므로 초기 자세까지의 경로를 비워두세요. 모터가 목표를 따라가지 못하거나 시간 제한을 넘으면 중단합니다. 위 예제는 Enter 대신 1시간이 지나도 에피소드를 저장하고 복귀합니다.

실행 전 구성 확인에는 같은 명령 뒤에 `--check`를 붙입니다(장치를 열지 않음). `--dry-run`은 실행할 명령만 표시합니다. `--return-home`을 빼면 기존 녹화 동작을 사용합니다.

장치 없이 기능을 검증하는 테스트:

```powershell
.\.venv\Scripts\python.exe -X utf8 windows\test_record_home.py
.\.venv\Scripts\python.exe -X utf8 windows\test_record_home_api.py
```

## 설치 범위

설치 확인은 패키지 import와 CLI 도움말까지만 수행합니다. 장치 연결, 보정, 데이터 다운로드, 학습 및 실제 추론은 별도 작업입니다. Windows가 지원하지 않는 Linux 전용 의존성(evdev, python-xlib, uvloop)은 설치 대상에 포함되지 않습니다. 원본 패키지 버전 제약은 유지합니다.
