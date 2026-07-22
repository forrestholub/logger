@echo OFF
setlocal enableextensions 
setlocal enabledelayedexpansion
cls

::PROGRAMS
SET TCPDUMP_DIRECTORY="%~dp0/programs/tcpdump"
SET PROGRAM_DIRECTORY="%~dp0/programs/"

:PreSettings
adb push %TCPDUMP_DIRECTORY% /data/local/tmp 1>nul 2>nul
adb shell chmod 6755 /data/local/tmp/tcpdump 1>nul 2>nul REM IF NO TMP directory, probably need to create one!

