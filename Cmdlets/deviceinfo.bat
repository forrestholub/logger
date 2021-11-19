::Name: Device INFO
::Version: 1.2
::Revision Date: 211109
::Author: Forrest Holub
::Company: ArclightWireless
::Copywrite: MIT Open Source License

@ECHO OFF
SETLOCAL ENABLEDELAYEDEXPANSION
REM CONSTANTS
SET yourself=%0
SET serial=%1

SET "iccid=na" 
:: if length 20 then good.
SET "imsi=na"  
:: if length 15 then good.
SET "mdn=na" 
:: if length 12 or starts with + then good.

REM IF EXIST %1(SET serial=%1
REM ) ELSE (FOR /F "tokens=1 delims=" %%A in ('adb -d get-serialno') do SET serial=%%A)

REM check for issues with device connecting to ADB
IF "%serial%"==""  (FOR /F "tokens=1 delims=" %%A in ('adb -d get-serialno') do SET serial=%%A
) ELSE ECHO Device found in param: %serial%

REM ECHO Device not connected correctly. Please try authorizing ADB or enabling ADB debugging && exit /b 1


:MAIN

REM Manufacture
FOR /f "delims=" %%A in ('adb -s %serial% shell getprop ro.product.brand') do SET brand=%%A
REM Model 
FOR /f "delims=" %%A in ('adb -s %serial% shell getprop ro.product.model') do SET model=%%A

REM -----------------------------------------------------------------------------------------------------------------------
REM Code Name
FOR /f "delims=" %%A in ('adb -s %serial% shell getprop ro.boot.device') do SET devicecodename=%%A
REM Code name using Product name
for /f "delims=" %%A in ('adb -s %serial% shell getprop ro.product.device') do SET product=%%A
REM SET CODE NAME CORRECTLY
IF "%devicecodename%"=="" (SET codename=%product%)
IF "%product%"=="" (SET codename=%devicecodename%)
REM -----------------------------------------------------------------------------------------------------------------------
REM [SW]:QPJ30.131-16
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop ro.build.id') do SET softwareid=%%A
REM [Artifact]: rav_retus_user_10_QPJ30.131-16_77c00b_bldccfg_test-keys_retus_US
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop ro.build.fingerprint') do SET software=%%A
REM [BuildTag]:
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop ro.build.tags') do SET buildtag=%%A
REM Model Number
FOR /f "delims=" %%A in ('adb -s %serial% shell getprop ro.boot.hardware.sku') do SET sku=%%A
REM [PLMN]:310260
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop gsm.sim.operator.numeric') do SET PLMN=%%A
ECHO [PLMN]:%PLMN%>>Device-info_%serial%.txt 
REM [ProgramUTags]:
for /f "delims=" %%A in ('adb -d -s %serial% shell getprop ro.carrier') do SET progtag=%%A
ECHO [ProgramUtag]:%progtag%>>Device-info_%serial%.txt 

REM Serial Number
FOR /f "delims=" %%A in ('adb -s %serial% shell getprop ro.boot.serialno') do SET serial=%%A
REM Barcode 
REM DON'T KNOW! DON'T CARE?

REM HW (DVT or PVT) __CURRENTLY BEST WAY TO DETERMINE HW____
FOR /f "delims=" %%A in ('adb -s %serial% shell getprop ro.vendor.hw.revision') do SET hardware=%%A

REM -----------------------------------------------------------------------------------------------------------------------
REM 4: carrier
FOR /f "delims=" %%A in ('adb -s %serial% shell getprop gsm.operator.alpha') do SET carrier1=%%A
FOR /f "delims=" %%A in ('adb -s %serial% shell getprop ro.carrier') do SET carrier2=%%A
REM incase carrier info isn't present---
IF "%carrier1%"=="" (SET carrier=%carrier2%
) ELSE (SET carrier=%carrier1% )

REM IMEI ----iphonesubinfo 1 (IMEI)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 1') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET imei1=%%i 
FOR %%? IN (temp.txt) DO ( SET /A strlength=%%~z?-8)
if "%strlength%"=="15" ( SET imei=%imei1%)
IF EXIST temp.txt del temp.txt 2>&1>NUL


