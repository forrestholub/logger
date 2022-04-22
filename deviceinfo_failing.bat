::Name: Device INFO
::Version: 1.1
::Revision Date: 200528
::Author: Forrest Holub
::Company: ArclightWireless
::Copywrite: MIT Open Source License


@ECHO ON
SETLOCAL ENABLEDELAYEDEXPANSION
REM CONSTANTS
SET yourself=%0

:SETUP
IF "%1"=="/?" (
	GOTO :help
	)
IF "%1"=="" (
choice /c abcdef /T 15 /D a /M "What device letter is this device in repro?" 
	IF ERRORLEVEL ==1 SET  dlet=A
	IF ERRORLEVEL ==2 SET  dlet=B
	IF ERRORLEVEL ==3 SET  dlet=C
	IF ERRORLEVEL ==4 SET  dlet=D
	IF ERRORLEVEL ==5 SET  dlet=E
	IF ERRORLEVEL ==6 SET  dlet=F
) ELSE ( SET dlet=%1 )


IF NOT "%2"=="" ( 
    GOTO :MAIN
) ELSE (
	FOR /F "tokens=1 delims=" %%A in ('adb -d get-serialno') do call %yourself% %dlet% %%A
    GOTO :EOF )

:MAIN
REM [Make]: Motorola
for /f "delims=" %%A in ('adb -d -s %2 shell getprop ro.product.brand') do SET brand=%%A
ECHO [Make]:%brand% >>Device_%serial%_Letter_%dlet%.txt 
REM [Model]: Moto g stylus
for /f "delims=" %%A in ('adb -d -s %2 shell getprop ro.product.model') do SET model=%%A
ECHO [Model]:%model% >>Device_%serial%_Letter_%dlet%.txt 
REM [CodeName]: RAV
for /f "delims=" %%A in ('adb -d -s %2 shell getprop ro.boot.device') do SET devicecodename=%%A
ECHO [DeviceCodeName]:%devicecodename%>>Device_%serial%_Letter_%dlet%.txt 
REM [Product]: RAVNA
for /f "delims=" %%A in ('adb -d -s %2 shell getprop ro.product.device') do SET product=%%A
ECHO [Product]:%product%>>Device_%serial%_Letter_%dlet%.txt 
REM [SerialNum]:
for /f "delims=" %%A in ('adb -d -s %2 shell getprop ro.boot.serialno') do SET serial=%%A
ECHO [SerialNumber]:%serial%>>Device_%serial%_Letter_%dlet%.txt 
REM [BuildTag]:
for /f "delims=" %%A in ('adb -d -s %2 shell getprop ro.build.tags') do SET buildtag=%%A
ECHO [BuildTag]:%buildtag%>>Device_%serial%_Letter_%dlet%.txt 
REM [ProgramUTags]:
for /f "delims=" %%A in ('adb -d -s %2 shell getprop ro.carrier') do SET progtag=%%A
ECHO [ProgramUtag]:%progtag%>>Device_%serial%_Letter_%dlet%.txt 
REM [PLMN]:310260
for /f "delims=" %%A in ('adb -d -s %2 shell getprop gsm.sim.operator.numeric') do SET PLMN=%%A
ECHO [PLMN]:%PLMN%>>Device_%serial%_Letter_%dlet%.txt 
REM [HW]:DVT2
for /f "delims=" %%A in ('adb -d -s %2 shell getprop ro.vendor.hw.revision') do SET hardware=%%A
ECHO [HW]:%hardware%>>Device_%serial%_Letter_%dlet%.txt 
REM [SW]:QPJ30.131-16
for /f "delims=" %%A in ('adb -d -s %2 shell getprop ro.build.id') do SET softwareid=%%A
ECHO [SW]:%softwareid%>>Device_%serial%_Letter_%dlet%.txt 
REM ]Artifact]: rav_retus_user_10_QPJ30.131-16_77c00b_bldccfg_test-keys_retus_US
for /f "delims=" %%A in ('adb -d -s %2 shell getprop ro.build.fingerprint') do SET software=%%A
ECHO [Artifact]:%software%>>Device_%serial%_Letter_%dlet%.txt 
REM [IMEI]: 359109100032570
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d -s %2 shell service call iphonesubinfo 1') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET imei=%%i 
ECHO [IMEI]:%imei%>>Device_%serial%_Letter_%dlet%.txt 
IF EXIST temp.txt del temp.txt
REM 10: MDN ----iphonesubinfo 17 (MDN)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d -s %2 shell service call iphonesubinfo 17') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET mdn1=%%i
IF EXIST temp.txt del temp.txt
REM 10: MDN ----iphonesubinfo 18 (MDN)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d -s %2 shell service call iphonesubinfo 18') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET mdn2=%%i
IF EXIST temp.txt del temp.txt
IF "%mdn1%"=="" ( SET mdn=%mdn2% 
)ELSE ( SET mdn=%mdn1% )
ECHO [MDN]:%mdn%>>Device_%serial%_Letter_%dlet%.txt 
GOTO :EOF

:help
    ECHO.
    ECHO Usage: %~nx0 [OPTION...]
    ECHO.
    ECHO.  Options:
    ECHO.      /?                       Help
	ECHO.	   1st param				Device Letter:A,B,C
	ECHO.	   2nd param				Serial No. (req if more than 1 device connected)
	ECHO.
	
    EXIT /b 0

ENDLOCAL

:EOF
exit /b 0

REM FORMAT:
REM [Make]: Motorola
REM [Model]: RAV
REM [Carrier]:T-Mobile NS (selection: 5,1)
REM [Programutags]: retus
REM [PLMN]:310260
REM [HW]:DVT2
REM [SW]:QPJ30.131-16
REM ]Artifact]: rav_retus_user_10_QPJ30.131-16_77c00b_bldccfg_test-keys_retus_US
REM [IMEI]: 359109100032570
REM [MDN]: 919-869-6655
REM :::::::::::::::::::::::::::::::::::::::GO FOR IT::::::::::::::::::::::::::::::::::::::::::::::::::::::::
