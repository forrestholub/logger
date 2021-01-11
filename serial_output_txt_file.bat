@echo OFF

title Multi Fascited Array of Expansion
COLOR 2
SETLOCAL ENABLEDELAYEDEXPANSION
REM for /f "delims=" %%A in ('adb get-serialno') do SET serialno=%%A
REM echo Your Serial Number: %serialno% 

REM CLEAR THE BUFFERS 
SET %%a=Null
SET %%b=Null
SET %%c=Null
SET %%d=Null

CALL :PopulateDevices
GOTO :END
REM SET THE LOOPS
:: ------------------------------------------------------------------------
:: Functions start here
:: ------------------------------------------------------------------------
:IdentifyDevice
	REM FOR L %%i in (1,1,%Count%) DO 
	SET device_%loop%=%~1
	ping -n 1 127.0.0.1>NUl
	ECHO !device_%loop%!>device_%loop%.txt
	exit /b 0
::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::

:PopulateDevices
	SET /A count=0
	SET /A loop=0

		FOR /F "SKIP=1 TOKENS=1 DELIMS=d" %%a IN ('adb devices') DO (
			SET /A count+=1
			SET "output[!count!]=%%a"   
			)
			FOR /L %%i in (1,1,%Count%) Do (
				SET /A loop+=1
				Call :IdentifyDevice "!output[%%i]!"
				)


::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::

::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::

ENDLOCAL
:END 
Exit /b 0