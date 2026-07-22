@echo OFF
adb -s %1 shell input keyevent KEYCODE_CALL
IF %ERRORLEVEL% == 1 ECHO Unable to answer call...
exit /b 0