REM IMEI ----iphonesubinfo 2 (IMEI)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 2') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET imei2=%%i 
FOR %%? IN (temp.txt) DO ( SET /A strlength=%%~z?-8)
if "%strlength%"=="15" ( SET imei=%imei2%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM -----------------------------------------------------------------------------------------------------------------------
REM IMEI ----iphonesubinfo 3 (MEID)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 3') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET imei3=%%i 
FOR %%? IN (temp.txt) DO ( SET /A strlength=%%~z?-8)
if "%strlength%"=="15" ( SET imei=%imei3%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM -----------------------------------------------------------------------------------------------------------------------
REM IMEI ----iphonesubinfo 4 (IMEI)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 4') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET imei4=%%i 
FOR %%? IN (temp.txt) DO ( SET /A strlength=%%~z?-8)
if "%strlength%"=="15" ( SET imei=%imei4%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM ----------------------------------------------------------------------------------------------------------------------
REM IMSI -----iphonesubinfo 5 (IMEI)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 5') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET imei5=%%i
FOR %%? IN (temp.txt) DO ( SET /A strlength=%%~z?-8)
if "%strlength%"=="15" ( SET imei=%imei5%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM IMSI -----iphonesubinfo 6 (IMEI)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 6') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET imei6=%%i
FOR %%? IN (temp.txt) DO ( SET /A strlength=%%~z?-8)
if "%strlength%"=="15" ( SET imei=%imei6%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM IMSI -----iphonesubinfo 7 (IMSI)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 7') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET imsi1=%%i
FOR %%? IN (temp.txt) DO ( SET /A strlength=%%~z?-8)
if "%strlength%"=="15" ( SET imsi=%imsi1%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM IMSI -----iphonesubinfo 8 (IMSI)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 8') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET imsi2=%%i
FOR %%? IN (temp.txt) DO ( SET /A strlength=%%~z?-8)
if "%strlength%"=="15" ( SET imsi=%imsi2%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM IMSI -----iphonesubinfo 9 (IMSI)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 9') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET imsi3=%%i
FOR %%? IN (temp.txt) DO ( SET /A strlength=%%~z?-8)
if "%strlength%"=="15" ( SET imsi=%imsi3%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM ICCID ----11 (ICCID)-
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 11') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET iccid1=%%i
FOR %%? IN (temp.txt) DO ( SET strlength=%%~z?)
if "%strlength%"=="20" ( SET iccid=%iccid1%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM ICCID ----12 (ICCID)-
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 12') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET iccid2=%%i
FOR %%? IN (temp.txt) DO ( SET strlength=%%~z?)
if "%strlength%"=="20" ( SET iccid=%iccid2%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM ICCID ----13 (ICCID)-
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 13') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET iccid3=%%i
FOR %%? IN (temp.txt) DO ( SET strlength=%%~z?)
if "%strlength%"=="20" ( SET iccid=%iccid3%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM ICCID ----14 (ICCID)-
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 14') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET iccid4=%%i
FOR %%? IN (temp.txt) DO ( SET strlength=%%~z?)
if "%strlength%"=="20" ( SET iccid=%iccid4%)
IF EXIST temp.txt del temp.txt 2>&1>NUL


REM : MDN ----iphonesubinfo 15 (MDN)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 15') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET mdn1=%%i
FOR %%? IN (temp.txt) DO ( SET strlength=%%~z?)
if "%strlength%"=="12" ( SET mdn=%mdn1%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM : MDN ----iphonesubinfo 16 (MDN)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 16') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET mdn2=%%i
FOR %%? IN (temp.txt) DO ( SET strlength=%%~z?)
if "%strlength%"=="12" ( SET mdn=%mdn2%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM : MDN ----iphonesubinfo 17 (MDN)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 17') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET mdn3=%%i
FOR %%? IN (temp.txt) DO ( SET strlength=%%~z?)
if "%strlength%"=="12" ( SET mdn=%mdn3%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM : MDN ----iphonesubinfo 18 (MDN)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 18') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET mdn4=%%i
FOR %%? IN (temp.txt) DO ( SET strlength=%%~z?)
if "%strlength%"=="12" ( SET mdn=%mdn4%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM : MDN ----iphonesubinfo 19 (MDN)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 19') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET mdn5=%%i
FOR %%? IN (temp.txt) DO ( SET strlength=%%~z?)
if "%strlength%"=="12" ( SET mdn=%mdn5%)
IF EXIST temp.txt del temp.txt 2>&1>NUL

REM : MDN ----iphonesubinfo 20 (MDN)
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -s %serial% shell service call iphonesubinfo 20') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
IF EXIST temp.txt FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET mdn6=%%i
FOR %%? IN (temp.txt) DO ( SET strlength=%%~z?)
if "%strlength%"=="12" ( SET mdn=%mdn6%)
IF EXIST temp.txt del temp.txt 2>&1>NUL



REM REM change nuences by manufacture
REM IF "%brand%"=="google" SET "iccid=%iccid2%"
REM IF "%brand%"=="google" SET "mdn=%mdn3%"
REM IF "%brand%"=="google" SET "imsi=%imsi1%"

REM IF "%brand%"=="samsung" SET "iccid=%iccid3%"
REM IF "%brand%"=="samsung" SET "mdn=%mdn1%"
REM IF "%brand%"=="samsung" SET "imsi=%imsi2%"

REM IF "%brand%"=="motorola" SET "iccid=%iccid1%"
REM IF "%brand%"=="motorola" SET "mdn=%mdn1%"
REM IF "%brand%"=="motorola" SET "imsi=%imsi1%"

REM if no brand specified 
REM IF "%iccid%"=="na" SET "iccid=%iccid1%"
REM IF "%imsi%"=="na" SET "imsi=%imsi1%"
REM IF "%mdn%"=="na" SET "mdn=%mdn1%"



GOTO :create_sheet

:create_sheet

ECHO [Make]:%brand%>>Device-info_%serial%.txt 

ECHO [Model]:%model%>>Device-info_%serial%.txt 

ECHO [DeviceCodeName]:%devicecodename%>>Device-info_%serial%.txt 

ECHO [Product]:%product%>>Device-info_%serial%.txt 

ECHO [SerialNumber]:%serial%>>Device-info_%serial%.txt 

ECHO [BuildTag]:%buildtag%>>Device-info_%serial%.txt 

ECHO [ProgramUtag]:%progtag%>>Device-info_%serial%.txt 

ECHO [PLMN]:%PLMN%>>Device-info_%serial%.txt 

ECHO [HW]:%hardware%>>Device-info_%serial%.txt 

ECHO [SW]:%softwareid%>>Device-info_%serial%.txt 

ECHO [Artifact]:%software%>>Device-info_%serial%.txt 

ECHO [IMEI]:%imei%>>Device-info_%serial%.txt 

ECHO [MDN]:%mdn%>>Device-info_%serial%.txt 

ECHO [ICCID]:%iccid%>>Device-info_%serial%.txt

ECHO [IMSI]: %imsi%>>Device-info_%serial%.txt

REM EXTRAS---------------------------------------------------------------
IF "%imei%"=="na" ECHO [IMEI1]:%imei1%>>Device-info_%serial%.txt 
IF "%imei%"=="na" ECHO [IMEI2]:%imei2%>>Device-info_%serial%.txt 
IF "%imei%"=="na" ECHO [IMEI3]:%imei3%>>Device-info_%serial%.txt 
IF "%imei%"=="na" ECHO [IMEI4]:%imei4%>>Device-info_%serial%.txt 
IF "%imei%"=="na" ECHO [IMEI5]:%imei5%>>Device-info_%serial%.txt 
IF "%imei%"=="na" ECHO [IMEI6]:%imei6%>>Device-info_%serial%.txt 
IF "%mdn%"=="na" ECHO [MDN1]:%mdn1%>>Device-info_%serial%.txt 
IF "%mdn%"=="na" ECHO [MDN2]:%mdn2%>>Device-info_%serial%.txt 
IF "%mdn%"=="na" ECHO [MDN3]:%mdn3%>>Device-info_%serial%.txt 
IF "%mdn%"=="na" ECHO [MDN4]:%mdn4%>>Device-info_%serial%.txt 
IF "%mdn%"=="na" ECHO [MDN5]:%mdn5%>>Device-info_%serial%.txt 
IF "%mdn%"=="na" ECHO [MDN6]:%mdn6%>>Device-info_%serial%.txt 
IF "%iccid%"=="na" ECHO [ICCID1]:%iccid1%>>Device-info_%serial%.txt
IF "%iccid%"=="na" ECHO [ICCID2]:%iccid2%>>Device-info_%serial%.txt
IF "%iccid%"=="na" ECHO [ICCID3]:%iccid3%>>Device-info_%serial%.txt
IF "%iccid%"=="na" ECHO [ICCID4]:%iccid4%>>Device-info_%serial%.txt
IF "%imsi%"=="na" ECHO [IMSI1]: %imsi1%>>Device-info_%serial%.txt
IF "%imsi%"=="na" ECHO [IMSI2]: %imsi2%>>Device-info_%serial%.txt
IF "%imsi%"=="na" ECHO [IMSI3]: %imsi3%>>Device-info_%serial%.txt

REM IMEI ----iphonesubinfo 1 (IMEI1)
REM IMEI ----iphonesubinfo 2 (IMEI2)
REM IMEI ----iphonesubinfo 3 (IMEI3)
REM IMEI ----iphonesubinfo 4 (IMEI4)
REM IMEI -----iphonesubinfo 5 (IMEI5)
REM IMEI -----iphonesubinfo 6 (IMEI6)
REM IMSI -----iphonesubinfo 7 (IMSI1)
REM IMSI -----iphonesubinfo 8 (IMSI2)
REM IMSI -----iphonesubinfo 9 (IMSI3)
REM ICCID ----11 (ICCID1)-
REM ICCID ----12 (ICCID2)-
REM ICCID ----13 (ICCID3)-
REM ICCID ----14 (ICCID4)-
REM : MDN ----iphonesubinfo 15 (MDN1)
REM : MDN ----iphonesubinfo 16 (MDN2)
REM : MDN ----iphonesubinfo 17 (MDN3)
REM : MDN ----iphonesubinfo 18 (MDN4)
REM : MDN ----iphonesubinfo 19 (MDN5)
REM : MDN ----iphonesubinfo 20 (MDN6)


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
