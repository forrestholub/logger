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
echo A new round log start:>>logall.txt
echo " " >>logall.txt
echo If you don't see "adb -d connected" in long time, please check adb -d connection.
adb -d wait-for-device 
echo adb -d connected
echo radio logging start
start /min cmd /C adb -d logcat -b radio -v threadtime ^>^>logradio.txt
echo main logging start
start /min cmd /C adb -d logcat -b main -v threadtime ^>^>logmain.txt
echo kernel logging start
start /min cmd /C adb -d logcat -b kernel -v threadtime ^>^>logkernel.txt
echo event logging start
start /min cmd /C adb -d logcat -b events -v threadtime ^>^>logevents.txt
echo system logging start
start /min cmd /C adb -d logcat -b system -v threadtime ^>^>logsystem.txt
echo logging all start
adb -d logcat -b all -v threadtime >>logall.txt

GOTO :EOF

:help
    ECHO.
    ECHO Usage: %~nx0 [OPTION...]
    ECHO.
    ECHO.  Options:
    ECHO.      /?                       Help
	ECHO.	   1st param				Serial No.
	ECHO.	   2nd param				Device Letter:A,B,C
	ECHO.
	ECHO. Nothing fancy round here..................
	
    EXIT /b 0

ENDLOCAL

:EOF
Exit /b 0