## For detailed description of the QUTS APIs, please refer to QUTS documentation at "C:\Program Files (x86)\Qualcomm\QUTS\QUTS_User_Guide.docm"
##This sample includes connecting to device, using Diag, sending commands and collecting logs.
import os
import sys
import time
import re
 
##The path where QUTS files are installed
from sys import platform
if sys.platform.startswith("linux"):
    sys.path.append('/opt/qcom/QXDM/Support/python')
	
elif sys.platform.startswith("win"):
    sys.path.append('C:\Program Files (x86)\Qualcomm\QXDM5\Support\python')
	
import QxdmAutomationClient
import QxdmAutomationService.ttypes
import Common.ttypes

def execTest():  
    print("Creating QXDM Automation client\n")
    qxdm_auto_client = QxdmAutomationClient.QxdmAutomationClient("OpenAndSaveSample")
    qxdmAutomationHandle = qxdm_auto_client.getQxdmAutomationManager()
	
	#Init Service
    init = qxdmAutomationHandle.InitializeService()
	
    if(init == False):
        print("Init not successful..exiting")
        return
		
    qxdmAutomationHandle.SetVisible(True)
    dmcFile = "E:\\Arclight\\tmo\\QXDM Log Masks"
    retVal = qxdmAutomationHandle.LoadConfig(dmcFile)
    hdffile = "E:\\Coding\\ogger\qxdm-logged-file.hdf"
    retVal = qxdmAutomationHandle.LoadItemStore(hdffile)
    print("loadFile returned:  ",retVal)	
    #deviceInfo = QxdmAutomationService.ttypes.ConnectDeviceInfo(str(281474976710656),str(281483566645248))
	
    # retVal = qxdmAutomationHandle.ConnectToDevice(deviceInfo)
    # print("ConnectToDevice returned:  ",retVal)
    # time.sleep(35)
    # qxdmAutomationHandle.DisconnectFromDevice()
    #retVal = qxdmAutomationHandle.SaveItemStore("\\\\harv-rahult\\Builds\saveisftest\\save_test.hdf")
    #print("SaveItemStore returned:  ",retVal)
    print("Closing QXDM session in 5 seconds")
    time.sleep(5)
    qxdmAutomationHandle.Close();
 
if __name__ == "__main__":
    execTest()