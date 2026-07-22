@ECHO OFF
adb shell settings put global airplane_mode_on 0; am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false 1>Nul
IF %ERRORLEVEL% == 1 ECHO Unable to turn airplane mode OFF...
exit /b 0
