@echo OFF
adb -s %1 shell am start -a android.intent.action.SENDTO -d sms:+%2  --es  sms_body "msg: %3" --ez exit_on_sent false
IF %ERRORLEVEL% == 1 ECHO Issue sending SMS via default gateway...
exit /b 0