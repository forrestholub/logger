@ECHO OFF
adb shell svc data enable 1>Nul
IF %ERRORLEVEL% == 1 ECHO Unable to turn mobile data ON...
exit /b 0