## For detailed description of the QUTS APIs, please refer to QUTS documentation at "C:\Program Files (x86)\Qualcomm\QUTS\QUTS_User_Guide.docm"
##This sample includes connecting to device, using Diag, sending commands and collecting logs.
import os
import sys
import time
import re

##The path where QUTS files are installed
sys.path.append('C:\Program Files (x86)\Qualcomm\QUTS\Support\python')
import QutsClient
import Common.ttypes
import LogSession.LogSession
import LogSession.constants
import LogSession.ttypes

import DiagService.DiagService
import DiagService.constants
import DiagService.ttypes

from win32com.client import Dispatch

import decimal

global handle
global diagService


def onDataQueueUpdated(queueName, queueSize):
    print(queueName, " update ", queueSize)
    '''
    diag_packets = diagService.getDataQueueItems(queueName, queueSize, 2000)
	
    print (len(diag_packets))
    print(diag_packets)
    print("####################################################")
    '''


def onMessage(level, location, title, description):
    print("Message Received " + title + " " + description)


def load_automation_window():
    """Initialize QXDM instance and return its automation window"""
    qxdm_instance = Dispatch("QXDM.QXDM5AutoApplication")

    auto_window = None

    if not bool(qxdm_instance):
        print("Unable to obtain ISF interface")
    else:
        auto_window = qxdm_instance.GetAutomationWindow2()
        auto_window.setVisible(True)  # change to False to hide QXDM UI

    return auto_window


def qxdm_exit_gracef(automation_window):
    automation_window.QuitApplication()


def execTest():
    quts_client = QutsClient.QutsClient("LogSessionLiveSample")
    if not quts_client:
        print("quts client is null upon instantiation")
        return

    # Set the callback functions to receive notification whenever the Dataqueue is changed.
    quts_client.setOnDataQueueUpdatedCallback(onDataQueueUpdated)

    # QUTS sends messages on the what is going on in the system.
    quts_client.setOnMessageCallback(onMessage)

    # Get a handle to the device Manager. Device manager has all the device related info.
    dev_manager = quts_client.getDeviceManager()
    if not dev_manager:
        print("dev_manager is null upon instantiation")
        return

    # Get the list of devices connected to the PC that supports Diag.
    device_list = dev_manager.getDevicesForService(DiagService.constants.DIAG_SERVICE_NAME)
    if not device_list or len(device_list) == 0:
        print("no device found in devlice_list")
        return

    # print the properties of the first device
    devicehandle = device_list[0]
    listOfProtocols = dev_manager.getProtocolList(devicehandle)
    diag_prot_handle = None
    print("printing the chip name of the first device with DIAG_PROT:")
    for i in range(len(listOfProtocols)):
        if listOfProtocols[i].protocolType == Common.ttypes.ProtocolType.PROT_DIAG:
            diag_prot_handle = listOfProtocols[i].protocolHandle
            print(dev_manager.getChipName(devicehandle, listOfProtocols[i].protocolHandle))
    print("")

    # Get the DiagService for the device. This handle will be used for manipulating Diag (send/receive commands etc).
    # The following line get the first Diag device connected in the PC.
    diagService = DiagService.DiagService.Client(
        quts_client.createService(DiagService.constants.DIAG_SERVICE_NAME, devicehandle))

    # for a single modem device
    if 0 != diagService.initializeService():
        print("Diag service init failed")
        return

    # start QXDM
    qxdm_window = load_automation_window()
    if qxdm_window is None:
        print("failed to get QXDM automation interface")
    else:
        print("QXDM automation interface successfully launched")

    dev_handle_digits = len(str(devicehandle))
    prot_handle_digits = len(str(diag_prot_handle))
    print("connecting to device with devicehandle={}, len={}; protoHandle={}, len={}".format(
        decimal.Decimal(devicehandle), dev_handle_digits, decimal.Decimal(diag_prot_handle), prot_handle_digits))
    device_connect_result = qxdm_window.ConnectToDevice(str(devicehandle), str(diag_prot_handle))
    if not device_connect_result:
        print("qxdm failed to connect to device")
    else:
        print("QXDM successfully connects to device with deviceHandle={0}, protHandle={1}".format(devicehandle,
                                                                                                  diag_prot_handle))

    # all the data collected from this point will be saved in a HDF file when saveLogFiles is called.
    dev_manager.startLogging()

    # Set the filters for items of interest.

    time.sleep(20)

    # Disconnect device
    qxdm_window.disconnectFromDevice()

    # save the data. This saves all the data that was generated in the device
    quts_log_file_folder = "C:\\temp\\testlog"

    HDF_path = dev_manager.saveLogFiles(quts_log_file_folder)  # size correlated with logs logged in QXDM

    print("hdf is saved to {}".format(HDF_path))

    diagService.destroyService()

    # qxdm_exit_gracef(qxdm_window)


if __name__ == "__main__":
    execTest()
