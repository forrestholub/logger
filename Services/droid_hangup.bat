@ECHO OFF
adb -s %1 shell input keyevent KEYCODE_ENDCALL 1>Nul
IF %ERRORLEVEL% == 1 ECHO Unable to hangup call...
exit /b 0