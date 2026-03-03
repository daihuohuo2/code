# -*- coding: utf-8 -*-

# Rewritten to use layout managers for proper resizable behavior.

from PyQt5 import QtCore, QtGui, QtWidgets


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(820, 860)
        MainWindow.setMinimumSize(600, 500)

        self.centralWidget = QtWidgets.QWidget(MainWindow)
        self.centralWidget.setObjectName("centralWidget")

        # ── 顶层：水平分栏（左=预览区，右=控制面板）──
        mainHLayout = QtWidgets.QHBoxLayout(self.centralWidget)
        mainHLayout.setContentsMargins(8, 8, 8, 8)
        mainHLayout.setSpacing(8)

        # ════════════════════════════════════════
        #  左侧：设备下拉 + 预览 + 串口设置
        # ════════════════════════════════════════
        leftVLayout = QtWidgets.QVBoxLayout()
        leftVLayout.setSpacing(6)

        self.ComboDevices = QtWidgets.QComboBox(self.centralWidget)
        self.ComboDevices.setObjectName("ComboDevices")
        leftVLayout.addWidget(self.ComboDevices)

        self.widgetDisplay = QtWidgets.QWidget(self.centralWidget)
        self.widgetDisplay.setObjectName("widgetDisplay")
        self.widgetDisplay.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.widgetDisplay.setMinimumSize(300, 200)
        leftVLayout.addWidget(self.widgetDisplay, stretch=1)

        # ------ 串口设置组 ------
        self.groupSerial = QtWidgets.QGroupBox(self.centralWidget)
        self.groupSerial.setObjectName("groupSerial")
        serialGrid = QtWidgets.QGridLayout(self.groupSerial)
        serialGrid.setContentsMargins(10, 16, 10, 10)
        serialGrid.setSpacing(6)

        self.label_serial_port = QtWidgets.QLabel()
        self.label_serial_port.setObjectName("label_serial_port")
        serialGrid.addWidget(self.label_serial_port, 0, 0)

        self.cmbSerialPort = QtWidgets.QComboBox()
        self.cmbSerialPort.setObjectName("cmbSerialPort")
        serialGrid.addWidget(self.cmbSerialPort, 0, 1)

        self.bnRefreshPort = QtWidgets.QPushButton()
        self.bnRefreshPort.setObjectName("bnRefreshPort")
        serialGrid.addWidget(self.bnRefreshPort, 0, 2)

        self.label_baud_rate = QtWidgets.QLabel()
        self.label_baud_rate.setObjectName("label_baud_rate")
        serialGrid.addWidget(self.label_baud_rate, 1, 0)

        self.cmbBaudRate = QtWidgets.QComboBox()
        self.cmbBaudRate.setObjectName("cmbBaudRate")
        serialGrid.addWidget(self.cmbBaudRate, 1, 1, 1, 2)

        self.label_timeout = QtWidgets.QLabel()
        self.label_timeout.setObjectName("label_timeout")
        serialGrid.addWidget(self.label_timeout, 2, 0)

        self.edtSerialTimeout = QtWidgets.QLineEdit()
        self.edtSerialTimeout.setObjectName("edtSerialTimeout")
        serialGrid.addWidget(self.edtSerialTimeout, 2, 1, 1, 2)

        self.bnConnectSerial = QtWidgets.QPushButton()
        self.bnConnectSerial.setObjectName("bnConnectSerial")
        serialGrid.addWidget(self.bnConnectSerial, 3, 0, 1, 2)

        self.lblSerialStatus = QtWidgets.QLabel()
        self.lblSerialStatus.setObjectName("lblSerialStatus")
        self.lblSerialStatus.setAlignment(QtCore.Qt.AlignCenter)
        serialGrid.addWidget(self.lblSerialStatus, 3, 2)

        serialGrid.setColumnStretch(0, 2)
        serialGrid.setColumnStretch(1, 3)
        serialGrid.setColumnStretch(2, 2)

        leftVLayout.addWidget(self.groupSerial)
        mainHLayout.addLayout(leftVLayout, stretch=1)

        # ════════════════════════════════════════
        #  右侧：各功能控制组
        # ════════════════════════════════════════
        rightVLayout = QtWidgets.QVBoxLayout()
        rightVLayout.setSpacing(6)

        # ── 初始化组 ──
        self.groupInit = QtWidgets.QGroupBox(self.centralWidget)
        self.groupInit.setObjectName("groupInit")
        initGrid = QtWidgets.QGridLayout(self.groupInit)
        initGrid.setContentsMargins(10, 16, 10, 10)
        initGrid.setSpacing(6)

        self.bnEnum = QtWidgets.QPushButton()
        self.bnEnum.setObjectName("bnEnum")
        initGrid.addWidget(self.bnEnum, 0, 0, 1, 2)

        self.bnOpen = QtWidgets.QPushButton()
        self.bnOpen.setObjectName("bnOpen")
        initGrid.addWidget(self.bnOpen, 1, 0)

        self.bnClose = QtWidgets.QPushButton()
        self.bnClose.setEnabled(False)
        self.bnClose.setObjectName("bnClose")
        initGrid.addWidget(self.bnClose, 1, 1)

        rightVLayout.addWidget(self.groupInit)

        # ── 采集组 ──
        self.groupGrab = QtWidgets.QGroupBox(self.centralWidget)
        self.groupGrab.setEnabled(False)
        self.groupGrab.setObjectName("groupGrab")
        grabGrid = QtWidgets.QGridLayout(self.groupGrab)
        grabGrid.setContentsMargins(10, 16, 10, 10)
        grabGrid.setSpacing(6)

        self.radioContinueMode = QtWidgets.QRadioButton()
        self.radioContinueMode.setObjectName("radioContinueMode")
        grabGrid.addWidget(self.radioContinueMode, 0, 0)

        self.radioTriggerMode = QtWidgets.QRadioButton()
        self.radioTriggerMode.setObjectName("radioTriggerMode")
        grabGrid.addWidget(self.radioTriggerMode, 0, 1)

        self.bnStart = QtWidgets.QPushButton()
        self.bnStart.setEnabled(False)
        self.bnStart.setObjectName("bnStart")
        grabGrid.addWidget(self.bnStart, 1, 0)

        self.bnStop = QtWidgets.QPushButton()
        self.bnStop.setEnabled(False)
        self.bnStop.setObjectName("bnStop")
        grabGrid.addWidget(self.bnStop, 1, 1)

        self.bnSoftwareTrigger = QtWidgets.QPushButton()
        self.bnSoftwareTrigger.setEnabled(False)
        self.bnSoftwareTrigger.setObjectName("bnSoftwareTrigger")
        grabGrid.addWidget(self.bnSoftwareTrigger, 2, 0, 1, 2)

        self.bnSaveImage = QtWidgets.QPushButton()
        self.bnSaveImage.setEnabled(False)
        self.bnSaveImage.setObjectName("bnSaveImage")
        grabGrid.addWidget(self.bnSaveImage, 3, 0, 1, 2)

        self.bnAutoFocus = QtWidgets.QPushButton()
        self.bnAutoFocus.setEnabled(False)
        self.bnAutoFocus.setObjectName("bnAutoFocus")
        grabGrid.addWidget(self.bnAutoFocus, 4, 0, 1, 1)

        self.bnStopAutoFocus = QtWidgets.QPushButton()
        self.bnStopAutoFocus.setEnabled(False)
        self.bnStopAutoFocus.setObjectName("bnStopAutoFocus")
        grabGrid.addWidget(self.bnStopAutoFocus, 4, 1, 1, 1)

        self.lblAutoFocusStatus = QtWidgets.QLabel()
        self.lblAutoFocusStatus.setObjectName("lblAutoFocusStatus")
        self.lblAutoFocusStatus.setAlignment(QtCore.Qt.AlignCenter)
        grabGrid.addWidget(self.lblAutoFocusStatus, 5, 0, 1, 2)

        rightVLayout.addWidget(self.groupGrab)

        # ── 参数组 ──
        self.groupParam = QtWidgets.QGroupBox(self.centralWidget)
        self.groupParam.setEnabled(False)
        self.groupParam.setObjectName("groupParam")
        paramGrid = QtWidgets.QGridLayout(self.groupParam)
        paramGrid.setContentsMargins(10, 16, 10, 10)
        paramGrid.setSpacing(6)

        self.label_4 = QtWidgets.QLabel()
        self.label_4.setObjectName("label_4")
        paramGrid.addWidget(self.label_4, 0, 0)

        self.edtExposureTime = QtWidgets.QLineEdit()
        self.edtExposureTime.setObjectName("edtExposureTime")
        paramGrid.addWidget(self.edtExposureTime, 0, 1)

        self.label_5 = QtWidgets.QLabel()
        self.label_5.setObjectName("label_5")
        paramGrid.addWidget(self.label_5, 1, 0)

        self.edtGain = QtWidgets.QLineEdit()
        self.edtGain.setObjectName("edtGain")
        paramGrid.addWidget(self.edtGain, 1, 1)

        self.label_6 = QtWidgets.QLabel()
        self.label_6.setObjectName("label_6")
        paramGrid.addWidget(self.label_6, 2, 0)

        self.edtFrameRate = QtWidgets.QLineEdit()
        self.edtFrameRate.setObjectName("edtFrameRate")
        paramGrid.addWidget(self.edtFrameRate, 2, 1)

        self.bnGetParam = QtWidgets.QPushButton()
        self.bnGetParam.setObjectName("bnGetParam")
        paramGrid.addWidget(self.bnGetParam, 3, 0)

        self.bnSetParam = QtWidgets.QPushButton()
        self.bnSetParam.setObjectName("bnSetParam")
        paramGrid.addWidget(self.bnSetParam, 3, 1)

        paramGrid.setColumnStretch(0, 2)
        paramGrid.setColumnStretch(1, 3)

        rightVLayout.addWidget(self.groupParam)

        # ── 自动拍摄组 ──
        self.groupAutoCapture = QtWidgets.QGroupBox(self.centralWidget)
        self.groupAutoCapture.setObjectName("groupAutoCapture")
        captureGrid = QtWidgets.QGridLayout(self.groupAutoCapture)
        captureGrid.setContentsMargins(10, 16, 10, 10)
        captureGrid.setSpacing(6)

        self.label_capture = QtWidgets.QLabel()
        self.label_capture.setObjectName("label_capture")
        captureGrid.addWidget(self.label_capture, 0, 0)

        self.edtCaptureCount = QtWidgets.QLineEdit()
        self.edtCaptureCount.setObjectName("edtCaptureCount")
        captureGrid.addWidget(self.edtCaptureCount, 0, 1)

        self.bnAutoCapture = QtWidgets.QPushButton()
        self.bnAutoCapture.setEnabled(False)
        self.bnAutoCapture.setObjectName("bnAutoCapture")
        captureGrid.addWidget(self.bnAutoCapture, 1, 0, 1, 2)

        self.bnSetSavePath = QtWidgets.QPushButton()
        self.bnSetSavePath.setObjectName("bnSetSavePath")
        captureGrid.addWidget(self.bnSetSavePath, 2, 0, 1, 2)

        self.lblSavePathInfo = QtWidgets.QLineEdit()
        self.lblSavePathInfo.setObjectName("lblSavePathInfo")
        self.lblSavePathInfo.setReadOnly(True)
        captureGrid.addWidget(self.lblSavePathInfo, 3, 0, 1, 2)

        captureGrid.setColumnStretch(0, 2)
        captureGrid.setColumnStretch(1, 3)

        rightVLayout.addWidget(self.groupAutoCapture)

        # ── 运动控制组 ──
        self.groupMotion = QtWidgets.QGroupBox(self.centralWidget)
        self.groupMotion.setObjectName("groupMotion")
        motionGrid = QtWidgets.QGridLayout(self.groupMotion)
        motionGrid.setContentsMargins(10, 16, 10, 10)
        motionGrid.setSpacing(6)

        self.bnHomeZ = QtWidgets.QPushButton()
        self.bnHomeZ.setObjectName("bnHomeZ")
        motionGrid.addWidget(self.bnHomeZ, 0, 0, 1, 3)

        self.bnMoveStep = QtWidgets.QPushButton()
        self.bnMoveStep.setObjectName("bnMoveStep")
        motionGrid.addWidget(self.bnMoveStep, 1, 0, 1, 3)

        self.label_light = QtWidgets.QLabel()
        self.label_light.setObjectName("label_light")
        motionGrid.addWidget(self.label_light, 2, 0)

        self.edtLightValue = QtWidgets.QLineEdit()
        self.edtLightValue.setObjectName("edtLightValue")
        motionGrid.addWidget(self.edtLightValue, 2, 1)

        self.bnSetLight = QtWidgets.QPushButton()
        self.bnSetLight.setObjectName("bnSetLight")
        motionGrid.addWidget(self.bnSetLight, 2, 2)

        motionGrid.setColumnStretch(0, 2)
        motionGrid.setColumnStretch(1, 3)
        motionGrid.setColumnStretch(2, 2)

        rightVLayout.addWidget(self.groupMotion)

        # ── 比例尺组 ──
        self.groupScaleBar = QtWidgets.QGroupBox(self.centralWidget)
        self.groupScaleBar.setObjectName("groupScaleBar")
        scaleGrid = QtWidgets.QGridLayout(self.groupScaleBar)
        scaleGrid.setContentsMargins(10, 16, 10, 10)
        scaleGrid.setSpacing(6)

        self.chkShowScaleBar = QtWidgets.QCheckBox()
        self.chkShowScaleBar.setObjectName("chkShowScaleBar")
        scaleGrid.addWidget(self.chkShowScaleBar, 0, 0, 1, 2)

        self.label_ppmm = QtWidgets.QLabel()
        self.label_ppmm.setObjectName("label_ppmm")
        scaleGrid.addWidget(self.label_ppmm, 1, 0)

        self.edtPixelsPerMm = QtWidgets.QLineEdit()
        self.edtPixelsPerMm.setObjectName("edtPixelsPerMm")
        scaleGrid.addWidget(self.edtPixelsPerMm, 1, 1)

        self.bnSetScaleCalib = QtWidgets.QPushButton()
        self.bnSetScaleCalib.setObjectName("bnSetScaleCalib")
        scaleGrid.addWidget(self.bnSetScaleCalib, 2, 0, 1, 2)

        self.lblScaleBarInfo = QtWidgets.QLabel()
        self.lblScaleBarInfo.setObjectName("lblScaleBarInfo")
        self.lblScaleBarInfo.setAlignment(QtCore.Qt.AlignCenter)
        scaleGrid.addWidget(self.lblScaleBarInfo, 3, 0, 1, 2)

        scaleGrid.setColumnStretch(0, 2)
        scaleGrid.setColumnStretch(1, 3)

        rightVLayout.addWidget(self.groupScaleBar)
        rightVLayout.addStretch(1)   # 底部弹簧，让各组靠上排列

        # 右侧面板限制宽度
        rightWidget = QtWidgets.QWidget()
        rightWidget.setLayout(rightVLayout)
        rightWidget.setMinimumWidth(200)
        rightWidget.setMaximumWidth(280)
        mainHLayout.addWidget(rightWidget, stretch=0)

        MainWindow.setCentralWidget(self.centralWidget)
        self.statusBar = QtWidgets.QStatusBar(MainWindow)
        self.statusBar.setObjectName("statusBar")
        MainWindow.setStatusBar(self.statusBar)

        self.retranslateUi(MainWindow)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "MainWindow"))
        self.groupInit.setTitle(_translate("MainWindow", "初始化"))
        self.bnClose.setText(_translate("MainWindow", "关闭设备"))
        self.bnOpen.setText(_translate("MainWindow", "打开设备"))
        self.bnEnum.setText(_translate("MainWindow", "查找设备"))
        self.groupGrab.setTitle(_translate("MainWindow", "采集"))
        self.bnSaveImage.setText(_translate("MainWindow", "保存图像"))
        self.radioContinueMode.setText(_translate("MainWindow", "连续模式"))
        self.radioTriggerMode.setText(_translate("MainWindow", "触发模式"))
        self.bnStop.setText(_translate("MainWindow", "停止采集"))
        self.bnStart.setText(_translate("MainWindow", "开始采集"))
        self.bnSoftwareTrigger.setText(_translate("MainWindow", "软触发一次"))
        self.groupParam.setTitle(_translate("MainWindow", "参数"))
        self.label_6.setText(_translate("MainWindow", "帧率"))
        self.edtGain.setText(_translate("MainWindow", "0"))
        self.label_5.setText(_translate("MainWindow", "增益"))
        self.label_4.setText(_translate("MainWindow", "曝光"))
        self.edtExposureTime.setText(_translate("MainWindow", "0"))
        self.bnGetParam.setText(_translate("MainWindow", "获取参数"))
        self.bnSetParam.setText(_translate("MainWindow", "设置参数"))
        self.edtFrameRate.setText(_translate("MainWindow", "0"))
        self.groupAutoCapture.setTitle(_translate("MainWindow", "自动拍摄"))
        self.label_capture.setText(_translate("MainWindow", "张数"))
        self.edtCaptureCount.setText(_translate("MainWindow", "1"))
        self.bnAutoCapture.setText(_translate("MainWindow", "开始自动拍摄"))
        self.bnSetSavePath.setText(_translate("MainWindow", "设置保存路径"))
        self.lblSavePathInfo.setText(_translate("MainWindow", "保存至: (默认)"))
        # 串口设置组
        self.groupSerial.setTitle(_translate("MainWindow", "串口设置"))
        self.label_serial_port.setText(_translate("MainWindow", "串口名称"))
        self.bnRefreshPort.setText(_translate("MainWindow", "刷新串口"))
        self.label_baud_rate.setText(_translate("MainWindow", "波特率"))
        self.label_timeout.setText(_translate("MainWindow", "超时 (s)"))
        self.edtSerialTimeout.setText(_translate("MainWindow", "1.0"))
        self.bnConnectSerial.setText(_translate("MainWindow", "连接串口"))
        self.lblSerialStatus.setText(_translate("MainWindow", "● 未连接"))
        # 运动控制组
        self.groupMotion.setTitle(_translate("MainWindow", "运动控制"))
        self.bnHomeZ.setText(_translate("MainWindow", "Z 轴归零"))
        self.bnMoveStep.setText(_translate("MainWindow", "Z 轴微调 (+0.1mm)"))
        self.label_light.setText(_translate("MainWindow", "亮度"))
        self.edtLightValue.setText(_translate("MainWindow", "0"))
        self.bnSetLight.setText(_translate("MainWindow", "设置亮度"))
        # 自动对焦
        self.bnAutoFocus.setText(_translate("MainWindow", "开始自动对焦"))
        self.bnStopAutoFocus.setText(_translate("MainWindow", "停止对焦"))
        self.lblAutoFocusStatus.setText(_translate("MainWindow", "就绪"))
        # 比例尺
        self.groupScaleBar.setTitle(_translate("MainWindow", "比例尺"))
        self.chkShowScaleBar.setText(_translate("MainWindow", "显示比例尺"))
        self.label_ppmm.setText(_translate("MainWindow", "像素/mm"))
        self.edtPixelsPerMm.setText(_translate("MainWindow", "100.0"))
        self.bnSetScaleCalib.setText(_translate("MainWindow", "应用标定值"))
        self.lblScaleBarInfo.setText(_translate("MainWindow", ""))
