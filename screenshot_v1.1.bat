@ECHO OFF
SETLOCAL ENABLEDELAYEDEXPANSION
REM CONSTANTS
SET yourself=%0

:SETUP
IF "%1"=="/?" (
	GOTO :help
	)
IF NOT "%1"=="" ( 
    GOTO :MAIN
) ELSE (
	FOR /F "tokens=1 delims=" %%A in ('adb -d get-serialno') do start cmd /k Call %yourself% %%A 
    GOTO :EOF )
	
:MAIN
FOR /F "tokens=1-3 delims=/ " %%i IN ("%date:~4,10%") DO SET d=%%i%%j%%k
FOR /F "tokens=1-3 delims=: " %%i IN ("%time:~0,8%")  DO SET t=%%i%%j%%k
SET log_dir=%d%_%t%

adb -d -s %1 shell screencap -p /sdcard/screen.png
echo SNAP!
adb -d -s %1 pull /sdcard/screen.png ./Screenshot_%log_dir%_%2.png
echo PULL!
adb -d -s %1 shell rm /sdcard/screen.png

GOTO :EOF

:help
    ECHO.
    ECHO Usage: %~nx0 [OPTION...]
    ECHO.
    ECHO.  Options:
    ECHO.      /?                       Help
	ECHO.	   1st param				Serial No.
	ECHO.	   2nd param				Screenshot_Name
	ECHO. Nothing fancy round here..................
	
    EXIT /b 0

ENDLOCAL

:EOF
Exit /b 0