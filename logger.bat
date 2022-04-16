@echo OFF
SETLOCAL ENABLEDELAYEDEXPANSION
::Project Name: Auto Logger
::Version: 3.0
::Revision Date: 201103
::Author: Forrest Holub
::Company: Arclight Wireless
::Copywrite: MIT Open Source License

:: lib path:
SET seven_zip=%~dp0Programs\7-Zip\7z.exe

::CMDlet locations

SET deviceinfo="%~dp0Cmdlets\deviceinfo.bat"
SET logging_all="%~dp0Cmdlets\logging_all.bat"
SET record="%~dp0Cmdlets\record.bat"
SET repro="%~dp0Cmdlets\repro.bat"
SET screenshot="%~dp0Cmdlets\screenshot.bat"

REM ECHO %deviceinfo%
REM ECHO %logging_all%
REM ECHO %record%
REM ECHO %repro%
REM ECHO %screenshot%

REM MAKE SURE THE ERRORLEVEL IS SET TO 0
CALL 
:setup
IF "%1"=="/?" (
	GOTO :help
	)


:: START 
:::01010101010101010101010101010101010101010101010101010101010101010101010101010101010:::

CHOICE /C dlp /N /M "[D]On-Device Logging -- [L]Laptop Logging -- [P] Pull logs ;"
IF %ERRORLEVEL% EQU 1 CALL :Device_Logs
IF %ERRORLEVEL% EQU 2 CALL :Laptop_Logs
IF %ERRORLEVEL% EQU 3 CALL :Pull_Logs

CHOICE /C 17 /N /M "Press [7] to 7zip file, otherwise press [1] to exit"

IF %ERRORLEVEL% EQU 1 GOTO :END
IF %ERRORLEVEL% EQU 2 CALL :zippy %log-name%

EXIT /b 0
:: END
:::01010101010101010101010101010101010101010101010101010101010101010101010101010101010:::

:::-------------------------------Functions begin---------------------------------------------------------------------------------------
:help
    ECHO.
    ECHO Usage: %~nx0 [OPTION...]
    ECHO.
    ECHO.  Options:
    ECHO.      /?                       Help
	ECHO. On device logging help:
	ECHO.
	ECHO.	   LG G6 logging code		*#546368#*872#
	ECHO.	   LG G5 logging code		*#546368#*830#
	ECHO. 	   LG V60 logging code		*#546368#*600#
	ECHO. 	   LG Debug (all phones)	2777634#*# 
	ECHO.      Mediatek logging code 	*#*#3646633#*#*
	ECHO.	   Mediatek logging code2   #*#*873733284#*#*
	ECHO.	   
    EXIT /b 0

:get_device_info
:: create new folder for phone using known info -- use list
adb kill-server
adb start-server
ECHO Waiting for ADB device to populate.... if waiting long time check connection and re-run script.
adb wait-for-device
:: Set time
FOR /F "tokens=1-6 delims=/ " %%i IN ("%date:~4,5%") DO SET dm=%%i
FOR /F "tokens=1-6 delims=/ " %%j IN ("%date:~6,7%") DO SET dd=%%j
FOR /F "tokens=1-2 delims=/ " %%k IN ("%date:~12,13%") DO SET dy=%%k
FOR /F "tokens=1-6 delims=/ " %%l IN ("%date:~0,3%") DO SET dw=%%l
FOR /F "tokens=1-6 delims=: " %%i IN ("%time:~0,20%")  DO SET t=%%i%%j%%k%%l
:: 11,12

:: get device name for log file generated
for /f "delims=" %%A in ('adb -d shell getprop ro.product.brand') do SET brand=%%A
for /f "delims=" %%A in ('adb -d shell getprop ro.boot.device') do SET devicecodename=%%A
for /f "delims=" %%A in ('adb -d shell getprop ro.product.device') do SET product=%%A
for /f "delims=" %%A in ('adb -d shell getprop ro.product.model') do SET model=%%A
for /f "delims=" %%A in ('adb -d get-serialno') do SET serialno=%%A

