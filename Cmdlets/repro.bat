@ECHO OFF

SETLOCAL ENABLEDELAYEDEXPANSION

:: create new folder for phone using known info -- use list
ECHO This terminal is used to input notes for the on-going test. Press enter to take a note in real time with prepended timestamp.
SET step=1
PAUSE
GOTO :gettime


:gettime
FOR /F "tokens=1-3 delims=/ " %%i IN ("%date:~0,10%") DO SET d=%%i%%j%%k
FOR /F "tokens=1-3 delims=: " %%i IN ("%time:~0,8%")  DO SET t=%%i:%%j:%%k
SET log_dir=%d%_%t%
GOTO :dataentry

:dataentry
SET /P "data=Add Entry: "
ECHO %log_dir%:Entry:%step%:: %data% >> repro_notes.txt
SET /A step=(%step%+1)

PAUSE
GOTO :gettime

end /b 0
