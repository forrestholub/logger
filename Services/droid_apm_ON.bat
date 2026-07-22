@ECHO OFF
adb shell settings put global airplane_mode_on 1; am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true 1>Nul
IF %ERRORLEVEL% == 1 ECHO Unable to turn airplane mode ON...
exit /b 0


