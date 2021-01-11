@echo OFF

ECHO START THE ADB SERVER
adb start-server

REM -------------------paramters setup-----------------------------------------------------
set ANDROID_SERIAL=""
set device1=""
set device1_from_file=""
set device2=""
set device2_from_file=""
set device3=""
set device3_from_file=""
set device4=""
set device4_from_file=""
SET count=1
SET use_device=""
SET use_device_properties=""

REM --------------------- Main Actions -----------------------------------------------------
for /f "Skip=1 tokens=1" %%G in ('adb devices') DO ( CALL :subroutine %%G )

call :attach_new_variables_to_device_names

REM Selections for device list
IF EXIST device_1_file.txt ECHO Selection 1: %device1_properties%
IF EXIST device_2_file.txt ECHO Selection 2: %device2_properties%
IF EXIST device_3_file.txt ECHO Selection 3: %device3_properties%
IF EXIST device_4_file.txt ECHO Selection 4: %device4_properties%

REM Make a choice
CHOICE /C 1234 /M "Please select device from above list"
IF "%ERRORLEVEL%"=="1" CALL :selected_device1
IF "%ERRORLEVEL%"=="2" CALL :selected_device2
IF "%ERRORLEVEL%"=="3" CALL :selected_device3
IF "%ERRORLEVEL%"=="4" CALL :selected_device4


REM Result:
ECHO You've selected %use_device_properties%
SET "%~1 = %use_device%"
exit /b 0

REM ------------------------------functions begin---------------------------------------------------------------------
:subroutine
 IF NOT "%1"=="" ECHO You are on iteration: %count%
 IF NOT "%1"=="" ECHO %count%:%1
 IF NOT "%1"=="" ECHO %1 >>device_%count%_file.txt
 set /a count+=1
GOTO :EOF

REM  ----------------------------------------------------------------------------------------------------------------------

:attach_new_variables_to_device_names
:pull_device_properties
IF EXIST device_1_file.txt call :newvar_dev1
IF EXIST device_2_file.txt call :newvar_dev2
IF EXIST device_3_file.txt call :newvar_dev3
IF EXIST device_4_file.txt call :newvar_dev4
GOTO :EOF

REM  ----------------------------------------------------------------------------------------------------------------------

:newvar_dev1
for /f "tokens=1 delims=" %%G in (device_1_file.txt) DO ( SET device1_from_file=%%G) 
SET device1_from_file=%device1_from_file: =%
REM [Make]: Motorola
for /f "delims=" %%A in ('adb -d -s %device1_from_file% shell getprop ro.product.brand') do SET device1_from_file_brand=%%A
REM [Model]: Moto g stylus
for /f "delims=" %%A in ('adb -d -s %device1_from_file% shell getprop ro.product.model') do SET device1_from_file_model=%%A
REM [CodeName]: RAV
for /f "delims=" %%A in ('adb -d -s %device1_from_file% shell getprop ro.boot.device') do SET device1_from_file_devicecodename=%%A
REM [IMEI]: 359109100032570
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d -s %device1_from_file% shell service call iphonesubinfo 1') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET device1_from_file_imei=%%i>NUL 
IF EXIST temp.txt del temp.txt
SET device1_properties="Brand: %device1_from_file_brand%, Model: %device1_from_file_model%, Codename: %device1_from_file_devicecodename%, Serial: %device1_from_file%, IMEI: %device1_from_file_imei%"
GOTO :EOF

:newvar_dev2
for /f "tokens=1 delims=" %%G in (device_2_file.txt) DO ( SET device2_from_file=%%G) 
SET device2_from_file=%device2_from_file: =%
REM [Make]: Motorola
for /f "delims=" %%A in ('adb -d -s %device2_from_file% shell getprop ro.product.brand') do SET device2_from_file_brand=%%A
REM [Model]: Moto g stylus
for /f "delims=" %%A in ('adb -d -s %device2_from_file% shell getprop ro.product.model') do SET device2_from_file_model=%%A
REM [CodeName]: RAV
for /f "delims=" %%A in ('adb -d -s %device2_from_file% shell getprop ro.boot.device') do SET device2_from_file_devicecodename=%%A
REM [IMEI]: 359109100032570
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d -s %device2_from_file% shell service call iphonesubinfo 1') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET device2_from_file_imei=%%i>NUL 
IF EXIST temp.txt del temp.txt
SET device2_properties="Brand: %device2_from_file_brand%, Model: %device2_from_file_model%, Codename: %device2_from_file_devicecodename%, Serial: %device2_from_file%, IMEI: %device2_from_file_imei%"
GOTO :EOF

