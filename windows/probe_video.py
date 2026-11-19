"""Camera/encoder diagnostics without connecting to either robot arm."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import time

import so_arm


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--backend', type=int)
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--codec', choices=['none', 'libsvtav1', 'h264'], default='none')
    parser.add_argument('--camera', choices=['front', 'wrist', 'both'], default='both')
    args = parser.parse_args()
    so_arm.environment()
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
    from lerobot.cameras.opencv.camera_opencv import OpenCVCamera
    import cv2
    settings = json.loads(so_arm.CONFIG.read_text(encoding='utf-8'))['cameras']
    out = so_arm.ROOT / 'windows/diagnostics' / datetime.now().strftime('video_%Y%m%d_%H%M%S')
    out.mkdir(parents=True)
    cameras = {}
    encoder = None
    stats = {'options': vars(args), 'cameras': {}, 'ticks': 0}
    try:
        for name, config in settings.items():
            if args.camera not in ('both', name):
                continue
            config = {key: value for key, value in config.items() if key != 'type'}
            config['fps'] = args.fps
            if args.backend is not None:
                config['backend'] = args.backend
            camera = OpenCVCamera(OpenCVCameraConfig(**config))
            cameras[name] = camera
            camera.connect()
            stats['cameras'][name] = {'unique_frames': 0, 'max_age_ms': 0, 'reported_fps': camera.videocapture.get(cv2.CAP_PROP_FPS)}
        if args.codec != 'none':
            from lerobot.configs.video import RGBEncoderConfig
            from lerobot.datasets.video_utils import StreamingVideoEncoder
            encoder = StreamingVideoEncoder(args.fps, rgb_encoder=RGBEncoderConfig(vcodec=args.codec, preset='ultrafast' if args.codec == 'h264' else 10), encoder_threads=2)
            encoder.start_episode(list(cameras), out)
        last = dict.fromkeys(cameras)
        start = time.perf_counter()
        while time.perf_counter() - start < args.seconds:
            tick = time.perf_counter()
            for name, camera in cameras.items():
                frame = camera.read_latest()
                with camera.frame_lock:
                    stamp = camera.latest_timestamp
                metrics = stats['cameras'][name]
                metrics['max_age_ms'] = max(metrics['max_age_ms'], round((time.perf_counter() - stamp) * 1000, 2))
                if stamp != last[name]:
                    metrics['unique_frames'] += 1
                    last[name] = stamp
                if encoder:
                    encoder.feed_frame(name, frame)
            stats['ticks'] += 1
            time.sleep(max(0, 1 / args.fps - (time.perf_counter() - tick)))
        stats['elapsed_s'] = round(time.perf_counter() - start, 3)
        if encoder:
            results = encoder.finish_episode()
            stats['videos'] = {name: str(data[0]) for name, data in results.items()}
            import av
            stats['decoded_frames'] = {}
            for name, (path, _) in results.items():
                with av.open(str(path)) as container:
                    stats['decoded_frames'][name] = sum(1 for _ in container.decode(video=0))
        stats['success'] = True
    except Exception as exc:
        stats['success'] = False
        stats['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if encoder:
            encoder.close()
        for camera in cameras.values():
            if camera.is_connected:
                camera.disconnect()
        (out / 'result.json').write_text(json.dumps(stats, indent=2), encoding='utf-8')
        print(json.dumps(stats, indent=2), flush=True)
    if not stats['success']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
