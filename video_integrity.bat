@ECHO OFF
REM check_video_integrity
REM wait until video file should be large enought to qualify as working ~4MB
timeout /t 10
SET /a min_filesize=102

	FOR /F "delims= " %%A in ('adb -d -s %1 shell "cd /sdcard/ && ls -s video.mp4"') do (
	SET  filesize=%%A
	IF "%filesize%" LSS "%min_filesize%" (
		SET RTN=1
		ECHO. Video recording integrity compromised. Size recorded was only: %filesize% kilobytes. Restarting video recording...
		EXIT /B %RTN%)ELSE ( 
			SET RTN=0
			ECHO. Video recording integrity validated. Size recorded was: %filesize% kilobytes and growing. Continuing recording...
			EXIT /B %RTN%)
	)