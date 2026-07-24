@ECHO OFF
REM check_video_integrity
REM wait until video file should be large enought to qualify as working ~4MB
timeout /t 10
REM min filesize in Kilobytes
SET /A min_filesize=102

FOR /F "delims= " %%A in ('adb -d -s %1 shell "cd /sdcard/ && ls -s video.mp4"') do ( SET /A cur_filesize=%%A)
SET "%rtn%=%~1"
IF %cur_filesize% LSS %min_filesize% (( SET "RTN=1") && ( ECHO Video recording integrity COMPROMISED. Size recorded was only: %cur_filesize% kilobytes. I advise you to restart the video recording.) && ( EXIT /B %RTN%)) ELSE (( SET "RTN=0") && ( ECHO. Video recording integrity validated. Size recorded was: %cur_filesize% kilobytes and growing. Continuing recording...) && ( EXIT /B %RTN%))


REM THE METHOD BELOW WORKS TOO, just used for debugging, it is a little cleaner looking TBH

@REM IF %filesize% GTR %min_filesize% GOTO :not_compromised
@REM IF %filesize% LSS %min_filesize% GOTO :compromised

@REM :compromised
@REM SET "RTN=1"
@REM ECHO Video recording integrity compromised. Size recorded was only: %filesize% kilobytes. Restarting video recording...
@REM ECHO Video BAD

@REM EXIT /B %RTN%


@REM :not_compromised
@REM SET "RTN=0"
@REM ECHO. Video recording integrity validated. Size recorded was: %filesize% kilobytes and growing. Continuing recording...
@REM ECHO Video GOOD
@REM EXIT /B %RTN%