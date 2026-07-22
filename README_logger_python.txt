ADB Logger (Python)

Overview:
This Python GUI replaces core functionality from logger.bat with a Windows interface. It lists connected ADB devices, lets you pick one, and start/stop a coordinated logging session with options:
- Logcat capture to six files (radio, main, kernel, events, system, all) with -v threadtime.
- Tcpdump packet capture (if tcpdump is available or provided and pushed to the device).
- JSON-backed modem logging profiles for MediaTek DebugLoggerUI and Samsung Qualcomm SilentLog.
- Optional OEM logger start/stop hooks (Bug2Go, SilentLogger, PixelLogger, MTK DebugLoggerUI).
- On-demand PNG screenshots from the selected Android device.

Requirements:
- Python 3.8+ on Windows.
- Tkinter available with your Python installation.
- ADB available. The app prefers the bundled adb at Cmdlets\iperf_installer\programs\adb.exe, and falls back to system adb if not found.
- An Android-compatible tcpdump binary. By default, the app looks at Cmdlets\tcpdump_installer\programs\tcpdump (no extension), or you can browse to a different file from the GUI.

How to run:
1) Open a terminal in this folder (C:\Users\forre\Desktop\Coding\logger).
2) Run:  python logger.py
3) In the GUI:
   - Click Refresh to list connected devices and select one.
   - Choose an output directory (default: ./Logs).
   - Enter a Test case name (an additional subfolder will be created under the output directory).
   - On the Session tab, select which sources to capture. Settings for Screen recording, Tcpdump, and Modem logs appear only when that source is enabled.
   - The chipset selector auto-populates from one Android getprop snapshot when a device is selected or refreshed; it can still be overridden manually. Enable "Modem logs" and choose the compatible MediaTek or Samsung Qualcomm profile.
   - Samsung Qualcomm capture uses the privileged com.sec.modem.settings SilentLog receiver and requires a firmware/device with valid Samsung OTP authorization. On commercial builds this is commonly provisioned through /efs/sec_efs/.otp_auth. The app reports a clear start timeout when authorization is missing.
   - Click "Manage…" beside the modem profile to create, duplicate, edit, delete, and save profiles in modem_logging_profiles.json. Profiles control SD/PLS/USB mode, MD type, size limit, storage, autostart, exception auto-reset, notifications, TagLog, timeouts, and the device log root.
   - The settings page labels every numeric mapping. Modem type 1 is MD1 (the primary cellular modem); modem type 3 is MD3 (a secondary/legacy modem, when the platform provides one).
   - MediaTek log types use an additive bitmask: 1=Mobile/AP, 2=Modem, 4=Network, 16=GPS host, 32=Connsys firmware, and 64=Bluetooth HCI host. For example, Modem only is 2; Mobile+Modem+Network is 7; all supported types is 119. Bit 8 is unused/reserved. A modem profile always includes bit 2.
   - Expand "Advanced options" only when you need OEM logging, disconnect/reconnect behavior, output zipping, or to skip post-processing.
   - Choose a Screenrecord video quality. Low is about 4 MB per 15 seconds, Medium about 8 MB, and High about 15 MB. Device default preserves the phone's original encoder setting.
   - The Events tab contains the four quick-event fields and opens automatically when capture begins. Live status and diagnostics are on the Output tab.
   - Click "Take Screenshot" whenever you need a still image. During a session it is saved in that session folder; otherwise a new output folder is created.
   - Click "Start" to begin the session; click "Stop" to end:
       * Tcpdump: if not found on device, the app will:
         - create /data/local/tmp if needed,
         - push the provided tcpdump binary,
         - chmod 6755 /data/local/tmp/tcpdump,
         - stream packets using: adb exec-out tcpdump -i any -s 0 -w -
       * MediaTek logs: DebugLoggerUI is configured from the selected profile and every selected bitmask type is started. Multi-type profiles are reset first so Mobile, Modem, Network, GPS, Connsys, and Bluetooth loggers create clean session folders rather than continuing unrelated historical captures.
       * Samsung Qualcomm logs: SilentLog is started/stopped through its explicit Android broadcast receiver, readiness is verified with dev.silentlog.on, and an existing capture is cycled first to isolate the session.
       * Samsung Qualcomm collection pulls only files created by the session from /sdcard/log/cp and /sdcard/log/ap_silentlog into Device_Logs/Samsung/SilentLog.
       * Stop finalizes the modem .muxz and recreates DebugLoggerUI's familiar layout under device_logs: connsyslog, mdlog1, mdlog1_config, mobilelog, netlog, and file_tree.txt. Selected session folders remain beneath their original relative paths.
       * The exact selected profile, per-type remote paths, successful pulls, and missing/failed types are recorded in modem_profile_used.json inside the session output.
       * After Stop, if "Zip session output at end" is enabled and 7z.exe is present, the session folder is zipped; otherwise files remain in the output folder.

Notes:
- Captures are stored under a timestamped session directory as logradio.txt, logmain.txt, logkernel.txt, logevents.txt, logsystem.txt, logall.txt, capture_*.pcap, and optional device_logs files.
- MediaTek .muxz traces are binary. Decode them with compatible MediaTek/OEM tooling and keep the MDDB_PHONE*.EDB and DbgInfo*.EDB.xz files from the same capture.
- Some devices need root to run tcpdump on all interfaces; if captures are empty, try enabling root (adb root) if supported.
- If you see no devices, ensure USB debugging is enabled and authorize the PC on the device.