REM PULL---- IMEI ----iphonesubinfo 1 (IMEI/MEID)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d shell service call iphonesubinfo 1') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
FOR /F "tokens=1 delims=" %%i IN (temp.txt) DO SET imei=%%i 
IF EXIST temp.txt del temp.txt
SET last_four_imei=%imei:~11,14%
SET last_four_imei=!last_four_imei: =!

ECHO.WELCOME TO THE AUTOMATIC LOG GENERATOR. 
ECHO.::::::::::::::::::::::::::::::::::::::::
ECHO. HAPPY.LOGGING.
ECHO.::::::::::::::::::::::::::::::::::::::::


SET log-time=%dy%%dm%%dd%
ping -n 3 127.0.0.1 > NUL
exit /b 0

:determine_device
if "%brand%"=="motorola" (
	SET device=%product%
	IF "%product%"=="" (
		SET /P "device=Enter product name: "
	)
	exit /b 0
)
if "%brand%"=="samsung" (
	SET device=%model%
	IF "%model%"=="" (
		SET /P "device=Enter product name: "
	)
	exit /b 0
)
if "%brand%"=="lge" (
	SET device=%model%
	IF "%model%"=="" (
		SET /P "device=Enter product name: "
	)
	exit /b 0
)
if "%brand%"=="google" (
	REM remove whitespace from model so 'Pixel 2' becomes 'Pixel2 '
	SET device=!model: =!
	IF "%model%"=="" (
		SET /P "device=Enter product name: "
	)
	exit /b 0
)
if "%devicecodename%"=="" (
	SET device=%product%
	) ELSE (
		SET device=%devicecodename%)
exit /b 0

:: input device last four IMEI
:check_imei
IF "%imei%"=="" (
	SET /P "lastfourimei=Input device last four IMEI: "
) ELSE (
    SET lastfourimei=%imei:~11,14%
)
SET lastfourimei_noSPACE=%lastfourimei: =%

:build_folder
:: test if I can set test value successfully and append to logname
:: also test to see if tc number can be appended using input request below
SET log-name-incomplete=%log-time%_%device%-%lastfourimei_noSPACE%_

