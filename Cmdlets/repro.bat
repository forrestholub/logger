@ECHO OFF

SETLOCAL ENABLEDELAYEDEXPANSION

:: create new folder for phone using known info -- use list
ECHO This terminal is used to input notes for the on-going test. Press enter to take a note in real time with prepended timestamp.
SET step=1
PAUSE
GOTO :gettime


:gettime
FOR /F "tokens=1" %%i IN ("%date:~4,12%") DO SET d=%%i
FOR /F "tokens=1-3 delims=: " %%i IN ("%time:~0,8%")  DO SET t=%%i:%%j:%%k
SET log_dir=%d% %t%
GOTO :dataentry

:dataentry
:: changed to colon delimited for easy switch to csv / excel sheet!
SET /P "data=Add Entry: "
ECHO %log_dir%,Entry,%step%,%data%>>repro_notes.txt
SET /A step=(%step%+1)

PAUSE
GOTO :gettime


end /b 0
