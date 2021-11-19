@ECHO OFF
:actionstart
echo A new round log start:>>logall.txt
echo " " >>logall.txt
echo If you don't see "ADB connected" in long time, please check ADB connection.
adb wait-for-device 
echo ADB connected
echo radio logging start
start /min cmd /C adb logcat -b radio -v threadtime ^>^>logradio.txt
echo main logging start
start /min cmd /C adb logcat -b main -v threadtime ^>^>logmain.txt
echo kernel logging start
start /min cmd /C adb logcat -b kernel -v threadtime ^>^>logkernel.txt
echo event logging start
start /min cmd /C adb logcat -b events -v threadtime ^>^>logevents.txt
echo system logging start
start /min cmd /C adb logcat -b system -v threadtime ^>^>logsystem.txt
echo logging all start
adb logcat -b all -v threadtime >>logall.txt
exit /b