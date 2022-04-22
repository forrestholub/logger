@ECHO OFF

SET /A min_filesize=53311
SET /A current_filesize=53311

IF /I %current_filesize% LSS %min_filesize% GOTO :lessthan
IF /I %current_filesize% EQU %min_filesize% GOTO :equal
IF /I %current_filesize% GTR %min_filesize% GOTO :greaterthan

exit /b 0

REM ----------------validation---------------------------------------------------
:lessthan
SET "RTN=1"
ECHO %current_filesize% LSS %min_filesize%
EXIT /B 0

:greaterthan
SET "RTN=0"
ECHO. %current_filesize% GTR %min_filesize%
EXIT /B 0

:equal
ECHO %current_filesize% EQU %min_filesize%
EXIT /B 0