@ECHO OFF
SETLOCAL ENABLEDELAYEDEXPANSION
SET flash_userdata=0
SET erase_userdata=0
SET para_flash=0
SET serial_number=
SET device_list=
SET device_count=0
SET opts=
SET this_script=%0
SET is_device_in_productlist=0
SET no_reboot=0
SET homebread=%4

::
:: process command line options
::
:: I Take in %4 as other batch files home bread

:proc_option

SET bad_option=1
SET no_reboot_option=0
:: I SET '0' to be for input so gogogoogog
IF "%1" == "0" GOTO :start_main_activity 
IF "%1" == "/?" GOTO :check_bad_option
IF "%1" == "/h" GOTO :check_bad_option
IF "%1" == "/H" GOTO :check_bad_option

:: flash userdata?
IF "%1" == "/u" (
    SET flash_userdata=1
    SHIFT
    SET bad_option=0
    SET opts=%opts% /u
    GOTO :check_bad_option
)


:: disable para-flash
IF "%1" == "/s" (
    SET para_flash=0
    SHIFT
    SET bad_option=0
    GOTO :check_bad_option
)

:: specify device number
IF NOT "%1" == "/d" GOTO :check_local_fastboot
    IF NOT "%serial_number%" == "" ECHO Too many possible serial numbers
    IF NOT "%serial_number%" == "" GOTO :check_bad_option
    SHIFT
    IF "%1" == "" ECHO No serial number specified.
    IF "%1" == "" GOTO :check_bad_option
    SET var=%1
    IF "%var:~0,1%" == "/" ECHO Bad serial number: %var%
    IF "%var:~0,1%" == "/" GOTO :check_bad_option
    SET serial_number=%1
    SHIFT
    SET bad_option=0
    GOTO :check_bad_option

:check_bad_option
IF %bad_option% == 1 (
    CALL :show_usage
    EXIT /b 1
)
:: Start flashing
::
:start_main_activity

:: not to erase userdata if we are flashing it
:: because bootloader erases the partition before
:: flashing it

ECHO.
ECHO.

:: Wait for fastboot device enumeration
ECHO.
ECHO. Waiting for fastboot enumeration...
ECHO.

CALL :enumerate_all_devices
IF %errorlevel% NEQ 0 EXIT /b 1 

ECHO. There are %device_count% device(s) connected: %device_list%
:: para_flash chooses which flashing procedure to follow 1.serial 2.parallel
IF %device_count% == 1 (
    SET /A para_flash=0 )
IF NOT "%serial_number%" == "" (
    CALL :main_acitivity_one_device )
    IF !errorlevel! NEQ 0 EXIT /b 1
) else (
    FOR %%D in (%device_list::= %) do (
        ECHO. Trying to flash device %%D
		::If not paralel, then reset serial number and execute in serial fashion
        IF %para_flash% == 0 (
            CALL SET serial_number=%%D
            CALL :main_acitivity_one_device
        ) else ( 
            start cmd /k Call %homebread% %%D  B COMMENT %device_count% %device_list%
        )
    )
)

ECHO. All devices have completed!

PAUSE

EXIT /b 0
:: ------------------------------------------------------------------------
:: Functions start here
:: ------------------------------------------------------------------------
:main_acitivity_one_device:
REM this is where you perform main activity in serial
    IF "%serial_number%" == "" (
        ECHO. No device specified
        EXIT /b 1
    )

    :: Check whether the phone is connected
    CALL SET replaced=%%device_list:%serial_number%=%%
    IF "%replaced%" == "%device_list%" (
        ECHO. Device %serial_number% is not connected
        EXIT /b 1
    )

    ECHO.
    ECHO. Starting main activity using device %serial_number%...
    ECHO. My joe is on this flash station WOOT!
	Call %homebread% %serial_number% B COMMENT %device_count% %device_list%
	exit /b 0
	
:show_usage
    ECHO.
    ECHO Usage: %~nx0 [OPTION...]
    ECHO.
    ECHO.  Options:
    ECHO.      /?                       Help
    ECHO.      /u                       Flash userdata
    ECHO.      /eu                      Erase userdata
    ECHO.      /s                       Execute script sequentially
    ECHO.      /nr, no-reboot           No reboot after flashing
    ECHO.      /d device_serial         The device serial number to be used. If there is no
    ECHO.                               device specified, all phones will be used.
    ECHO.      device_serial            The device serial number to be used. If there is no
    ECHO.                               device specified, all phones will be used.
    ECHO.      /local-fastboot [PATH]   Use local fastboot from PATH or specified
    ECHO.
	
    EXIT /b 0

:enumerate_all_devices
    SET /A wait_time=1
    SET /A ret=0

    :loop

    FOR /F "usebackq tokens=1 skip=1" %%X in (`adb devices`) do (
        IF NOT "%%X" == "" (
            SET /A device_count+=1
            SET device_list=!device_list! %%X
        )
    )
    IF "%device_list%" == "" (
        ping -n 2 127.0.0.1 > NUL
        SET /A wait_time+=1
        IF %wait_time% == 10 (
            ECHO. Not found any devices connected. Please check and try again.
            ECHO.

            SET /A ret=1
            GOTO :exit_enumeration
        )
        GOTO :loop
    )

    IF NOT "%serial_number%" == "" (
        :: Check whether the phone is connected
        CALL SET replaced=%%device_list:%serial_number%=%%
        IF "%replaced%" == "%device_list%" (
            ECHO. Device %serial_number% is not connected
            EXIT /b 1
        )
    )
    ECHO. ADB device is ready!!

:exit_enumeration
    EXIT /b %ret%