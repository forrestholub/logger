@echo OFF
REM SETLOCAL ENABLEDELAYEDEXPANSION
REM CONSTANTS      
SET yourself=%0
SET device_3=%7
SET device_2=%6
SET device_1=%5
SET device_count=%4
SET comment=%3
SET dev_let=%2
SET dev_serial=%1
SET /A record_num=0

SET video_integrity="%~dp0video_integrity.bat"

:SETUP
IF "%1"=="/?" GOTO :HELP
IF NOT "%1"=="" GOTO :RECORD

@REM IF NOT "%device_count%"=="1" CALL master-mutli-man_v1.1 0 0 0 %yourself%
@REM IF "%1"=="" ( (IF NOT "%device_count%"=="1" CALL master-mutli-man_v1.1 0 0 0 %yourself% )
@REM 	FOR /F "tokens=1 delims=" %%A in ('adb -d get-serialno') do SET serialno=%%A
@REM 	SET /p dev_letter="Set Device Letter: "
@REM 	SET /p comment="Set comment: "
@REM 	start cmd /C Call %yourself% %serialno% %dev_letter% %comment% 
@REM     GOTO :EOF )

:RECORD
SET /a record_num=%record_num%+1
FOR /F "tokens=1-3 delims=/ " %%i IN ("%date:~0,10%") DO SET d=%%i%%j%%k
FOR /F "tokens=1-3 delims=: " %%i IN ("%time:~0,8%")  DO SET t=%%i-%%j-%%k
SET log_dir=%d%_%t%

ping -n 1 127.0.0.1 > NUL
REM SET --bit-rate to 4MB -- time limit to 60 seconds -- also show-clock
echo Recording in progress...
START /MIN "ADB_RECORD" cmd /C adb -s %dev_serial% shell screenrecord --bugreport --time-limit 1200 /sdcard/video.mp4
CALL %video_integrity% %dev_serial%
::ECHO %ERRORLEVEL%
IF "%ERRORLEVEL%"=="4" CALL :KILL_RECORDING
IF "%ERRORLEVEL%"=="8" CALL :MANAGE_RECORDING
GOTO :EOF

:MANAGE_RECORDING
CALL
REM if recording IS good, check if the process is running (once per second). After process ends, pull log and goto restart_recording
SET /A i = 1

:loop 
IF %i%==62 GOTO :RESTART_RECORDING
echo Recording seconds elapsed : %i%
FOR /f "eol=c delims=, " %%Z in ('tasklist /FI "WINDOWTITLE eq ADB_RECORD" /FO CSV') DO SET recording_word=%%Z
IF %recording_word%=="cmd.exe" (ECHO.)ELSE GOTO :RESTART_RECORDING
SET /a i=%i%+1
timeout 1 >NUL
GOTO :loop

:RESTART_RECORDING
CALL
echo Video has ended! Pulling files...
adb -s %dev_serial% pull /sdcard/video.mp4 ./video_%log_dir%.mp4
adb -s %dev_serial% shell "rm /sdcard/Video.mp4"
CHOICE /C yn /D y /T 4 /N /M "Continue Recording? [Y] or [N]"
IF %ERRORLEVEL% EQU 1 GOTO :RECORD
IF %ERRORLEVEL% EQU 2 GOTO :EOF
GOTO :RECORD

:KILL_RECORDING
CALL
@REM FOR /f "delims=" %%A in ('adb shell "ps -eo pid,args | grep -m 1 'screenrecord --bit-rate 4000000 --bugreport --time-limit 60 /sdcard/video.mp4' | awk '{ print $1 }'"') do SET recording_pid=%%A
@REM adb shell "kill %recording_pid%"
@REM ECHO "killing process: %recording_pid%"
adb -s %dev_serial% shell "ps -eo pid,args | grep 'screenrecord --bugreport --time-limit 60 /sdcard/video.mp4' | awk '{ print $1 }' | xargs kill x"
adb -s %dev_serial% shell rm /sdcard/video.mp4
::xargs -I X adb -s X shell getprop ro.build.version.release
::try: adb shell "ps -eo pid,args | grep -m 1 'screenrecord  --bugreport --time-limit 60 /sdcard/video.mp4' | awk '{ print $1 }' | xargs kill"
::taskill /F WINDOWTITLE eq "ADB_RECORD"
::kill `ps -eo pid,args | grep -m 1 '/screenrecord  --bugreport --time-limit 60 /sdcard/video.mp4/ | grep -v grep | awk '{ print $1 }'`
CHOICE /C yn /D y /T 5 /N /M "Continue Recording? [Y] or [N]"
IF %ERRORLEVEL% EQU 1 GOTO :RECORD
IF %ERRORLEVEL% EQU 2 GOTO :EOF
GOTO :RECORD

exit /b 0

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
FOR /F "delims= " %%A in ('adb -s %dev_serial% shell "cd /sdcard/ && ls -s video.mp4"') do ( SET /A cur_filesize=%%A)
IF %cur_filesize% LSS 10 (ECHO No file to pull)ELSE adb -s %dev_serial% pull /sdcard/video.mp4 ./video_%log_dir%.mp4
ECHO Make sure you /C on any open "ADB_RECORD" command windows open. Then press enter to pull last video log
PAUSE

Exit /b 0

