"""Native Windows entry point. Original Ubuntu files remain unchanged."""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "source" / "jaemin0319-so-arm101_ws-a21b2ad"
CONFIG = ROOT / "windows" / "config.json"
DLL_HANDLES = []


def environment():
    os.environ.pop("PYTHONPATH", None)
    os.environ["PYTHONUTF8"] = "1"
    os.environ["SO101_WS"] = str(WORKSPACE)
    os.environ["HF_LEROBOT_HOME"] = str(WORKSPACE / "data")
    # These are different arms until the user explicitly calibrates this PC.
    os.environ["HF_LEROBOT_CALIBRATION"] = str(ROOT / "windows" / "calibration")
    bins = [str(Path(sys.executable).parent)]
    for ffmpeg in (ROOT / ".runtime" / "ffmpeg").glob("**/ffmpeg.exe"):
        bins.append(str(ffmpeg.parent))
        DLL_HANDLES.append(os.add_dll_directory(str(ffmpeg.parent)))
    os.environ["PATH"] = os.pathsep.join(bins + [os.environ.get("PATH", "")])
    os.chdir(WORKSPACE)


def entry(name, args):
    matches = list(importlib.metadata.entry_points(group="console_scripts", name=name))
    if not matches:
        raise SystemExit(f"Command not installed: {name}")
    sys.argv = [name, *args]
    result = matches[0].load()()
    if isinstance(result, int):
        raise SystemExit(result)


def arm(config, side):
    port = config[f"{side}_port"]
    if not isinstance(port, str) or not re.fullmatch(r"COM[1-9][0-9]*", port, re.I):
        raise SystemExit(f"Set {side}_port to its actual COM port in {CONFIG}")
    prefix, kind = ("robot", "so101_follower") if side == "follower" else ("teleop", "so101_leader")
    return [f"--{prefix}.type={kind}", f"--{prefix}.port={port}",
            f"--{prefix}.id={config[f'{side}_id']}"]


def cameras(config, required=False):
    cams = config["cameras"]
    if required and not cams:
        raise SystemExit(f"Configure cameras in {CONFIG} first. See WINDOWS.md.")
    for name, cam in cams.items():
        if not isinstance(cam.get("index_or_path"), int):
            raise SystemExit(f"Camera {name}: index_or_path must be an integer on Windows.")
    return ["--robot.cameras=" + json.dumps(cams)] if cams else []


def help_text():
    print("""SO-ARM101 / Windows (PowerShell or cmd)
  .\\so-arm.cmd check                  Software and video decoder versions
  .\\so-arm.cmd ports                  List COM ports (no robot connection)
  .\\so-arm.cmd cameras --help         LeRobot camera discovery options
  .\\so-arm.cmd calibrate follower|leader
  .\\so-arm.cmd setup-motors follower|leader
  .\\so-arm.cmd teleop [--display] [LeRobot flags...]
  .\\so-arm.cmd save-home              Save current follower pose (read-only)
  .\\so-arm.cmd record [--return-home] [--display] [LeRobot flags...]
  .\\so-arm.cmd replay [LeRobot flags...]
  .\\so-arm.cmd train [LeRobot flags...]
  .\\so-arm.cmd rollout [LeRobot flags...]
  .\\so-arm.cmd hf auth login
  .\\so-arm.cmd cli lerobot-<command> [flags...]
  .\\so-arm.cmd python [Python arguments...]
Add --dry-run to a workflow to print the command without opening devices.
Edit windows/config.json for COM ports and camera indices.
Use native LeRobot flags (--dataset.repo_id=..., --policy.type=act, etc.).
Read WINDOWS.md for examples. Ubuntu .sh scripts are not Windows entry points.""")


