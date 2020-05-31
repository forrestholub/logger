::Project Name: Auto Logger
::Version: 1.6
::Revision Date: 200521
::Author: Forrest Holub
::Company: Arclight Wireless
::Copywrite: MIT Open Source License

@echo OFF

SETLOCAL ENABLEDELAYEDEXPANSION
REM REFRESH BUFFERS
REM SET %%A=
REM SET %%B=
REM SET %%C=

:: create new folder for phone using known info -- use list

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

REM PULL IMEI 
FOR /F "skip=1 tokens=4,6 delims= " %%i IN ('adb -d shell service call iphonesubinfo 1') DO SET mess=%%i,%%j, & <nul set /p =!mess!>>imei_messyboy.txt 
FOR /F "tokens=2,4,5 delims=," %%i IN (imei_messyboy.txt) DO ECHO %%i%%j%%k%%l%%m%%n%%o>>imei_less_messyboy.txt 
FOR /F "tokens=1-15 delims='. " %%i IN (imei_less_messyboy.txt) DO SET imei=%%t%%u%%v%%w
SET imei=!imei: =!
REM SET imei_short=!imei_short: =!
IF EXIST imei_messyboy.txt del imei_messyboy.txt
IF EXIST imei_less_messyboy.txt del imei_less_messyboy.txt

REM BETTER WAY-needs adjustment however---- IMEI ----iphonesubinfo 1 (IMEI/MEID)
REM FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d shell service call iphonesubinfo 1') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
REM FOR /F "tokens=1 delims=" %%i IN (temp.txt) DO SET imei=%%i 
REM IF EXIST temp.txt del temp.txt

ECHO.WELCOME TO THE AUTOMATIC LOG GENERATOR. 
ECHO.::::::::::::::::::::::::::::::::::::::::
ECHO. HAPPY.LOGGING.
ECHO.::::::::::::::::::::::::::::::::::::::::


SET log-time=%dy%%dm%%dd%
ping -n 3 127.0.0.1 > NUL


:determine_device
if "%brand%"=="motorola" (
	SET device=%product%
	IF "%product%"=="" (
		SET /P "device=Enter product name: "
	)
	GOTO :main
)
if "%brand%"=="samsung" (
	SET device=%model%
	IF "%model%"=="" (
		SET /P "device=Enter product name: "
	)
	GOTO :main
)
if "%brand%"=="lge" (
	SET device=%model%
	IF "%model%"=="" (
		SET /P "device=Enter product name: "
	)
	GOTO :main
)
if "%brand%"=="google" (
	REM remove whitespace from model so 'Pixel 2' becomes 'Pixel2 '
	SET device=%model: =%!
	IF "%model%"=="" (
		SET /P "device=Enter product name: "
	)
	GOTO :main
)

:: input device last four IMEI
:imei
IF "%imei%"=="" (
	SET /P "imei=Input device last four IMEI: " 
)

:main
ECHO. Select Reason for test
ECHO. 1 - Failure Log
ECHO. 2 - Retest Log
SET /P "choice=Please select option: "
IF "%choice%"=="1" (
	SET test=TC-
)
IF "%choice%"=="2" (
	SET test=IKSWQ-
)

echo setting the value for 'test'
ping -n 1 127.0.0.1 > NUL
:: test if I can set test value successfully and append to logname
:: also test to see if tc number can be appended using input request below
Set /p tc= "Enter TC or IKSWQ number: "
:: give cpu a second to save the number received by user
ping -n 1 127.0.0.1 > NUL

echo Create new folder for logs to live in
mkdir %log-time%_%device%-%imei%_%test%%tc%
echo Direct to folder to begin da process
cd %log-time%_%device%-%imei%_%test%%tc%
echo Creating a lot more folders....

mkdir AP_Logs 
mkdir Videos
mkdir Screenshots
mkdir BP_Logs
ping -n 2 127.0.0.1 > NUL

:: now we start logging 
adb -d wait-for-device

echo Pulling Device Information

START CALL deviceinfo %serialno% Device_A

echo Starting helpful text entry logger tool
START CALL reproduction-text


ping -n 1 127.0.0.1 > NUL
cd AP_Logs
echo Starting adb -d logging. Please make sure multiple windows opened after this request. If not, check adb -d settings and device connectivity"
START CALL logging_all

ping -n 1 127.0.0.1 > NUL
cd ..
cd Videos
ping -1 2 127.0.0.1 > NUL
echo Use this cmd window to execute additional videos by typing 'record' plus enter key
echo Don't worry about re-write, a new timestamp will be generated with video log
START CALL  record

ping -1 2 127.0.0.1 > NUL
cd ..
cd Screenshots
ping -1 2 127.0.0.1 > NUL
echo Use this cmd window to execute additional screenshots by typing 'screenshot' plus enter key
echo Don't worry about re-write, a new timestamp will be generated with screenshot
START CALL screenshot



echo Quality is never an accident; it is always the result of intelligent effort.
ENDLOCAL
EXIT /B