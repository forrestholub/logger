import os
import subprocess
import sys
import threading
import time
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Optional, List, Tuple
import json
import copy
from datetime import datetime
from dataclasses import dataclass

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
except Exception as e:
    print("Tkinter not available:", e)
    sys.exit(1)

ROOT = Path(__file__).parent
ADB_PATHS = [
    str(ROOT / 'Cmdlets' / 'iperf_installer' / 'programs' / 'adb.exe'),
    'adb',
]

def which_adb():
    for p in ADB_PATHS:
        try:
            out = subprocess.run([p, 'version'], capture_output=True, text=True)
            if out.returncode == 0:
                return p
        except Exception:
            pass
    return 'adb'

ADB = which_adb()

LOG_TIMESTAMP_FORMAT = '%Y-%d-%m_%H-%M-%S'
AP_LOGS_DIRNAME = 'AP_Logs'

MODEM_PROFILES_VERSION = 1
MODEM_PROFILES_FILE = ROOT / 'modem_logging_profiles.json'
MTK_LOG_RECEIVER = 'com.debug.loggerui/.framework.LogReceiver'
MTK_ADB_ACTION = 'com.debug.loggerui.ADB_CMD'
SAMSUNG_SILENTLOG_PACKAGE = 'com.sec.modem.settings'
SAMSUNG_SILENTLOG_RECEIVER = (
    'com.sec.modem.settings/.cplogging.SilentLogReceiver'
)
SAMSUNG_SILENTLOG_ACTION_PREFIX = 'com.sec.modem.settings.cplogging.SilentLog'
SAMSUNG_SILENTLOG_STATE_PROPERTY = 'dev.silentlog.on'
SAMSUNG_SILENTLOG_CP_ROOT = '/sdcard/log/cp'
SAMSUNG_SILENTLOG_AP_ROOT = '/sdcard/log/ap_silentlog'
MTK_MODE_VALUES = {'USB': 1, 'SD': 2, 'PLS': 3}
MTK_MODE_LABELS = {
    '1: USB (stream to host tooling)': 'USB',
    '2: SD (record on device)': 'SD',
    '3: PLS (passive log to storage)': 'PLS',
}
MTK_MODEM_TYPE_LABELS = {
    '1: MD1 (primary cellular modem)': 1,
    '3: MD3 (secondary/legacy modem, if present)': 3,
}
MTK_LOG_TYPE_BITS = {
    1: 'Mobile/AP log',
    2: 'Modem log',
    4: 'Network log',
    16: 'GPS host log',
    32: 'Connsys firmware log',
    64: 'Bluetooth HCI host log',
}
MTK_ALL_LOG_TYPE_MASK = sum(MTK_LOG_TYPE_BITS)
MTK_LOG_TYPE_SOURCE_SPECS = {
    1: {
        'key': 'mobile', 'output': 'mobilelog',
        'root': '/data/debuglogger/mobilelog', 'pattern': 'APLog*',
    },
    2: {
        'key': 'modem', 'output': 'mdlog1',
        'root': None, 'pattern': 'MDLog*',
    },
    4: {
        'key': 'network', 'output': 'netlog',
        'root': '/data/debuglogger/netlog', 'pattern': 'NTLog*',
    },
    16: {
        'key': 'gps_host', 'output': 'connsyslog/gpshost',
        'root': '/data/debuglogger/connsyslog/gpshost', 'pattern': 'CSLog*',
    },
    32: {
        'key': 'connsys_fw', 'output': 'connsyslog/fw',
        'root': '/data/debuglogger/connsyslog/fw', 'pattern': 'CsLog*',
    },
    64: {
        'key': 'bluetooth_hci', 'output': 'connsyslog/bthci',
        'root': '/data/debuglogger/connsyslog/bthci', 'pattern': 'CsLog*',
    },
}

DEFAULT_MODEM_PROFILES = [
    {
        'name': 'MediaTek On-device 600 MB',
        'chipset': 'Mediatek',
        'enabled': True,
        'mode': 'SD',
        'modem_type': 1,
        'log_type_mask': 2,
        'max_log_size_mb': 600,
        'storage': 'internal_sd',
        'auto_start_on_boot': False,
        'auto_reset_on_exception': True,
        'show_notification': True,
        'taglog_enabled': False,
        'device_log_root': '/data/debuglogger/mdlog1',
        'start_timeout_seconds': 30,
        'stop_timeout_seconds': 30,
        'finalize_wait_seconds': 3,
    },
    {
        'name': 'Samsung Qualcomm SilentLog (device default)',
        'chipset': 'Qualcomm',
        'enabled': True,
        'mode': 'SD',
        'modem_type': 1,
        'log_type_mask': 2,
        'max_log_size_mb': 1024,
        'storage': 'internal_sd',
        'auto_start_on_boot': False,
        'auto_reset_on_exception': False,
        'show_notification': True,
        'taglog_enabled': False,
        'device_log_root': SAMSUNG_SILENTLOG_CP_ROOT,
        'silentlog_profile': 'default',
        'start_timeout_seconds': 45,
        'stop_timeout_seconds': 45,
        'finalize_wait_seconds': 5,
    },
]


def normalize_modem_profile(profile: dict) -> dict:
    """Validate and normalize one JSON modem profile."""
    if not isinstance(profile, dict):
        raise ValueError('Each modem profile must be a JSON object.')
    result = copy.deepcopy(DEFAULT_MODEM_PROFILES[0])
    result.update(profile)
    result['name'] = str(result.get('name', '')).strip()
    result['chipset'] = str(result.get('chipset', '')).strip()
    result['mode'] = str(result.get('mode', '')).strip().upper()
    result['storage'] = str(result.get('storage', '')).strip().lower()
    result['device_log_root'] = str(result.get('device_log_root', '')).strip().rstrip('/')
    result['silentlog_profile'] = str(result.get('silentlog_profile', 'default')).strip()
    if not result['name']:
        raise ValueError('Profile name cannot be empty.')
    if result['chipset'] not in ('Mediatek', 'Qualcomm', 'Exynos'):
        raise ValueError(f"Unsupported chipset in profile {result['name']!r}: {result['chipset']!r}")
    if result['chipset'] == 'Mediatek' and result['mode'] not in MTK_MODE_VALUES:
        raise ValueError('MediaTek mode must be USB, SD, or PLS.')
    if result['storage'] not in ('internal_sd', 'external_sd'):
        raise ValueError('MediaTek storage must be internal_sd or external_sd.')
    if not result['device_log_root'].startswith('/'):
        raise ValueError('Device log root must be an absolute Android path.')
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', result['device_log_root']):
        raise ValueError('Device log root contains unsupported shell characters.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', result['silentlog_profile']):
        raise ValueError('SilentLog profile contains unsupported characters.')
    if result['chipset'] == 'Qualcomm' and result['device_log_root'] != SAMSUNG_SILENTLOG_CP_ROOT:
        raise ValueError(
            f'Samsung Qualcomm SilentLog writes to {SAMSUNG_SILENTLOG_CP_ROOT}; '
            'the device log root must match it.'
        )
    for key, minimum, maximum in (
        ('modem_type', 1, 3),
        ('log_type_mask', 1, MTK_ALL_LOG_TYPE_MASK),
        ('max_log_size_mb', 1, 100000),
        ('start_timeout_seconds', 1, 300),
        ('stop_timeout_seconds', 1, 300),
        ('finalize_wait_seconds', 0, 120),
    ):
        try:
            result[key] = int(result[key])
        except (TypeError, ValueError):
            raise ValueError(f'{key} must be a whole number.') from None
        if not minimum <= result[key] <= maximum:
            raise ValueError(f'{key} must be between {minimum} and {maximum}.')
    unknown_log_bits = result['log_type_mask'] & ~MTK_ALL_LOG_TYPE_MASK
    if result['modem_type'] not in MTK_MODEM_TYPE_LABELS.values():
        raise ValueError('modem_type must be 1 (MD1) or 3 (MD3).')
    if unknown_log_bits:
        raise ValueError(
            f'log_type_mask contains unsupported bit(s): {unknown_log_bits}. '
            f'Supported bits are {list(MTK_LOG_TYPE_BITS)}.'
        )
    if result['chipset'] == 'Mediatek' and not (result['log_type_mask'] & 2):
        raise ValueError('A modem logging profile must include bit 2 (Modem log).')
    for key in (
        'enabled', 'auto_start_on_boot', 'auto_reset_on_exception',
        'show_notification', 'taglog_enabled',
    ):
        result[key] = bool(result.get(key))
    return result


def save_modem_profiles(path: Path, profiles: List[dict]) -> None:
    """Atomically save validated modem profiles to JSON."""
    normalized = [normalize_modem_profile(item) for item in profiles]
    names = [item['name'].casefold() for item in normalized]
    if len(names) != len(set(names)):
        raise ValueError('Modem profile names must be unique.')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'version': MODEM_PROFILES_VERSION,
        'log_type_bits': {str(bit): meaning for bit, meaning in MTK_LOG_TYPE_BITS.items()},
        'profiles': normalized,
    }
    temp_path = path.with_suffix(path.suffix + '.tmp')
    with open(temp_path, 'w', encoding='utf-8') as config_file:
        json.dump(payload, config_file, indent=2)
        config_file.write('\n')
    os.replace(temp_path, path)


def load_modem_profiles(path: Path) -> List[dict]:
    """Load modem profiles, creating a safe MediaTek default when absent."""
    path = Path(path)
    if not path.exists():
        defaults = copy.deepcopy(DEFAULT_MODEM_PROFILES)
        save_modem_profiles(path, defaults)
        return defaults
    with open(path, 'r', encoding='utf-8') as config_file:
        payload = json.load(config_file)
    if not isinstance(payload, dict) or payload.get('version') != MODEM_PROFILES_VERSION:
        raise ValueError(f'Unsupported modem profile file version in {path}.')
    profiles = payload.get('profiles')
    if not isinstance(profiles, list):
        raise ValueError('The modem profile file must contain a profiles list.')
    normalized = [normalize_modem_profile(item) for item in profiles]
    names = [item['name'].casefold() for item in normalized]
    if len(names) != len(set(names)):
        raise ValueError('Modem profile names must be unique.')
    return normalized


def profiles_for_chipset(profiles: List[dict], chipset: str) -> List[dict]:
    selected = (chipset or '').strip().casefold()
    return [
        item for item in profiles
        if item.get('enabled', True) and str(item.get('chipset', '')).casefold() == selected
    ]


def mediatek_selected_log_sources(profile: dict) -> List[dict]:
    """Return ordered source descriptors for every selected MediaTek log bit."""
    profile = normalize_modem_profile(profile)
    sources = []
    for bit, spec in MTK_LOG_TYPE_SOURCE_SPECS.items():
        if not profile['log_type_mask'] & bit:
            continue
        item = dict(spec)
        item['bit'] = bit
        item['meaning'] = MTK_LOG_TYPE_BITS[bit]
        if bit == 2:
            item['root'] = profile['device_log_root']
        sources.append(item)
    return sources


def _mtk_broadcast(command_name: str, target, target_type: str = '--ei') -> List[str]:
    return [
        'shell', 'am', 'broadcast', '-a', MTK_ADB_ACTION,
        '-e', 'cmd_name', str(command_name), target_type, 'cmd_target', str(target),
        '-n', MTK_LOG_RECEIVER,
    ]


def mediatek_profile_setup_commands(profile: dict) -> List[List[str]]:
    """Return DebugLoggerUI configuration commands for a MediaTek profile."""
    profile = normalize_modem_profile(profile)
    if profile['chipset'] != 'Mediatek':
        raise ValueError('MediaTek commands require a Mediatek profile.')
    mode_value = MTK_MODE_VALUES[profile['mode']]
    return [
        _mtk_broadcast('switch_logpath', profile['storage'], target_type='-e'),
        _mtk_broadcast(f'switch_modem_log_mode_{mode_value}', profile['modem_type']),
        _mtk_broadcast(f"set_log_size_{profile['max_log_size_mb']}", 2),
        _mtk_broadcast(f"set_auto_start_{int(profile['auto_start_on_boot'])}", 2),
        _mtk_broadcast(f"modem_auto_reset_{int(profile['auto_reset_on_exception'])}", 2),
        _mtk_broadcast(f"show_notification_{int(profile['show_notification'])}", -1),
        _mtk_broadcast('switch_taglog', int(profile['taglog_enabled'])),
    ]


def mediatek_start_command(log_type_mask: int = 2) -> List[str]:
    return _mtk_broadcast('start', int(log_type_mask))


def mediatek_stop_command(log_type_mask: int = 2) -> List[str]:
    return _mtk_broadcast('stop', int(log_type_mask))


def mediatek_restart_command(log_type_mask: int = 2) -> List[str]:
    return _mtk_broadcast('restart', int(log_type_mask))


def samsung_silentlog_command(action: str, profile: str = 'default') -> List[str]:
    """Build a non-blocking explicit broadcast to Samsung's SilentLog receiver."""
    normalized_action = str(action).strip().upper()
    if normalized_action not in ('START', 'STOP'):
        raise ValueError('Samsung SilentLog action must be START or STOP.')
    profile = str(profile).strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', profile):
        raise ValueError('Samsung SilentLog profile contains unsupported characters.')
    broadcast_action = f'{SAMSUNG_SILENTLOG_ACTION_PREFIX}.SILENT_LOG_{normalized_action}'
    # Samsung's receiver can keep `am broadcast` attached while its privileged service
    # initializes DIAG. Run it device-side in the background and verify the real state
    # through dev.silentlog.on instead of treating broadcast completion as readiness.
    remote_command = (
        f'am broadcast --user 0 -a {broadcast_action} '
        f'-n {SAMSUNG_SILENTLOG_RECEIVER} --es profile {profile} '
        '>/dev/null 2>&1 &'
    )
    return ['shell', 'sh', '-c', remote_command]

VIDEO_QUALITY_DEVICE_DEFAULT = 'Device default'
VIDEO_QUALITY_PRESETS = {
    VIDEO_QUALITY_DEVICE_DEFAULT: None,
    'Low (2 Mbps, ~4 MB/15s)': 2_000_000,
    'Medium (4 Mbps, ~8 MB/15s)': 4_000_000,
    'High (8 Mbps, ~15 MB/15s)': 8_000_000,
}


def format_log_timestamp(moment: Optional[datetime] = None) -> str:
    """Return the timestamp used by session folders and recording files."""
    return (moment or datetime.now()).strftime(LOG_TIMESTAMP_FORMAT)


def build_session_folder_name(timestamp: str, test_name: str, serial: str) -> str:
    """Build a session folder name in timestamp_testcase_serial order."""
    testcase = test_name.strip() or 'UnnamedTest'
    return f'{timestamp}_{testcase}_{serial}'


def build_segment_filename(timestamp: str, segment_num: int) -> str:
    return f'{timestamp}_screenRecord_{int(segment_num)}.mp4'


def video_quality_bitrate(quality: str) -> Optional[int]:
    """Return the Android screenrecord bitrate for a UI quality preset."""
    return VIDEO_QUALITY_PRESETS.get(quality)


def screenrecord_bitrate_args(quality: str, capabilities: dict) -> List[str]:
    """Build bitrate arguments only when the connected recorder advertises support."""
    bitrate = video_quality_bitrate(quality)
    bitrate_flag = capabilities.get('bitrate_flag')
    if bitrate is None or not bitrate_flag:
        return []
    return [bitrate_flag, str(bitrate)]


def take_device_screenshot(serial: str, out_dir: Path, prefix: str = 'screenshot') -> Path:
    """Capture a device screenshot to a unique, verified PNG file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp_ms = int(time.time() * 1000)
    screenshot_path = out_dir / f'{prefix}_{timestamp_ms}.png'
    while screenshot_path.exists():
        timestamp_ms += 1
        screenshot_path = out_dir / f'{prefix}_{timestamp_ms}.png'

    try:
        with open(screenshot_path, 'wb') as screenshot:
            result = subprocess.run(
                [ADB, '-s', serial, 'exec-out', 'screencap', '-p'],
                stdout=screenshot,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        if result.returncode != 0:
            detail = (result.stderr or b'').decode(errors='replace').strip()
            raise RuntimeError(detail or f'adb screencap exited with code {result.returncode}')
        with open(screenshot_path, 'rb') as screenshot:
            if screenshot.read(8) != b'\x89PNG\r\n\x1a\n':
                raise RuntimeError('adb screencap did not return a valid PNG image')
        return screenshot_path
    except Exception:
        try:
            screenshot_path.unlink()
        except FileNotFoundError:
            pass
        raise

def run(cmd, timeout=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def run_shell(serial: str, command: str, timeout=None):
    """Run one complete remote shell command (compatible with older bundled ADBs)."""
    return run([ADB, '-s', serial, 'shell', command], timeout=timeout)


def list_devices():
    res = run([ADB, 'devices'])
    lines = res.stdout.strip().splitlines()[1:]
    devices = []
    for line in lines:
        parts = line.split('\t')
        if len(parts) == 2 and parts[1] == 'device':
            devices.append(parts[0])
    return devices


def parse_android_properties(output: str) -> dict:
    """Parse Android's ``getprop`` output into a plain property dictionary."""
    properties = {}
    for line in (output or '').splitlines():
        match = re.fullmatch(r'\[([^]]+)\]: \[(.*)\]', line.strip())
        if match:
            properties[match.group(1)] = match.group(2)
    return properties


def detect_modem_chipset(properties: dict) -> str:
    """Return the GUI chipset label inferred from stable Android properties."""
    props = {str(key): str(value).strip().lower() for key, value in properties.items()}
    soc_manufacturer = props.get('ro.soc.manufacturer', '')
    soc_model = props.get('ro.soc.model', '')
    board = props.get('ro.board.platform', '')
    hardware = ' '.join((
        props.get('ro.hardware', ''),
        props.get('ro.boot.hardware', ''),
        props.get('ro.hardware.chipname', ''),
    ))
    mediatek = ' '.join((
        props.get('ro.vendor.mediatek.platform', ''),
        props.get('ro.mediatek.version.release', ''),
        props.get('ro.mediatek.chip_ver', ''),
    ))

    if (
        'mediatek' in soc_manufacturer
        or board.startswith(('mt', 'mediatek'))
        or any(token in hardware for token in ('mediatek', ' mt'))
        or mediatek.strip()
    ):
        return 'Mediatek'
    if (
        any(token in soc_manufacturer for token in ('qti', 'qualcomm'))
        or 'qcom' in board
        or 'qcom' in hardware
        or 'snapdragon' in soc_model
    ):
        return 'Qualcomm'
    if (
        'exynos' in board
        or 'exynos' in soc_model
        or soc_model.startswith('s5e')
        or ('samsung' in soc_manufacturer and 'qcom' not in hardware)
    ):
        return 'Exynos'
    return 'Auto/Unknown'


def detect_device_modem_chipset(serial: str) -> str:
    """Read one getprop snapshot and infer the device modem chipset."""
    try:
        result = run([ADB, '-s', serial, 'shell', 'getprop'], timeout=10)
    except Exception:
        return 'Auto/Unknown'
    if result.returncode != 0:
        return 'Auto/Unknown'
    return detect_modem_chipset(parse_android_properties(result.stdout or ''))


def ensure_tmp(serial: str):
    run([ADB, '-s', serial, 'shell', 'mkdir', '-p', '/data/local/tmp'])


def _try_adb_root(serial: str):
    """Use root adbd when the build supports it, and wait through its restart."""
    try:
        result = run([ADB, '-s', serial, 'root'], timeout=10)
        output = ((result.stdout or '') + (result.stderr or '')).lower()
        if 'restarting adbd' in output or 'already running as root' in output:
            run([ADB, '-s', serial, 'wait-for-device'], timeout=15)
        return result
    except Exception:
        return None


def _privileged_command(command: str, privilege: str) -> str:
    if privilege == 'su':
        return f"su -c '{command}'"
    return command


