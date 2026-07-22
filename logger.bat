@echo OFF
SETLOCAL ENABLEDELAYEDEXPANSION
::Project Name: Auto Logger
::Version: 10.2
::Revision Date: 220810
::Author: Forrest Holub
::Company: Arclight Wireless
::Copywrite: MIT Open Source License
:: latest additions:
::adds to Moto On-Device Pass Logs
:: --> allowing all qualcom logs to be included: bin, qmdl, adpl, qmdl2, 
:: --> setup protection from attempting mediatek logging
:: --> setup protection against unrooted devices (will not be able to start program)
:: --> allowing APM and Zipping as options instead of forced operation

:: future additions:
:: add status for log size while the log is running
:: add status that checks if AP logs are still running by checking the same way as "record"
:: create auto-updater by having a location on server to check the versions of all the latest sw I've released

CALL :graphic

:: lib path:
SET seven_zip="%~dp0Programs\7-Zip\7z.exe"
SET auto_apm="false"
SET execution_root_folder_path="%cd%"


::CMDlet locations

SET deviceinfo="%~dp0Cmdlets\deviceinfo.bat"
SET logging_all="%~dp0Cmdlets\logging_all.bat"
SET record="%~dp0Cmdlets\record.bat"
SET video_integrity="%~dp0Cmdlets\video_integrity.bat"
SET repro="%~dp0Cmdlets\repro.bat"
SET screenshot="%~dp0Cmdlets\screenshot.bat"

SET apm_off="%~dp0Services\droid_apm_OFF.bat"
REM ECHO %apm_off%
SET apm_on="%~dp0Services\droid_apm_ON.bat"
REM ECHO %apm_on%

REM ECHO %deviceinfo%
REM ECHO %logging_all%
REM ECHO %record%
REM ECHO %repro%
REM ECHO %screenshot%

REM MAKE SURE THE ERRORLEVEL IS SET TO 0
CALL 
:setup
IF "%1"=="-version" GOTO :version
IF "%1"=="-v" GOTO :version
IF "%1"=="/?" GOTO :help
IF "%1"=="/h" GOTO :help
IF "%1"=="--help" GOTO :help
IF "%1"=="help" GOTO :help
IF "%1"=="-help" GOTO :help
:: START 
:::01010101010101010101010101010101010101010101010101010101010101010101010101010101010:::

CHOICE /C dlpm /N /M "[D]On-Device Logging -- [L]Laptop Logging -- [P] Pull logs -- [M] Moto Pass Logs;"
IF %ERRORLEVEL% EQU 1 CALL :Device_Logs
IF %ERRORLEVEL% EQU 2 CALL :Laptop_Logs
IF %ERRORLEVEL% EQU 3 CALL :Pull_Logs
IF %ERRORLEVEL% EQU 4 CALL :Bug2goRealTime_Logs

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
adb unroot
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
for /f "delims=" %%A in ('adb -d shell getprop gsm.version.baseband') do SET baseband=%%A
for /f "delims=" %%A in ('adb -d shell getprop ro.bootmode') do SET bootmode=%%A

REM PULL---- IMEI ----iphonesubinfo 1 (IMEI/MEID)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d shell service call iphonesubinfo 1') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>imei.txt
IF EXIST imei.txt (FOR /F "tokens=1 delims=" %%i IN (imei.txt) DO SET imei=%%i )
IF EXIST imei.txt del imei.txt
SET last_four_imei=%imei:~11,14%
SET last_four_imei=!last_four_imei: =!
ECHO ::::::::::::::::::::::::::::::::::::::::
ECHO  WELCOME TO THE AUTOMATIC LOG GENERATOR
ECHO ::::::::::::::::::::::::::::::::::::::::
ECHO ...........HAPPY.LOGGING................
ECHO ::::::::::::::::::::::::::::::::::::::::

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
exit /b 0

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
SET log_directory=%cd%

