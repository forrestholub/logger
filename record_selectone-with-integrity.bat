@echo OFF
REM SETLOCAL ENABLEDELAYEDEXPANSION
REM CONSTANTS
SET yourself=%0

adb kill-server
adb start-server

:SETUP
call pick_1_device.bat

:RECORD
FOR /F "tokens=1-3 delims=/ " %%i IN ("%date:~0,10%") DO SET d=%%i%%j%%k
FOR /F "tokens=1-3 delims=: " %%i IN ("%time:~0,8%")  DO SET t=%%i%%j%%k
SET log_dir=%d%_%t%

cmd /c "exit /b 0"
ECHO eror level after reset %ERRORLEVEL%
REM SET "%ERRORLEVEL%"="0"

REM SET --bit-rate to 4MB -- time limit to 60 seconds -- also show-clock
ECHO.
echo Recording in progress...
ECHO.
START "screen_record" cmd /K "adb.exe -d -s %use_device% shell screenrecord --bit-rate 4000000 --bugreport --time-limit 60 /sdcard/video.mp4"
ECHO ERROR LEVEL %ERRORLEVEL%
PAUSE
START "video_integrity" cmd /K CALL video_integrity %use_device%

SET "RTN=%RTN%"
ECHO RTN=%RTN%
ECHO ERROR LEVEL %ERRORLEVEL%
PAUSE
REM IF %ERRORLEVEL% EQU 1 GOTO :RESTART_RECORDING

REM CONTINUES IF RUNNING NORMALLY....
ECHO.
echo Use [/C] to stop recording. If reached max record time, press any button to pull video...
ECHO.
PAUSE>NUL

adb -d -s %use_device% pull /sdcard/video.mp4 ./video_%log_dir%_Device_%dev_let%_%use_device%_%comment%.mp4

adb -d -s %use_device% shell rm /sdcard/Video.mp4
ECHO.
echo Video has ended!
ECHO.
GOTO :EOF

:RESTART_RECORDING
ECHO Restarting recording (THat stuff)
PAUSE
TASKKILL /IM cmd.exe /FI "WINDOWTITLE eq screen_record"
TASKKILL /IM adb.exe /FI "WINDOWTITLE eq screen_record"
adb -d -s %use_device% shell rm /sdcard/Video.mp4
GOTO :RECORD 

:HELP
    ECHO.
    ECHO Usage: %~nx0 [OPTION...]
    ECHO.
    ECHO.  Options:
    ECHO.      /?                       Help
	ECHO.	   1st param				Serial No.
	ECHO.	   2nd param				Device Letter:A,B,C
	ECHO.	   3rd param				Description of video: no-spaces-please.
	ECHO. Nothing fancy round here..................
	
    EXIT /b 0

REM ENDLOCAL

:EOF
Exit /b 0