def _remote_process_alive(serial: str, pid: int, privilege: str = 'shell') -> bool:
    try:
        command = _privileged_command(f'kill -0 {int(pid)} 2>/dev/null', privilege)
        result = run_shell(serial, command, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def _remote_signal(serial: str, pid: int, signal: int, privilege: str = 'shell'):
    command = _privileged_command(f'kill -{int(signal)} {int(pid)}', privilege)
    return run_shell(serial, command, timeout=5)


def _device_has_root_su(serial: str) -> bool:
    try:
        result = run_shell(serial, "su -c 'id'", timeout=5)
        output = (result.stdout or '') + (result.stderr or '')
        return result.returncode == 0 and 'uid=0(' in output
    except Exception:
        return False


def _remote_text(serial: str, path: str) -> str:
    try:
        result = run_shell(serial, f'cat {path} 2>/dev/null', timeout=5)
        return (result.stdout or '').strip()
    except Exception:
        return ''


def push_tcpdump_if_needed(serial: str, tcpdump_path: Path):
    """Return a verified device tcpdump, pushing the host binary only if needed."""
    chk = run_shell(serial, 'command -v tcpdump 2>/dev/null || which tcpdump 2>/dev/null', timeout=5)
    candidates = [line.strip() for line in (chk.stdout or '').splitlines() if line.strip().startswith('/')]
    if candidates:
        remote = candidates[0]
        verify = run([ADB, '-s', serial, 'shell', remote, '--version'], timeout=5)
        if verify.returncode == 0:
            return remote

    if _device_has_root_su(serial):
        chk = run_shell(
            serial,
            "su -c 'command -v tcpdump 2>/dev/null || which tcpdump 2>/dev/null'",
            timeout=5,
        )
        candidates = [line.strip() for line in (chk.stdout or '').splitlines() if line.strip().startswith('/')]
        if candidates:
            remote = candidates[0]
            verify = run_shell(serial, f"su -c '{remote} --version'", timeout=5)
            if verify.returncode == 0:
                return remote

    if not tcpdump_path.is_file():
        raise RuntimeError(f'tcpdump binary not found: {tcpdump_path}')
    ensure_tmp(serial)
    remote = '/data/local/tmp/logger_tcpdump'
    pushed = run([ADB, '-s', serial, 'push', str(tcpdump_path), remote], timeout=30)
    if pushed.returncode != 0:
        raise RuntimeError(f'adb push tcpdump failed: {(pushed.stderr or pushed.stdout or "").strip()}')
    chmod = run([ADB, '-s', serial, 'shell', 'chmod', '0755', remote], timeout=5)
    if chmod.returncode != 0:
        raise RuntimeError(f'could not make tcpdump executable: {(chmod.stderr or chmod.stdout or "").strip()}')
    verify = run([ADB, '-s', serial, 'shell', remote, '--version'], timeout=5)
    if verify.returncode != 0:
        detail = (verify.stderr or verify.stdout or '').strip()
        raise RuntimeError(
            f'pushed tcpdump cannot run on this device ({detail or "CPU/ABI mismatch"}). '
            'Install a tcpdump binary matching the device ABI.'
        )
    return remote


@dataclass
class RemoteTcpdumpProcess:
    serial: str
    remote_pid: int
    remote_pcap: str
    remote_error: str
    local_pcap: str
    privilege: str = 'shell'
    stopped: bool = False

    # Keep the small subprocess-like surface used by the existing GUI.
    def poll(self):
        if self.stopped:
            return 0
        return None if _remote_process_alive(self.serial, self.remote_pid, self.privilege) else 1

    def terminate(self):
        self.stopped = True

    def wait(self, timeout=None):
        self.stopped = True
        return 0

    def kill(self):
        self.stopped = True


def _valid_pcap(path: Path) -> bool:
    try:
        if path.stat().st_size < 24:
            return False
        with open(path, 'rb') as capture:
            magic = capture.read(4)
        return magic in {
            b'\xd4\xc3\xb2\xa1', b'\xa1\xb2\xc3\xd4',
            b'\x4d\x3c\xb2\xa1', b'\xa1\xb2\x3c\x4d',
            b'\x0a\x0d\x0d\x0a',
        }
    except OSError:
        return False


def start_logcat_streams(serial: str, out_dir: Path):
    ap_logs_dir = out_dir / AP_LOGS_DIRNAME
    ap_logs_dir.mkdir(parents=True, exist_ok=True)
    # Start six parallel logcat streams similar to Cmdlets\logging_all.bat
    specs = [
        ('radio', 'logradio.txt'),
        ('main', 'logmain.txt'),
        ('kernel', 'logkernel.txt'),
        ('events', 'logevents.txt'),
        ('system', 'logsystem.txt'),
        ('all', 'logall.txt'),
    ]
    procs = {}
    files = {}
    for buffer_name, filename in specs:
        logfile = ap_logs_dir / filename
        f = open(logfile, 'a', encoding='utf-8', errors='ignore')
        # -v threadtime per requirement
        proc = subprocess.Popen([ADB, '-s', serial, 'logcat', '-b', buffer_name, '-v', 'threadtime'], stdout=f, stderr=subprocess.STDOUT)
        procs[buffer_name] = proc
        files[buffer_name] = f
    return procs, files


def start_tcpdump(serial: str, out_dir: Path, tcpdump_local: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    pcap = out_dir / f'capture_{int(time.time())}.pcap'
    _try_adb_root(serial)
    remote = push_tcpdump_if_needed(serial, tcpdump_local)
    stamp = f'{int(time.time() * 1000)}_{os.getpid()}'
    remote_pcap = f'/data/local/tmp/logger_tcpdump_{stamp}.pcap'
    remote_error = f'/data/local/tmp/logger_tcpdump_{stamp}.err'
    capture_cmd = (
        f'rm -f {remote_pcap} {remote_error}; '
        f'{remote} -i any -s 0 -U -w {remote_pcap} '
        f'>/dev/null 2>{remote_error} </dev/null & echo $!'
    )
    modes = ['shell']
    if _device_has_root_su(serial):
        modes.append('su')
    failures = []

    for privilege in modes:
        start_cmd = _privileged_command(capture_cmd, privilege)
        try:
            pid_res = run_shell(serial, start_cmd, timeout=10)
        except subprocess.TimeoutExpired:
            failures.append(f'{privilege}: startup timed out')
            continue
        pid_text = (pid_res.stdout or '').strip()
        if pid_res.returncode != 0 or not pid_text.isdigit():
            detail = (pid_res.stderr or pid_res.stdout or '').strip()
            failures.append(f'{privilege}: {detail or "no device PID returned"}')
            continue

        remote_pid = int(pid_text)
        deadline = time.time() + 3.0
        failure = ''
        while time.time() < deadline:
            if not _remote_process_alive(serial, remote_pid, privilege):
                failure = _remote_text(serial, remote_error) or 'unknown device error'
                break
            size = run([ADB, '-s', serial, 'shell', 'stat', '-c', '%s', remote_pcap], timeout=5)
            if (size.stdout or '').strip().isdigit() and int(size.stdout.strip()) >= 24:
                return RemoteTcpdumpProcess(
                    serial=serial,
                    remote_pid=remote_pid,
                    remote_pcap=remote_pcap,
                    remote_error=remote_error,
                    local_pcap=str(pcap),
                    privilege=privilege,
                ), pcap
            time.sleep(0.2)
        if not failure:
            failure = _remote_text(serial, remote_error) or 'no pcap header written'
        failures.append(f'{privilege}: {failure}')
        if _remote_process_alive(serial, remote_pid, privilege):
            _remote_signal(serial, remote_pid, 2, privilege)
        run([ADB, '-s', serial, 'shell', 'rm', '-f', remote_pcap, remote_error])

    detail = '; '.join(failures)
    if 'permission denied' in detail.lower() or "don't have permission" in detail.lower():
        build_type = run([ADB, '-s', serial, 'shell', 'getprop', 'ro.build.type']).stdout.strip()
        debuggable = run([ADB, '-s', serial, 'shell', 'getprop', 'ro.debuggable']).stdout.strip()
        raise RuntimeError(
            'Packet capture is blocked by the device: tcpdump requires root or '
            'CAP_NET_RAW/CAP_NET_ADMIN, but adb shell has neither and no root su is available. '
            f'Android build={build_type or "unknown"}, ro.debuggable={debuggable or "unknown"}. '
            'Use a rooted/userdebug device or a VPN-based packet-capture app. '
            f'Device response: {detail}'
        )
    raise RuntimeError(f'tcpdump failed to start: {detail or "unknown device error"}')


class ModemProfileSettingsWindow(tk.Toplevel):
    """JSON-backed editor for modem logging profiles."""

    def __init__(self, parent, profiles_file: Path, on_saved):
        super().__init__(parent)
        self.title('Modem Logging Settings')
        self.geometry('820x610')
        self.minsize(760, 560)
        self.transient(parent)
        self.profiles_file = Path(profiles_file)
        self.on_saved = on_saved
        self.profiles = load_modem_profiles(self.profiles_file)
        self.editing_index = None

        self.name_var = tk.StringVar()
        self.chipset_var = tk.StringVar(value='Mediatek')
        self.enabled_var = tk.BooleanVar(value=True)
        self.mode_var = tk.StringVar(value='2: SD (record on device)')
        self.modem_type_var = tk.StringVar(value='1: MD1 (primary cellular modem)')
        self.log_type_vars = {
            bit: tk.BooleanVar(value=(bit == 2)) for bit in MTK_LOG_TYPE_BITS
        }
        self.bitmask_summary_var = tk.StringVar()
        self.max_size_var = tk.IntVar(value=600)
        self.storage_var = tk.StringVar(value='internal_sd')
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_reset_var = tk.BooleanVar(value=True)
        self.notification_var = tk.BooleanVar(value=True)
        self.taglog_var = tk.BooleanVar(value=False)
        self.device_root_var = tk.StringVar(value='/data/debuglogger/mdlog1')
        self.start_timeout_var = tk.IntVar(value=30)
        self.stop_timeout_var = tk.IntVar(value=30)
        self.finalize_wait_var = tk.IntVar(value=3)

        self._create_widgets()
        self._refresh_list()
        if self.profiles:
            self.profile_list.selection_set(0)
            self._load_selected()

    def _create_widgets(self):
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=1)

        ttk.Label(outer, text='Profiles are saved to:').grid(row=0, column=0, sticky='w')
        ttk.Label(outer, text=str(self.profiles_file)).grid(row=0, column=1, sticky='w', padx=(8, 0))

        left = ttk.Frame(outer)
        left.grid(row=1, column=0, sticky='nsw', pady=(10, 0), padx=(0, 12))
        self.profile_list = tk.Listbox(left, width=30, exportselection=False)
        self.profile_list.pack(fill='both', expand=True)
        self.profile_list.bind('<<ListboxSelect>>', lambda _event: self._load_selected())
        list_buttons = ttk.Frame(left)
        list_buttons.pack(fill='x', pady=(6, 0))
        ttk.Button(list_buttons, text='New', command=self._new_profile).pack(side='left', padx=(0, 4))
        ttk.Button(list_buttons, text='Duplicate', command=self._duplicate_profile).pack(side='left', padx=4)
        ttk.Button(list_buttons, text='Delete', command=self._delete_profile).pack(side='left', padx=4)

        form = ttk.LabelFrame(outer, text='Profile', padding=10)
        form.grid(row=1, column=1, sticky='nsew', pady=(10, 0))
        form.columnconfigure(1, weight=1)
        row = 0

        def add_row(label, widget):
            nonlocal row
            ttk.Label(form, text=label).grid(row=row, column=0, sticky='w', pady=3, padx=(0, 8))
            widget.grid(row=row, column=1, sticky='ew', pady=3)
            row += 1

        add_row('Profile name:', ttk.Entry(form, textvariable=self.name_var))
        add_row('Chipset:', ttk.Combobox(
            form, textvariable=self.chipset_var, values=['Mediatek', 'Qualcomm'], state='readonly'
        ))
        add_row('Modem logging mode:', ttk.Combobox(
            form, textvariable=self.mode_var, values=list(MTK_MODE_LABELS), state='readonly'
        ))
        add_row('Modem type:', ttk.Combobox(
            form, textvariable=self.modem_type_var, values=list(MTK_MODEM_TYPE_LABELS), state='readonly'
        ))

        log_types = ttk.LabelFrame(form, text='Log types (add values to form the bitmask)', padding=6)
        log_types.grid(row=row, column=0, columnspan=2, sticky='ew', pady=(7, 4))
        for index, (bit, meaning) in enumerate(MTK_LOG_TYPE_BITS.items()):
            check = ttk.Checkbutton(
                log_types,
                text=f'{bit}: {meaning}',
                variable=self.log_type_vars[bit],
                command=self._update_bitmask_summary,
            )
            check.grid(row=index // 2, column=index % 2, sticky='w', padx=(0, 16), pady=2)
            if bit == 2:
                check.state(['disabled'])
        ttk.Label(log_types, textvariable=self.bitmask_summary_var, wraplength=490).grid(
            row=3, column=0, columnspan=2, sticky='w', pady=(5, 0)
        )
        self._update_bitmask_summary()
        row += 1

        add_row('Maximum modem log size (MB):', ttk.Spinbox(
            form, textvariable=self.max_size_var, from_=1, to=100000
        ))
        add_row('Storage selection:', ttk.Combobox(
            form, textvariable=self.storage_var, values=['internal_sd', 'external_sd'], state='readonly'
        ))
        add_row('Device log root:', ttk.Entry(form, textvariable=self.device_root_var))
        add_row('Start timeout (seconds):', ttk.Spinbox(
            form, textvariable=self.start_timeout_var, from_=1, to=300
        ))
        add_row('Stop timeout (seconds):', ttk.Spinbox(
            form, textvariable=self.stop_timeout_var, from_=1, to=300
        ))
        add_row('Finalize wait (seconds):', ttk.Spinbox(
            form, textvariable=self.finalize_wait_var, from_=0, to=120
        ))

        toggles = ttk.LabelFrame(form, text='Behavior', padding=6)
        toggles.grid(row=row, column=0, columnspan=2, sticky='ew', pady=(8, 4))
        ttk.Checkbutton(toggles, text='Enabled', variable=self.enabled_var).grid(row=0, column=0, sticky='w')
        ttk.Checkbutton(toggles, text='Autostart after boot', variable=self.auto_start_var).grid(row=0, column=1, sticky='w', padx=10)
        ttk.Checkbutton(toggles, text='Auto-reset after modem exception', variable=self.auto_reset_var).grid(row=1, column=0, sticky='w')
        ttk.Checkbutton(toggles, text='Show notification', variable=self.notification_var).grid(row=1, column=1, sticky='w', padx=10)
        ttk.Checkbutton(toggles, text='Enable TagLog', variable=self.taglog_var).grid(row=2, column=0, sticky='w')
        row += 1

        note = (
            'SD records a normal on-device .muxz capture. PLS is passive logging. '
            'USB mode may require a MediaTek USB logging driver and host decoder.'
        )
        ttk.Label(form, text=note, wraplength=490).grid(row=row, column=0, columnspan=2, sticky='w', pady=(6, 2))

        buttons = ttk.Frame(outer)
        buttons.grid(row=2, column=0, columnspan=2, sticky='e', pady=(10, 0))
        ttk.Button(buttons, text='Reload JSON', command=self._reload).pack(side='left', padx=4)
        ttk.Button(buttons, text='Save Profile to JSON', command=self._save_current).pack(side='left', padx=4)
        ttk.Button(buttons, text='Close', command=self.destroy).pack(side='left', padx=4)

    def _refresh_list(self, select_index=None):
        self.profile_list.delete(0, 'end')
        for profile in self.profiles:
            suffix = '' if profile.get('enabled', True) else ' (disabled)'
            self.profile_list.insert('end', f"{profile['name']} [{profile['chipset']}]{suffix}")
        if select_index is not None and 0 <= select_index < len(self.profiles):
            self.profile_list.selection_clear(0, 'end')
            self.profile_list.selection_set(select_index)
            self.profile_list.see(select_index)

    def _selected_index(self):
        selection = self.profile_list.curselection()
        return int(selection[0]) if selection else None

    def _load_selected(self):
        index = self._selected_index()
        if index is None or index >= len(self.profiles):
            return
        self.editing_index = index
        profile = self.profiles[index]
        self.name_var.set(profile['name'])
        self.chipset_var.set(profile['chipset'])
        self.enabled_var.set(profile['enabled'])
        mode_label = next(
            (label for label, value in MTK_MODE_LABELS.items() if value == profile['mode']),
            '2: SD (record on device)',
        )
        modem_type_label = next(
            (label for label, value in MTK_MODEM_TYPE_LABELS.items() if value == profile['modem_type']),
            '1: MD1 (primary cellular modem)',
        )
        self.mode_var.set(mode_label)
        self.modem_type_var.set(modem_type_label)
        for bit, variable in self.log_type_vars.items():
            variable.set(bool(profile['log_type_mask'] & bit))
        self._update_bitmask_summary()
        self.max_size_var.set(profile['max_log_size_mb'])
        self.storage_var.set(profile['storage'])
        self.auto_start_var.set(profile['auto_start_on_boot'])
        self.auto_reset_var.set(profile['auto_reset_on_exception'])
        self.notification_var.set(profile['show_notification'])
        self.taglog_var.set(profile['taglog_enabled'])
        self.device_root_var.set(profile['device_log_root'])
        self.start_timeout_var.set(profile['start_timeout_seconds'])
        self.stop_timeout_var.set(profile['stop_timeout_seconds'])
        self.finalize_wait_var.set(profile['finalize_wait_seconds'])

    def _form_profile(self):
        log_type_mask = sum(
            bit for bit, variable in self.log_type_vars.items() if variable.get()
        )
        return normalize_modem_profile({
            'name': self.name_var.get(),
            'chipset': self.chipset_var.get(),
            'enabled': self.enabled_var.get(),
            'mode': MTK_MODE_LABELS.get(self.mode_var.get(), self.mode_var.get()),
            'modem_type': MTK_MODEM_TYPE_LABELS.get(self.modem_type_var.get(), 1),
            'log_type_mask': log_type_mask,
            'max_log_size_mb': self.max_size_var.get(),
            'storage': self.storage_var.get(),
            'auto_start_on_boot': self.auto_start_var.get(),
            'auto_reset_on_exception': self.auto_reset_var.get(),
            'show_notification': self.notification_var.get(),
            'taglog_enabled': self.taglog_var.get(),
            'device_log_root': self.device_root_var.get(),
            'start_timeout_seconds': self.start_timeout_var.get(),
            'stop_timeout_seconds': self.stop_timeout_var.get(),
            'finalize_wait_seconds': self.finalize_wait_var.get(),
        })

    def _update_bitmask_summary(self):
        selected = [bit for bit, variable in self.log_type_vars.items() if variable.get()]
        mask = sum(selected)
        meanings = ', '.join(MTK_LOG_TYPE_BITS[bit] for bit in selected) or 'none'
        addition = ' + '.join(str(bit) for bit in selected) or '0'
        self.bitmask_summary_var.set(
            f'Selected mask: {mask} = {addition} ({meanings}). Bit 2 is required for modem profiles.'
        )

    def _new_profile(self):
        self.editing_index = None
        profile = copy.deepcopy(DEFAULT_MODEM_PROFILES[0])
        existing = {item['name'].casefold() for item in self.profiles}
        base = 'New MediaTek Profile'
        name = base
        counter = 2
        while name.casefold() in existing:
            name = f'{base} {counter}'
            counter += 1
        profile['name'] = name
        self.profiles.append(profile)
        self._refresh_list(len(self.profiles) - 1)
        self._load_selected()

    def _duplicate_profile(self):
        index = self._selected_index()
        if index is None:
            return
        duplicate = copy.deepcopy(self.profiles[index])
        existing = {item['name'].casefold() for item in self.profiles}
        base = f"{duplicate['name']} Copy"
        name = base
        counter = 2
        while name.casefold() in existing:
            name = f'{base} {counter}'
            counter += 1
        duplicate['name'] = name
        self.profiles.append(duplicate)
        self._refresh_list(len(self.profiles) - 1)
        self._load_selected()

    def _delete_profile(self):
        index = self._selected_index()
        if index is None:
            return
        name = self.profiles[index]['name']
        if not messagebox.askyesno('Delete profile', f'Delete modem profile {name!r}?', parent=self):
            return
        try:
            del self.profiles[index]
            save_modem_profiles(self.profiles_file, self.profiles)
            self.profiles = load_modem_profiles(self.profiles_file)
            self.editing_index = None
            next_index = min(index, len(self.profiles) - 1)
            self._refresh_list(next_index if next_index >= 0 else None)
            if self.profiles:
                self._load_selected()
            if self.on_saved:
                self.on_saved()
        except Exception as exc:
            messagebox.showerror('Could not delete profile', str(exc), parent=self)

    def _save_current(self):
        try:
            profile = self._form_profile()
            index = self.editing_index
            if index is None:
                self.profiles.append(profile)
                index = len(self.profiles) - 1
            else:
                self.profiles[index] = profile
            save_modem_profiles(self.profiles_file, self.profiles)
            self.profiles = load_modem_profiles(self.profiles_file)
            self.editing_index = index
            self._refresh_list(index)
            if self.on_saved:
                self.on_saved()
            messagebox.showinfo('Saved', f'Modem profiles saved to:\n{self.profiles_file}', parent=self)
        except Exception as exc:
            messagebox.showerror('Invalid modem profile', str(exc), parent=self)

    def _reload(self):
        try:
            self.profiles = load_modem_profiles(self.profiles_file)
            self.editing_index = None
            self._refresh_list(0 if self.profiles else None)
            if self.profiles:
                self._load_selected()
        except Exception as exc:
            messagebox.showerror('Could not load profiles', str(exc), parent=self)


class LoggerGUI(tk.Tk):
    # Snapshot helpers
    def log(self, msg: str):
        def _append():
            try:
                self.log_text.insert('end', time.strftime('%H:%M:%S ') + msg + '\n')
                self.log_text.see('end')
            except Exception:
                pass
        try:
            self.after(0, _append)
        except Exception:
            pass

    def busy(self, on: bool):
        def _set():
            try:
                if on:
                    self.progress.start(60)
                else:
                    self.progress.stop()
            except Exception:
                pass
        try:
            self.after(0, _set)
        except Exception:
            pass

    def run_bg(self, target, *args, **kwargs):
        t = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
        t.start()
        return t

    # Snapshot helpers
    def device_snapshot(self, serial: str):
        ts = int(time.time() * 1000)
        # Android elapsedRealtimeNanos and Wall time
        wall = run([ADB, '-s', serial, 'shell', 'date', '+%s']).stdout.strip()
        ipv4 = run([ADB, '-s', serial, 'shell', 'ip', '-4', 'addr', 'show']).stdout
        ipv6 = run([ADB, '-s', serial, 'shell', 'ip', '-6', 'addr', 'show']).stdout
        plmn = run([ADB, '-s', serial, 'shell', 'getprop', 'gsm.operator.numeric']).stdout.strip()
        return {
            'timestamp_ms': ts,
            'unix_seconds': wall,
            'ipv4': ' | '.join([l.strip() for l in ipv4.splitlines() if 'inet ' in l]),
            'ipv6': ' | '.join([l.strip() for l in ipv6.splitlines() if 'inet6 ' in l]),
            'plmn': plmn,
        }

    def write_snapshot_csv(self, serial: str, out_dir: Path, phase: str):
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / 'session_snapshot.csv'
        snap = self.device_snapshot(serial)
        header = 'phase,timestamp_ms,unix_seconds,ipv4,ipv6,plmn\n'
        line = f"{phase},{snap['timestamp_ms']},{snap['unix_seconds']},\"{snap['ipv4']}\",\"{snap['ipv6']}\",{snap['plmn']}\n"
        need_header = not csv_path.exists()
        with open(csv_path, 'a', encoding='utf-8') as f:
            if need_header:
                f.write(header)
            f.write(line)

    # --- Safe pull helpers for screenrecord ---
    def _detect_screenrecord_caps(self, serial: str):
        """Detect screenrecord flags without creating several probe recordings."""
        try:
            if self.screenrecord_caps and getattr(self, 'screenrecord_caps_serial', None) == serial:
                return self.screenrecord_caps
            self.screenrecord_caps = None
            result = run([ADB, '-s', serial, 'shell', 'screenrecord', '--help'], timeout=10)
            help_text = ((result.stdout or '') + '\n' + (result.stderr or '')).lower()
            if 'screenrecord' in help_text and ('<filename>' in help_text or 'filename' in help_text):
                tflag = '--time-limit' if '--time-limit' in help_text else '-t'
                self.screenrecord_caps = {'syntax': 'positional', 'tflag': tflag}
                if '--bit-rate' in help_text:
                    self.screenrecord_caps['bitrate_flag'] = '--bit-rate'
                self.screenrecord_caps_serial = serial
                return self.screenrecord_caps
            if 'screenrecord' in help_text and '-o' in help_text:
                tflag = '--time-limit' if '--time-limit' in help_text else '-t'
                self.screenrecord_caps = {'syntax': 'dash_o', 'tflag': tflag}
                if '--bit-rate' in help_text:
                    self.screenrecord_caps['bitrate_flag'] = '--bit-rate'
                self.screenrecord_caps_serial = serial
                return self.screenrecord_caps
        except Exception:
            pass
        self.screenrecord_caps = {'syntax': 'unknown'}
        self.screenrecord_caps_serial = serial
        return self.screenrecord_caps
    def _remote_file_size(self, serial: str, remote: str) -> int:
        try:
            cmd = f"stat -c %s {remote} 2>/dev/null || wc -c < {remote} 2>/dev/null || echo 0"
            res = run_shell(serial, cmd)
            txt = (res.stdout or '').strip()
            return int(txt) if txt.isdigit() else 0
        except Exception:
            return 0

    def _wait_for_file_stable(self, serial: str, remote: str, stable_samples: int = 3, interval: float = 0.5, timeout: float = 10.0):
        """Wait until remote file size stops changing for stable_samples intervals or timeout."""
        start = time.time()
        last = -1
        stable = 0
        # First, ensure filesystem flush best-effort
        try:
            run([ADB, '-s', serial, 'shell', 'sync'])
        except Exception:
            pass
        while time.time() - start < timeout:
            sz = self._remote_file_size(serial, remote)
            if sz == last and sz > 0:
                stable += 1
                if stable >= stable_samples:
                    return True
            else:
                stable = 0
                last = sz
            time.sleep(interval)
        return False

    def _remote_mtime(self, serial: str, remote: str) -> int:
        """Return remote file mtime (epoch seconds) or 0 on error."""
        try:
            res = run([ADB, '-s', serial, 'shell', 'stat', '-c', '%Y', remote])
            txt = (res.stdout or '').strip()
            return int(txt) if txt.isdigit() else 0
        except Exception:
            return 0

    def _settle_and_pull_video(self, serial: str, remote_mp4: str, local_path: Path, max_retries: int = 3):
        """Wait for finalization, pull atomically, and verify MP4 size/signature."""
        part_path = local_path.with_name(local_path.name + '.part')
        try:
            try:
                run([ADB, '-s', serial, 'shell', 'sync'])
            except Exception:
                pass
            self._wait_for_file_stable(serial, remote_mp4, stable_samples=2, interval=0.35, timeout=8.0)
            attempts = max(1, int(max_retries))
            for attempt in range(1, attempts + 1):
                remote_size = self._remote_file_size(serial, remote_mp4)
                if remote_size <= 0:
                    self.log(f'Screen recording is missing or empty on device (attempt {attempt}/{attempts}).')
                    time.sleep(0.5)
                    continue
                try:
                    if part_path.exists():
                        part_path.unlink()
                except OSError:
                    pass
                self.log(f'Pulling finalized screen recording (attempt {attempt}/{attempts})...')
                res = run([ADB, '-s', serial, 'pull', remote_mp4, str(part_path)], timeout=120)
                local_size = part_path.stat().st_size if part_path.exists() else 0
                valid_mp4 = False
                if local_size >= 12:
                    with open(part_path, 'rb') as video:
                        valid_mp4 = video.read(12)[4:8] == b'ftyp'
                if res.returncode == 0 and local_size == remote_size and valid_mp4:
                    os.replace(part_path, local_path)
                    self.log(f'Video pulled and verified: {local_size} bytes.')
                    return True
                detail = (res.stderr or res.stdout or '').strip()
                self.log(
                    f'Video verification failed: remote={remote_size}, local={local_size}, '
                    f'mp4={valid_mp4}. {detail}'
                )
                time.sleep(0.5)
            return False
        except Exception as e:
            self.log(f'Error during video pull: {e}')
            return False
        finally:
            try:
                if part_path.exists():
                    part_path.unlink()
            except OSError:
                pass

    # --- Connectivity helpers ---
    def is_device_connected(self, serial: str) -> bool:
        """Return True if ADB reports the device as 'device' state for the given serial.
        Uses a short timeout to avoid hangs when ADB server is stuck.
        """
        try:
            res = run([ADB, '-s', serial, 'get-state'], timeout=2)
            state = (res.stdout or '').strip().lower()
            if res.returncode != 0:
                return False
            return state == 'device'
        except Exception:
            return False

    def is_device_ready(self, serial: str, boot_timeout: float = 90.0) -> bool:
        """Best-effort readiness check after reconnect/reboot.
        - Waits briefly for device, checks sys.boot_completed and a trivial shell command.
        - Returns True if ready, False otherwise.
        """
        try:
            # Quick wait-for-device with timeout
            try:
                run([ADB, '-s', serial, 'wait-for-device'], timeout=10)
            except Exception:
                pass
            # Poll boot_completed up to boot_timeout seconds
            t0 = time.time()
            while time.time() - t0 < boot_timeout:
                try:
                    bc = self.getprop(serial, 'sys.boot_completed').strip()
                    if bc == '1':
                        # Try a trivial command to ensure shell responds
                        res = run([ADB, '-s', serial, 'shell', 'id'], timeout=5)
                        if res.returncode == 0 and res.stdout:
                            return True
                except Exception:
                    pass
                time.sleep(2)
        except Exception:
            pass
        return False

    def _start_reconnect_monitor(self):
        """Ensure reconnect monitor is running if enabled and we have a target serial."""
        if not self.auto_reconnect.get():
            return
        target = getattr(self, 'last_active_serial', '')
        if not target:
            return
        # Reset/control event
        try:
            if self.reconnect_event is None:
                self.reconnect_event = threading.Event()
            else:
                self.reconnect_event.clear()
        except Exception:
            self.reconnect_event = threading.Event()
        # Start thread if not alive
        if self.reconnect_thread is None or not self.reconnect_thread.is_alive():
            self.reconnect_thread = self.run_bg(self._reconnect_monitor, target)
            self.log(f'Reconnect monitor started for {target}.')

    def _reconnect_monitor(self, serial: str, interval: float = 2.0):
        """Background thread that waits for the specified serial to reappear and optionally auto-resumes."""
        consecutive = 0
        backoff = 0
        while True:
            # Stop conditions
            ev = getattr(self, 'reconnect_event', None)
            if ev is not None and ev.is_set():
                break
            # Only monitor if auto_reconnect still enabled and we still target same serial
            if not self.auto_reconnect.get() or serial != getattr(self, 'last_active_serial', serial):
                break
            try:
                devices = list_devices()
            except Exception:
                devices = []
            if serial in devices:
                consecutive += 1
            else:
                consecutive = 0
            if consecutive >= 2:  # debounce
                # Update UI selection to the target serial if needed
                try:
                    self.after(0, lambda s=serial: self.sel.set(s))
                    self.after(0, self.refresh_devices)
                except Exception:
                    pass
                self.log(f'Device {serial} reconnected. Checking readiness...')
                ready = self.is_device_ready(serial)
                if not ready:
                    self.log('Device detected but not ready yet (booting or ADB not responsive). Will keep waiting...')
                    consecutive = 1
                else:
                    # Optionally auto-resume
                    do_resume = self.auto_resume_on_reconnect.get() and self.session_was_active_on_disconnect
                    status_msg = 'Reconnected'
                    if do_resume:
                        status_msg = 'Reconnected – resuming session...'
                    try:
                        self.after(0, lambda m=status_msg: self.status.set(m))
                    except Exception:
                        pass
                    if do_resume:
                        try:
                            # Clear flags before resume
                            self.session_was_active_on_disconnect = False
                            self.auto_stopping = False
                            # Ensure selection matches and call start_all on UI thread
                            self.after(0, self.start_all)
                        except Exception:
                            pass
                    # Stop monitor after handling
                    try:
                        if self.reconnect_event is not None:
                            self.reconnect_event.set()
                    except Exception:
                        pass
                    break
            # Sleep with basic backoff on failures
            delay = interval + backoff
            time.sleep(delay)
            if consecutive == 0 and backoff < 3:
                backoff += 1
            else:
                backoff = 0

    def _device_watchdog(self, serial: str, interval: float = 2.0, threshold: int = 2):
        """Background monitor that detects device disconnects and auto-stops the session.
        - interval: seconds between checks
        - threshold: consecutive failed checks before triggering stop
        """
        fail_count = 0
        while getattr(self, 'session_active', False) and not getattr(self, 'watchdog_event', threading.Event()).is_set():
            ok = self.is_device_connected(serial)
            if ok:
                fail_count = 0
            else:
                fail_count += 1
            if fail_count >= threshold and not getattr(self, 'auto_stopping', False):
                # Trigger auto-stop
                self.auto_stopping = True
                self.session_active = False
                # Mark that we should auto-resume on reconnect and remember the serial
                self.session_was_active_on_disconnect = True
                self.last_active_serial = serial
                try:
                    self.after(0, lambda: self.status.set('Device disconnected – stopping…'))
                except Exception:
                    pass
                self.log('Device disconnected or ADB link lost. Initiating automatic stop…')
                if not getattr(self, 'disconnected_notified', False):
                    self.disconnected_notified = True
                    try:
                        self.after(0, lambda: messagebox.showerror('Device disconnected', f'ADB connection to {serial} was lost. The session will stop.'))
                    except Exception:
                        pass
                # Signal watchdog to finish and initiate stop
                try:
                    self.watchdog_event.set()
                except Exception:
                    pass
                try:
                    # Call stop on the UI thread to keep sequencing consistent
                    self.after(0, self.stop_all)
                except Exception:
                    pass
                break
            time.sleep(interval)

    # Device info collection (Python version of Cmdlets\\deviceinfo.bat)
    def getprop(self, serial: str, key: str) -> str:
        try:
            return run([ADB, '-s', serial, 'shell', 'getprop', key]).stdout.strip()
        except Exception:
            return ''

    # --- iphonesubinfo best-effort helpers ---
    def _svc_call(self, serial: str, code: int, slot: Optional[int] = None) -> str:
        try:
            base = [ADB, '-s', serial, 'shell', 'service', 'call', 'iphonesubinfo', str(code)]
            if slot is not None:
                base += ['i32', str(slot)]
            res = run(base)
            return res.stdout or ''
        except Exception:
            return ''

    def _parse_iphonesubinfo(self, text: str) -> str:
        # Convert service call UCS-2/hex dump into a string and keep digits and optional leading +
        if not text:
            return ''
        hex8 = re.findall(r'0x([0-9a-fA-F]{8})', text)
        pieces: List[str] = []
        for h in hex8:
            pieces.append(h[:4])
            pieces.append(h[4:])
        # Some builds print bare 4-hex groups like 0031
        hex4 = re.findall(r'\b([0-9a-fA-F]{4})\b', text)
        for h in hex4:
            pieces.append(h)
        # Decode UCS-2 code units
        chars: List[str] = []
        for h in pieces:
            try:
                cp = int(h, 16)
                if 0x20 <= cp <= 0x7E:  # printable ASCII
                    chars.append(chr(cp))
            except Exception:
                pass
        s = ''.join(chars)
        # Keep digits and plus, collapse spaces
        s = re.sub(r'[^0-9+]', '', s)
        # Deduplicate repeated patterns (some outputs repeat)
        # Keep the longest run of digits/+
        candidates = re.findall(r'\+?[0-9]{5,}', s)
        if not candidates:
            return ''
        return max(candidates, key=len)

    def _best_effort_subinfo(self, serial: str, codes: List[int], min_len: int, max_len: int) -> str:
        # Try without slot, then slot 0 and 1
        for slot in [None, 0, 1]:
            for code in codes:
                parsed = self._parse_iphonesubinfo(self._svc_call(serial, code, slot))
                if parsed and (min_len <= len(parsed) <= max_len):
                    return parsed
        return ''

    def _collect_imei_imsi_mdn(self, serial: str) -> Tuple[str, str, str]:
        imei = ''
        # Common codes for IMEI on various Android telephony stacks
        for codes in ([1, 2, 3, 4], [1, 3], [4, 2]):
            imei = self._best_effort_subinfo(serial, list(codes), 14, 17)
            if imei:
                break
        # Prefer 15-digit if longer
        if imei and len(imei) != 15:
            m = re.search(r'(\d{15})', imei)
            if m:
                imei = m.group(1)
        # IMSI (usually 15 digits)
        imsi = self._best_effort_subinfo(serial, [5, 7], 6, 17)
        if imsi:
            m = re.search(r'(\d{10,15})', imsi)
            if m:
                imsi = m.group(1)
        # MDN/Line1 number
        mdn = self._best_effort_subinfo(serial, [13, 12], 7, 15)
        # Fallback properties for MDN
        if not mdn:
            prop_candidates = [
                'ril.line1.number', 'line1.number', 'persist.radio.line1number',
                'vendor.ril.line1.number', 'gsm.sim.msisdn']
            for k in prop_candidates:
                v = self.getprop(serial, k)
                v_norm = re.sub(r'[^0-9+]', '', v)
                if v_norm and len(re.sub(r'\D', '', v_norm)) >= 7:
                    mdn = v_norm
                    break
        return imei or 'NA', imsi or 'NA', mdn or 'NA'

    def write_device_info(self, serial: str, out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        info_path = out_dir / f'Device-info_{serial}.txt'
        # Collect properties (best-effort; some may be empty depending on OEM/build)
        props = {
            'Brand': self.getprop(serial, 'ro.product.brand'),
            'Model': self.getprop(serial, 'ro.product.model'),
            'DeviceCodeName': self.getprop(serial, 'ro.boot.device'),
            'ProductDevice': self.getprop(serial, 'ro.product.device'),
            'AndroidVersion': self.getprop(serial, 'ro.build.version.release'),
            'SDK': self.getprop(serial, 'ro.build.version.sdk'),
            'BuildID': self.getprop(serial, 'ro.build.id'),
            'BuildFingerprint': self.getprop(serial, 'ro.build.fingerprint'),
            'BuildTags': self.getprop(serial, 'ro.build.tags'),
            'SKU': self.getprop(serial, 'ro.boot.hardware.sku'),
            'PLMN': self.getprop(serial, 'gsm.sim.operator.numeric'),
            'ProgramUtag': self.getprop(serial, 'ro.carrier'),
            'Serial': self.getprop(serial, 'ro.boot.serialno'),
            'HWRevision': self.getprop(serial, 'ro.vendor.hw.revision'),
            'Carrier': (self.getprop(serial, 'gsm.operator.alpha') or self.getprop(serial, 'ro.carrier')),
        }
        # Determine codename preference between ro.boot.device and ro.product.device
        codename = props.get('DeviceCodeName') or props.get('ProductDevice')
        # Write file
        with open(info_path, 'w', encoding='utf-8') as f:
            f.write('=== Device Info ===\n')
            f.write(f"[Brand]: {props['Brand']}\n")
            f.write(f"[Model]: {props['Model']}\n")
            f.write(f"[CodeName]: {codename}\n")
            f.write(f"[BuildID]: {props['BuildID']}\n")
            f.write(f"[BuildFingerprint]: {props['BuildFingerprint']}\n")
            f.write(f"[BuildTags]: {props['BuildTags']}\n")
            f.write(f"[Android]: {props['AndroidVersion']} (SDK {props['SDK']})\n")
            f.write(f"[SKU]: {props['SKU']}\n")
            f.write(f"[PLMN]: {props['PLMN']}\n")
            f.write(f"[ProgramUtag]: {props['ProgramUtag']}\n")
            f.write(f"[Serial]: {props['Serial']}\n")
            f.write(f"[HWRevision]: {props['HWRevision']}\n")
            f.write(f"[Carrier]: {props['Carrier']}\n")
            # iphonesubinfo best-effort fields
            try:
                imei, imsi, mdn = self._collect_imei_imsi_mdn(serial)
            except Exception:
                imei, imsi, mdn = 'NA', 'NA', 'NA'
            f.write(f"[IMEI]: {imei}\n")
            f.write(f"[IMSI]: {imsi}\n")
            f.write(f"[MDN]: {mdn}\n")
        self.log(f'Device info written: {info_path}')

    def __init__(self):
        super().__init__()
        self.title('ADB Logger (Python)')
        self.geometry('860x640')
        self.minsize(740, 540)
        self.devices = []
        self.sel = tk.StringVar()
        self.log_dir = tk.StringVar(value=str(ROOT / 'Logs'))
        self.tcpdump_path = tk.StringVar(value=str(ROOT / 'Cmdlets' / 'tcpdump_installer' / 'programs' / 'tcpdump'))
        self.test_name = tk.StringVar()
        self.capture_logcat = tk.BooleanVar(value=True)
        self.capture_tcpdump = tk.BooleanVar(value=False)
        self.capture_modem = tk.BooleanVar(value=False)
        self.capture_bugreport = tk.BooleanVar(value=False)
        self.capture_screenshot = tk.BooleanVar(value=True)
        self.capture_screenrecord = tk.BooleanVar(value=True)
        self.enable_watchdog = tk.BooleanVar(value=True)
        # Zip-at-end option (OFF by default)
        self.zip_at_end = tk.BooleanVar(value=False)
        # Option to skip post-processing (OFF by default; can be enabled via env LOGGER_SKIP_POST=1/true)
        self.skip_post_processing = tk.BooleanVar(value=False)
        try:
            env_skip = os.environ.get('LOGGER_SKIP_POST', '').strip().lower()
            if env_skip in ('1', 'true', 'yes', 'y'):
                self.skip_post_processing.set(True)
        except Exception:
            pass
        # Segmented screenrecord settings
        # Default to normal (single-file) recording; segmented can be enabled manually
        self.segmented_screenrecord = tk.BooleanVar(value=False)
        self.segment_length = tk.IntVar(value=15)
        self.video_quality = tk.StringVar(value=VIDEO_QUALITY_DEVICE_DEFAULT)
        self.chipset = tk.StringVar(value='Auto/Unknown')
        self.modem_profile = tk.StringVar()
        self.modem_profiles_file = MODEM_PROFILES_FILE
        try:
            self.modem_profiles = load_modem_profiles(self.modem_profiles_file)
        except Exception:
            self.modem_profiles = copy.deepcopy(DEFAULT_MODEM_PROFILES)
        self.oem_logger = tk.StringVar(value='None')
        self.logcat_procs = {}
        self.logcat_files = {}
        self.logcat_proc = None
        self.tcpdump_proc = None
        # Session/watchdog state
        self.session_active = False
        self.auto_stopping = False
        self.disconnected_notified = False
        self.watchdog_event = threading.Event()
        self.watchdog_thread = None
        self.active_serial = ''
        self.stopping = False
        self.session_out_dir = None
        self.session_output_serial = ''
        self.session_output_test_name = ''
        self.session_output_base = None
        self.active_modem_profile = None
        self.active_modem_remote_path = ''
        self.active_mtk_log_paths = {}
        self.mtk_log_paths_before = {}
        self.active_samsung_log_files = []
        self.samsung_log_files_before = []
        self.modem_capture_started = False
        # Auto-reconnect/auto-resume state
        self.auto_reconnect = tk.BooleanVar(value=True)
        self.auto_resume_on_reconnect = tk.BooleanVar(value=True)
        self.advanced_expanded = tk.BooleanVar(value=False)
        self.advanced_button_text = tk.StringVar(value='Advanced options  ▸')
        self.reconnect_event = threading.Event()
        self.reconnect_thread = None
        self.last_active_serial = ''
        self.session_was_active_on_disconnect = False
        # Screenrecord runtime state
        self.screenrecord_pid = None
        self.screenrecord_proc = None
        self.screenrecord_remote = None
        self.screenrecord_loop_pid = None
        self.session_start_epoch = 0
        # Detected screenrecord capabilities for current session/device
        self.screenrecord_caps = None
        self.screenrecord_caps_serial = None
        # Events feature state
        self.event_fields = [tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar()]
        # Old combined presets (kept for backward compatibility and migration)
        self.event_presets: List[dict] = []
        self.selected_preset = tk.StringVar()
        self.presets_file = ROOT / 'event_presets.json'
        try:
            self.load_event_presets()
        except Exception:
            self.event_presets = []
        # New per-field presets
        self.field_presets: List[List[dict]] = [[], [], [], []]
        self.field_selected_preset_vars: List[tk.StringVar] = [tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar()]
        self.field_preset_combos: List[ttk.Combobox] = []
        self.per_field_presets_file = ROOT / 'event_presets_per_field.json'
        try:
            self.load_field_presets()
        except Exception:
            # Best effort: initialize empty and try to migrate from old combined presets
            self.field_presets = [[], [], [], []]
        try:
            self._migrate_old_event_presets_to_field_presets()
        except Exception:
            pass
        self.create_widgets()
        self.refresh_devices()
        
    def create_widgets(self):
        root = ttk.Frame(self, padding=(10, 10, 10, 8))
        root.pack(fill='both', expand=True)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill='both', expand=True)
        self.session_tab = ttk.Frame(self.notebook, padding=12)
        self.events_tab = ttk.Frame(self.notebook, padding=12)
        self.output_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.session_tab, text='Session')
        self.notebook.add(self.events_tab, text='Events')
        self.notebook.add(self.output_tab, text='Output')

        session = self.session_tab
        session.columnconfigure(1, weight=1)
        ttk.Label(session, text='Device').grid(column=0, row=0, sticky='w', pady=4)
        self.combo = ttk.Combobox(
            session, textvariable=self.sel, values=self.devices, state='readonly', width=40
        )
        self.combo.grid(column=1, row=0, sticky='ew', padx=(12, 8), pady=4)
        self.combo.bind('<<ComboboxSelected>>', lambda _event: self._autodetect_modem_chipset())
        ttk.Button(session, text='Refresh', command=self.refresh_devices).grid(
            column=2, row=0, sticky='ew', pady=4
        )

        ttk.Label(session, text='Test case').grid(column=0, row=1, sticky='w', pady=4)
        ttk.Entry(session, textvariable=self.test_name).grid(
            column=1, row=1, columnspan=2, sticky='ew', padx=(12, 0), pady=4
        )

        ttk.Label(session, text='Save to').grid(column=0, row=2, sticky='w', pady=4)
        ttk.Entry(session, textvariable=self.log_dir, state='readonly').grid(
            column=1, row=2, sticky='ew', padx=(12, 8), pady=4
        )
        ttk.Button(session, text='Change…', command=self.browse_dir).grid(
            column=2, row=2, sticky='ew', pady=4
        )

        capture = ttk.LabelFrame(session, text='Capture', padding=10)
        capture.grid(column=0, row=3, columnspan=3, sticky='ew', pady=(12, 6))
        capture.columnconfigure(0, weight=1)
        capture.columnconfigure(1, weight=1)
        capture_choices = (
            ('Logcat', self.capture_logcat, None),
            ('Screen recording', self.capture_screenrecord, self._sync_contextual_controls),
            ('Tcpdump', self.capture_tcpdump, self._sync_contextual_controls),
            ('Initial screenshot', self.capture_screenshot, None),
            ('Modem logs', self.capture_modem, self._sync_contextual_controls),
            ('Bugreport', self.capture_bugreport, None),
        )
        for index, (label, variable, command) in enumerate(capture_choices):
            ttk.Checkbutton(capture, text=label, variable=variable, command=command).grid(
                column=index % 2, row=index // 2, sticky='w', padx=6, pady=3
            )

        self.video_settings_frame = ttk.LabelFrame(session, text='Screen recording settings', padding=8)
        self.video_settings_frame.grid(column=0, row=4, columnspan=3, sticky='ew', pady=4)
        self.video_settings_frame.columnconfigure(1, weight=1)
        ttk.Label(self.video_settings_frame, text='Quality').grid(column=0, row=0, sticky='w')
        self.video_quality_combo = ttk.Combobox(
            self.video_settings_frame,
            textvariable=self.video_quality,
            values=list(VIDEO_QUALITY_PRESETS),
            state='readonly',
        )
        self.video_quality_combo.grid(column=1, row=0, sticky='ew', padx=(10, 0))
        ttk.Checkbutton(
            self.video_settings_frame,
            text='Split into segments',
            variable=self.segmented_screenrecord,
            command=self._sync_contextual_controls,
        ).grid(column=0, row=1, sticky='w', pady=(8, 0))
        self.segment_controls = ttk.Frame(self.video_settings_frame)
        self.segment_controls.grid(column=1, row=1, sticky='w', padx=(10, 0), pady=(8, 0))
        ttk.Label(self.segment_controls, text='Length').pack(side='left')
        self.segment_len_entry = ttk.Entry(
            self.segment_controls, textvariable=self.segment_length, width=6
        )
        self.segment_len_entry.pack(side='left', padx=(6, 3))
        ttk.Label(self.segment_controls, text='seconds').pack(side='left')

        self.tcpdump_settings_frame = ttk.LabelFrame(session, text='Tcpdump settings', padding=8)
        self.tcpdump_settings_frame.grid(column=0, row=5, columnspan=3, sticky='ew', pady=4)
        self.tcpdump_settings_frame.columnconfigure(1, weight=1)
        ttk.Label(self.tcpdump_settings_frame, text='Host binary').grid(column=0, row=0, sticky='w')
        ttk.Entry(self.tcpdump_settings_frame, textvariable=self.tcpdump_path).grid(
            column=1, row=0, sticky='ew', padx=8
        )
        ttk.Button(self.tcpdump_settings_frame, text='Browse…', command=self.browse_tcpdump).grid(
            column=2, row=0
        )

        self.modem_settings_frame = ttk.LabelFrame(session, text='Modem log settings', padding=8)
        self.modem_settings_frame.grid(column=0, row=6, columnspan=3, sticky='ew', pady=4)
        self.modem_settings_frame.columnconfigure(1, weight=1)
        ttk.Label(self.modem_settings_frame, text='Chipset').grid(column=0, row=0, sticky='w', pady=3)
        self.chipset_combo = ttk.Combobox(
            self.modem_settings_frame,
            textvariable=self.chipset,
            values=['Auto/Unknown', 'Qualcomm', 'Mediatek', 'Exynos'],
            state='readonly',
        )
        self.chipset_combo.grid(column=1, row=0, sticky='ew', padx=(10, 0), pady=3)
        self.chipset_combo.bind(
            '<<ComboboxSelected>>', lambda _event: self.refresh_modem_profile_choices()
        )
        ttk.Label(self.modem_settings_frame, text='Profile').grid(column=0, row=1, sticky='w', pady=3)
        self.modem_profile_combo = ttk.Combobox(
            self.modem_settings_frame, textvariable=self.modem_profile, state='disabled'
        )
        self.modem_profile_combo.grid(column=1, row=1, sticky='ew', padx=(10, 8), pady=3)
        ttk.Button(
            self.modem_settings_frame, text='Manage…', command=self.open_modem_settings
        ).grid(column=2, row=1, pady=3)

        self.advanced_toggle = ttk.Button(
            session, textvariable=self.advanced_button_text, command=self._toggle_advanced
        )
        self.advanced_toggle.grid(column=0, row=7, columnspan=3, sticky='w', pady=(10, 4))
        self.advanced_frame = ttk.LabelFrame(session, text='Advanced options', padding=10)
        self.advanced_frame.grid(column=0, row=8, columnspan=3, sticky='ew', pady=(0, 4))
        self.advanced_frame.columnconfigure(1, weight=1)
        ttk.Label(self.advanced_frame, text='OEM logger').grid(column=0, row=0, sticky='w', pady=3)
        ttk.Combobox(
            self.advanced_frame,
            textvariable=self.oem_logger,
            values=['None', 'Motorola Bug2Go', 'Samsung SilentLogger', 'Google PixelLogger', 'MTK DebugLoggerUI'],
            state='readonly',
        ).grid(column=1, row=0, columnspan=2, sticky='ew', padx=(12, 0), pady=3)
        self.watchdog_check = ttk.Checkbutton(
            self.advanced_frame,
            text='Auto-stop if the device disconnects',
            variable=self.enable_watchdog,
            command=self._sync_contextual_controls,
        )
        self.watchdog_check.grid(column=0, row=1, columnspan=2, sticky='w', pady=3)
        self.reconnect_check = ttk.Checkbutton(
            self.advanced_frame,
            text='Reconnect automatically',
            variable=self.auto_reconnect,
            command=self._sync_contextual_controls,
        )
        self.reconnect_check.grid(column=2, row=1, sticky='w', padx=(18, 0), pady=3)
        self.resume_check = ttk.Checkbutton(
            self.advanced_frame,
            text='Resume capture after reconnecting',
            variable=self.auto_resume_on_reconnect,
        )
        self.resume_check.grid(column=0, row=2, columnspan=2, sticky='w', pady=3)
        ttk.Checkbutton(
            self.advanced_frame, text='Zip session output at end', variable=self.zip_at_end
        ).grid(column=2, row=2, sticky='w', padx=(18, 0), pady=3)
        ttk.Checkbutton(
            self.advanced_frame, text='Skip post-processing', variable=self.skip_post_processing
        ).grid(column=0, row=3, columnspan=2, sticky='w', pady=3)

        events = self.events_tab
        events.columnconfigure(1, weight=1)
        events.columnconfigure(2, weight=1)
        ttk.Label(
            events,
            text='Record notable moments while a session is running.',
        ).grid(column=0, row=0, columnspan=4, sticky='w', pady=(0, 12))
        self.field_preset_combos = []
        for i in range(4):
            ttk.Label(events, text=f'Field {i + 1}').grid(
                column=0, row=i + 1, sticky='w', padx=(0, 8), pady=5
            )
            ttk.Entry(events, textvariable=self.event_fields[i]).grid(
                column=1, row=i + 1, sticky='ew', padx=(0, 8), pady=5
            )
            combo = ttk.Combobox(
                events, textvariable=self.field_selected_preset_vars[i], state='readonly'
            )
            self.field_preset_combos.append(combo)
            combo.grid(column=2, row=i + 1, sticky='ew', padx=(0, 8), pady=5)
            self._refresh_field_preset_combo(i)
            combo.bind('<<ComboboxSelected>>', lambda _event, idx=i: self.apply_field_preset(idx))
            ttk.Button(events, text='Log', command=lambda idx=i: self.save_single_event(idx)).grid(
                column=3, row=i + 1, pady=5
            )
        event_buttons = ttk.Frame(events)
        event_buttons.grid(column=0, row=5, columnspan=4, sticky='w', pady=(12, 0))
        ttk.Button(event_buttons, text='Save all fields', command=self.save_event_clicked).pack(
            side='left', padx=(0, 8)
        )
        ttk.Button(
            event_buttons, text='Clear fields', command=lambda: [v.set('') for v in self.event_fields]
        ).pack(side='left')

        output = self.output_tab
        output.columnconfigure(0, weight=1)
        output.rowconfigure(0, weight=1)
        log_frame = ttk.Frame(output)
        log_frame.grid(column=0, row=0, sticky='nsew')
        self.log_text = tk.Text(log_frame, height=12, wrap='word')
        self.log_text.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient='vertical', command=self.log_text.yview)
        scrollbar.pack(side='right', fill='y')
        self.log_text.configure(yscrollcommand=scrollbar.set)
        ttk.Button(output, text='Clear output folder…', command=self.clear_output_dir_clicked).grid(
            column=0, row=1, sticky='w', pady=(10, 0)
        )

        footer = ttk.Frame(root, padding=(0, 10, 0, 0))
        footer.pack(fill='x')
        footer.columnconfigure(0, weight=1)
        self.status = tk.StringVar(value='Idle')
        ttk.Label(footer, textvariable=self.status).grid(column=0, row=0, sticky='w')
        self.screenshot_button = ttk.Button(
            footer, text='Take Screenshot', command=self.take_screenshot_clicked
        )
        self.screenshot_button.grid(column=1, row=0, padx=(8, 4))
        self.start_button = ttk.Button(footer, text='Start', command=self.start_all)
        self.start_button.grid(column=2, row=0, padx=4)
        self.stop_button = ttk.Button(footer, text='Stop', command=self.stop_all, state='disabled')
        self.stop_button.grid(column=3, row=0, padx=(4, 0))
        self.progress = ttk.Progressbar(root, mode='indeterminate')
        self.progress.pack(fill='x', pady=(8, 0))

        self.columnconfigure(0, weight=1)
        self.refresh_modem_profile_choices()
        self._sync_contextual_controls()
        self._toggle_advanced(force=False)

    def _toggle_advanced(self, force=None):
        """Show advanced settings only when the user asks for them."""
        expanded = (not self.advanced_expanded.get()) if force is None else bool(force)
        self.advanced_expanded.set(expanded)
        self.advanced_button_text.set(
            'Advanced options  ▾' if expanded else 'Advanced options  ▸'
        )
        if expanded:
            self.advanced_frame.grid()
        else:
            self.advanced_frame.grid_remove()

    def _sync_contextual_controls(self):
        """Keep optional settings close to, and dependent on, their capture choice."""
        if self.capture_screenrecord.get():
            self.video_settings_frame.grid()
        else:
            self.video_settings_frame.grid_remove()

        if self.capture_screenrecord.get() and self.segmented_screenrecord.get():
            self.segment_controls.grid()
        else:
            self.segment_controls.grid_remove()

        if self.capture_tcpdump.get():
            self.tcpdump_settings_frame.grid()
        else:
            self.tcpdump_settings_frame.grid_remove()

        if self.capture_modem.get():
            self.modem_settings_frame.grid()
        else:
            self.modem_settings_frame.grid_remove()
        self._update_modem_profile_state()

        reconnect_available = self.enable_watchdog.get()
        self.reconnect_check.configure(state='normal' if reconnect_available else 'disabled')
        resume_available = reconnect_available and self.auto_reconnect.get()
        self.resume_check.configure(state='normal' if resume_available else 'disabled')

    def _set_session_ui(self, active: bool, stopping: bool = False):
        """Emphasize event capture while running and prevent setup edits mid-session."""
        if active:
            self.notebook.select(self.events_tab)
            self.notebook.tab(self.session_tab, state='disabled')
            self.start_button.configure(state='disabled')
            self.stop_button.configure(state='normal')
            return

        if stopping:
            self.notebook.select(self.output_tab)
            self.notebook.tab(self.session_tab, state='disabled')
            self.start_button.configure(state='disabled')
            self.stop_button.configure(state='disabled')
            return

        self.notebook.tab(self.session_tab, state='normal')
        self.start_button.configure(state='normal')
        self.stop_button.configure(state='disabled')

    def open_modem_settings(self):
        try:
            ModemProfileSettingsWindow(
                self, self.modem_profiles_file, self._reload_modem_profiles
            )
        except Exception as exc:
            messagebox.showerror('Modem settings', f'Could not open modem settings:\n{exc}')

    def _reload_modem_profiles(self):
        previous = self.modem_profile.get()
        try:
            self.modem_profiles = load_modem_profiles(self.modem_profiles_file)
            self.refresh_modem_profile_choices(preferred=previous)
            self.log(f'Loaded {len(self.modem_profiles)} modem profile(s).')
        except Exception as exc:
            self.log(f'Could not reload modem profiles: {exc}')
            messagebox.showerror('Modem profiles', str(exc))

    def refresh_modem_profile_choices(self, preferred=None):
        compatible = profiles_for_chipset(self.modem_profiles, self.chipset.get())
        names = [profile['name'] for profile in compatible]
        self.modem_profile_combo['values'] = names
        wanted = preferred if preferred in names else self.modem_profile.get()
        if wanted in names:
            self.modem_profile.set(wanted)
        elif names:
            self.modem_profile.set(names[0])
        else:
            self.modem_profile.set('')
        self._update_modem_profile_state()

    def _update_modem_profile_state(self):
        try:
            enabled = self.capture_modem.get() and bool(self.modem_profile_combo['values'])
            self.modem_profile_combo.configure(state='readonly' if enabled else 'disabled')
        except Exception:
            pass

    def selected_modem_profile(self):
        name = self.modem_profile.get().strip()
        compatible = profiles_for_chipset(self.modem_profiles, self.chipset.get())
        for profile in compatible:
            if profile['name'] == name:
                return copy.deepcopy(profile)
        return None

    def refresh_devices(self):
        # Preserve current selection if the device is still connected
        prev = self.sel.get().strip()
        self.devices = list_devices()
        self.combo['values'] = self.devices
        if prev and prev in self.devices:
            # Keep the last used/selected device
            self.sel.set(prev)
        else:
            # Fallback to previous behavior
            if self.devices:
                self.sel.set(self.devices[0])
            else:
                self.sel.set('')
        self.status.set(f'Devices: {", ".join(self.devices) if self.devices else "none"}')
        self._autodetect_modem_chipset()

    def _autodetect_modem_chipset(self):
        """Populate chipset/profile choices from one device getprop snapshot."""
        serial = self.sel.get().strip()
        if not serial:
            return
        detected = detect_device_modem_chipset(serial)
        if detected == 'Auto/Unknown':
            return
        changed = self.chipset.get() != detected
        self.chipset.set(detected)
        self.refresh_modem_profile_choices()
        if changed:
            self.log(f'Auto-detected modem chipset for {serial}: {detected}')

    def browse_dir(self):
        d = filedialog.askdirectory(initialdir=self.log_dir.get() or str(ROOT))
        if d:
            self.log_dir.set(d)

    def browse_tcpdump(self):
        f = filedialog.askopenfilename(title='Select tcpdump binary', initialdir=str(ROOT))
        if f:
            self.tcpdump_path.set(f)

    # === Events feature helpers ===
    def load_event_presets(self):
        try:
            if self.presets_file.exists():
                with open(self.presets_file, 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                if isinstance(data, list):
                    self.event_presets = [p for p in data if isinstance(p, dict) and isinstance(p.get('fields'), list)]
                else:
                    self.event_presets = []
            else:
                self.event_presets = []
        except Exception as e:
            self.log(f'Failed to load event presets: {e}')
            self.event_presets = []
        # Ensure sort by last_used desc
        for p in self.event_presets:
            if 'last_used' not in p:
                p['last_used'] = 0
        self.event_presets.sort(key=lambda x: x.get('last_used', 0), reverse=True)
        self._refresh_preset_combo()

    def save_event_presets(self):
        try:
            with open(self.presets_file, 'w', encoding='utf-8') as fp:
                json.dump(self.event_presets, fp, indent=2)
        except Exception as e:
            self.log(f'Failed to save event presets: {e}')

    def _preset_display_name(self, preset: dict) -> str:
        fields = [str(x) for x in (preset.get('fields') or [])]
        non_empty = [s for s in fields if s.strip()]
        if non_empty:
            label = ' | '.join(non_empty)
        else:
            label = '(empty preset)'
        return label[:80]

    def _refresh_preset_combo(self):
        try:
            values = [self._preset_display_name(p) for p in self.event_presets]
            self.preset_combo['values'] = values if hasattr(self, 'preset_combo') else values
            if values:
                self.selected_preset.set(values[0])
            else:
                self.selected_preset.set('')
        except Exception:
            pass

    def apply_selected_preset(self):
        sel = self.selected_preset.get()
        for p in self.event_presets:
            if self._preset_display_name(p) == sel:
                fields = (p.get('fields') or [])
                for i in range(4):
                    val = fields[i] if i < len(fields) else ''
                    self.event_fields[i].set(val)
                # update last_used
                p['last_used'] = int(time.time())
                # Reorder to keep last used first
                self.event_presets.sort(key=lambda x: x.get('last_used', 0), reverse=True)
                self._refresh_preset_combo()
                self.save_event_presets()
                break

    def _get_current_event_values(self) -> List[str]:
        return [v.get().strip() for v in self.event_fields]

    def save_event_clicked(self):
        # Build output line with local timestamp and user fields
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        fields = self._get_current_event_values()
        if not any(fields):
            messagebox.showwarning('No data', 'Please enter at least one field before saving the event.')
            return
        serial = self.sel.get().strip()
        if not serial:
            messagebox.showerror('Error', 'No device selected')
            return
        out_dir = self.effective_out_dir(serial)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            events_path = out_dir / 'events.txt'
            line = f"{ts}\t" + "\t".join(fields) + "\n"
            with open(events_path, 'a', encoding='utf-8') as fp:
                fp.write(line)
            self.log(f'Event saved -> {events_path}')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to write events.txt: {e}')
            return
        # Update presets using current fields; keep unique by exact fields list
        norm = fields[:]  # exact order
        if any(s for s in norm):
            found = None
            for p in self.event_presets:
                if p.get('fields') == norm:
                    found = p
                    break
            if found is None:
                found = {'fields': norm, 'last_used': int(time.time())}
                self.event_presets.insert(0, found)
            else:
                found['last_used'] = int(time.time())
            # Deduplicate by fields keeping first (most recent)
            seen = set()
            uniq = []
            for p in self.event_presets:
                key = tuple(p.get('fields') or [])
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(p)
            self.event_presets = uniq
            self.event_presets.sort(key=lambda x: x.get('last_used', 0), reverse=True)
            self._refresh_preset_combo()
            self.save_event_presets()

    # === Per-field presets and logging ===
    def load_field_presets(self):
        try:
            if self.per_field_presets_file.exists():
                with open(self.per_field_presets_file, 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                # Accept either list-of-lists or dict with keys 'fields'
                if isinstance(data, list) and len(data) == 4:
                    lists = data
                elif isinstance(data, dict) and 'fields' in data and isinstance(data['fields'], list) and len(data['fields']) == 4:
                    lists = data['fields']
                else:
                    lists = [[], [], [], []]
                norm_lists: List[List[dict]] = [[], [], [], []]
                for i in range(4):
                    lst = lists[i] if i < len(lists) else []
                    if isinstance(lst, list):
                        for item in lst:
                            if isinstance(item, dict) and 'value' in item:
                                v = str(item.get('value', '')).strip()
                                if not v:
                                    continue
                                last = int(item.get('last_used', 0) or 0)
                                norm_lists[i].append({'value': v, 'last_used': last})
                self.field_presets = norm_lists
                # Dedup and sort
                for i in range(4):
                    self._dedup_and_sort_field_presets(i)
            else:
                self.field_presets = [[], [], [], []]
        except Exception as e:
            self.log(f'Failed to load per-field presets: {e}')
            self.field_presets = [[], [], [], []]

    def save_field_presets(self):
        try:
            with open(self.per_field_presets_file, 'w', encoding='utf-8') as fp:
                json.dump(self.field_presets, fp, indent=2)
        except Exception as e:
            self.log(f'Failed to save per-field presets: {e}')

    def _refresh_field_preset_combo(self, idx: int):
        try:
            values = [item['value'] for item in self.field_presets[idx]]
            if idx < len(self.field_preset_combos) and self.field_preset_combos[idx]:
                self.field_preset_combos[idx]['values'] = values
            # Set selection to first (most recent) if list not empty
            if values:
                self.field_selected_preset_vars[idx].set(values[0])
            else:
                self.field_selected_preset_vars[idx].set('')
        except Exception:
            pass

    def _dedup_and_sort_field_presets(self, idx: int):
        seen = set()
        uniq: List[dict] = []
        for item in self.field_presets[idx]:
            key = item.get('value', '').strip()
            if not key or key in seen:
                continue
            seen.add(key)
            # ensure last_used exists
            if 'last_used' not in item:
                item['last_used'] = 0
            uniq.append(item)
        uniq.sort(key=lambda x: x.get('last_used', 0), reverse=True)
        self.field_presets[idx] = uniq

    def apply_field_preset(self, idx: int):
        try:
            sel = self.field_selected_preset_vars[idx].get()
            if not sel:
                return
            # Set the entry to selected value
            self.event_fields[idx].set(sel)
            # Update last_used and reorder
            now = int(time.time())
            updated = False
            for item in self.field_presets[idx]:
                if item.get('value') == sel:
                    item['last_used'] = now
                    updated = True
                    break
            if not updated:
                self.field_presets[idx].insert(0, {'value': sel, 'last_used': now})
            self._dedup_and_sort_field_presets(idx)
            self._refresh_field_preset_combo(idx)
            self.save_field_presets()
        except Exception as e:
            self.log(f'Error applying field preset: {e}')

    def save_single_event(self, idx: int):
        try:
            value = self.event_fields[idx].get().strip()
            if not value:
                messagebox.showwarning('No data', f'Field {idx+1} is empty.')
                return
            serial = self.sel.get().strip()
            if not serial:
                messagebox.showerror('Error', 'No device selected')
                return
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            out_dir = self.effective_out_dir(serial)
            out_dir.mkdir(parents=True, exist_ok=True)
            events_path = out_dir / 'events.txt'
            line = f"{ts}\tField{idx+1}\t{value}\n"
            with open(events_path, 'a', encoding='utf-8') as fp:
                fp.write(line)
            self.log(f'Event (Field {idx+1}) saved -> {events_path}')
            # Update per-field presets
            now = int(time.time())
            found = None
            for item in self.field_presets[idx]:
                if item.get('value') == value:
                    found = item
                    break
            if found is None:
                self.field_presets[idx].insert(0, {'value': value, 'last_used': now})
            else:
                found['last_used'] = now
            self._dedup_and_sort_field_presets(idx)
            self._refresh_field_preset_combo(idx)
            self.save_field_presets()
        except Exception as e:
            messagebox.showerror('Error', f'Failed to write events.txt: {e}')

    def _migrate_old_event_presets_to_field_presets(self):
        # Seed per-field preset lists from old combined presets if present
        try:
            if not any(self.field_presets):
                for p in self.event_presets:
                    fields = p.get('fields') or []
                    last = int(p.get('last_used', 0) or 0)
                    for i in range(4):
                        if i < len(fields):
                            v = str(fields[i]).strip()
                            if not v:
                                continue
                            self.field_presets[i].append({'value': v, 'last_used': last})
                for i in range(4):
                    self._dedup_and_sort_field_presets(i)
        except Exception as e:
            self.log(f'Preset migration warning: {e}')

    def effective_out_dir(self, serial: str) -> Path:
        base = Path(self.log_dir.get())
        test_name = self.test_name.get().strip()
        cached = getattr(self, 'session_out_dir', None)
        if getattr(self, 'session_active', False) and cached is not None:
            return self.session_out_dir
        if (
            cached is not None
            and getattr(self, 'session_output_serial', '') == serial
            and getattr(self, 'session_output_test_name', '') == test_name
            and getattr(self, 'session_output_base', None) == base
        ):
            return cached
        folder = build_session_folder_name(format_log_timestamp(), test_name, serial)
        self.session_out_dir = base / folder
        self.session_output_serial = serial
        self.session_output_test_name = test_name
        self.session_output_base = base
        return self.session_out_dir

    def take_screenshot_clicked(self):
        serial = self.sel.get().strip()
        if not serial:
            messagebox.showerror('Error', 'No device selected')
            return
        out_dir = self.effective_out_dir(serial)
        self.screenshot_button.configure(state='disabled')
        self.busy(True)
        self.log('Taking screenshot...')
        self.run_bg(self._take_screenshot_worker, serial, out_dir)

    def _take_screenshot_worker(self, serial: str, out_dir: Path):
        try:
            screenshot_path = take_device_screenshot(serial, out_dir)
            self.log(f'Screenshot saved -> {screenshot_path}')
            self.after(0, lambda: self.status.set(f'Screenshot saved -> {screenshot_path}'))
        except Exception as e:
            self.log(f'Failed to take screenshot: {e}')
            self.after(0, lambda error=str(e): messagebox.showerror(
                'Screenshot failed', f'Failed to take screenshot: {error}'
            ))
        finally:
            self.busy(False)
            self.after(0, lambda: self.screenshot_button.configure(state='normal'))

    def clear_output_dir_clicked(self):
        try:
            # Prevent clearing while a session is running
            if getattr(self, 'session_active', False):
                messagebox.showwarning('Session active', 'Please stop logging before clearing the output directory.')
                return
            serial = self.sel.get().strip()
            if not serial:
                messagebox.showerror('Error', 'No device selected')
                return
            out_dir = self.effective_out_dir(serial)
            # Confirm with the user
            msg = (
                'Clear ALL files and subfolders in the current output directory?\n\n'
                f'{out_dir}\n\n'
                'This will permanently delete files in that folder.'
            )
            if not messagebox.askyesno('Confirm clear output', msg, icon='warning'):
                return
            # Ensure directory exists (if not, nothing to do)
            if not out_dir.exists():
                self.log(f'Output directory does not exist: {out_dir} (nothing to clear).')
                messagebox.showinfo('Nothing to clear', f'No output directory found for {serial}.')
                return
            # Safety: only clear contents, keep the directory itself
            errors = []
            for child in list(out_dir.iterdir()):
                try:
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        try:
                            child.unlink()
                        except FileNotFoundError:
                            pass
                except Exception as e:
                    errors.append((str(child), str(e)))
            if errors:
                self.log('Clear output completed with errors:')
                for path, err in errors:
                    self.log(f'  Failed to remove {path}: {err}')
                messagebox.showwarning('Partial clear', f'Output cleared with {len(errors)} errors. See log for details.')
            else:
                self.log(f'Output directory cleared: {out_dir}')
                messagebox.showinfo('Cleared', 'Output directory contents have been cleared.')
            # Refresh UI state/status text
            try:
                self.status.set('Idle (output cleared)')
            except Exception:
                pass
        except Exception as e:
            try:
                self.log(f'Failed to clear output directory: {e}')
            except Exception:
                pass
            messagebox.showerror('Error', f'Failed to clear output directory: {e}')

    def start_all(self):
        serial = self.sel.get()
        if not serial:
            messagebox.showerror('Error', 'No device selected')
            return
        if self.capture_modem.get():
            profile = self.selected_modem_profile()
            if profile is None:
                messagebox.showerror(
                    'Modem profile required',
                    f'No enabled modem profile is selected for chipset {self.chipset.get()!r}.\n\n'
                    'Choose the chipset, then select or create a compatible modem profile.',
                )
                return
            self.active_modem_profile = profile
            self.active_modem_remote_path = ''
            self.active_mtk_log_paths = {}
            self.mtk_log_paths_before = {}
            self.active_samsung_log_files = []
            self.samsung_log_files_before = []
            self.modem_capture_started = False
        else:
            self.active_modem_profile = None
            self.active_modem_remote_path = ''
            self.active_mtk_log_paths = {}
            self.mtk_log_paths_before = {}
            self.active_samsung_log_files = []
            self.samsung_log_files_before = []
            self.modem_capture_started = False
        # Reset session/watchdog flags
        self.session_active = True
        self._set_session_ui(True)
        # Capture this once so every start/stop action targets the same session folder.
        session_timestamp = format_log_timestamp()
        self.session_out_dir = Path(self.log_dir.get()) / build_session_folder_name(
            session_timestamp, self.test_name.get(), serial
        )
        self.session_output_serial = serial
        self.session_output_test_name = self.test_name.get().strip()
        self.session_output_base = Path(self.log_dir.get())
        self.auto_stopping = False
        self.disconnected_notified = False
        self.watchdog_event = threading.Event()
        self.active_serial = serial
        # Remember last active serial; clear any pending reconnect state
        self.last_active_serial = serial
        self.session_was_active_on_disconnect = False
        try:
            if hasattr(self, 'reconnect_event') and self.reconnect_event is not None:
                self.reconnect_event.set()
        except Exception:
            pass
        self.busy(True)
        self.log('Starting logging session...')
        self.run_bg(self._start_all_worker, serial)

    def _start_all_worker(self, serial: str):
        # Wake device and take initial screenshot if requested
        try:
            if self.capture_screenshot.get():
                run([ADB, '-s', serial, 'shell', 'input', 'keyevent', 'KEYCODE_WAKEUP'])
                time.sleep(0.5)
                run([ADB, '-s', serial, 'shell', 'wm', 'dismiss-keyguard'])
        except Exception:
            pass
        out_dir = self.effective_out_dir(serial)
        out_dir.mkdir(parents=True, exist_ok=True)
        # Write device info at the very beginning of the test
        try:
            self.write_device_info(serial, out_dir)
        except Exception as e:
            self.log(f'Failed to write device info: {e}')
        actions = []
        # Initial screenshot capture
        if self.capture_screenshot.get():
            try:
                self.log('Taking initial screenshot...')
                take_device_screenshot(serial, out_dir, prefix='start_screenshot')
                actions.append('screenshot')
            except Exception as e:
                self.log(f'Failed to take screenshot: {e}')
        if self.oem_logger.get() != 'None':
            self.log(f'Starting OEM logger: {self.oem_logger.get()}')
            self.start_oem_logger(serial)
            actions.append('OEM logger')
        if self.capture_logcat.get():
            self.log('Starting logcat streams...')
            procs, files = start_logcat_streams(serial, out_dir)
            self.logcat_procs, self.logcat_files = procs, files
            actions.append('logcat')
        if self.capture_tcpdump.get():
            tcpdump_local = Path(self.tcpdump_path.get())
            if tcpdump_local.exists():
                self.log('Starting tcpdump...')
                try:
                    proc, pcap = start_tcpdump(serial, out_dir, tcpdump_local)
                    self.tcpdump_proc = proc
                    actions.append('tcpdump')
                    self.log(f'tcpdump started -> {pcap}')
                except Exception as e:
                    self.tcpdump_proc = None
                    self.log(f'Failed to start tcpdump: {e}')
            else:
                self.log('tcpdump binary not found on host; skipping tcpdump.')
        if self.capture_screenrecord.get():
            try:
                run([ADB, '-s', serial, 'shell', 'mkdir', '-p', '/sdcard/Logs/tmp'])
                # Screenrecord preflight diagnostics
                try:
                    # Check tool presence and versions
                    ver = run([ADB, '-s', serial, 'shell', 'getprop', 'ro.build.version.release']).stdout.strip()
                    sr_which = run([ADB, '-s', serial, 'shell', 'which', 'screenrecord']).stdout.strip()
                    self.log(f'screenrecord preflight: Android={ver or "?"}, which={sr_which or "(not found)"}')
                    # Free space on /sdcard
                    df_out = run([ADB, '-s', serial, 'shell', 'df', '-k', '/sdcard']).stdout or ''
                    last = df_out.strip().splitlines()[-1] if df_out.strip() else ''
                    if last:
                        self.log('SDCard df -k: ' + last)
                    # Write/Read test in /sdcard/Logs/tmp
                    ts = int(time.time())
                    test_path = f"/sdcard/Logs/tmp/.sr_write_test_{ts}"
                    wr = run_shell(serial, f"echo test > {test_path} && ls -l {test_path}")
                    self.log(f'Write test to {test_path}: rc={wr.returncode} out={(wr.stdout or "").strip()}')
                    run([ADB, '-s', serial, 'shell', 'rm', '-f', test_path])
                    # Existing screenrecord processes
                    ps = run_shell(serial, "ps -A | grep -w screenrecord || true").stdout or ''
                    if ps.strip():
                        self.log('Existing screenrecord processes prior to start:\n' + ps.strip())
                except Exception as e:
                    self.log(f'Preflight diagnostics error (non-fatal): {e}')
                # Detect screenrecord capabilities and choose correct syntax
                caps = self._detect_screenrecord_caps(serial)
                if not caps:
                    caps = {}
                if caps.get('syntax') == 'unknown':
                    # Default to positional syntax on v1.4+; proceed best-effort
                    caps = {
                        'syntax': 'positional',
                        'tflag': '--time-limit',
                        'bitrate_flag': '--bit-rate',
                    }
                    self.screenrecord_caps = caps
                    self.log('screenrecord: proceeding with default positional syntax (v1.4) despite inconclusive probe.')
                quality = self.video_quality.get()
                bitrate = video_quality_bitrate(quality)
                bitrate_args = screenrecord_bitrate_args(quality, caps)
                bitrate_shell = (' ' + ' '.join(bitrate_args)) if bitrate_args else ''
                if bitrate is None:
                    self.log('Screen recording quality: device default bitrate.')
                elif bitrate_args:
                    self.log(f'Screen recording quality: {quality}.')
                else:
                    self.log(
                        f'Screen recording quality {quality} requested, but this device does not '
                        'advertise bitrate control; using its default bitrate.'
                    )
                if self.capture_screenrecord.get() and self.segmented_screenrecord.get():
                    seg_len = int(self.segment_length.get() or 15)
                    if seg_len < 5:
                        seg_len = 5
                    if seg_len > 300:
                        seg_len = 300
                    # Record session epoch and create device-side marker for discovery by mtime
                    self.session_start_epoch = int(time.time())
                    epoch = self.session_start_epoch
                    segment_remote_dir = f"/sdcard/Logs/tmp/screenrecord_{epoch}"
                    self.screenrecord_segment_dir = segment_remote_dir
                    try:
                        run([ADB, '-s', serial, 'shell', 'mkdir', '-p', '/sdcard/Logs/tmp'])
                        run([ADB, '-s', serial, 'shell', 'mkdir', '-p', segment_remote_dir])
                        run_shell(serial, f"touch /sdcard/Logs/tmp/.sr_marker_{epoch}")
                        # Optional: log free space on /sdcard
                        df_out = run([ADB, '-s', serial, 'shell', 'df', '-k', '/sdcard']).stdout.strip()
                        if df_out:
                            self.log('SDCard space (KB): ' + df_out.splitlines()[-1])
                    except Exception:
                        pass
                    self.log(f'Starting segmented screen recording ({seg_len}s segments)...')
                    self.log(f'Segment filename format: {format_log_timestamp()}_screenRecord_<segmentNum>.mp4')
                    # Build a loop that gives every segment its start time and sequence number.
                    stop_flag = f"/sdcard/Logs/tmp/.sr_stop_{epoch}"
                    self.screenrecord_stop_flag = stop_flag
                    tflag = caps.get('tflag', '-t')
                    if caps.get('syntax') == 'dash_o':
                        seg_cmd = f"screenrecord{bitrate_shell} {tflag} {seg_len} -o \"$out\""
                    else:
                        seg_cmd = f"screenrecord{bitrate_shell} {tflag} {seg_len} \"$out\""
                    loop_body = (
                        f"stop={stop_flag}; rm -f \"$stop\"; "
                        f"i=0; while true; do "
                        f"[ -f \"$stop\" ] && break; "
                        f"out={segment_remote_dir}/$(date +{LOG_TIMESTAMP_FORMAT})_screenRecord_$i.mp4; "
                        f"{seg_cmd}; "
                        f"i=$((i+1)); done"
                    )
                    # Detach the loop so adb shell returns instead of waiting for its jobs.
                    pid_res = None
                    pid_txt = ''
                    loop_alive = False
                    detach_commands = [
                        f"nohup sh -c '{loop_body}' >/dev/null 2>&1 </dev/null & echo $!",
                        f"setsid sh -c '{loop_body}' >/dev/null 2>&1 </dev/null & echo $!",
                    ]
                    for detach_cmd in detach_commands:
                        try:
                            candidate = run_shell(serial, detach_cmd, timeout=8)
                        except subprocess.TimeoutExpired:
                            continue
                        candidate_pid = (candidate.stdout or '').strip()
                        if (
                            candidate.returncode == 0
                            and candidate_pid.isdigit()
                            and _remote_process_alive(serial, int(candidate_pid))
                        ):
                            pid_res = candidate
                            pid_txt = candidate_pid
                            loop_alive = True
                            break
                    if pid_res is not None and pid_txt.isdigit() and loop_alive:
                        try:
                            self.screenrecord_loop_pid = int(pid_txt)
                        except Exception:
                            self.screenrecord_loop_pid = None
                        self.screenrecord_remote = None
                        self.screenrecord_pid = None
                        # Persist PID to a file on device for later retrieval
                        try:
                            run_shell(serial, f"echo {pid_txt} > /sdcard/Logs/tmp/.sr_loop_{epoch}.pid")
                        except Exception:
                            pass
                        self.log(f'Segmented screenrecord loop started with PID {pid_txt}')
                    else:
                        self.log('Failed to start segmented loop; will still attempt discovery-based pulls on stop. Falling back to single-file screenrecord...')
                        self.segmented_screenrecord.set(False)
                        # Fall through to single-file start below
                if self.capture_screenrecord.get() and not self.segmented_screenrecord.get():
                    self.log('Starting screen recording...')
                    ts_launch = int(time.time())
                    remote_mp4 = f"/sdcard/Logs/tmp/screen_{ts_launch}.mp4"
                    err_path = f"/sdcard/Logs/tmp/.sr_err_{ts_launch}.txt"
                    self.screenrecord_err_path = err_path
                    self.screenrecord_start_epoch = ts_launch
                    self.screenrecord_start_failed = False
                    # Launch screenrecord in background on device and capture its PID with stderr redirected to device file
                    # Prefer positional output syntax first (works on AOSP v1.4+), then fall back to -o if needed
                    tried_syntaxes = []
                    def _try_launch(use_dash_o: bool):
                        output_arg = f'-o {remote_mp4}' if use_dash_o else remote_mp4
                        cmd = f"screenrecord{bitrate_shell} {output_arg}"
                        lc = f"{cmd} >/dev/null 2> {err_path} </dev/null & echo $!"
                        res = run_shell(serial, lc)
                        pid_text = (res.stdout or '').strip()
                        if res.returncode != 0 or not pid_text.isdigit():
                            return res, '', False
                        time.sleep(0.5)
                        return res, pid_text, _remote_process_alive(serial, int(pid_text))

                    preferred_dash_o = caps.get('syntax') == 'dash_o'
                    launch_order = [preferred_dash_o, not preferred_dash_o]
                    pid_res = None
                    pid_txt = ''
                    launch_alive = False
                    for use_dash_o in launch_order:
                        syntax_name = 'dash_o' if use_dash_o else 'positional'
                        tried_syntaxes.append(syntax_name)
                        pid_res, pid_txt, launch_alive = _try_launch(use_dash_o)
                        if launch_alive:
                            break
                        err_peek = _remote_text(serial, err_path)
                        if err_peek:
                            self.log(f'screenrecord {syntax_name} failed: ' + err_peek.splitlines()[0])
                        run([ADB, '-s', serial, 'shell', 'rm', '-f', remote_mp4, err_path])

                    if pid_res is not None and launch_alive and pid_txt.isdigit():
                        self.screenrecord_remote = remote_mp4
                        self.screenrecord_pid = int(pid_txt)
                        self.log(f"screenrecord started with PID {self.screenrecord_pid} -> {remote_mp4} (syntax tried: {tried_syntaxes})")
                        # Correlate PID and process list (best-effort)
                        try:
                            ps_lines = run_shell(serial, "ps -A | grep -w screenrecord || true").stdout or ''
                            if ps_lines.strip():
                                self.log('Process list around start (screenrecord):\n' + ps_lines.strip())
                        except Exception:
                            pass
                        # A live process is the reliable startup signal. Some encoders do not
                        # publish MP4 bytes until SIGINT finalizes the container.
                        try:
                            rsz = self._remote_file_size(serial, remote_mp4)
                            self.log(f'screenrecord startup check: process alive, current file size={rsz} bytes')
                        except Exception:
                            pass
                    else:
                        # Fallback: keep adb attached, but verify the command remains alive.
                        self.log('Failed to get remote PID; falling back to attached screenrecord process...')
                        self.screenrecord_remote = remote_mp4
                        self.screenrecord_proc = None
                        for use_dash_o in launch_order:
                            cmd_parts = ['screenrecord'] + bitrate_args
                            if use_dash_o:
                                cmd_parts.append('-o')
                            cmd_parts.append(remote_mp4)
                            candidate = subprocess.Popen(
                                [ADB, '-s', serial, 'shell'] + cmd_parts,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            time.sleep(0.5)
                            if candidate.poll() is None:
                                self.screenrecord_proc = candidate
                                break
                        if self.screenrecord_proc is None:
                            self.screenrecord_start_failed = True
                            detail = _remote_text(serial, err_path)
                            raise RuntimeError(detail or 'screenrecord exited during attached startup')
                    actions.append('screenrecord')
            except Exception as e:
                self.log(f'Failed to start screenrecord: {e}')
        if self.capture_modem.get():
            try:
                profile_name = (self.active_modem_profile or {}).get('name', 'unknown')
                self.log(f'Starting modem logging with profile: {profile_name}')
                self.start_modem_logging(serial)
                actions.append(f'modem ({profile_name})')
            except Exception as exc:
                self.log(f'Failed to start modem logging: {exc}')
        # Record START CSV snapshot
        try:
            self.log('Recording START snapshot...')
            self.write_snapshot_csv(serial, out_dir, phase='START')
        except Exception as e:
            self.log(f'Failed to write START snapshot: {e}')
        try:
            self.after(0, lambda: self.status.set(f"Started: {', '.join(actions)} -> {out_dir}"))
        except Exception:
            pass
        self.log(f"Started components: {', '.join(actions)}")
        # Start watchdog to monitor device connectivity (optional via UI toggle)
        try:
            if self.enable_watchdog.get():
                if self.watchdog_thread is None or not self.watchdog_thread.is_alive():
                    self.watchdog_thread = self.run_bg(self._device_watchdog, serial)
                self.log('Watch-dog enabled (will auto-stop on disconnect).')
            else:
                self.log('Watch-dog disabled (will NOT auto-stop on disconnect).')
        except Exception:
            pass
        self.busy(False)

    def stop_all(self):
        serial = self.sel.get()
        # Signal watchdog/session to stop monitoring
        try:
            self.session_active = False
            if hasattr(self, 'watchdog_event') and self.watchdog_event is not None:
                self.watchdog_event.set()
        except Exception:
            pass
        self._set_session_ui(False, stopping=True)
        self.busy(True)
        if getattr(self, 'auto_stopping', False):
            self.log('Auto-stopping logging session due to device disconnect...')
        else:
            self.log('Stopping logging session...')
        self.run_bg(self._stop_all_worker, serial)

    def _stop_all_worker(self, serial: str):
        try:
            self.log('Stopping tcpdump...')
            self.stop_tcpdump_clicked()
            self.log('Stopping logcat...')
            self.stop_logcat_clicked()
        except Exception as e:
            self.log(f'Error stopping captures: {e}')
        # Stop screenrecord and pull if enabled
        # Handle screenrecord stop and pull with flush/verification
        out_dir = self.effective_out_dir(serial)
        out_dir.mkdir(parents=True, exist_ok=True)
        # Segmented mode branch (pull segments regardless of PID availability)
        if self.capture_screenrecord.get() and self.segmented_screenrecord.get():
            epoch = getattr(self, 'session_start_epoch', 0)
            # Try to retrieve loop PID from memory or PID file
            loop_pid = getattr(self, 'screenrecord_loop_pid', None)
            if not loop_pid and epoch:
                try:
                    pid_text = run([ADB, '-s', serial, 'shell', 'cat', f'/sdcard/Logs/tmp/.sr_loop_{epoch}.pid']).stdout.strip()
                    if pid_text.isdigit():
                        loop_pid = int(pid_text)
                        self.log(f'Recovered segmented loop PID from device file: {loop_pid}')
                except Exception:
                    pass
            # Attempt graceful stop of loop to let last segment finalize
            if loop_pid:
                try:
                    seg_len = 15
                    try:
                        seg_len = int(self.segment_length.get() or 15)
                    except Exception:
                        seg_len = 15
                    # Create stop flag so loop will exit after current chunk
                    stop_flag = getattr(self, 'screenrecord_stop_flag', f"/sdcard/Logs/tmp/.sr_stop_{epoch}")
                    run_shell(serial, f"touch {stop_flag}")
                    self.log(f'Stopping segmented screenrecord loop (SIGINT {loop_pid}) ...')
                    run([ADB, '-s', serial, 'shell', 'kill', '-2', str(loop_pid)])
                    # Also try to gracefully stop any running screenrecord child for this session
                    kill_children = (
                        f"pkill -2 -f 'screenrecord .*screenrecord_{epoch}/' 2>/dev/null || "
                        f"for p in $(ps -A | grep 'screenrecord' | grep 'screenrecord_{epoch}/' | awk '{{print $1}}'); do kill -2 $p; done"
                    )
                    run_shell(serial, kill_children)
                    # Wait up to seg_len+8 seconds for loop and children to stop
                    t_deadline = time.time() + max(8, seg_len + 8)
                    while time.time() < t_deadline:
                        ps = run_shell(serial, f"ps -A | grep -w {loop_pid} || true").stdout
                        child = run_shell(serial, f"ps -A | grep 'screenrecord' | grep 'screenrecord_{epoch}/' || true").stdout
                        if (not ps or str(loop_pid) not in ps) and (not child or 'screenrecord' not in child):
                            break
                        time.sleep(0.3)
                    try:
                        run([ADB, '-s', serial, 'shell', 'sync'])
                    except Exception:
                        pass
                    time.sleep(1.0)
                except Exception as e:
                    self.log(f'Error stopping segmented loop: {e}')
            else:
                self.log('Segmented loop PID not available; proceeding to stop any running screenrecord children and pull by discovery.')
                try:
                    # Create stop flag so loop (if alive) will exit after current chunk
                    stop_flag = getattr(self, 'screenrecord_stop_flag', f"/sdcard/Logs/tmp/.sr_stop_{epoch}")
                    run_shell(serial, f"touch {stop_flag}")
                    # Try to gracefully stop any screenrecord child for this session prefix
                    kill_children = (
                        f"pkill -2 -f 'screenrecord .*screenrecord_{epoch}/' 2>/dev/null || "
                        f"for p in $(ps -A | grep 'screenrecord' | grep 'screenrecord_{epoch}/' | awk '{{print $1}}'); do kill -2 $p; done"
                    )
                    run_shell(serial, kill_children)
                    time.sleep(1.0)
                except Exception:
                    pass
            # Discover and pull segments for this session
            if self.is_device_connected(serial):
                try:
                    seg_dir = out_dir / 'Video_Recording'
                    seg_dir.mkdir(parents=True, exist_ok=True)
                    manifest = out_dir / 'Video_Recording'/ 'segments_manifest.txt'
                    pulled = 0
                    candidates: List[str] = []
                    if epoch:
                        segment_remote_dir = getattr(
                            self, 'screenrecord_segment_dir', f"/sdcard/Logs/tmp/screenrecord_{epoch}"
                        )
                        ls_cmd = f"ls -1 {segment_remote_dir}/*.mp4 2>/dev/null"
                        ls_res = run_shell(serial, ls_cmd)
                        candidates = [p.strip() for p in (ls_res.stdout or '').splitlines() if p.strip().startswith('/sdcard/')]
                    with open(manifest, 'w', encoding='utf-8') as mf:
                        mf.write('filename\tremote_bytes\tlocal_bytes\tstatus\n')
                        bytes_freed = 0
                        for remote in candidates:
                            base = os.path.basename(remote)
                            local = seg_dir / base
                            rsz = self._remote_file_size(serial, remote)
                            if rsz <= 0:
                                status = 'skip_zero'
                                mf.write(f"{base}\t{rsz}\t0\t{status}\n")
                                continue
                            self._wait_for_file_stable(serial, remote, stable_samples=3, interval=0.5, timeout=(int(self.segment_length.get() or 15)+10))
                            self._settle_and_pull_video(serial, remote, local, max_retries=2)
                            try:
                                lsz = local.stat().st_size
                            except Exception:
                                lsz = 0
                            status = 'ok' if (lsz >= rsz and lsz > 0) else 'incomplete'
                            if status == 'ok':
                                pulled += 1
                                # Remove remote segment after successful pull to free space
                                try:
                                    run([ADB, '-s', serial, 'shell', 'rm', '-f', remote])
                                    bytes_freed += rsz
                                except Exception:
                                    pass
                            mf.write(f"{base}\t{rsz}\t{lsz}\t{status}\n")
                    # Cleanup marker/flag files and report space reclaimed
                    try:
                        if epoch:
                            run([ADB, '-s', serial, 'shell', 'rm', '-f', f"/sdcard/Logs/tmp/.sr_marker_{epoch}", f"/sdcard/Logs/tmp/.sr_stop_{epoch}", f"/sdcard/Logs/tmp/.sr_loop_{epoch}.pid"])    
                            segment_remote_dir = getattr(
                                self, 'screenrecord_segment_dir', f"/sdcard/Logs/tmp/screenrecord_{epoch}"
                            )
                            run([ADB, '-s', serial, 'shell', 'rmdir', segment_remote_dir])
                    except Exception:
                        pass
                    if bytes_freed > 0:
                        self.log(f'Segmented cleanup: freed approximately {bytes_freed} bytes on device.')
                    # HOWTO
                    howto = out_dir / 'HOWTO_Play_Segments.txt'
                    try:
                        with open(howto, 'w', encoding='utf-8') as hf:
                            hf.write('These screenrecord segments are finalized MP4s recorded in sequence.\n')
                            hf.write('Play them in filename order. To merge with ffmpeg (if installed):\n')
                            hf.write('  1) In the segments folder, create list.txt with lines: file "<filename>"\n')
                            hf.write('  2) Run: ffmpeg -f concat -safe 0 -i list.txt -c copy merged.mp4\n')
                    except Exception:
                        pass
                    self.log(f'Segmented recording: pulled {pulled}/{len(candidates)} segments.')
                    # Early-stop informative message
                    try:
                        seg_len = int(self.segment_length.get() or 15)
                        run_time = max(0, int(time.time()) - int(epoch or 0))
                        if pulled == 0 and run_time < seg_len:
                            self.log('No segments finalized: session shorter than segment length. Let it run longer or reduce segment length.')
                    except Exception:
                        pass
                except Exception as e:
                    self.log(f'Failed to pull segmented screen recordings: {e}')
        else:
            # Single-file mode stop/pull
            remote_mp4 = getattr(self, 'screenrecord_remote', None)
            screen_pid = getattr(self, 'screenrecord_pid', None)
            if screen_pid:
                try:
                    self.log(f'Stopping screenrecord gracefully (SIGINT {screen_pid}) ...')
                    run([ADB, '-s', serial, 'shell', 'kill', '-2', str(screen_pid)])
                    # Wait for process exit (up to 5s), escalate if needed
                    t0 = time.time()
                    while time.time() - t0 < 5.0:
                        if not _remote_process_alive(serial, int(screen_pid)):
                            break
                        time.sleep(0.3)
                    else:
                        self.log('screenrecord still running; sending SIGKILL...')
                        run([ADB, '-s', serial, 'shell', 'kill', '-9', str(screen_pid)])
                except Exception as e:
                    self.log(f'Error signaling screenrecord: {e}')
            elif getattr(self, 'screenrecord_proc', None) is not None:
                try:
                    self.log('Stopping attached screenrecord process...')
                    if remote_mp4:
                        run_shell(
                            serial,
                            f"pkill -2 -f 'screenrecord .*{remote_mp4}' 2>/dev/null || true",
                        )
                        time.sleep(0.5)
                    self.screenrecord_proc.terminate()
                    self.screenrecord_proc.wait(timeout=3)
                except Exception:
                    pass
            # Pull video to output dir with settle and verification
            if remote_mp4 and self.is_device_connected(serial):
                try:
                    target_local = out_dir / 'screenrecord.mp4'
                    # Inspect remote size/mtime before pulling
                    try:
                        rsz = self._remote_file_size(serial, remote_mp4)
                        rmt = self._remote_mtime(serial, remote_mp4)
                        self.log(f'Remote video before pull: size={rsz} bytes, mtime={rmt}')
                        # If zero/missing or start_failed flagged, gather diagnostics before pull
                        if rsz <= 0 or getattr(self, 'screenrecord_start_failed', False):
                            try:
                                self.log('Collecting screenrecord diagnostics before pull (zero-byte or start_failed)...')
                                # ls -l and stat
                                ls_out = run([ADB, '-s', serial, 'shell', 'ls', '-l', remote_mp4]).stdout or ''
                                st_out = run_shell(serial, f"stat -c '%s %Y' {remote_mp4} 2>/dev/null || echo 'stat_failed' ").stdout or ''
                                self.log(f'ls -l {remote_mp4}: ' + ls_out.strip())
                                self.log(f"stat -c '%s %Y' {remote_mp4}: " + st_out.strip())
                                try:
                                    run([ADB, '-s', serial, 'shell', 'sync'])
                                except Exception:
                                    pass
                                # Pull device-side stderr if present
                                err_path = getattr(self, 'screenrecord_err_path', '') or ''
                                if err_path:
                                    try:
                                        # Check existence and size
                                        err_sz = self._remote_file_size(serial, err_path)
                                        if err_sz >= 0:  # even 0-size may be informative
                                            dst = out_dir / 'screenrecord_stderr.txt'
                                            res_pe = run([ADB, '-s', serial, 'pull', err_path, str(dst)])
                                            if res_pe.returncode == 0:
                                                try:
                                                    lsz = dst.stat().st_size
                                                    self.log(f'Pulled screenrecord stderr to {dst.name} ({lsz} bytes).')
                                                except Exception:
                                                    self.log('Pulled screenrecord stderr to local file.')
                                                # Cleanup stderr on device
                                                try:
                                                    run([ADB, '-s', serial, 'shell', 'rm', '-f', err_path])
                                                    if err_sz > 0:
                                                        self.log(f'Diagnostics cleanup: removed device stderr file (~{err_sz} bytes).')
                                                except Exception:
                                                    pass
                                            else:
                                                self.log(f'Failed to pull stderr file from device (rc={res_pe.returncode}).')
                                    except Exception:
                                        pass
                                # Capture filtered logcat and other signals
                                try:
                                    diag_path = out_dir / 'screenrecord_diag.txt'
                                    with open(diag_path, 'w', encoding='utf-8', errors='ignore') as df:
                                        df.write('=== Filtered logcat (screenrecord/mediacodec/SurfaceControl/Permission/avc) ===\n')
                                        grep_cmd = "logcat -v threadtime -d -t 2000 | grep -E 'screenrecord|mediacodec|SurfaceControl|Permission|avc:' || true"
                                        flt = run_shell(serial, grep_cmd).stdout or ''
                                        df.write(flt)
                                        df.write('\n\n=== getenforce ===\n')
                                        df.write((run([ADB, '-s', serial, 'shell', 'getenforce']).stdout or '').strip() + '\n')
                                        df.write('\n=== dmesg (tail -n 200) ===\n')
                                        df.write((run_shell(serial, 'dmesg | tail -n 200 2>/dev/null || echo dmesg_unavailable').stdout or ''))
                                        df.write('\n=== appops get shell ===\n')
                                        df.write((run([ADB, '-s', serial, 'shell', 'appops', 'get', 'shell']).stdout or ''))
                                        df.write('\n=== cmd media_projection list ===\n')
                                        df.write((run([ADB, '-s', serial, 'shell', 'cmd', 'media_projection', 'list']).stdout or ''))
                                    self.log(f'Wrote diagnostics to {diag_path.name}.')
                                except Exception as e:
                                    self.log(f'Failed to capture diagnostics: {e}')
                            except Exception:
                                pass
                    except Exception:
                        pass
                    self._settle_and_pull_video(serial, remote_mp4, target_local)
                    # Fallback: if file still missing or empty, try newest screen_*.mp4 under /sdcard/Logs/tmp
                    need_fallback = False
                    try:
                        if (not target_local.exists()) or target_local.stat().st_size == 0:
                            need_fallback = True
                    except Exception:
                        need_fallback = True
                    fallback_cand = None
                    if need_fallback:
                        self.log('Primary video not found locally after pull; searching for latest screen_*.mp4 on device...')
                        ls_res = run_shell(serial, "ls -t /sdcard/Logs/tmp/screen_*.mp4 2>/dev/null | head -n 1")            
                        cand = (ls_res.stdout or '').strip()
                        if cand:
                            fallback_cand = cand
                            self.log(f'Attempting fallback pull from {cand} ...')
                            res2 = run([ADB, '-s', serial, 'pull', cand, str(target_local)])
                            if res2.returncode != 0:
                                err2 = (res2.stderr or '').strip()
                                self.log(f'Fallback pull failed (rc={res2.returncode}). {err2}')
                            else:
                                try:
                                    sz = target_local.stat().st_size
                                    self.log(f'Fallback video pulled successfully ({sz} bytes).')
                                except Exception:
                                    pass
                        else:
                            self.log('No screen_*.mp4 found on device for fallback.')
                    # If we have a local file now, remove remote(s) to free space
                    try:
                        if target_local.exists() and target_local.stat().st_size >= 12:
                            with open(target_local, 'rb') as video:
                                ok_local = video.read(12)[4:8] == b'ftyp'
                        else:
                            ok_local = False
                    except Exception:
                        ok_local = False
                    if ok_local:
                        bytes_freed = 0
                        try:
                            rsz1 = self._remote_file_size(serial, remote_mp4)
                            run([ADB, '-s', serial, 'shell', 'rm', '-f', remote_mp4])
                            bytes_freed += max(0, rsz1)
                        except Exception:
                            pass
                        if fallback_cand and fallback_cand != remote_mp4:
                            try:
                                rsz2 = self._remote_file_size(serial, fallback_cand)
                                run([ADB, '-s', serial, 'shell', 'rm', '-f', fallback_cand])
                                bytes_freed += max(0, rsz2)
                            except Exception:
                                pass
                        if bytes_freed > 0:
                            self.log(f'Single-file cleanup: freed approximately {bytes_freed} bytes on device.')
                except Exception as e:
                    self.log(f'Video pull/verify failed: {e}')
        if self.capture_modem.get():
            self.log('Stopping modem logging...')
            try:
                self.stop_modem_logging(serial)
            except Exception as exc:
                self.log(f'Failed to stop/finalize modem logging: {exc}')
        # Trigger OEM log collection if applicable before stopping app
        if self.oem_logger.get() == 'Motorola Bug2Go':
            self.log('Triggering Bug2Go finalization...')
            run([ADB, '-s', serial, 'shell', 'am', 'broadcast', '-a', 'com.motorola.intent.action.BUG2GO'])
            time.sleep(5)
            out_dir = self.effective_out_dir(serial)
            moto_dir = out_dir / 'Bug2Go'
            moto_dir.mkdir(parents=True, exist_ok=True)
            for path in ['/sdcard/bug2go', '/sdcard/motorola/bug2go', '/sdcard/Download/bug2go']:
                self.log(f'Pulling Bug2Go from {path} ...')
                run([ADB, '-s', serial, 'pull', path, str(moto_dir)])
        if self.oem_logger.get() != 'None':
            self.stop_oem_logger(serial)
        # END snapshot CSV and optional bugreport
        out_dir = self.effective_out_dir(serial)
        try:
            self.write_snapshot_csv(serial, out_dir, phase='END')
        except Exception:
            pass
        if self.capture_bugreport.get():
            if self.is_device_connected(serial):
                # Use adb bugreport to a file in out_dir
                br_path = out_dir / f'bugreport_{int(time.time())}.zip'
                self.log('Collecting adb bugreport (this may take several minutes)...')
                try:
                    with open(br_path, 'wb') as f:
                        subprocess.run([ADB, '-s', serial, 'bugreport'], stdout=f, stderr=subprocess.DEVNULL)
                except Exception as e:
                    self.log(f'Skipping bugreport due to error: {e}')
            else:
                self.log('Skipping bugreport: device disconnected.')
        self.log('Pulling modem logs and finalizing output...')
        self.pull_and_zip(serial)
        self.busy(False)
        self.log('Stop complete.')
        # Tear down watchdog and session state
        try:
            self.session_active = False
            if hasattr(self, 'watchdog_event') and self.watchdog_event is not None:
                self.watchdog_event.set()
            if getattr(self, 'watchdog_thread', None) is not None and self.watchdog_thread.is_alive():
                # Give watchdog up to 1s to exit
                self.watchdog_thread.join(timeout=1.0)
        except Exception:
            pass
        # Update UI status accordingly
        try:
            if getattr(self, 'auto_stopping', False):
                self.after(0, lambda: self.status.set('Idle (last session ended due to device disconnect)'))
            else:
                self.after(0, lambda: self.status.set('Idle'))
            self.after(0, lambda: self._set_session_ui(False))
        except Exception:
            pass
        # Reset flags for next session
        self.auto_stopping = False
        self.disconnected_notified = False
        # Refresh device list to reflect current connection state
        try:
            self.after(0, self.refresh_devices)
        except Exception:
            pass
        # If the stop was due to disconnect and auto-reconnect is enabled, start monitoring for return
        try:
            if getattr(self, 'auto_stopping', False) and self.auto_reconnect.get() and self.session_was_active_on_disconnect and self.last_active_serial:
                self.log('Auto-reconnect enabled; monitoring for device to return...')
                self.after(0, self._start_reconnect_monitor)
        except Exception:
            pass

    def start_logcat_clicked(self):
        serial = self.sel.get()
        if not serial:
            messagebox.showerror('Error', 'No device selected')
            return
        out_dir = self.effective_out_dir(serial)
        procs, files = start_logcat_streams(serial, out_dir)
        self.logcat_procs = procs
        self.logcat_files = files
        started = ', '.join(sorted(procs.keys()))
        self.status.set(
            f'Logcat running (buffers: {started}) -> {out_dir / AP_LOGS_DIRNAME}'
        )

    def stop_logcat_clicked(self):
        # Stop all six logcat streams if running
        for name, proc in list(self.logcat_procs.items()):
            self.log(f'Stopping logcat buffer: {name} ...')
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        # Close file handles
        for f in self.logcat_files.values():
            try:
                f.close()
            except Exception:
                pass
        self.logcat_procs = {}
        self.logcat_files = {}
        self.status.set('Logcat stopped')
        self.log('Logcat stopped.')

    def start_tcpdump_clicked(self):
        serial = self.sel.get()
        if not serial:
            messagebox.showerror('Error', 'No device selected')
            return
        tcpdump_local = Path(self.tcpdump_path.get())
        if not tcpdump_local.exists():
            messagebox.showerror('Error', f'tcpdump not found: {tcpdump_local}')
            return
        out_dir = self.effective_out_dir(serial)
        try:
            proc, pcap = start_tcpdump(serial, out_dir, tcpdump_local)
            self.tcpdump_proc = proc
            self.status.set(f'Tcpdump running -> {pcap}')
        except Exception as e:
            self.tcpdump_proc = None
            messagebox.showerror('Tcpdump error', str(e))
            self.status.set('Tcpdump failed to start')

    def stop_tcpdump_clicked(self):
        if self.tcpdump_proc:
            # If we launched background on-device capture, kill PID and pull
            remote_pid = getattr(self.tcpdump_proc, 'remote_pid', None)
            remote_pcap = getattr(self.tcpdump_proc, 'remote_pcap', None)
            serial = getattr(self.tcpdump_proc, 'serial', self.sel.get())
            local_pcap = getattr(self.tcpdump_proc, 'local_pcap', None)
            remote_error = getattr(self.tcpdump_proc, 'remote_error', None)
            privilege = getattr(self.tcpdump_proc, 'privilege', 'shell')
            if remote_pid and remote_pcap:
                self.log('Stopping tcpdump on device...')
                _remote_signal(serial, int(remote_pid), 2, privilege)
                deadline = time.time() + 5.0
                while time.time() < deadline and _remote_process_alive(serial, int(remote_pid), privilege):
                    time.sleep(0.2)
                if _remote_process_alive(serial, int(remote_pid), privilege):
                    self.log('tcpdump did not exit after SIGINT; sending SIGKILL...')
                    _remote_signal(serial, int(remote_pid), 9, privilege)
                run([ADB, '-s', serial, 'shell', 'sync'])
                # Pull final pcap to host
                if local_pcap:
                    self.log('Pulling pcap from device...')
                    pull = run([ADB, '-s', serial, 'pull', remote_pcap, local_pcap], timeout=120)
                    local_path = Path(local_pcap)
                    if pull.returncode == 0 and _valid_pcap(local_path):
                        self.log(f'Pcap pulled and verified: {local_path.stat().st_size} bytes.')
                        cleanup = [remote_pcap]
                        if remote_error:
                            cleanup.append(remote_error)
                        run([ADB, '-s', serial, 'shell', 'rm', '-f'] + cleanup)
                    else:
                        detail = _remote_text(serial, remote_error) if remote_error else ''
                        self.log(
                            'Pcap pull or validation failed. '
                            + (detail or (pull.stderr or pull.stdout or '').strip())
                        )
            # Stop any local placeholder process
            if self.tcpdump_proc.poll() is None:
                self.tcpdump_proc.terminate()
                try:
                    self.tcpdump_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.tcpdump_proc.kill()
            self.tcpdump_proc = None
        self.status.set('Tcpdump stopped')
        self.log('Tcpdump stopped.')

    # --- OEM/app logger control dictionary ---
    OEM_START_CMDS = {
        'Motorola Bug2Go': ['shell', 'am', 'broadcast', '-a', 'com.motorola.intent.action.BUG2GO'],
        'Samsung SilentLogger': samsung_silentlog_command('START'),
        'Google PixelLogger': ['shell', 'am', 'start', '-n', 'com.google.android.apps.dump/.MainActivity'],
        'MTK DebugLoggerUI': ['shell', 'am', 'start', '-n', 'com.debug.loggerui/.MainActivity'],
    }
    OEM_STOP_CMDS = {
        'Motorola Bug2Go': ['shell', 'am', 'broadcast', '-a', 'com.motorola.intent.action.BUG2GO'],
        'Samsung SilentLogger': samsung_silentlog_command('STOP'),
        'Google PixelLogger': ['shell', 'am', 'force-stop', 'com.google.android.apps.dump'],
        'MTK DebugLoggerUI': ['shell', 'am', 'force-stop', 'com.debug.loggerui'],
    }

    def start_oem_logger(self, serial: str):
        name = self.oem_logger.get()
        cmd = self.OEM_START_CMDS.get(name)
        if cmd:
            run([ADB, '-s', serial] + cmd)

    def stop_oem_logger(self, serial: str):
        name = self.oem_logger.get()
        cmd = self.OEM_STOP_CMDS.get(name)
        if cmd:
            run([ADB, '-s', serial] + cmd)

    # --- Profile-driven modem logging ---
    def _run_adb_checked(self, serial: str, args: List[str], description: str, timeout=30):
        result = run([ADB, '-s', serial] + list(args), timeout=timeout)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or '').strip()
            raise RuntimeError(f'{description} failed: {detail or "adb returned an error"}')
        return result

    def _mediatek_modem_status(self, serial: str, profile: Optional[dict] = None) -> str:
        result = run([ADB, '-s', serial, 'shell', 'getprop', 'vendor.mdlogger.Running'], timeout=10)
        property_value = (result.stdout or '').strip() if result.returncode == 0 else ''
        if property_value in ('0', '1'):
            return property_value

        # Some production MTK builds deny the shell UID access to vendor.mdlogger.Running.
        # In on-device SD mode, the open .muxz.tmp file is a stronger observable signal:
        # it appears after start and is renamed to .muxz only after clean finalization.
        if profile and profile.get('mode') == 'SD':
            device_root = profile['device_log_root']
            temporary = run_shell(
                serial,
                f'find {device_root} -type f -name "*.muxz.tmp" -print -quit 2>/dev/null',
                timeout=10,
            )
            return '1' if (temporary.stdout or '').strip() else '0'
        return property_value

    def _wait_for_mediatek_modem_status(
        self, serial: str, running: bool, timeout_seconds: int, profile: Optional[dict] = None
    ):
        deadline = time.time() + max(1, int(timeout_seconds))
        wanted = '1' if running else 'not 1'
        last = ''
        while time.time() < deadline:
            last = self._mediatek_modem_status(serial, profile)
            if (last == '1') == running:
                return last
            time.sleep(0.5)
        shown = last if last else '<empty>'
        raise RuntimeError(
            f'MediaTek modem logger did not reach state {wanted} within '
            f'{timeout_seconds}s (vendor.mdlogger.Running={shown}).'
        )

    def _latest_mediatek_log_dir(self, serial: str, device_root: str) -> str:
        source = {'root': device_root, 'pattern': 'MDLog*'}
        return self._latest_mtk_source_dir(serial, source)

    def _latest_mtk_source_dir(self, serial: str, source: dict) -> str:
        result = run_shell(
            serial,
            f"ls -1dt {source['root']}/{source['pattern']} 2>/dev/null | head -n 1",
            timeout=10,
        )
        candidate = (result.stdout or '').strip().splitlines()
        return candidate[0].strip() if candidate else ''

    def _latest_mtk_selected_log_dirs(self, serial: str, profile: dict) -> dict:
        paths = {}
        for source in mediatek_selected_log_sources(profile):
            path = self._latest_mtk_source_dir(serial, source)
            if path:
                paths[source['key']] = path
        return paths

    def _samsung_silentlog_status(self, serial: str) -> bool:
        result = run(
            [ADB, '-s', serial, 'shell', 'getprop', SAMSUNG_SILENTLOG_STATE_PROPERTY],
            timeout=10,
        )
        return result.returncode == 0 and (result.stdout or '').strip().casefold() == 'on'

    def _wait_for_samsung_silentlog_status(
        self, serial: str, running: bool, timeout_seconds: int
    ):
        deadline = time.time() + max(1, int(timeout_seconds))
        while time.time() < deadline:
            if self._samsung_silentlog_status(serial) == running:
                return
            time.sleep(0.5)
        wanted = 'On' if running else 'off'
        detail = (
            ' On commercial Samsung builds, verify that the device has valid '
            '/efs/sec_efs/.otp_auth provisioning.' if running else ''
        )
        raise RuntimeError(
            f'Samsung SilentLog did not reach state {wanted} within '
            f'{timeout_seconds}s ({SAMSUNG_SILENTLOG_STATE_PROPERTY}).{detail}'
        )

    def _samsung_silentlog_file_snapshot(self, serial: str) -> List[str]:
        files = set()
        for root in (SAMSUNG_SILENTLOG_CP_ROOT, SAMSUNG_SILENTLOG_AP_ROOT):
            result = run_shell(serial, f'find {root} -type f -print 2>/dev/null', timeout=15)
            if result.returncode != 0:
                continue
            for line in (result.stdout or '').splitlines():
                path = line.strip()
                if path.startswith(root + '/'):
                    files.add(path)
        return sorted(files)

    def _start_samsung_silentlog(self, serial: str, profile: dict):
        package = run(
            [ADB, '-s', serial, 'shell', 'pm', 'path', SAMSUNG_SILENTLOG_PACKAGE],
            timeout=10,
        )
        if package.returncode != 0 or 'package:' not in (package.stdout or ''):
            raise RuntimeError(
                f'Samsung SilentLog ({SAMSUNG_SILENTLOG_PACKAGE}) is not installed on the device.'
            )

        if self._samsung_silentlog_status(serial):
            self.log('Resetting an existing Samsung SilentLog capture to isolate this session...')
            self._run_adb_checked(
                serial,
                samsung_silentlog_command('STOP', profile['silentlog_profile']),
                'Samsung SilentLog reset stop',
                timeout=10,
            )
            self._wait_for_samsung_silentlog_status(
                serial, False, profile['stop_timeout_seconds']
            )
            if profile['finalize_wait_seconds']:
                time.sleep(min(5, profile['finalize_wait_seconds']))

        before = self._samsung_silentlog_file_snapshot(serial)
        self.samsung_log_files_before = before
        self.log(
            f"Starting Samsung Qualcomm SilentLog profile {profile['silentlog_profile']!r}..."
        )
        self._run_adb_checked(
            serial,
            samsung_silentlog_command('START', profile['silentlog_profile']),
            'Samsung SilentLog start broadcast',
            timeout=10,
        )
        self._wait_for_samsung_silentlog_status(
            serial, True, profile['start_timeout_seconds']
        )
        self.active_modem_profile = profile
        self.active_modem_remote_path = SAMSUNG_SILENTLOG_CP_ROOT
        self.active_samsung_log_files = []
        self.modem_capture_started = True
        self.log(f'Samsung Qualcomm SilentLog is running at {SAMSUNG_SILENTLOG_CP_ROOT}.')

    def _stop_samsung_silentlog(self, serial: str, profile: dict):
        if self._samsung_silentlog_status(serial):
            self._run_adb_checked(
                serial,
                samsung_silentlog_command('STOP', profile['silentlog_profile']),
                'Samsung SilentLog stop broadcast',
                timeout=10,
            )
            self._wait_for_samsung_silentlog_status(
                serial, False, profile['stop_timeout_seconds']
            )
        else:
            self.log('Samsung SilentLog is already stopped; continuing finalization.')

        finalize_wait = profile['finalize_wait_seconds']
        if finalize_wait:
            self.log(f'Waiting {finalize_wait}s for Samsung SilentLog finalization...')
            time.sleep(finalize_wait)
        before = set(getattr(self, 'samsung_log_files_before', []) or [])
        after = self._samsung_silentlog_file_snapshot(serial)
        self.active_samsung_log_files = [path for path in after if path not in before]
        self.active_modem_remote_path = SAMSUNG_SILENTLOG_CP_ROOT
        self.log(
            f'Samsung SilentLog stopped; {len(self.active_samsung_log_files)} '
            'new session file(s) are ready to pull.'
        )

    def start_modem_logging(self, serial: str):
        profile = copy.deepcopy(getattr(self, 'active_modem_profile', None) or self.selected_modem_profile())
        if not profile:
            raise RuntimeError('No modem profile selected.')
        profile = normalize_modem_profile(profile)
        if profile['chipset'] == 'Qualcomm':
            return self._start_samsung_silentlog(serial, profile)
        if profile['chipset'] != 'Mediatek':
            raise RuntimeError(f"Chipset {profile['chipset']} is not implemented for profile-driven modem logging yet.")

        package = run([ADB, '-s', serial, 'shell', 'pm', 'path', 'com.debug.loggerui'], timeout=10)
        if package.returncode != 0 or 'package:' not in (package.stdout or ''):
            raise RuntimeError('MediaTek DebugLoggerUI (com.debug.loggerui) is not installed on the device.')

        before_paths = self._latest_mtk_selected_log_dirs(serial, profile)
        self.mtk_log_paths_before = before_paths
        before = before_paths.get('modem', '')
        was_running = self._mediatek_modem_status(serial, profile) == '1'
        log_type_mask = profile['log_type_mask']

        # A multi-type profile may include loggers that were already running before this
        # session. Cycle the selected mask first so every type gets a clean current folder
        # instead of silently continuing an unrelated historical capture.
        isolate_multi_type_session = log_type_mask != 2
        if isolate_multi_type_session:
            self.log(
                f'Resetting MediaTek bitmask {log_type_mask} to isolate selected log folders...'
            )
            self._run_adb_checked(
                serial,
                mediatek_stop_command(log_type_mask),
                'MediaTek selected-log reset stop',
                timeout=20,
            )
            self._wait_for_mediatek_modem_status(
                serial, False, profile['stop_timeout_seconds'], profile
            )
            time.sleep(min(3, profile['finalize_wait_seconds']))
            was_running = False

        for index, command in enumerate(mediatek_profile_setup_commands(profile), start=1):
            self._run_adb_checked(
                serial, command, f"MediaTek profile setup command {index}", timeout=20
            )

        start_command = (
            mediatek_restart_command(log_type_mask)
            if was_running else mediatek_start_command(log_type_mask)
        )
        action = 'restart' if was_running else 'start'
        selected_types = ', '.join(
            meaning for bit, meaning in MTK_LOG_TYPE_BITS.items() if log_type_mask & bit
        )
        self.log(f'MediaTek {action} bitmask {log_type_mask}: {selected_types}')
        self._run_adb_checked(serial, start_command, f'MediaTek modem logger {action}', timeout=20)
        self._wait_for_mediatek_modem_status(
            serial, True, profile['start_timeout_seconds'], profile
        )

        deadline = time.time() + min(15, profile['start_timeout_seconds'])
        latest = ''
        while time.time() < deadline:
            latest = self._latest_mediatek_log_dir(serial, profile['device_log_root'])
            if latest and (latest != before or not before):
                break
            time.sleep(0.5)
        self.active_modem_profile = profile
        self.active_modem_remote_path = latest or before
        self.active_mtk_log_paths = self._latest_mtk_selected_log_dirs(serial, profile)
        if self.active_modem_remote_path:
            self.active_mtk_log_paths['modem'] = self.active_modem_remote_path
        self.modem_capture_started = True
        if self.active_modem_remote_path:
            self.log(f'MediaTek modem capture path: {self.active_modem_remote_path}')
        else:
            self.log(
                'MediaTek modem logger is running, but its capture folder is not visible yet; '
                'the newest folder will be selected when logging stops.'
            )

    def stop_modem_logging(self, serial: str):
        profile = copy.deepcopy(getattr(self, 'active_modem_profile', None))
        if not profile:
            profile = self.selected_modem_profile()
        if not profile:
            raise RuntimeError('No active modem profile is available for stop.')
        profile = normalize_modem_profile(profile)
        if profile['chipset'] == 'Qualcomm':
            return self._stop_samsung_silentlog(serial, profile)
        if profile['chipset'] != 'Mediatek':
            raise RuntimeError(f"Chipset {profile['chipset']} modem stop is not implemented yet.")

        self._run_adb_checked(
            serial,
            mediatek_stop_command(profile['log_type_mask']),
            'MediaTek modem logger stop',
            timeout=20,
        )
        self._wait_for_mediatek_modem_status(
            serial, False, profile['stop_timeout_seconds'], profile
        )
        finalize_wait = profile['finalize_wait_seconds']
        if finalize_wait:
            self.log(f'Waiting {finalize_wait}s for MediaTek .muxz finalization...')
            time.sleep(finalize_wait)
        latest = self._latest_mediatek_log_dir(serial, profile['device_log_root'])
        if latest:
            self.active_modem_remote_path = latest
        final_paths = self._latest_mtk_selected_log_dirs(serial, profile)
        if latest:
            final_paths['modem'] = latest
        self.active_mtk_log_paths = final_paths
        self.log('MediaTek modem logger stopped and finalized.')

    # --- Post-processing helpers ---
    def _detect_postprocess_family(self, serial: str) -> Optional[str]:
        """Return 'MTK' for Mediatek devices, 'Samsung' for Samsung/Exynos, else None.
        Uses getprop brand and chipset-related props."""
        try:
            brand = (self.getprop(serial, 'ro.product.brand') or '').strip().lower()
            soc_manu = (self.getprop(serial, 'ro.soc.manufacturer') or '').strip().lower()
            board = (self.getprop(serial, 'ro.board.platform') or '').strip().lower()
            soc_model = (self.getprop(serial, 'ro.soc.model') or '').strip().lower()
            mtk_keys = ['ro.vendor.mediatek.platform', 'ro.mediatek.version.release', 'ro.mediatek.chip_ver', 'ro.hardware.chipname']
            mtk_vals = ' '.join([(self.getprop(serial, k) or '') for k in mtk_keys]).lower()
            # MTK detection
            if 'mediatek' in soc_manu or 'mtk' in board or 'mediatek' in mtk_vals or 'mtk' in mtk_vals:
                return 'MTK'
            # Samsung / Exynos detection by brand or SoC
            if 'samsung' in brand or 'exynos' in board or 'exynos' in soc_model:
                return 'Samsung'
            return None
        except Exception:
            return None

    def run_post_processing(self, serial: str, out_dir: Path, timeout_sec: int = 300):
        """Run post-processing scripts in Cmdlets\\Post_Processing.
        - Always run scripts starting with 'ALL_' (applies to all devices)
        - If chipset detected as MTK -> also run scripts starting with 'mtk_'
        - If chipset detected as Samsung/Exynos -> also run scripts starting with 'samsung_'
        Each script runs with cwd set to the logging output directory.
        Stdout/stderr are saved to out_dir/Post_Processing/<script>.log
        """
        family = self._detect_postprocess_family(serial)
        scripts_dir = ROOT / 'Cmdlets' / 'Post_Processing'
        if not scripts_dir.exists():
            self.log(f'Post-processing directory not found: {scripts_dir}')
            return
        # Collect scripts: ALL_* always, plus family-specific if available
        all_scripts = sorted([p for p in scripts_dir.glob('ALL_*.py') if p.is_file()])
        specific_scripts: List[Path] = []
        prefix = None
        if family:
            prefix = 'mtk_' if family == 'MTK' else 'samsung_'
            specific_scripts = sorted([p for p in scripts_dir.glob(f'{prefix}*.py') if p.is_file()])
        else:
            self.log('Post-processing: chipset not identified; will run ALL_* scripts only.')
        scripts = all_scripts + specific_scripts
        if not scripts:
            if family and prefix:
                self.log(f'Post-processing: no scripts matching ALL_* or {prefix}*.py in {scripts_dir}')
            else:
                self.log(f'Post-processing: no scripts matching ALL_* in {scripts_dir}')
            return
        pp_dir = out_dir / 'Post_Processing'
        pp_dir.mkdir(parents=True, exist_ok=True)
        fam_msg = family if family else 'Unknown'
        self.log(f'Post-processing: detected {fam_msg}; running {len(scripts)} script(s): {len(all_scripts)} ALL_ + {len(specific_scripts)} specific.')
        # Run ALL_ scripts first, then family-specific scripts
        for script in scripts:
            log_path = pp_dir / f'{script.stem}.log'
            self.log(f'Running post-processing: {script.name} ...')
            try:
                with open(log_path, 'w', encoding='utf-8', errors='ignore') as lf:
                    lf.write(f'Executing {script.name} in {out_dir}\n')
                    lf.flush()
                    res = subprocess.run([sys.executable, str(script)], cwd=str(out_dir), stdout=lf, stderr=subprocess.STDOUT, timeout=timeout_sec)
                    lf.write(f'\nExit code: {res.returncode}\n')
                if res.returncode == 0:
                    self.log(f'Post-processing OK: {script.name}')
                else:
                    self.log(f'Post-processing FAILED (exit {res.returncode}): {script.name}')
            except subprocess.TimeoutExpired:
                self.log(f'Post-processing TIMEOUT after {timeout_sec}s: {script.name}')
            except Exception as e:
                self.log(f'Post-processing error in {script.name}: {e}')

    def _pull_samsung_silentlog(self, serial: str, out_dir: Path, profile: dict):
        metadata_path = out_dir / 'modem_profile_used.json'
        if not getattr(self, 'modem_capture_started', False):
            self.log('Samsung SilentLog capture did not start successfully; skipping stale logs.')
            return

        before = set(getattr(self, 'samsung_log_files_before', []) or [])
        current = set(self._samsung_silentlog_file_snapshot(serial))
        session_files = set(getattr(self, 'active_samsung_log_files', []) or [])
        session_files.update(path for path in current if path not in before)
        session_files = sorted(session_files)
        metadata = {
            'version': MODEM_PROFILES_VERSION,
            'provider': 'Samsung Qualcomm SilentLog',
            'profile': profile,
            'state_property': SAMSUNG_SILENTLOG_STATE_PROPERTY,
            'remote_capture_path': SAMSUNG_SILENTLOG_CP_ROOT,
            'remote_capture_paths': {
                'cp': SAMSUNG_SILENTLOG_CP_ROOT,
                'ap': SAMSUNG_SILENTLOG_AP_ROOT,
            },
            'remote_files_before_start': sorted(before),
            'session_remote_files': session_files,
            'pulled_at': datetime.now().isoformat(timespec='seconds'),
        }

        device_logs_dir = out_dir / 'Device_Logs' / 'Samsung' / 'SilentLog'
        roots = (
            (SAMSUNG_SILENTLOG_CP_ROOT, device_logs_dir / 'cp'),
            (SAMSUNG_SILENTLOG_AP_ROOT, device_logs_dir / 'ap_silentlog'),
        )
        for _remote_root, local_root in roots:
            local_root.mkdir(parents=True, exist_ok=True)

        pulled_files = []
        failed_files = []
        total_bytes = 0
        for remote_path in session_files:
            mapping = next(
                (
                    (remote_root, local_root)
                    for remote_root, local_root in roots
                    if remote_path.startswith(remote_root + '/')
                ),
                None,
            )
            if mapping is None:
                failed_files.append(remote_path)
                self.log(f'Refusing unexpected Samsung SilentLog path: {remote_path}')
                continue
            remote_root, local_root = mapping
            relative = PurePosixPath(remote_path).relative_to(PurePosixPath(remote_root))
            local_path = local_root.joinpath(*relative.parts)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            result = run([ADB, '-s', serial, 'pull', remote_path, str(local_path)], timeout=300)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or '').strip()
                self.log(
                    f'Samsung SilentLog pull failed for {remote_path}: '
                    f'{detail or "adb pull returned an error"}'
                )
                failed_files.append(remote_path)
                continue
            size = local_path.stat().st_size if local_path.is_file() else 0
            total_bytes += size
            pulled_files.append(remote_path)

        metadata['pulled_files'] = pulled_files
        metadata['missing_or_failed_files'] = failed_files
        with open(metadata_path, 'w', encoding='utf-8') as metadata_file:
            json.dump(metadata, metadata_file, indent=2)
            metadata_file.write('\n')
        if not session_files:
            self.log(
                'Samsung SilentLog produced no new visible files. Verify OTP authorization, '
                'the selected modem profile, and available device storage.'
            )
        self.log(
            f'Samsung SilentLog pull complete: {len(pulled_files)} file(s), '
            f'{total_bytes} bytes; {len(failed_files)} failed.'
        )

    def _pull_modem_logs(self, serial: str, out_dir: Path):
        profile = copy.deepcopy(getattr(self, 'active_modem_profile', None))
        if not profile:
            self.log('No active modem profile was recorded; skipping modem pull.')
            return
        profile = normalize_modem_profile(profile)
        metadata_path = out_dir / 'modem_profile_used.json'

        if profile['chipset'] == 'Qualcomm':
            return self._pull_samsung_silentlog(serial, out_dir, profile)
        if profile['chipset'] != 'Mediatek':
            self.log(f"Modem pull for {profile['chipset']} profiles is not implemented yet.")
            return
        if not getattr(self, 'modem_capture_started', False):
            self.log('MediaTek modem capture did not start successfully; skipping stale modem logs.')
            return

        active_paths = dict(getattr(self, 'active_mtk_log_paths', {}) or {})
        latest_paths = self._latest_mtk_selected_log_dirs(serial, profile)
        for key, path in latest_paths.items():
            active_paths[key] = path
        remote_path = active_paths.get('modem', getattr(self, 'active_modem_remote_path', ''))
        metadata = {
            'version': MODEM_PROFILES_VERSION,
            'profile': profile,
            'remote_capture_path': remote_path,
            'remote_capture_paths': active_paths,
            'remote_paths_before_start': dict(getattr(self, 'mtk_log_paths_before', {}) or {}),
            'pulled_at': datetime.now().isoformat(timespec='seconds'),
        }
        with open(metadata_path, 'w', encoding='utf-8') as metadata_file:
            json.dump(metadata, metadata_file, indent=2)
            metadata_file.write('\n')

        device_logs_dir = out_dir / 'Device_Logs'
        device_logs_dir.mkdir(parents=True, exist_ok=True)

        # Preserve the familiar DebugLoggerUI root layout even when some types are not
        # selected. This lets reviewers navigate captures exactly as they do on-device.
        root_tree = run(
            [ADB, '-s', serial, 'pull', '/data/debuglogger/file_tree.txt', str(device_logs_dir / 'file_tree.txt')],
            timeout=60,
        )
        if root_tree.returncode != 0:
            self.log('MediaTek root file_tree.txt was not available to pull.')
        md_config = run(
            [ADB, '-s', serial, 'pull', '/data/debuglogger/mdlog1_config', str(device_logs_dir)],
            timeout=120,
        )
        if md_config.returncode != 0:
            self.log('MediaTek mdlog1_config was not available to pull; creating an empty folder.')
        for relative_dir in ('connsyslog', 'mdlog1', 'mdlog1_config', 'mobilelog', 'netlog'):
            (device_logs_dir / relative_dir).mkdir(parents=True, exist_ok=True)

        total_files = 0
        total_bytes = 0
        pulled_types = []
        missing_types = []
        for source in mediatek_selected_log_sources(profile):
            source_key = source['key']
            source_name = source['meaning']
            source_path = active_paths.get(source_key, '')
            if not source_path:
                missing_types.append(source_name)
                self.log(f'No current MediaTek {source_name} folder was found to pull.')
                continue
            if not source_path.startswith(source['root'] + '/'):
                self.log(f'Refusing unexpected {source_name} path: {source_path}')
                missing_types.append(source_name)
                continue

            destination = device_logs_dir / Path(source['output'])
            destination.mkdir(parents=True, exist_ok=True)
            size_result = run_shell(
                serial, f'du -sk {source_path} 2>/dev/null | head -n 1', timeout=15
            )
            remote_size = (size_result.stdout or '').strip()
            if remote_size:
                self.log(f'MediaTek {source_name} device size: {remote_size}')
            self.log(f'Pulling MediaTek {source_name}: {source_path}')
            result = run([ADB, '-s', serial, 'pull', source_path, str(destination)], timeout=900)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or '').strip()
                self.log(f'{source_name} pull failed: {detail or "adb pull returned an error"}')
                missing_types.append(source_name)
                continue

            local_capture = destination / Path(source_path).name
            files = (
                [path for path in local_capture.rglob('*') if path.is_file()]
                if local_capture.exists() else []
            )
            source_bytes = sum(path.stat().st_size for path in files)
            total_files += len(files)
            total_bytes += source_bytes
            pulled_types.append(source_name)
            self.log(
                f'MediaTek {source_name} pull complete: '
                f'{len(files)} file(s), {source_bytes} bytes.'
            )

        metadata['pulled_log_types'] = pulled_types
        metadata['missing_or_failed_log_types'] = missing_types
        with open(metadata_path, 'w', encoding='utf-8') as metadata_file:
            json.dump(metadata, metadata_file, indent=2)
            metadata_file.write('\n')
        self.log(
            f'MediaTek selected-log pull complete: {len(pulled_types)} type(s), '
            f'{total_files} file(s), {total_bytes} bytes.'
        )

    def pull_and_zip(self, serial: str):
        out_dir = self.effective_out_dir(serial)
        out_dir.mkdir(parents=True, exist_ok=True)
        if self.capture_modem.get():
            try:
                self._pull_modem_logs(serial, out_dir)
            except Exception as exc:
                self.log(f'Modem pull failed: {exc}')
        # Run post-processing before zipping so results are included
        if self.skip_post_processing.get():
            self.log('Skipping post-processing (option enabled).')
        else:
            try:
                self.run_post_processing(serial, out_dir)
            except Exception as e:
                self.log(f'Post-processing step failed: {e}')
        # Zip everything using 7zip if present and option enabled
        seven_zip = ROOT / 'Programs' / '7-Zip' / '7z.exe'
        if self.zip_at_end.get():
            if seven_zip.exists():
                archive = out_dir.parent / f"{out_dir.name}.zip"
                self.log(f'Zipping output to {archive.name} ...')
                res = subprocess.run([str(seven_zip), 'a', '-tzip', str(archive), str(out_dir)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if res.returncode == 0:
                    self.log('Zip completed successfully.')
                else:
                    self.log(f'Zip failed with exit code {res.returncode}.')
            else:
                self.log('Zip-at-end requested but 7z.exe not found; skipping zip.')
        else:
            self.log('Skipping zip (option disabled).')

        # Try copying to SD card as backup before pull (best effort)
        try:
            sd_dir = f"/sdcard/Logs/{out_dir.name}"
            run([ADB, '-s', serial, 'shell', 'mkdir', '-p', sd_dir])
            # push the folder name marker
            run([ADB, '-s', serial, 'shell', 'touch', f"{sd_dir}/.placeholder"])  # marker
        except Exception:
            pass


def main():
    app = LoggerGUI()
    app.mainloop()


if __name__ == '__main__':
    main()
