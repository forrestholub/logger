"""Run a short, safe MediaTek modem capture using the production profile code."""

import argparse
import copy
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serial', help='ADB serial; defaults to the only connected device')
    parser.add_argument('--profile', help='Profile name; defaults to the first enabled MediaTek profile')
    parser.add_argument('--mask', type=int, help='Override the profile log-type bitmask for this test')
    parser.add_argument('--observe-seconds', type=int, default=20)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()

    devices = logger.list_devices()
    serial = args.serial or (devices[0] if len(devices) == 1 else '')
    if not serial or serial not in devices:
        raise SystemExit(f'Choose one connected device with --serial. Connected: {devices}')

    profiles = logger.load_modem_profiles(logger.MODEM_PROFILES_FILE)
    profile = next(
        (
            item for item in profiles
            if (not args.profile and item['chipset'] == 'Mediatek' and item.get('enabled', True))
            or (args.profile and item['name'] == args.profile)
        ),
        None,
    )
    if not profile:
        raise SystemExit(f'Profile not found: {args.profile or "enabled MediaTek profile"}')
    if profile['chipset'] != 'Mediatek':
        raise SystemExit('This live test only supports a MediaTek profile.')
    profile = copy.deepcopy(profile)
    if args.mask is not None:
        profile['log_type_mask'] = args.mask
    profile = logger.normalize_modem_profile(profile)

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output = args.output or (logger.ROOT / 'testing_results' / f'mtk_live_{stamp}_{serial}')
    output.mkdir(parents=True, exist_ok=True)

    harness = object.__new__(logger.LoggerGUI)
    harness.active_modem_profile = profile
    harness.active_modem_remote_path = ''
    harness.active_mtk_log_paths = {}
    harness.mtk_log_paths_before = {}
    harness.modem_capture_started = False
    harness.log = lambda message: print(message, flush=True)

    start_attempted = False
    readings = []
    try:
        start_attempted = True
        harness.start_modem_logging(serial)
        remote = harness.active_modem_remote_path
        if not remote:
            raise RuntimeError('Logger started but no MediaTek capture directory appeared.')
        for _ in range(3):
            result = logger.run_shell(serial, f'du -sk {remote} 2>/dev/null | head -n 1', timeout=15)
            text = (result.stdout or '').strip()
            size_kb = int(text.split()[0]) if text and text.split()[0].isdigit() else -1
            readings.append(size_kb)
            print(f'Capture size: {size_kb} KiB ({remote})', flush=True)
            if len(readings) < 3:
                time.sleep(max(1, args.observe_seconds // 2))
    finally:
        if start_attempted:
            try:
                harness.stop_modem_logging(serial)
            except Exception as exc:
                print(f'Cleanup stop failed: {exc}', flush=True)

    harness._pull_modem_logs(serial, output)
    traces = list((output / 'device_logs' / 'mdlog1').rglob('*.muxz'))
    metadata = json.loads((output / 'modem_profile_used.json').read_text(encoding='utf-8'))
    if not traces:
        raise SystemExit('Live test failed: no finalized .muxz file was pulled.')
    if readings[-1] <= readings[0]:
        raise SystemExit(f'Live test failed: modem capture did not grow: {readings}')
    expected_types = len(logger.mediatek_selected_log_sources(profile))
    if len(metadata.get('pulled_log_types', [])) != expected_types:
        raise SystemExit(
            'Live test failed: not every selected type was pulled: '
            f"{metadata.get('pulled_log_types')} / {metadata.get('missing_or_failed_log_types')}"
        )
    print(f'PASS: size grew {readings[0]} -> {readings[-1]} KiB; pulled {len(traces)} .muxz file(s).')
    print(f'Output: {output}')


if __name__ == '__main__':
    main()