def main():
    environment()
    config = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    argv = sys.argv[1:]
    if not argv or argv[0] in ("help", "--help", "-h"):
        help_text()
        return
    action, *args = argv
    dry = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    if action == "save-home":
        if args:
            raise SystemExit("Usage: so-arm.cmd save-home [--dry-run]")
        if dry:
            print(f"Read current follower pose on {config['follower_port']} into windows/home-pose.json")
        else:
            from home_pose import save_home
            save_home(config)
        return
    return_to_home = action == "record" and "--return-home" in args
    check_home = return_to_home and "--check" in args
    if return_to_home:
        args = [a for a in args if a not in ("--return-home", "--check")]
    if action == "check":
        import lerobot
        import torch
        import torchvision
        import av
        from torchcodec.decoders import VideoDecoder
        print(f"Python {sys.version.split()[0]} | LeRobot {lerobot.__version__}")
        print(f"torch {torch.__version__} | torchvision {torchvision.__version__}")
        print(f"CUDA: {torch.cuda.is_available()} | Intel XPU: {torch.xpu.is_available()}")
        print(f"PyAV {av.__version__} | TorchCodec VideoDecoder import OK")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise SystemExit("FFmpeg missing")
        subprocess.run([ffmpeg, "-version"], check=True)
        return
    if action == "ports":
        from serial.tools.list_ports import comports
        for port in sorted(comports()):
            print(f"{port.device}: {port.description} [{port.hwid}]")
        return
    if action == "python":
        raise SystemExit(subprocess.call([sys.executable, *args]))
    if action == "hf":
        entry("hf", args)
        return
    if action == "cli":
        if not args or not args[0].startswith("lerobot-"):
            raise SystemExit("Usage: so-arm.cmd cli lerobot-<command> [flags]")
        name, *args = args
    else:
        names = {"teleop": "teleoperate", "calibrate": "calibrate", "setup-motors": "setup-motors",
                 "record": "record", "replay": "replay", "train": "train",
                 "rollout": "rollout", "cameras": "find-cameras"}
        if action not in names:
            raise SystemExit(f"Unknown workflow: {action}. Run so-arm.cmd help")
        name = "lerobot-" + names[action]
        # Let upstream describe all supported native options, without needing devices configured.
        if "--help" not in args and "-h" not in args:
            defaults = []
            if action in ("calibrate", "setup-motors"):
                if not args or args[0] not in ("follower", "leader"):
                    raise SystemExit(f"Usage: so-arm.cmd {action} follower|leader")
                side, *args = args
                defaults += arm(config, side)
            elif action in ("teleop", "record", "replay", "rollout"):
                defaults += arm(config, "follower")
                if action in ("teleop", "record"):
                    if config["follower_port"].upper() == str(config["leader_port"]).upper():
                        raise SystemExit("Follower and leader must use different COM ports.")
                    defaults += arm(config, "leader")
                display = "--display" in args
                args = [a for a in args if a != "--display"]
                if action in ("record", "rollout") or display:
                    defaults += cameras(config, required=True)
                if display:
                    defaults += ["--display_data=true"]
                if action == "record":
                    defaults += ["--dataset.push_to_hub=false", "--dataset.no_stamp=true"]
                elif action == "rollout":
                    defaults += ["--device=cpu"]
            elif action == "train":
                defaults += ["--policy.type=act", "--policy.device=cpu", "--policy.push_to_hub=false",
                             "--num_workers=0"]
            # Explicit arguments override defaults without duplicate parser arguments.
            explicit = {arg.split("=", 1)[0] for arg in args if arg.startswith("--")}
            args = [a for a in defaults if a.split("=", 1)[0] not in explicit] + args
    if dry:
        print(subprocess.list2cmdline([name, *args]))
        if return_to_home:
            print("Enter/home mode: wait -> record -> save -> return home -> wait. Q/Esc exits.")
        return
    if return_to_home and "--help" not in args and "-h" not in args:
        from record_home import record
        record(args, check=check_home)
        return
    if action == "calibrate" and "--help" not in args and "-h" not in args:
        from calibration_session import calibrate
        calibrate(args)
        return
    entry(name, args)


if __name__ == "__main__":
    main()
