@ECHO OFF


:actionstart
echo A new round log start:>>%1_logall_.txt
echo " " >>%1_logall_%.txt
echo radio logging start
start /min cmd /C adb -s %1 logcat -b radio -v threadtime ^>^>1_logradio_%.txt
echo main logging start
start /min cmd /C adb -s %1 logcat -b main -v threadtime ^>^>%1_logmain_.txt
echo kernel logging start
start /min cmd /C adb -s %1 logcat -b kernel -v threadtime ^>^>%1_logkernel.txt
echo event logging start
start /min cmd /C adb -s %1 logcat -b events -v threadtime ^>^>%1_logevents_.txt
echo system logging start
start /min cmd /C adb -s %1 logcat -b system -v threadtime ^>^>%1_logsystem_.txt
echo logging all start
adb -s %1 logcat -b all -v threadtime >>%1_logall_.txt
exit /b