:newvar_dev3
for /f "tokens=1 delims=" %%G in (device_3_file.txt) DO ( SET device3_from_file=%%G) 
SET device3_from_file=%device3_from_file: =%
REM [Make]: Motorola
for /f "delims=" %%A in ('adb -d -s %device3_from_file% shell getprop ro.product.brand') do SET device3_from_file_brand=%%A
REM [Model]: Moto g stylus
for /f "delims=" %%A in ('adb -d -s %device3_from_file% shell getprop ro.product.model') do SET device3_from_file_model=%%A
REM [CodeName]: RAV
for /f "delims=" %%A in ('adb -d -s %device3_from_file% shell getprop ro.boot.device') do SET device3_from_file_devicecodename=%%A
REM [IMEI]: 359109100032570
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d -s %device3_from_file% shell service call iphonesubinfo 1') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET device3_from_file_imei=%%i>NUL 
IF EXIST temp.txt del temp.txt
SET device3_properties="Brand: %device3_from_file_brand%, Model: %device3_from_file_model%, Codename: %device3_from_file_devicecodename%, Serial: %device3_from_file%, IMEI: %device3_from_file_imei%"
GOTO :EOF

:newvar_dev4
for /f "tokens=1 delims=" %%G in (device_4_file.txt) DO ( SET device4_from_file=%%G)
SET device4_from_file=%device4_from_file: =%
REM [Make]: Motorola
for /f "delims=" %%A in ('adb -d -s %device4_from_file% shell getprop ro.product.brand') do SET device4_from_file_brand=%%A
REM [Model]: Moto g stylus
for /f "delims=" %%A in ('adb -d -s %device4_from_file% shell getprop ro.product.model') do SET device4_from_file_model=%%A
REM [CodeName]: RAV
for /f "delims=" %%A in ('adb -d -s %device4_from_file% shell getprop ro.boot.device') do SET device4_from_file_devicecodename=%%A
REM [IMEI]: 359109100032570
FOR /F "skip=1 tokens=2,3,4,5,6,7,8,9 delims='.)" %%i IN ('adb -d -s %device4_from_file% shell service call iphonesubinfo 1') DO <NUL SET /P result=%%i%%j%%k%%l%%m%%n%%o%%p>>temp.txt
FOR /F "tokens=1 delims= " %%i IN (temp.txt) DO SET device4_from_file_imei=%%i>NUL
IF EXIST temp.txt del temp.txt
SET device4_properties="Brand: %device4_from_file_brand%, Model: %device4_from_file_model%, Codename: %device4_from_file_devicecodename%, Serial: %device4_from_file%, IMEI: %device4_from_file_imei%"
GOTO :EOF

REM  ----------------------------------------------------------------------------------------------------------------------

:selected_device1
SET use_device=%device1_from_file%
SET use_device_properties=%device1_properties%
GOTO :EOF

:selected_device2
SET use_device=%device2_from_file%
SET use_device_properties=%device2_properties%
GOTO :EOF

:selected_device3
SET use_device=%device3_from_file%
SET use_device_properties=%device3_properties%
GOTO :EOF

:selected_device4
SET use_device=%device4_from_file%
SET use_device_properties=%device4_properties%
GOTO :EOF


:: for /f "delims=" %%A in ('adb get-serialno') do SET serialno=%%A
:: echo Your Serial Number: %serialno% 

REM  ----------------------------------------------------------------------------------------------------------------------


exit /b 0
