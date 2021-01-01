::Name: Device INFO
::Version: 1.1
::Revision Date: 200528
::Author: Forrest Holub
::Company: ArclightWireless
::Copywrite: MIT Open Source License

@ECHO OFF
SETLOCAL ENABLEDELAYEDEXPANSION
REM CONSTANTS
SET yourself=%0

FOR /F "tokens=1 delims=" %%A in ('adb -d get-serialno') do SET serial=%%A


:MAIN
REM [Make]: Motorola
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop ro.product.brand') do SET brand=%%A
ECHO [Make]:%brand%>>Device-info_%serial%.txt 
REM [Model]: Moto g stylus
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop ro.product.model') do SET model=%%A
ECHO [Model]:%model%>>Device-info_%serial%.txt 
REM [CodeName]: RAV
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop ro.boot.device') do SET devicecodename=%%A
ECHO [DeviceCodeName]:%devicecodename%>>Device-info_%serial%.txt 
REM [Product]: RAVNA
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop ro.product.device') do SET product=%%A
ECHO [Product]:%product%>>Device-info_%serial%.txt 
REM [SerialNum]:
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop ro.boot.serialno') do SET serial=%%A
ECHO [SerialNumber]:%serial%>>Device-info_%serial%.txt 
REM [BuildTag]:
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop ro.build.tags') do SET buildtag=%%A
ECHO [BuildTag]:%buildtag%>>Device-info_%serial%.txt 
REM [ProgramUTags]:
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop ro.carrier') do SET progtag=%%A
ECHO [ProgramUtag]:%progtag%>>Device-info_%serial%.txt 
REM [PLMN]:310260
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop gsm.sim.operator.numeric') do SET PLMN=%%A
ECHO [PLMN]:%PLMN%>>Device-info_%serial%.txt 
REM [HW]:DVT2
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop ro.vendor.hw.revision') do SET hardware=%%A
ECHO [HW]:%hardware%>>Device-info_%serial%.txt 
REM [SW]:QPJ30.131-16
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop ro.build.id') do SET softwareid=%%A
ECHO [SW]:%softwareid%>>Device-info_%serial%.txt 
REM [Artifact]: rav_retus_user_10_QPJ30.131-16_77c00b_bldccfg_test-keys_retus_US
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop ro.build.fingerprint') do SET software=%%A
ECHO [Artifact]:%software%>>Device-info_%serial%.txt 
REM [IMEI]: 359109100032570
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d -s %serial% shell service call iphonesubinfo 1') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET imei=%%i 
ECHO [IMEI]:%imei%>>Device-info_%serial%.txt 
IF EXIST temp.txt del temp.txt
REM [MDN1] ----iphonesubinfo 17 (MDN)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d -s %serial% shell service call iphonesubinfo 17') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET mdn1=%%i
IF EXIST temp.txt del temp.txt
REM [MDN2] ----iphonesubinfo 18 (MDN)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d -s %serial% shell service call iphonesubinfo 18') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET mdn2=%%i
IF EXIST temp.txt del temp.txt
IF "%mdn1%"=="" ( SET mdn=%mdn2% 
)ELSE ( SET mdn=%mdn1% )
ECHO [MDN]:%mdn%>>Device-info_%serial%.txt 
REM [ICCID] ----11 (ICCID)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 11') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temper1.txt
IF EXIST temper1.txt FOR /F "tokens=1 delims= " %%i IN (temper1.txt) DO SET iccid1=%%i
IF EXIST temper1.txt del temper1.txt
REM [ICCID] ----12 (ICCID)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 12') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temper2.txt
IF EXIST temper2.txt FOR /F "tokens=1 delims= " %%i IN (temper2.txt) DO SET iccid2=%%i
IF EXIST temper2.txt del temper2.txt
IF "%iccid1%"=="" ( SET iccid=%iccid2% 
)ELSE ( SET iccid=%iccid1% )
ECHO [ICCID]:%iccid%>>Device-info_%serial%.txt


GOTO :EOF

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
