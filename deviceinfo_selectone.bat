::Name: Device INFO
::Version: 1.1
::Revision Date: 200528
::Author: Forrest Holub
::Company: ArclightWireless
::Copywrite: MIT Open Source License

@ECHO OFF
SET yourself=%0

:MAIN
IF "%use_device%"=="/?" ( GOTO :help)
call pick_1_device.bat
REM ECHO Mydevice=%use_device%

:PULL_INFO
REM [Make]: Motorola
for /f "delims=" %%A in ('adb -d -s %use_device% shell getprop ro.product.brand') do SET brand=%%A
ECHO [Make]:%brand% >>Device_%use_device%_.txt 
REM [Model]: Moto g stylus
for /f "delims=" %%A in ('adb -d -s %use_device% shell getprop ro.product.model') do SET model=%%A
ECHO [Model]:%model% >>Device_%use_device%_.txt 
REM [CodeName]: RAV
for /f "delims=" %%A in ('adb -d -s %use_device% shell getprop ro.boot.device') do SET devicecodename=%%A
ECHO [DeviceCodeName]:%devicecodename%>>Device_%use_device%_.txt 
REM [Product]: RAVNA
for /f "delims=" %%A in ('adb -d -s %use_device% shell getprop ro.product.device') do SET product=%%A
ECHO [Product]:%product%>>Device_%use_device%_.txt 
REM [%use_device%Num]:
for /f "delims=" %%A in ('adb -d -s %use_device% shell getprop ro.boot.%use_device%no') do SET %use_device%=%%A
ECHO [%use_device%Number]:%use_device%>>Device_%use_device%_.txt 
REM [BuildTag]:
for /f "delims=" %%A in ('adb -d -s %use_device% shell getprop ro.build.tags') do SET buildtag=%%A
ECHO [BuildTag]:%buildtag%>>Device_%use_device%_.txt 
REM [ProgramUTags]:
for /f "delims=" %%A in ('adb -d -s %use_device% shell getprop ro.carrier') do SET progtag=%%A
ECHO [ProgramUtag]:%progtag%>>Device_%use_device%_.txt 
REM [PLMN]:310260
for /f "delims=" %%A in ('adb -d -s %use_device% shell getprop gsm.sim.operator.numeric') do SET PLMN=%%A
ECHO [PLMN]:%PLMN%>>Device_%use_device%_.txt 
REM [HW]:DVT2
for /f "delims=" %%A in ('adb -d -s %use_device% shell getprop ro.vendor.hw.revision') do SET hardware=%%A
ECHO [HW]:%hardware%>>Device_%use_device%_.txt 
REM [SW]:QPJ30.131-16
for /f "delims=" %%A in ('adb -d -s %use_device% shell getprop ro.build.id') do SET softwareid=%%A
ECHO [SW]:%softwareid%>>Device_%use_device%_.txt 
REM ]Artifact]: rav_retus_user_10_QPJ30.131-16_77c00b_bldccfg_test-keys_retus_US
for /f "delims=" %%A in ('adb -d -s %use_device% shell getprop ro.build.fingerprint') do SET software=%%A
ECHO [Artifact]:%software%>>Device_%use_device%_.txt 
REM [IMEI]: 359109100032570
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d -s %use_device% shell service call iphonesubinfo 1') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET imei=%%i 
ECHO [IMEI]:%imei%>>Device_%use_device%_.txt 
IF EXIST temp.txt del temp.txt
REM 10: MDN ----iphonesubinfo 17 (MDN)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d -s %use_device% shell service call iphonesubinfo 17') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET mdn1=%%i
IF EXIST temp.txt del temp.txt
REM 10: MDN ----iphonesubinfo 18 (MDN)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d -s %use_device% shell service call iphonesubinfo 18') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET mdn2=%%i
IF EXIST temp.txt del temp.txt
IF "%mdn1%"=="" ( SET mdn=%mdn2% 
)ELSE ( SET mdn=%mdn1% )
ECHO [MDN]:%mdn%>>Device_%use_device%_.txt 




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

