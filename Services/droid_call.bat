@ECHO OFF
REM CALL parameters %1 = device_serial %2 = MDN 
adb -s %1 shell am start -a android.intent.action.CALL -d tel:%2 1>Nul
IF %ERRORLEVEL% == 1 ECHO Issue placing CALL...
exit /b 0