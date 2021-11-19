@echo OFF
SETLOCAL ENABLEDELAYEDEXPANSION
::Project Name: Auto Logger
::Version: 3.0
::Revision Date: 201103
::Author: Forrest Holub
::Company: Arclight Wireless
::Copywrite: MIT Open Source License

::CMDlet locations

SET deviceinfo=%~dp0Cmdlets\deviceinfo.bat
SET logging_all=%~dp0Cmdlets\logging_all.bat
SET record=%~dp0Cmdlets\record.bat
SET repro=%~dp0Cmdlets\repro.bat
SET screenshot=%~dp0Cmdlets\screenshot.bat

:setup
IF "%1"=="/?" (
	GOTO :help
	)

:: START 
:::01010101010101010101010101010101010101010101010101010101010101010101010101010101010:::

CALL :get_device_info
CALL :determine_device
CALL :imei
CALL :build_folder

CHOICE /C yn /N /M "Are logs on device?: [y]-- YES ; [n]-- NO "
IF %ERRORLEVEL% EQU 1 CALL :PULL_LOGS
IF %ERRORLEVEL% EQU 2 CALL :GET_LOGS

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
	ECHO.	   LG G5 logging code		*#546368#*820#
	ECHO. 	   LG V60 logging code		*#546368#*600#
	ECHO. 	   LG Debug (all phones)	2777634#*# 
	ECHO.
	ECHO.
    EXIT /b 0


	
:get_device_info
:: create new folder for phone using known info -- use list
adb kill-server >NUL
adb start-server >NUL
adb wait-for-device >NUL
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
:imei
IF "%imei%"=="" (
	SET /P "imei=Input device last four IMEI: " 
)
exit /b 0

:build_folder

CHOICE /C 135 /N /M "Select reason for test: [1]New Failure Log -- [3]Retest Log -- [5] Other	-- will leave blank"

IF %ERRORLEVEL% EQU 1 SET test=TC-
IF %ERRORLEVEL% EQU 2 SET test=IKSWQ-
IF %ERRORLEVEL% EQU 3 SET test=Issue-


:: test if I can set test value successfully and append to logname
:: also test to see if tc number can be appended using input request below
SET log-name-incomplete=%log-time%_%device%-%last_four_imei%_%test%

ECHO Complete this log name: %log-name-incomplete%  _____________
SET /p detail= "":
ping -n 1 127.0.0.1 > NUL
:: give cpu a second to save the number received by user`

mkdir %log-time%_%device%-%last_four_imei%_%test%%detail%
cd %log-time%_%device%-%last_four_imei%_%test%%detail%

SET log-name=%log-time%_%device%-%last_four_imei%_%test%%detail%

exit /b 0


:PULL_LOGS

if "%brand%"=="motorola" (
	GOTO :PULL_MOTO
)

if "%brand%"=="lge" (
	GOTO :PULL_LG	
)

:PULL_MOTO
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
	adb shell rm -r /data/vendor/bug2go/*
)	
IF "%loglocation%"=="2" (
	echo pulling from device storage
	adb pull /storage/emulated/0/Android/data/com.motorola.bug2go/files
	
	mkdir additional-mdm-logs
	cd additional-mdm-logs
	echo pulling extra diag mdm logs
	adb pull /data/vendor/diag_mdlog/logs
	adb shell rm -r /storage/emulated/0/Android/data/com.motorola.bug2go/files/*
	adb shell rm -r /data/vendor/diag_mdlog/logs/*

IF "%loglocation%"=="3" (
	mkdir additional-mdm-logs
	cd additional-mdm-logs
	echo pulling extra diag mdm logs
	adb pull /data/vendor/diag_mdlog/logs
	adb shell rm -r /data/vendor/diag_mdlog/logs/*
)	

:: shhhh just pull it all baby
adb pull /sdcard/pictures/screenshots/
adb shell rm -r /sdcard/pictures/screenshots/*
adb pull /sdcard/videos/
adb shell rm -r /sdcard/videos/*
CALL deviceinfo
exit /b 0

:PULL_LG
adb pull /sdcard/logger/
IF (%ERRORLEVEL% EQU 1 ) 
( exit /b 1
) ELSE 
(
adb shell rm -r /sdcard/logger/*
adb pull /sdcard/pictures/screenshots/
adb shell rm -r /sdcard/pictures/screenshots/*
adb pull /sdcard/videos/
adb shell rm -r /sdcard/videos/*
)
CALL deviceinfo
exit /b 0

:GET_LOGS
mkdir AP_Logs 
mkdir Videos
mkdir Screenshots
mkdir BP_Logs
ping -n 2 127.0.0.1 > NUL

:: now we start logging 
adb -d wait-for-device
CALL %deviceinfo%

echo START REPRODUCTION TEXT
START CALL %repro%

ping -n 1 127.0.0.1 > NUL
ECHO Clear previous logs

START /D "%cd%\AP_Logs\" CALL adb logcat -c

ECHO START AP LOGS (minimized)
ECHO %logging_all%
START /D "%cd%\AP_Logs\" CALL %logging_all%

ping -1 2 127.0.0.1 > NUL
ECHO START VIDEO RECORDING
ECHO %record%
START /D "%cd%\Videos\" CALL %record%

ping -1 2 127.0.0.1 > NUL
ECHO START SCREENSHOT CAPTURE
START /D "%cd%\Screenshots\" CALL %screenshot%

exit /b 0

:zippy
cd ..
C:\"Program Files"\7-Zip\7z.exe a -tzip %~1.zip "%cd%\"%~1\*
GOTO :END



:END

echo Quality is never an accident; it is always the result of intelligent effort.
ENDLOCAL
EXIT /B 0



