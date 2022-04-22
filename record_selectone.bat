::Name: Device INFO
::Version: 1.1
::Revision Date: 200528
::Author: Forrest Holub
::Company: ArclightWireless
::Copywrite: MIT Open Source License

@ECHO ON
SET yourself=%0

:setup
IF "%use_device%"=="/?" ( GOTO :help)
call pick_1_device.bat
call :main
GOTO :EOF


:main 
adb -d -s %use_device% shell screenrecord /sdcard/video.mp4
adb -d -s %use_device% pull /sdcard/video.mp4

GOTO :EOF

:help
    ECHO.
    ECHO Usage: %~nx0 [OPTION...]
    ECHO.
    ECHO.  Options:
    ECHO.      /?                       Help

	
    EXIT /b 0

:EOF
exit /b 0

