@ECHO OFF
REM check_video_integrity
REM wait until video file should be large enought to qualify as working ~4MB
timeout /t 10
REM min filesize in Kilobytes
SET /A min_filesize=102
SET cur_filesize=0

FOR /F "delims= " %%A in ('adb -d -s %1 shell "cd /sdcard/ && ls -s video.mp4"') do ( SET /A cur_filesize=%%A)
REM SET "%rtn%=%~1"
REM IF %cur_filesize% LSS %min_filesize% (( SET "RTN=1") && ( ECHO Video recording integrity COMPROMISED. Size recorded was only: %cur_filesize% kilobytes. I advise you to restart the video recording.) && ( EXIT /B %RTN%)) ELSE (( SET "RTN=0") && ( ECHO. Video recording integrity validated. Size recorded was: %cur_filesize% kilobytes and growing. Continuing recording...) && ( EXIT /B %RTN%))

IF %cur_filesize% LSS %min_filesize% ECHO Video recording integrity COMPROMISED. Size recorded was only: %cur_filesize% kilobytes& (EXIT /B 4
)ELSE ECHO. Video recording integrity validated. Size recorded was: %cur_filesize% kilobytes and growing. Continuing recording...& ( EXIT /B 8)

exit /b 0