ECHO log directory is:%log_directory%

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
	adb shell rm -r /data/vendor/diag_mdlog/logs/*.qmdl2
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
	adb pull /sdcard/debuglogger
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
CALL :ap_logging
CALL :bp_logging
Call :Both_Logs
Call :zippy_choice
exit /b 0

:ap_logging
ping -n 1 127.0.0.1 > NUL
ECHO Clearing old logs...
mkdir AP_Logs
SET AP_DIRECTORY="%cd%"\AP_Logs\
START /D %AP_DIRECTORY% CALL adb logcat -c

ECHO START AP LOGS (minimized)
START /D %AP_DIRECTORY% CALL %logging_all%
exit /b 0

:bp_logging
mkdir BP_Logs
SET BP_DIRECTORY="%cd%"\BP_Logs\
exit /b 0

:Both_Logs
mkdir Videos
SET Video_DIRECTORY="%cd%"\Videos\

mkdir Screenshots
SET Screenshot_DIRECTORY="%cd%"\Screenshots\
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

:: get back to main directory
cd ..
exit /b 0

:Bug2goRealTime_Logs
CALL :get_device_info
CALL :determine_device
CALL :check_imei
CALL :root_check
IF ERRORLEVEL==1 exit /b 1

REM CHECK DEVICE TYPE (qualcomm vs mediatek)
:: ECHO baseband: %baseband%
SET MTK_CHECK=%baseband:~0,2%
:: ECHO %MTK_CHECK%
IF "%MTK_CHECK%"=="MT" ECHO Mediatek device found: %baseband%, only Qualcomm chipsets allowed&exit /B 1
IF "%bootmode%"=="qcom" (
	ECHO Bootmode is QCOM, needs to be NORMAL
	ECHO changing this now..
	adb reboot bootloader
	fastboot oem config bootmode "normal"
	fastboot reboot
	adb wait-for-device
	adb root
)

SET /A i = 1
REM QUESTIONS!!!!!!!!!!!!!!!!!!!
CHOICE /C yn /N /M "Defect log? [Y] Yes or [N] No"
IF %ERRORLEVEL% EQU 1 SET defect_pass_log="true"
IF %ERRORLEVEL% EQU 2 SET defect_pass_log="false"

CHOICE /C yn /N /M "Set Airplane mode ON at beginning and end of test? [Y] Yes or [N] No"
IF %ERRORLEVEL% EQU 1 SET auto_apm="true"
IF %ERRORLEVEL% EQU 2 SET auto_apm="false"

CHOICE /C yn /N /M "ZIP files at the end of each test case? [Y] Yes or [N] No"
IF %ERRORLEVEL% EQU 1 SET auto_zip="true"
IF %ERRORLEVEL% EQU 2 SET auto_zip="false"

REM END QUESTIONS!!!!!!!!!!!!



:loop
ECHO %execution_root_folder_path%
cd %execution_root_folder_path%
CALL :build_folder
if %defect_pass_log%=="true" (
	CALL :ap_logging
	CALL :bp_logging
	Call :Both_Logs
)

SET /a i=%i%+1
ECHO %cd%
if %auto_apm%=="true" ( ECHO Action: Airplane Mode ON )
if %auto_apm%=="true" ( CALL %apm_on% )
ECHO Action: Deleting logs off phone
CALL :delete_mdm_logs
if %auto_apm%=="true" ( ECHO Action: Airplane Mode OFF )
if %auto_apm%=="true" ( CALL %apm_off% )
ECHO ----START-THE-TEST-CASE----
PAUSE
ECHO Press any key to pull logs
PAUSE > NUL
if %auto_apm%=="true" ( ECHO Action: Airplane Mode ON )
if %auto_apm%=="true" ( CALL %apm_on% )
CALL :pull_mdm_logs
ECHO Action:Deleting logs off phone
CALL :delete_mdm_logs
if %auto_zip%=="true" ( CALL :zippy %log-name% )

CHOICE /C ec /N /M "Press [e] to end logging session, otherwise press [c] to continue to next log"
IF %ERRORLEVEL% EQU 1 GOTO :END
IF %ERRORLEVEL% EQU 2 GOTO :loop
EXIT /B 0

:pull_mdm_logs
@REM SET Video_DIRECTORY="%cd%\Videos\
@REM SET Screenshot_DIRECTORY="%cd%\Screenshots\
@REM SET AP_DIRECTORY="%cd%\AP_Logs\
@REM SET BP_DIRECTORY="%cd%\BP_Logs\
@REM ls: /data/vendor/diag_mdlog/logs/*.qdss: No such file or directory
@REM adb: error: cannot create 'C:\Users\designated user\Desktop\testing\221018_milanf-1111_whynotwork\BP_Logs" ': No such file or directory
@REM ls: /data/vendor/diag_mdlog/logs/*.qmdl: No such file or directory
@REM adb: error: cannot create 'C:\Users\designated user\Desktop\testing\221018_milanf-1111_whynotwork\BP_Logs" ': No such file or directory


ECHO PULLING TO THIS FOLDER:%BP_DIRECTORY%
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.qdss"') do (
	adb pull %%A %BP_DIRECTORY%)
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.qmdl2"') do (
	adb pull %%A %BP_DIRECTORY%)
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.qmdl"') do (
	adb pull %%A %BP_DIRECTORY%)
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.qdb"') do (
	adb pull %%A %BP_DIRECTORY%)
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.adpl"') do (
	adb pull %%A %BP_DIRECTORY%)
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.bin"') do (
	adb pull %%A %BP_DIRECTORY%)
::cls
EXIT /B 0

:root_check
:: possible responses
SET already_run="adbd is already running as root"
SET can_run="restarting adbd as root"
SET device_unauthorized="adb: unable to connect for root: device unauthorized."
SET production_build="adbd cannot run as root in production builds"

REM adbd is already running as root
REM restarting adbd as root
REM adb: unable to connect for root: device unauthorized.
REM adbd cannot run as root in production builds

FOR /F "delims=" %%A in ('adb root') do ( SET root_response="%%A" )
IF %root_response%==%already_run% (ECHO. )ELSE ECHO.
IF %root_response%==%can_run% (ECHO. )ELSE ECHO.
IF %root_response%==%device_unauthorized% (ECHO Root Check Failed&exit /b 1 )ELSE ECHO.
IF %root_response%==%production_build% (ECHO Root Check Failed&exit /b 1 )ELSE ECHO Root Check Passed
exit /b 0

:delete_mdm_logs
::adb shell rm /data/vendor/diag_mdlog/logs/*.qdss 2&1>Nul
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.qmdl"') do ( SET curr_file=%%A )
SET curr_file=%curr_file: =%
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.qmdl"') do (
	IF "%%A"=="%curr_file%" (ECHO Action: QMDL files deleted)ELSE adb shell rm %%A
	)
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.qmdl2"') do ( SET curr_file=%%A )
SET curr_file=%curr_file: =%
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.qmdl2"') do (
	IF "%%A"=="%curr_file%" (ECHO Action: QMDL2 files deleted)ELSE adb shell rm %%A
	)
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.qdss"') do ( SET curr_file=%%A )
SET curr_file=%curr_file: =%
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.qdss"') do (
	IF "%%A"=="%curr_file%" (ECHO Action: QDSS files deleted)ELSE adb shell rm %%A
	)
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.adpl"') do ( SET curr_file=%%A )
SET curr_file=%curr_file: =%
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.adpl"') do (
	IF "%%A"=="%curr_file%" (ECHO Action: ADPL files deleted)ELSE adb shell rm %%A
	)
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.bin"') do ( SET curr_file=%%A )
SET curr_file=%curr_file: =%
FOR /F "tokens=8 delims= " %%A in ('adb -d shell "ls -lrt /data/vendor/diag_mdlog/logs/*.bin"') do (
	IF "%%A"=="%curr_file%" (ECHO Action: BIN files deleted)ELSE adb shell rm %%A
	)
::cls
exit /b 0

:zippy_choice
ECHO **Be sure to exit out of all folders before ZIPPING**
CHOICE /C 17 /N /M "Press [7] to 7zip file, otherwise press [1] to exit"
IF %ERRORLEVEL% EQU 1 GOTO :END
IF %ERRORLEVEL% EQU 2 CALL :zippy %log-name%
exit /b 0

:zippy
cd log_directory
cd ..
ECHO zipping file: "%cd%"\%~1
%seven_zip% a -tzip %~1.zip "%cd%"\%~1
EXIT /B 0

:version
ECHO Version: 10.3
ECHO Revision Date: v24-09-11
ECHO Author: Forrest Holub
ECHO Company: Arclight Wireless
ECHO Copywrite: MIT Open Source License
EXIT /B 0

:graphic
ECHO         @ =====================================================================================
ECHO        @@@ @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
ECHO       @@@@@ =================================================================================
ECHO      @@@@@@@ @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
ECHO     @@@@@@@@@ =============================================================================
ECHO    @@@@@@@@@@@ @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
ECHO   @@@@@@@@@@@@@ =========================================================================
ECHO  @@@@@@@@@@@@@@@ @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
ECHO @@@@@@@@@@@@@@@@@ =====================================================================
EXIT /B 0

:END
echo Quality is never an accident; it is always the result of intelligent effort.
ENDLOCAL
EXIT /B 0

:EOF
@REM ECHO         @ =====================================================================================
@REM ECHO        @@@ @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@REM ECHO       @@@@@ =================================================================================
@REM ECHO      @@@@@@@ @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@REM ECHO     @@@@@@@@@ =============================================================================
@REM ECHO    @@@@@@@@@@@ @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@REM ECHO   @@@@@@@@@@@@@ =========================================================================
@REM ECHO  @@@@@@@@@@@@@@@ @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@REM ECHO @@@@@@@@@@@@@@@@@ =====================================================================
@REM EXIT /B 0