@ECHO OFF
adb.exe shell am start -a android.intent.action.VIEW -d http://172.22.1.201 1>Nul
IF %ERRORLEVEL% == 1 ECHO Unable to access internet ...
exit /b 0