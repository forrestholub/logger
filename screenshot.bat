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

adb wait-for-device 

adb shell screencap -p /sdcard/screen.png
echo SNAP!
adb pull /sdcard/screen.png ./Screenshot_%log_dir%_%1.png

adb shell rm /sdcard/screen.png

echo DONE BOOM!

GOTO :EOF

:help
    ECHO.
    ECHO Usage: %~nx0 [OPTION...]
    ECHO.
    ECHO.  Options:
    ECHO.      /?                       Help
	ECHO.	   1st param				Screenshot_Name (no-spaces-allowed)
	ECHO.
	ECHO. Use this cmd window to execute additional screenshots by typing 'screenshot' plus enter key
	ECHO. Don't worry about re-write, a new timestamp will be generated with screenshot
    EXIT /b 0

ENDLOCAL

:EOF
Exit /b 0