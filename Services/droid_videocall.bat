@ECHO OFF
REM VideoCALL parameters %1 = device_serial %2 = MDN 
adb -s %1 shell am start -a "android.intent.action.CALL" --ei "android.telecom.extra.START_CALL_WITH_VIDEO_STATE" 3 -d tel:%2 1>Nul
IF %ERRORLEVEL% == 1 ECHO Issue placing video call...
exit /b 0


REM ADD
REM LATER...................
REM 04-02 13:32:11.635 30014 30014 I DialerVideoCallFragment: com.android.incallui.video.impl.VideoCallFragment.setHold:809 value: false
REM 04-02 13:32:11.635 30014 30014 I DialerVideoCallFragment: com.android.incallui.video.impl.VideoCallFragment.setVideoPaused:819 isPaused: false
REM 04-02 13:32:11.635 30014 30014 I DialerVideoCallFragment: com.android.incallui.video.impl.VideoCallFragment.updateButtonStates:833 updateButtonStates
REM 04-02 13:32:09.340 30014 30014 I DialerVideoCallFragment: com.android.incallui.video.impl.VideoCallFragment.setAudioState:825 audioState: [AudioState isMuted: false, route: EARPIECE, supportedRouteMask: EARPIECE, SPEAKER, activeBluetoothDevice: [null], supportedBluetoothDevices: []]
REM 04-02 13:32:09.340 30014 30014 I DialerSpeakerButtonController: com.android.incallui.video.impl.SpeakerButtonController.setAudioState:71 audioState: [AudioState isMuted: false, route: EARPIECE, supportedRouteMask: EARPIECE, SPEAKER, activeBluetoothDevice: [null], supportedBluetoothDevices: []]




REM from log:
REM android.intent.action.CALL dat=tel:xxxxxxxxxx (has extras) }, android.telecom.extra.START_CALL_WITH_VIDEO_STATE=3

REM SUCCESS!!!!!
adb shell am start -a "android.intent.action.CALL" --ei "android.telecom.extra.START_CALL_WITH_VIDEO_STATE" 3 -d tel:9198696655