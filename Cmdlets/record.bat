@ECHO OFF
SETLOCAL ENABLEDELAYEDEXPANSION
REM CONSTANTS
SET yourself=%0

:SETUP
IF "%1"=="/?" (
	GOTO :help
	)
	
:MAIN
FOR /F "tokens=1-3 delims=/ " %%i IN ("%date:~0,10%") DO SET d=%%i%%j%%k
FOR /F "tokens=1-3 delims=: " %%i IN ("%time:~0,8%")  DO SET t=%%i%%j%%k

SET log_dir=%d%_%t%

adb start-server
adb wait-for-device 
echo Type 'record /?' for help
echo Recording in progress...
adb shell screenrecord --bit-rate 3000000 --bugreport /sdcard/Video.mp4 

adb pull /sdcard/Video.mp4 ./Video.%log_dir%_%1.mp4


adb shell rm /sdcard/Video.mp4
ping -n 1 127.0.0.1 > NUL

echo Video has ended!
GOTO :EOF

:help
    ECHO.
    ECHO Usage: %~nx0 [OPTION...]
    ECHO.
    ECHO.  Options:
    ECHO.      /?                       Help
	ECHO.	   1st param				Record_name (No-spaces-allowed)
	ECHO.
	ECHO. Use ctrl + c to stop video recording. Then type 'n'. 
    EXIT /b 0

ENDLOCAL

:EOF
Exit /b 0

