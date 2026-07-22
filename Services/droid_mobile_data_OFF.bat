@ECHO OFF
adb shell svc data disable 1>Nul
IF %ERRORLEVEL% == 1 ECHO Unable to turn mobile data OFF...
exit /b 0


