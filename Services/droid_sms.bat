@ECHO OFF
REM SMS parameters %1 = device_serial %2 = MDN %3 = test msg data
adb -s %1 shell service call isms 7 i32 0 s16 'com.android.mms.service' s16 '+%2' s16 'null' s16 'Test Msg: %3' s16 'null' s16 'null' 1>nul
IF %ERRORLEVEL% == 1 ECHO Issue sending SMS...
exit /b 0