ECHO Complete this log name: %log-name-incomplete%  _____________
SET /p detail= "":
ping -n 1 127.0.0.1 > NUL
:: give cpu a second to save the number received by user`

mkdir %log-time%_%device%-%lastfourimei_noSPACE%_%test%%detail%
cd %log-time%_%device%-%lastfourimei_noSPACE%_%test%%detail%

SET log-name=%log-time%_%device%-%lastfourimei_noSPACE%_%test%%detail%

exit /b 0


:Device_Logs
CALL :get_device_info
CALL :determine_device
CALL :check_imei
CALL :build_folder
Call :Both_Logs

ECHO After test case has been reproduced, click any button to continue with log pull
pause 1>NUL

:Pull_Logs
CHOICE /C 1234 /N /M "(1)--Bug2Go, (2)--LG-on-device, (3)--Mediatek (4)--skip/exit" 

IF %ERRORLEVEL% EQU 1 GOTO :PULL_Bug2Go
IF %ERRORLEVEL% EQU 2 GOTO :PULL_LG	
IF %ERRORLEVEL% EQU 3 GOTO :PULL_MediaTek	
IF %ERRORLEVEL% EQU 4 GOTO :END

:PULL_Bug2Go
adb root >NUL
mkdir Bug2goFiles
ping -n 2 127.0.0.1 > NUL
cd Bug2goFiles

ECHO. Locations of log files
ECHO. 1 - Data files
ECHO. 2 - SD Card
ECHO. 3 - Pull Extra Modem Logs
SET /P "loglocation=Which directory is the log file in? ":

IF "%loglocation%"=="1" (
	echo pulling from data files
	adb pull /data/vendor/bug2go/ 
)	
IF "%loglocation%"=="2" (
	ECHO. 1 - New app
	ECHO. 0 - Old app (prior to 2022)
	SET /P "app_choice=Choose option:"
	IF "%app_choice%"=="1"(
		echo pulling from sdcard/download
		adb pull /sdcard/download/
	)
	IF "%app_choice%"=="0"(
		echo pulling from sdcard/Android/data/
		adb pull /storage/emulated/0/Android/data/com.motorola.bug2go/files
	)
IF "%loglocation%"=="3" (
	mkdir additional-mdm-logs
	cd additional-mdm-logs
	echo pulling extra diag mdm logs
	adb pull /data/vendor/diag_mdlog/logs
)

ECHO. Log Removal
ECHO. 1 - Yes
ECHO. 0 - No
SET /P "remove_device=Remove all logs from device? ":
IF "%remove_device%"=="1" (
	adb shell rm -r /data/vendor/bug2go/*
	adb shell rm -r /storage/emulated/0/Android/data/com.motorola.bug2go/files/*
	adb shell rm -r /data/vendor/diag_mdlog/logs/*
	adb shell rm -r /data/vendor/diag_mdlog/logs/*
	adb shell rm -r /sdcard/download/*
)
IF "%remove_device%"=="0" (
	ECHO Nothing removed from device..
)
:: shhhh just pull it all baby
adb pull /sdcard/pictures/screenshots/
adb shell rm -r /sdcard/pictures/screenshots/*
@REM adb pull /sdcard/videos/
@REM adb shell rm -r /sdcard/videos/*
exit /b 0

:PULL_LG
call 
adb pull /sdcard/logger/
IF (%ERRORLEVEL% EQU 1 ) 
( exit /b 1
) ELSE 
(
adb shell rm -r /sdcard/logger/*
adb pull /sdcard/pictures/screenshots/
adb shell rm -r /sdcard/pictures/screenshots/*
)
exit /b 0

:PULL_MediaTek
ECHO. Locations of log files
ECHO. 1 - Data files
ECHO. 2 - SD Card
SET /P "loglocation=Which directory is the log file in? ":
CALL 
IF "%loglocation%"=="1" (
	echo pulling from data files
	adb pull /data/debuglogger/
	IF %ERRORLEVEL% EQU 0 ( adb shell rm -r /data/debuglogger/* ) ELSE ( ECHO Unable to pull logs, something went wrong ))
IF "%loglocation%"=="2" (
	echo pulling from device storage
	adb pull /sdcard/debuglogger/
	IF %ERRORLEVEL% EQU 0 ( adb shell rm -r /sdcard/debuglogger/* ) ELSE ( ECHO Unable to pull logs, something went wrong ))
:: shhhh just pull it all baby
CALL 
adb pull /sdcard/pictures/screenshots/
IF %ERRORLEVEL% EQU 0 ( adb shell rm -r /sdcard/pictures/screenshots/* ) ELSE ( ECHO Unable to remove screenshots )
exit /b 0

:Laptop_Logs
CALL :get_device_info
CALL :determine_device
CALL :check_imei
CALL :build_folder
Call :Both_Logs

ping -n 1 127.0.0.1 > NUL
ECHO Clear previous logs

START /D "%cd%\AP_Logs\" CALL adb logcat -c

ECHO START AP LOGS (minimized)
START /D "%cd%\AP_Logs\" CALL %logging_all%
exit /b 0

:Both_Logs
mkdir AP_Logs 
mkdir Videos
mkdir Screenshots
mkdir BP_Logs
ping -n 2 127.0.0.1 > NUL

:: now we start logging 
ECHO Waiting for ADB device to populate.... if waiting long time check connection and re-run script.
adb -d wait-for-device
CALL %deviceinfo%

echo START REPRODUCTION TEXT
START CALL %repro%
ping -1 2 127.0.0.1 > NUL
ECHO START VIDEO RECORDING
::ECHO %record%
START /D "%cd%\Videos\" CALL %record%

ping -1 2 127.0.0.1 > NUL
ECHO START SCREENSHOT CAPTURE
START /D "%cd%\Screenshots\" CALL %screenshot%
exit /b 0

:zippy
cd ..
%seven_zip% a -tzip %~1.zip "%cd%\"%~1\*
GOTO :END

:END
echo Quality is never an accident; it is always the result of intelligent effort.
ENDLOCAL
EXIT /B 0