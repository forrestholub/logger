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

:SETUP
IF "%1"=="/?" GOTO :HELP

IF NOT "%1"=="" GOTO :RECORD

IF NOT "%device_count%"=="1" CALL master-mutli-man_v1.1 0 0 0 %yourself%

IF "%1"=="" ( (IF NOT "%device_count%"=="1" CALL master-mutli-man_v1.1 0 0 0 %yourself% )
	FOR /F "tokens=1 delims=" %%A in ('adb -d get-serialno') do SET serialno=%%A
	SET /p dev_letter="Set Device Letter: "
	SET /p comment="Set comment: "
	start cmd /C Call %yourself% %serialno% %dev_letter% %comment% 
    GOTO :EOF )

:RECORD
FOR /F "tokens=1-3 delims=/ " %%i IN ("%date:~0,10%") DO SET d=%%i%%j%%k
FOR /F "tokens=1-3 delims=: " %%i IN ("%time:~0,8%")  DO SET t=%%i%%j%%k
SET log_dir=%d%_%t%

ping -n 1 127.0.0.1 > NUL
REM SET --bit-rate to 4MB -- time limit to 60 seconds -- also show-clock
echo Recording in progress...
START cmd /K CALL video_integrity %dev_serial%
adb -d -s %1 shell screenrecord --bit-rate 4000000 --bugreport --time-limit 60 /sdcard/video.mp4
IF %ERRORLEVEL% EQU 1 ( SET ERRORLEVEL=0 , GOTO :RESTART_RECORDING )
echo Use [/C] to stop recording. If reached max record time, press any button to pull video...
pause>Nul
adb -d -s %1 pull /sdcard/video.mp4 ./video_%log_dir%_Device_%dev_let%_%dev_serial%_%comment%.mp4

adb -d -s %1 shell rm /sdcard/Video.mp4
echo Video has ended!
GOTO :EOF
REM echo %4 is device count list
REM echo %device_count% is device count using var
REM echo %device_1%  should be same as above
REM echo %5 2nd on list using param val
REM echo %device_2%  6th param  2nd on the list using var
REM echo %device_3%  7th param 3rd on list using var

REM :check_video_integrity
REM REM wait until video file should be large enought to qualify as working ~4MB
REM timeout /t 10
REM SET /a min_filesize=102

	REM FOR /F "delims= " %%A in ('adb -d -S %1 shell "cd /sdcard/ && ls -s video.mp4"') do (
	REM SET  filesize=%%A
	REM IF "%filesize%" LSS "%min_filesize%" (
		REM SET RTN=1
		REM ECHO. Video recording integrity compromised. Size recorded was only: %filesize% kilobytes. Restarting video recording...
		REM EXIT /B %RTN%)ELSE ( 
			REM SET RTN=0
			REM ECHO. Video recording integrity validated. Size recorded was: %filesize% kilobytes and growing. Continuing recording...
			REM EXIT /B %RTN%)
	REM )

:RESTART_RECORDING
adb -d -s %1 shell rm /sdcard/Video.mp4
IF %ERRORLEVEL% EQU 0 ( GOTO :RECORD
) ELSE ( GOTO :EOF )

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

