import subprocess
import tempfile
import unittest
import json
from datetime import datetime
from pathlib import Path
from unittest import mock

import logger


class CaptureFeatureTests(unittest.TestCase):
    @staticmethod
    def _value(initial):
        return type(
            'Value',
            (),
            {
                'current': initial,
                'get': lambda self: self.current,
                'set': lambda self, value: setattr(self, 'current', value),
            },
        )()

    def test_contextual_ui_only_shows_settings_for_enabled_captures(self):
        harness = object.__new__(logger.LoggerGUI)
        harness.capture_screenrecord = self._value(True)
        harness.segmented_screenrecord = self._value(False)
        harness.capture_tcpdump = self._value(False)
        harness.capture_modem = self._value(True)
        harness.enable_watchdog = self._value(True)
        harness.auto_reconnect = self._value(False)
        harness.video_settings_frame = mock.Mock()
        harness.segment_controls = mock.Mock()
        harness.tcpdump_settings_frame = mock.Mock()
        harness.modem_settings_frame = mock.Mock()
        harness.reconnect_check = mock.Mock()
        harness.resume_check = mock.Mock()
        harness._update_modem_profile_state = mock.Mock()

        logger.LoggerGUI._sync_contextual_controls(harness)

        harness.video_settings_frame.grid.assert_called_once_with()
        harness.segment_controls.grid_remove.assert_called_once_with()
        harness.tcpdump_settings_frame.grid_remove.assert_called_once_with()
        harness.modem_settings_frame.grid.assert_called_once_with()
        harness.reconnect_check.configure.assert_called_once_with(state='normal')
        harness.resume_check.configure.assert_called_once_with(state='disabled')
        harness._update_modem_profile_state.assert_called_once_with()

    def test_session_ui_focuses_events_and_locks_setup_while_recording(self):
        harness = object.__new__(logger.LoggerGUI)
        harness.notebook = mock.Mock()
        harness.session_tab = object()
        harness.events_tab = object()
        harness.output_tab = object()
        harness.start_button = mock.Mock()
        harness.stop_button = mock.Mock()

        logger.LoggerGUI._set_session_ui(harness, True)

        harness.notebook.select.assert_called_once_with(harness.events_tab)
        harness.notebook.tab.assert_called_once_with(harness.session_tab, state='disabled')
        harness.start_button.configure.assert_called_once_with(state='disabled')
        harness.stop_button.configure.assert_called_once_with(state='normal')

    def test_advanced_options_start_collapsed_and_can_expand(self):
        harness = object.__new__(logger.LoggerGUI)
        harness.advanced_expanded = self._value(False)
        harness.advanced_button_text = self._value('')
        harness.advanced_frame = mock.Mock()

        logger.LoggerGUI._toggle_advanced(harness, force=False)
        harness.advanced_frame.grid_remove.assert_called_once_with()

        logger.LoggerGUI._toggle_advanced(harness)
        harness.advanced_frame.grid.assert_called_once_with()
        self.assertTrue(harness.advanced_expanded.get())

    def test_logcat_streams_write_all_buffers_to_ap_logs_folder(self):
        fake_process = mock.Mock()

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            logger.subprocess, 'Popen', return_value=fake_process
        ) as mocked_popen:
            output = Path(tmp)
            processes, files = logger.start_logcat_streams('emulator-5554', output)
            try:
                ap_logs = output / logger.AP_LOGS_DIRNAME
                self.assertTrue(ap_logs.is_dir())
                self.assertEqual(
                    {
                        'logall.txt',
                        'logevents.txt',
                        'logkernel.txt',
                        'logmain.txt',
                        'logradio.txt',
                        'logsystem.txt',
                    },
                    {Path(handle.name).name for handle in files.values()},
                )
                self.assertTrue(
                    all(Path(handle.name).parent == ap_logs for handle in files.values())
                )
                self.assertFalse(any(output.glob('log*.txt')))
                self.assertEqual(set(files), set(processes))
                self.assertEqual(6, mocked_popen.call_count)
            finally:
                for handle in files.values():
                    handle.close()

    def test_modem_profile_round_trip_and_chipset_filter(self):
        profiles = [dict(logger.DEFAULT_MODEM_PROFILES[0])]
        disabled = dict(profiles[0], name='Disabled MTK', enabled=False)
        profiles.append(disabled)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'modem_profiles.json'
            logger.save_modem_profiles(path, profiles)
            loaded = logger.load_modem_profiles(path)
            payload = json.loads(path.read_text(encoding='utf-8'))

        self.assertEqual(2, len(loaded))
        self.assertEqual('Modem log', payload['log_type_bits']['2'])
        self.assertEqual(2, loaded[0]['log_type_mask'])
        self.assertEqual(
            ['MediaTek On-device 600 MB'],
            [item['name'] for item in logger.profiles_for_chipset(loaded, 'Mediatek')],
        )
        self.assertEqual([], logger.profiles_for_chipset(loaded, 'Qualcomm'))

    def test_android_getprop_chipset_detection(self):
        qualcomm = logger.parse_android_properties(
            '[ro.product.manufacturer]: [samsung]\n'
            '[ro.board.platform]: [kona]\n'
            '[ro.hardware]: [qcom]\n'
            '[ro.soc.manufacturer]: [QTI]\n'
            '[ro.soc.model]: [SM8250]\n'
        )
        mediatek = {
            'ro.soc.manufacturer': 'MediaTek',
            'ro.board.platform': 'mt6893',
        }
        exynos = {
            'ro.soc.manufacturer': 'Samsung',
            'ro.board.platform': 'exynos2100',
        }

        self.assertEqual('Qualcomm', logger.detect_modem_chipset(qualcomm))
        self.assertEqual('Mediatek', logger.detect_modem_chipset(mediatek))
        self.assertEqual('Exynos', logger.detect_modem_chipset(exynos))
        self.assertEqual('Auto/Unknown', logger.detect_modem_chipset({}))

    def test_device_chipset_detection_uses_one_getprop_snapshot(self):
        completed = subprocess.CompletedProcess(
            [], 0, '[ro.hardware]: [qcom]\n[ro.soc.manufacturer]: [QTI]\n', ''
        )
        with mock.patch.object(logger, 'run', return_value=completed) as mocked_run:
            detected = logger.detect_device_modem_chipset('device')

        self.assertEqual('Qualcomm', detected)
        mocked_run.assert_called_once_with(
            [logger.ADB, '-s', 'device', 'shell', 'getprop'], timeout=10
        )

    def test_missing_modem_profile_file_creates_safe_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'modem_profiles.json'

            profiles = logger.load_modem_profiles(path)

            self.assertTrue(path.is_file())
            self.assertEqual('Mediatek', profiles[0]['chipset'])
            self.assertEqual('SD', profiles[0]['mode'])
            self.assertEqual('/data/debuglogger/mdlog1', profiles[0]['device_log_root'])
            self.assertEqual('Qualcomm', profiles[1]['chipset'])
            self.assertEqual('/sdcard/log/cp', profiles[1]['device_log_root'])

    def test_samsung_silentlog_commands_are_explicit_and_non_blocking(self):
        start = logger.samsung_silentlog_command('START', 'default')
        stop = logger.samsung_silentlog_command('STOP', 'default')

        self.assertEqual(['shell', 'sh', '-c'], start[:3])
        self.assertIn('SILENT_LOG_START', start[-1])
        self.assertIn('SILENT_LOG_STOP', stop[-1])
        self.assertIn(logger.SAMSUNG_SILENTLOG_RECEIVER, start[-1])
        self.assertIn('--es profile default', start[-1])
        self.assertTrue(start[-1].endswith('>/dev/null 2>&1 &'))

    def test_qualcomm_profile_rejects_non_samsung_silentlog_root(self):
        profile = dict(logger.DEFAULT_MODEM_PROFILES[1], device_log_root='/sdcard/other')

        with self.assertRaisesRegex(ValueError, 'must match'):
            logger.normalize_modem_profile(profile)

    def test_samsung_silentlog_start_uses_profile_and_state_wait(self):
        profile = dict(logger.DEFAULT_MODEM_PROFILES[1])
        harness = object.__new__(logger.LoggerGUI)
        harness.active_modem_profile = profile
        harness.log = mock.Mock()
        harness._samsung_silentlog_status = mock.Mock(return_value=False)
        harness._samsung_silentlog_file_snapshot = mock.Mock(return_value=['/sdcard/log/cp/old.qmdl'])
        harness._run_adb_checked = mock.Mock()
        harness._wait_for_samsung_silentlog_status = mock.Mock()
        package = subprocess.CompletedProcess([], 0, 'package:/system/app/SilentLog/SilentLog.apk\n', '')

        with mock.patch.object(logger, 'run', return_value=package):
            logger.LoggerGUI.start_modem_logging(harness, 'device')

        sent = harness._run_adb_checked.call_args.args[1]
        self.assertIn('SILENT_LOG_START', sent[-1])
        self.assertIn('--es profile default', sent[-1])
        harness._wait_for_samsung_silentlog_status.assert_called_once_with(
            'device', True, profile['start_timeout_seconds']
        )
        self.assertEqual(['/sdcard/log/cp/old.qmdl'], harness.samsung_log_files_before)
        self.assertTrue(harness.modem_capture_started)

    def test_samsung_silentlog_stop_tracks_only_new_files(self):
        profile = dict(logger.DEFAULT_MODEM_PROFILES[1], finalize_wait_seconds=0)
        harness = object.__new__(logger.LoggerGUI)
        harness.active_modem_profile = profile
        harness.samsung_log_files_before = ['/sdcard/log/cp/old.qmdl']
        harness.log = mock.Mock()
        harness._samsung_silentlog_status = mock.Mock(return_value=True)
        harness._run_adb_checked = mock.Mock()
        harness._wait_for_samsung_silentlog_status = mock.Mock()
        harness._samsung_silentlog_file_snapshot = mock.Mock(return_value=[
            '/sdcard/log/ap_silentlog/logcat_new.txt',
            '/sdcard/log/cp/Diag_new.qmdl',
            '/sdcard/log/cp/old.qmdl',
        ])

        logger.LoggerGUI.stop_modem_logging(harness, 'device')

        sent = harness._run_adb_checked.call_args.args[1]
        self.assertIn('SILENT_LOG_STOP', sent[-1])
        self.assertEqual([
            '/sdcard/log/ap_silentlog/logcat_new.txt',
            '/sdcard/log/cp/Diag_new.qmdl',
        ], harness.active_samsung_log_files)

    def test_samsung_silentlog_pull_preserves_cp_and_ap_layout(self):
        profile = dict(logger.DEFAULT_MODEM_PROFILES[1])
        files = [
            '/sdcard/log/ap_silentlog/logcat_new.txt',
            '/sdcard/log/cp/Diag_new.qmdl',
        ]
        harness = object.__new__(logger.LoggerGUI)
        harness.active_modem_profile = profile
        harness.modem_capture_started = True
        harness.samsung_log_files_before = ['/sdcard/log/cp/old.qmdl']
        harness.active_samsung_log_files = list(files)
        harness._samsung_silentlog_file_snapshot = mock.Mock(return_value=files)
        harness.log = mock.Mock()

        def fake_run(command, timeout=None):
            if 'pull' in command:
                target = Path(command[-1])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'silent log')
            return subprocess.CompletedProcess(command, 0, '', '')

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            logger, 'run', side_effect=fake_run
        ):
            output = Path(tmp)
            logger.LoggerGUI._pull_modem_logs(harness, 'device', output)
            metadata = json.loads((output / 'modem_profile_used.json').read_text(encoding='utf-8'))

            samsung = output / 'Device_Logs' / 'Samsung' / 'SilentLog'
            self.assertTrue((samsung / 'cp' / 'Diag_new.qmdl').is_file())
            self.assertTrue((samsung / 'ap_silentlog' / 'logcat_new.txt').is_file())
            self.assertEqual(files, metadata['pulled_files'])
            self.assertEqual([], metadata['missing_or_failed_files'])

    def test_mediatek_profile_builds_debugloggerui_commands(self):
        profile = dict(
            logger.DEFAULT_MODEM_PROFILES[0],
            max_log_size_mb=750,
            auto_start_on_boot=True,
            taglog_enabled=True,
        )

        commands = logger.mediatek_profile_setup_commands(profile)
        command_text = [' '.join(command) for command in commands]

        self.assertEqual(7, len(commands))
        self.assertIn('-e cmd_name switch_logpath -e cmd_target internal_sd', command_text[0])
        self.assertTrue(any('switch_modem_log_mode_2 --ei cmd_target 1' in item for item in command_text))
        self.assertTrue(any('set_log_size_750 --ei cmd_target 2' in item for item in command_text))
        self.assertTrue(any('set_auto_start_1 --ei cmd_target 2' in item for item in command_text))
        self.assertTrue(any('switch_taglog --ei cmd_target 1' in item for item in command_text))
        self.assertTrue(all(command[-2:] == ['-n', logger.MTK_LOG_RECEIVER] for command in commands))

    def test_mediatek_start_stop_commands_target_only_modem_logging(self):
        self.assertIn('-e cmd_name start --ei cmd_target 2', ' '.join(logger.mediatek_start_command()))
        self.assertIn('-e cmd_name stop --ei cmd_target 2', ' '.join(logger.mediatek_stop_command()))
        self.assertIn('-e cmd_name restart --ei cmd_target 2', ' '.join(logger.mediatek_restart_command()))

    def test_mediatek_combined_log_type_bitmask_is_used_by_lifecycle_commands(self):
        mask = 1 + 2 + 4 + 16 + 32 + 64

        self.assertEqual(119, mask)
        self.assertIn('--ei cmd_target 119', ' '.join(logger.mediatek_start_command(mask)))
        self.assertIn('--ei cmd_target 119', ' '.join(logger.mediatek_stop_command(mask)))
        self.assertEqual(1, logger.MTK_MODEM_TYPE_LABELS['1: MD1 (primary cellular modem)'])
        self.assertEqual('SD', logger.MTK_MODE_LABELS['2: SD (record on device)'])
        self.assertEqual('Connsys firmware log', logger.MTK_LOG_TYPE_BITS[32])

    def test_mediatek_selected_log_sources_map_each_bit_to_its_device_root(self):
        profile = dict(logger.DEFAULT_MODEM_PROFILES[0], log_type_mask=1 + 2 + 4 + 32)

        sources = logger.mediatek_selected_log_sources(profile)

        self.assertEqual(['mobile', 'modem', 'network', 'connsys_fw'], [item['key'] for item in sources])
        self.assertEqual('/data/debuglogger/mobilelog', sources[0]['root'])
        self.assertEqual('/data/debuglogger/mdlog1', sources[1]['root'])
        self.assertEqual('NTLog*', sources[2]['pattern'])
        self.assertEqual('connsyslog/fw', sources[3]['output'])

    def test_mediatek_pull_collects_every_selected_log_type(self):
        profile = dict(logger.DEFAULT_MODEM_PROFILES[0], log_type_mask=1 + 2 + 4 + 32)
        paths = {
            'mobile': '/data/debuglogger/mobilelog/APLog_current',
            'modem': '/data/debuglogger/mdlog1/MDLog_current',
            'network': '/data/debuglogger/netlog/NTLog_current',
            'connsys_fw': '/data/debuglogger/connsyslog/fw/CsLog_current',
        }
        harness = object.__new__(logger.LoggerGUI)
        harness.active_modem_profile = profile
        harness.active_modem_remote_path = paths['modem']
        harness.active_mtk_log_paths = dict(paths)
        harness.mtk_log_paths_before = {}
        harness.modem_capture_started = True
        messages = []
        harness.log = messages.append
        harness._latest_mtk_selected_log_dirs = lambda _serial, _profile: dict(paths)

        def fake_run(command, timeout=None):
            if 'pull' in command:
                source = command[-2]
                target = Path(command[-1])
                if source.endswith('/file_tree.txt'):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text('tree', encoding='utf-8')
                elif source.endswith('/mdlog1_config'):
                    destination = target / 'mdlog1_config'
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / 'filter_history').write_text('filter', encoding='utf-8')
                else:
                    destination = target / Path(source).name
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / 'capture.bin').write_bytes(b'log data')
            return subprocess.CompletedProcess(command, 0, '', '')

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            logger, 'run', side_effect=fake_run
        ), mock.patch.object(
            logger, 'run_shell', return_value=subprocess.CompletedProcess([], 0, '8\tpath\n', '')
        ):
            output = Path(tmp)
            logger.LoggerGUI._pull_modem_logs(harness, 'device', output)
            metadata = json.loads((output / 'modem_profile_used.json').read_text(encoding='utf-8'))

            device_logs = output / 'device_logs'
            for folder in ('connsyslog', 'mdlog1', 'mdlog1_config', 'mobilelog', 'netlog'):
                self.assertTrue((device_logs / folder).is_dir())
            self.assertTrue((device_logs / 'file_tree.txt').is_file())
            self.assertTrue((device_logs / 'mobilelog' / 'APLog_current').is_dir())
            self.assertTrue((device_logs / 'mdlog1' / 'MDLog_current').is_dir())
            self.assertTrue((device_logs / 'netlog' / 'NTLog_current').is_dir())
            self.assertTrue((device_logs / 'connsyslog' / 'fw' / 'CsLog_current').is_dir())
            self.assertEqual(4, len(metadata['pulled_log_types']))
            self.assertEqual([], metadata['missing_or_failed_log_types'])

    def test_modem_profile_rejects_unsafe_device_path(self):
        profile = dict(logger.DEFAULT_MODEM_PROFILES[0], device_log_root='/data/debuglogger; reboot')

        with self.assertRaisesRegex(ValueError, 'unsupported shell characters'):
            logger.normalize_modem_profile(profile)

    def test_modem_profile_requires_modem_bit_and_rejects_reserved_bits(self):
        without_modem = dict(logger.DEFAULT_MODEM_PROFILES[0], log_type_mask=1)
        reserved_bit = dict(logger.DEFAULT_MODEM_PROFILES[0], log_type_mask=2 + 8)
        unknown_modem = dict(logger.DEFAULT_MODEM_PROFILES[0], modem_type=2)

        with self.assertRaisesRegex(ValueError, 'include bit 2'):
            logger.normalize_modem_profile(without_modem)
        with self.assertRaisesRegex(ValueError, 'unsupported bit'):
            logger.normalize_modem_profile(reserved_bit)
        with self.assertRaisesRegex(ValueError, r'1 \(MD1\) or 3 \(MD3\)'):
            logger.normalize_modem_profile(unknown_modem)

    def test_mediatek_status_uses_open_muxz_when_vendor_property_is_hidden(self):
        harness = object.__new__(logger.LoggerGUI)
        hidden_property = subprocess.CompletedProcess([], 0, '', 'Access denied finding property')
        open_trace = subprocess.CompletedProcess([], 0, '/data/debuglogger/mdlog1/run/log.muxz.tmp\n', '')

        with mock.patch.object(logger, 'run', return_value=hidden_property), mock.patch.object(
            logger, 'run_shell', return_value=open_trace
        ):
            status = logger.LoggerGUI._mediatek_modem_status(
                harness, 'device', logger.DEFAULT_MODEM_PROFILES[0]
            )

        self.assertEqual('1', status)

    def test_session_folder_name_starts_with_timestamp(self):
        timestamp = logger.format_log_timestamp(datetime(2026, 7, 21, 15, 4, 5))

        self.assertEqual('2026-21-07_15-04-05', timestamp)
        self.assertEqual(
            '2026-21-07_15-04-05_CallSetup_R3CR50DK68L',
            logger.build_session_folder_name(timestamp, 'CallSetup', 'R3CR50DK68L'),
        )

    def test_segment_filename_uses_timestamp_and_segment_number(self):
        self.assertEqual(
            '2026-21-07_15-04-05_screenRecord_3.mp4',
            logger.build_segment_filename('2026-21-07_15-04-05', 3),
        )

    def test_effective_output_folder_remains_stable_for_session(self):
        value = lambda result: type('Value', (), {'get': lambda self: result})()
        harness = type(
            'Harness',
            (),
            {
                'log_dir': value('C:/logs'),
                'test_name': value('CallSetup'),
                'session_active': False,
                'session_out_dir': None,
                'session_output_serial': '',
                'session_output_test_name': '',
                'session_output_base': None,
            },
        )()

        with mock.patch.object(logger, 'format_log_timestamp', return_value='2026-21-07_15-04-05'):
            first = logger.LoggerGUI.effective_out_dir(harness, 'R3CR50DK68L')
        with mock.patch.object(logger, 'format_log_timestamp', return_value='2099-01-01_00-00-00'):
            second = logger.LoggerGUI.effective_out_dir(harness, 'R3CR50DK68L')

        self.assertEqual(first, second)
        self.assertEqual(
            Path('C:/logs/2026-21-07_15-04-05_CallSetup_R3CR50DK68L'),
            first,
        )

    def test_run_shell_keeps_remote_command_as_one_argument(self):
        with mock.patch.object(logger, 'run') as mocked_run:
            mocked_run.return_value = subprocess.CompletedProcess([], 0, '', '')
            logger.run_shell('emulator-5554', 'echo one && echo two', timeout=7)

        mocked_run.assert_called_once_with(
            [logger.ADB, '-s', 'emulator-5554', 'shell', 'echo one && echo two'],
            timeout=7,
        )

    def test_su_wraps_the_complete_capture_command(self):
        wrapped = logger._privileged_command('tcpdump -i any -w capture.pcap & echo $!', 'su')
        self.assertEqual("su -c 'tcpdump -i any -w capture.pcap & echo $!'", wrapped)

    def test_device_tcpdump_path_is_returned_and_verified(self):
        responses = [
            subprocess.CompletedProcess([], 0, '/system/bin/tcpdump\n', ''),
            subprocess.CompletedProcess([], 0, 'tcpdump version 4.9.2\n', ''),
        ]
        with mock.patch.object(logger, 'run', side_effect=responses):
            path = logger.push_tcpdump_if_needed('emulator-5554', Path('unused'))

        self.assertEqual('/system/bin/tcpdump', path)

    def test_screenrecord_help_detects_positional_syntax(self):
        help_result = subprocess.CompletedProcess(
            [], 1, '', 'Usage: screenrecord [options] <filename>\n--time-limit TIME\n'
        )
        harness = type('Harness', (), {'screenrecord_caps': None})()
        with mock.patch.object(logger, 'run', return_value=help_result):
            caps = logger.LoggerGUI._detect_screenrecord_caps(harness, 'emulator-5554')

        self.assertEqual({'syntax': 'positional', 'tflag': '--time-limit'}, caps)

    def test_screenrecord_help_detects_bitrate_support(self):
        help_result = subprocess.CompletedProcess(
            [],
            1,
            '',
            'Usage: screenrecord [options] <filename>\n--time-limit TIME\n--bit-rate RATE\n',
        )
        harness = type('Harness', (), {'screenrecord_caps': None})()
        with mock.patch.object(logger, 'run', return_value=help_result):
            caps = logger.LoggerGUI._detect_screenrecord_caps(harness, 'emulator-5554')

        self.assertEqual('--bit-rate', caps['bitrate_flag'])

    def test_video_quality_builds_supported_bitrate_args(self):
        quality = 'Low (2 Mbps, ~4 MB/15s)'

        self.assertEqual(2_000_000, logger.video_quality_bitrate(quality))
        self.assertEqual(
            ['--bit-rate', '2000000'],
            logger.screenrecord_bitrate_args(quality, {'bitrate_flag': '--bit-rate'}),
        )
        self.assertEqual([], logger.screenrecord_bitrate_args(quality, {}))
        self.assertEqual(
            [],
            logger.screenrecord_bitrate_args(logger.VIDEO_QUALITY_DEVICE_DEFAULT, {'bitrate_flag': '--bit-rate'}),
        )

    def test_pcap_magic_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            valid = Path(tmp) / 'valid.pcap'
            invalid = Path(tmp) / 'invalid.pcap'
            valid.write_bytes(b'\xd4\xc3\xb2\xa1' + bytes(20))
            invalid.write_bytes(b'not a pcap' + bytes(20))

            self.assertTrue(logger._valid_pcap(valid))
            self.assertFalse(logger._valid_pcap(invalid))

    def test_take_device_screenshot_saves_verified_png(self):
        def fake_screencap(command, stdout, stderr, timeout):
            stdout.write(b'\x89PNG\r\n\x1a\nimage data')
            return subprocess.CompletedProcess(command, 0, b'', b'')

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(logger.subprocess, 'run', side_effect=fake_screencap) as mocked_run:
                screenshot = logger.take_device_screenshot('emulator-5554', Path(tmp))

            self.assertTrue(screenshot.is_file())
            self.assertTrue(screenshot.name.startswith('screenshot_'))
            self.assertEqual(b'\x89PNG\r\n\x1a\n', screenshot.read_bytes()[:8])
            self.assertEqual(
                [logger.ADB, '-s', 'emulator-5554', 'exec-out', 'screencap', '-p'],
                mocked_run.call_args.args[0],
            )

    def test_take_device_screenshot_removes_invalid_output(self):
        def fake_screencap(command, stdout, stderr, timeout):
            stdout.write(b'not a png')
            return subprocess.CompletedProcess(command, 0, b'', b'')

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with mock.patch.object(logger.subprocess, 'run', side_effect=fake_screencap):
                with self.assertRaisesRegex(RuntimeError, 'valid PNG'):
                    logger.take_device_screenshot('emulator-5554', out_dir)

            self.assertEqual([], list(out_dir.iterdir()))


if __name__ == '__main__':
    unittest.main()
