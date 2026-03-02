# -*- coding: utf-8 -*-
import sys
import os
import configparser
import threading
import time
from datetime import datetime
try:
    import serial
    import serial.tools.list_ports
    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False
    print("[Warning] pyserial 未安装，串口功能不可用。请执行: pip install pyserial")
from PyQt5.QtWidgets import *
from PyQt5.QtCore import QTimer
from CamOperation_class import CameraOperation
from MvCameraControl_class import *
from MvErrorDefine_const import *
from CameraParams_header import *
from PyUICBasicDemo import Ui_MainWindow
import ctypes


# 获取选取设备信息的索引，通过[]之间的字符去解析
def TxtWrapBy(start_str, end, all):
    start = all.find(start_str)
    if start >= 0:
        start += len(start_str)
        end = all.find(end, start)
        if end >= 0:
            return all[start:end].strip()


# 将返回的错误码转换为十六进制显示
def ToHexStr(num):
    chaDic = {10: 'a', 11: 'b', 12: 'c', 13: 'd', 14: 'e', 15: 'f'}
    hexStr = ""
    if num < 0:
        num = num + 2 ** 32
    while num >= 16:
        digit = num % 16
        hexStr = chaDic.get(digit, str(digit)) + hexStr
        num //= 16
    hexStr = chaDic.get(num, str(num)) + hexStr
    return hexStr


if __name__ == "__main__":

    # ch:初始化SDK | en: initialize SDK
    MvCamera.MV_CC_Initialize()

    global deviceList
    deviceList = MV_CC_DEVICE_INFO_LIST()
    global cam
    cam = MvCamera()
    global nSelCamIndex
    nSelCamIndex = 0
    global obj_cam_operation
    obj_cam_operation = 0
    global isOpen
    isOpen = False
    global isGrabbing
    isGrabbing = False
    global isCalibMode  # 是否是标定模式（获取原始图像）
    isCalibMode = True
    global save_path
    save_path = ""  # 空字符串表示使用脚本所在目录作为默认路径
    global auto_capture_running
    auto_capture_running = False
    global serial_conn
    serial_conn = None
    global is_serial_connected
    is_serial_connected = False

    # 脚本所在目录作为默认保存路径
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    SETTINGS_FILE = os.path.join(SCRIPT_DIR, "setting.ini")

    # 绑定下拉列表至设备信息索引
    def xFunc(event):
        global nSelCamIndex
        nSelCamIndex = TxtWrapBy("[", "]", ui.ComboDevices.get())

    # Decoding Characters
    def decoding_char(ctypes_char_array):
        """
        安全地从 ctypes 字符数组中解码出字符串。
        适用于 Python 2.x 和 3.x，以及 32/64 位环境。
        """
        byte_str = memoryview(ctypes_char_array).tobytes()
        
        # 在第一个空字符处截断
        null_index = byte_str.find(b'\x00')
        if null_index != -1:
            byte_str = byte_str[:null_index]
        
        # 多编码尝试解码
        for encoding in ['gbk', 'utf-8', 'latin-1']:
            try:
                return byte_str.decode(encoding)
            except UnicodeDecodeError:
                continue
        
        # 如果所有编码都失败，使用替换策略
        return byte_str.decode('latin-1', errors='replace')

    # ch:枚举相机 | en:enum devices
    def enum_devices():
        global deviceList
        global obj_cam_operation

        deviceList = MV_CC_DEVICE_INFO_LIST()
        n_layer_type = (MV_GIGE_DEVICE | MV_USB_DEVICE | MV_GENTL_CAMERALINK_DEVICE
                        | MV_GENTL_CXP_DEVICE | MV_GENTL_XOF_DEVICE)
        ret = MvCamera.MV_CC_EnumDevices(n_layer_type, deviceList)
        if ret != 0:
            strError = "Enum devices fail! ret = :" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
            return ret

        if deviceList.nDeviceNum == 0:
            QMessageBox.warning(mainWindow, "Info", "Find no device", QMessageBox.Ok)
            return ret
        print("Find %d devices!" % deviceList.nDeviceNum)

        devList = []
        for i in range(0, deviceList.nDeviceNum):
            mvcc_dev_info = cast(deviceList.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
            if mvcc_dev_info.nTLayerType == MV_GIGE_DEVICE or mvcc_dev_info.nTLayerType == MV_GENTL_GIGE_DEVICE:
                print("\ngige device: [%d]" % i)
                user_defined_name = decoding_char(mvcc_dev_info.SpecialInfo.stGigEInfo.chUserDefinedName)
                model_name = decoding_char(mvcc_dev_info.SpecialInfo.stGigEInfo.chModelName)
                print("device user define name: " + user_defined_name)
                print("device model name: " + model_name)

                nip1 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0xff000000) >> 24)
                nip2 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x00ff0000) >> 16)
                nip3 = ((mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x0000ff00) >> 8)
                nip4 = (mvcc_dev_info.SpecialInfo.stGigEInfo.nCurrentIp & 0x000000ff)
                print("current ip: %d.%d.%d.%d " % (nip1, nip2, nip3, nip4))
                devList.append(
                    "[" + str(i) + "]GigE: " + user_defined_name + " " + model_name + "(" + str(nip1) + "." + str(
                        nip2) + "." + str(nip3) + "." + str(nip4) + ")")
            elif mvcc_dev_info.nTLayerType == MV_USB_DEVICE:
                print("\nu3v device: [%d]" % i)
                user_defined_name = decoding_char(mvcc_dev_info.SpecialInfo.stUsb3VInfo.chUserDefinedName)
                model_name = decoding_char(mvcc_dev_info.SpecialInfo.stUsb3VInfo.chModelName)
                print("device user define name: " + user_defined_name)
                print("device model name: " + model_name)

                strSerialNumber = ""
                for per in mvcc_dev_info.SpecialInfo.stUsb3VInfo.chSerialNumber:
                    if per == 0:
                        break
                    strSerialNumber = strSerialNumber + chr(per)
                print("user serial number: " + strSerialNumber)
                devList.append("[" + str(i) + "]USB: " + user_defined_name + " " + model_name
                               + "(" + str(strSerialNumber) + ")")
            elif mvcc_dev_info.nTLayerType == MV_GENTL_CAMERALINK_DEVICE:
                print("\nCML device: [%d]" % i)
                user_defined_name = decoding_char(mvcc_dev_info.SpecialInfo.stCMLInfo.chUserDefinedName)
                model_name = decoding_char(mvcc_dev_info.SpecialInfo.stCMLInfo.chModelName)
                print("device user define name: " + user_defined_name)
                print("device model name: " + model_name)

                strSerialNumber = ""
                for per in mvcc_dev_info.SpecialInfo.stCMLInfo.chSerialNumber:
                    if per == 0:
                        break
                    strSerialNumber = strSerialNumber + chr(per)
                print("user serial number: " + strSerialNumber)
                devList.append("[" + str(i) + "]CML: " + user_defined_name + " " + model_name
                               + "(" + str(strSerialNumber) + ")")
            elif mvcc_dev_info.nTLayerType == MV_GENTL_CXP_DEVICE:
                print("\nCXP device: [%d]" % i)
                user_defined_name = decoding_char(mvcc_dev_info.SpecialInfo.stCXPInfo.chUserDefinedName)
                model_name = decoding_char(mvcc_dev_info.SpecialInfo.stCXPInfo.chModelName)
                print("device user define name: " + user_defined_name)
                print("device model name: " + model_name)

                strSerialNumber = ""
                for per in mvcc_dev_info.SpecialInfo.stCXPInfo.chSerialNumber:
                    if per == 0:
                        break
                    strSerialNumber = strSerialNumber + chr(per)
                print("user serial number: " + strSerialNumber)
                devList.append("[" + str(i) + "]CXP: " + user_defined_name + " " + model_name
                               + "(" + str(strSerialNumber) + ")")
            elif mvcc_dev_info.nTLayerType == MV_GENTL_XOF_DEVICE:
                print("\nXoF device: [%d]" % i)
                user_defined_name = decoding_char(mvcc_dev_info.SpecialInfo.stXoFInfo.chUserDefinedName)
                model_name = decoding_char(mvcc_dev_info.SpecialInfo.stXoFInfo.chModelName)
                print("device user define name: " + user_defined_name)
                print("device model name: " + model_name)

                strSerialNumber = ""
                for per in mvcc_dev_info.SpecialInfo.stXoFInfo.chSerialNumber:
                    if per == 0:
                        break
                    strSerialNumber = strSerialNumber + chr(per)
                print("user serial number: " + strSerialNumber)
                devList.append("[" + str(i) + "]XoF: " + user_defined_name + " " + model_name
                               + "(" + str(strSerialNumber) + ")")

        ui.ComboDevices.clear()
        ui.ComboDevices.addItems(devList)
        ui.ComboDevices.setCurrentIndex(0)

    # ch:打开相机 | en:open device
    def open_device():
        global deviceList
        global nSelCamIndex
        global obj_cam_operation
        global isOpen
        if isOpen:
            QMessageBox.warning(mainWindow, "Error", 'Camera is Running!', QMessageBox.Ok)
            return MV_E_CALLORDER

        nSelCamIndex = ui.ComboDevices.currentIndex()
        if nSelCamIndex < 0:
            QMessageBox.warning(mainWindow, "Error", 'Please select a camera!', QMessageBox.Ok)
            return MV_E_CALLORDER

        obj_cam_operation = CameraOperation(cam, deviceList, nSelCamIndex)
        ret = obj_cam_operation.Open_device()
        if 0 != ret:
            strError = "Open device failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
            isOpen = False
        else:
            set_continue_mode()

            get_param()

            isOpen = True
            enable_controls()

    # ch:开始取流 | en:Start grab image
    def start_grabbing():
        global obj_cam_operation
        global isGrabbing

        ret = obj_cam_operation.Start_grabbing(ui.widgetDisplay.winId())
        if ret != 0:
            strError = "Start grabbing failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            isGrabbing = True
            enable_controls()

    # ch:停止取流 | en:Stop grab image
    def stop_grabbing():
        global obj_cam_operation
        global isGrabbing
        ret = obj_cam_operation.Stop_grabbing()
        if ret != 0:
            strError = "Stop grabbing failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            isGrabbing = False
            enable_controls()

    # ch:关闭设备 | Close device
    def close_device():
        global isOpen
        global isGrabbing
        global obj_cam_operation

        if isOpen:
            obj_cam_operation.Close_device()
            isOpen = False

        isGrabbing = False

        enable_controls()

    # ch:设置触发模式 | en:set trigger mode
    def set_continue_mode():
        ret = obj_cam_operation.Set_trigger_mode(False)
        if ret != 0:
            strError = "Set continue mode failed ret:" + ToHexStr(ret) + " mode is " + str(is_trigger_mode)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            ui.radioContinueMode.setChecked(True)
            ui.radioTriggerMode.setChecked(False)
            ui.bnSoftwareTrigger.setEnabled(False)

    # ch:设置软触发模式 | en:set software trigger mode
    def set_software_trigger_mode():
        ret = obj_cam_operation.Set_trigger_mode(True)
        if ret != 0:
            strError = "Set trigger mode failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            ui.radioContinueMode.setChecked(False)
            ui.radioTriggerMode.setChecked(True)
            ui.bnSoftwareTrigger.setEnabled(isGrabbing)

    # ch:设置触发命令 | en:set trigger software
    def trigger_once():
        ret = obj_cam_operation.Trigger_once()
        if ret != 0:
            strError = "TriggerSoftware failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)

    # ch:存图 | en:save image
    def save_bmp():
        ret = obj_cam_operation.Save_Bmp()
        if ret != MV_OK:
            strError = "Save BMP failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            print("Save image success")

    # ---- 设置读写 ----
    def load_settings():
        """从 setting.ini 读取保存路径及串口设置"""
        global save_path
        config = configparser.ConfigParser()
        if os.path.exists(SETTINGS_FILE):
            config.read(SETTINGS_FILE, encoding='utf-8')
            save_path = config.get('Settings', 'save_path', fallback='')
            saved_baud    = config.get('Serial', 'baud_rate', fallback='115200')
            saved_timeout = config.get('Serial', 'timeout',   fallback='1.0')
            saved_port    = config.get('Serial', 'port',      fallback='')
        else:
            save_path     = ''
            saved_baud    = '115200'
            saved_timeout = '1.0'
            saved_port    = ''
        _update_path_label()
        # 填充波特率下拉列表
        baud_rates = ['9600', '19200', '38400', '57600', '115200', '230400', '460800', '921600']
        ui.cmbBaudRate.clear()
        ui.cmbBaudRate.addItems(baud_rates)
        idx = ui.cmbBaudRate.findText(saved_baud)
        ui.cmbBaudRate.setCurrentIndex(idx if idx >= 0 else baud_rates.index('115200'))
        # 填充超时
        ui.edtSerialTimeout.setText(saved_timeout)
        # 初始化可用串口并尝试恢复上次选择
        refresh_serial_ports()
        if saved_port:
            idx_port = ui.cmbSerialPort.findText(saved_port)
            if idx_port >= 0:
                ui.cmbSerialPort.setCurrentIndex(idx_port)
        _update_serial_status()
        print("Settings loaded. Save path: '{}'".format(save_path or SCRIPT_DIR))

    def save_settings():
        """将保存路径及串口设置写入 setting.ini"""
        config = configparser.ConfigParser()
        config['Settings'] = {'save_path': save_path}
        config['Serial'] = {
            'port':      ui.cmbSerialPort.currentText() if ui.cmbSerialPort.count() > 0 else '',
            'baud_rate': ui.cmbBaudRate.currentText(),
            'timeout':   ui.edtSerialTimeout.text().strip(),
        }
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            config.write(f)
        print("Settings saved. Save path: '{}'".format(save_path))

    def _update_path_label():
        """刷新界面上的路径提示标签"""
        effective = save_path if save_path else SCRIPT_DIR
        ui.lblSavePathInfo.setText("保存至: " + effective)

    def get_effective_save_path():
        """返回实际使用的保存目录"""
        return save_path if save_path else SCRIPT_DIR

    def set_save_path():
        """打开文件夹选择对话框，保存选中路径到 setting.ini"""
        global save_path
        new_path = QFileDialog.getExistingDirectory(
            mainWindow, "选择图片保存路径", get_effective_save_path())
        if new_path:
            save_path = new_path
            save_settings()
            _update_path_label()

    # ---- 自动拍摄 ----
    def _auto_capture_worker(count):
        """后台线程：连续拍摄 count 张图片并保存"""
        global auto_capture_running
        save_dir = get_effective_save_path()
        os.makedirs(save_dir, exist_ok=True)
        success_count = 0
        timestamp_base = datetime.now().strftime("%Y%m%d_%H%M%S")

        for i in range(count):
            if not auto_capture_running:
                break
            file_name = "{}_{:03d}.bmp".format(timestamp_base, i + 1)
            full_path = os.path.join(save_dir, file_name)
            try:
                ret = obj_cam_operation.Save_Bmp_with_path(full_path)
                if ret == MV_OK:
                    success_count += 1
                    print("Auto capture [{}/{}]: {}".format(i + 1, count, full_path))
                else:
                    print("Auto capture [{}/{}] failed, ret: {}".format(
                        i + 1, count, ToHexStr(ret)))
            except Exception as e:
                print("Auto capture [{}/{}] error: {}".format(i + 1, count, str(e)))
            # 等待一小段时间以获取不同帧
            time.sleep(0.2)

        auto_capture_running = False
        msg = "自动拍摄完成！成功保存 {}/{} 张图片\n保存路径: {}".format(
            success_count, count, save_dir)
        QTimer.singleShot(0, lambda: QMessageBox.information(mainWindow, "完成", msg))

    def start_auto_capture():
        """检查输入并启动自动拍摄线程"""
        global auto_capture_running
        if auto_capture_running:
            QMessageBox.warning(mainWindow, "提示", "自动拍摄正在进行中！", QMessageBox.Ok)
            return
        count_str = ui.edtCaptureCount.text().strip()
        if not count_str.isdigit() or int(count_str) <= 0:
            QMessageBox.warning(mainWindow, "错误", "请输入正整数！", QMessageBox.Ok)
            return
        count = int(count_str)
        auto_capture_running = True
        t = threading.Thread(target=_auto_capture_worker, args=(count,), daemon=True)
        t.start()

    def is_float(str):
        try:
            float(str)
            return True
        except ValueError:
            return False

    # ---- 串口功能 ----
    def refresh_serial_ports():
        """扫描系统可用串口并刷新下拉列表"""
        if not _SERIAL_AVAILABLE:
            ui.cmbSerialPort.clear()
            ui.cmbSerialPort.addItem("pyserial 未安装")
            return
        current = ui.cmbSerialPort.currentText()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        ui.cmbSerialPort.clear()
        if ports:
            ui.cmbSerialPort.addItems(ports)
            idx = ui.cmbSerialPort.findText(current)
            if idx >= 0:
                ui.cmbSerialPort.setCurrentIndex(idx)
        else:
            ui.cmbSerialPort.addItem("无可用串口")
        print("已刷新串口列表: {}".format(ports if ports else "无"))

    def _update_serial_status():
        """根据连接状态更新状态标签样式"""
        if is_serial_connected:
            ui.lblSerialStatus.setText("● 已连接")
            ui.lblSerialStatus.setStyleSheet("color: green; font-weight: bold;")
            ui.bnConnectSerial.setText("断开串口")
        else:
            ui.lblSerialStatus.setText("● 未连接")
            ui.lblSerialStatus.setStyleSheet("color: red; font-weight: bold;")
            ui.bnConnectSerial.setText("连接串口")

    def connect_serial():
        """切换串口连接状态（连接/断开）"""
        global serial_conn, is_serial_connected
        if not _SERIAL_AVAILABLE:
            QMessageBox.warning(mainWindow, "错误",
                                "pyserial 未安装，请执行:\npip install pyserial",
                                QMessageBox.Ok)
            return

        if is_serial_connected:
            # 断开连接
            try:
                serial_conn.close()
            except Exception:
                pass
            serial_conn = None
            is_serial_connected = False
            _update_serial_status()
            save_settings()
            print("串口已断开")
        else:
            # 建立连接
            port = ui.cmbSerialPort.currentText()
            if not port or port in ("无可用串口", "pyserial 未安装"):
                QMessageBox.warning(mainWindow, "错误",
                                    "请先选择有效的串口！", QMessageBox.Ok)
                return
            baud_str    = ui.cmbBaudRate.currentText()
            timeout_str = ui.edtSerialTimeout.text().strip()
            try:
                baud = int(baud_str)
            except ValueError:
                QMessageBox.warning(mainWindow, "错误", "波特率格式不正确！", QMessageBox.Ok)
                return
            try:
                timeout = float(timeout_str)
            except ValueError:
                QMessageBox.warning(mainWindow, "错误",
                                    "超时时间格式不正确，请输入数字！", QMessageBox.Ok)
                return
            try:
                serial_conn = serial.Serial(
                    port=port,
                    baudrate=baud,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=timeout
                )
                is_serial_connected = True
                _update_serial_status()
                save_settings()
                print("串口已连接: {} @ {} baud, timeout={}s".format(port, baud, timeout))
            except serial.SerialException as e:
                QMessageBox.warning(mainWindow, "串口错误",
                                    "无法打开串口:\n" + str(e), QMessageBox.Ok)

    # ---- G-code 发送 ----
    def send_gcode(cmd):
        """通用 G-code 发送函数：检查连接状态后将命令编码发送至串口"""
        if not is_serial_connected or serial_conn is None:
            QMessageBox.warning(mainWindow, "错误",
                                "串口未连接，请先连接串口！", QMessageBox.Ok)
            return False
        try:
            serial_conn.write(cmd.encode('utf-8'))
            print("已发送 G-code: {}".format(cmd.strip()))
            return True
        except Exception as e:
            QMessageBox.warning(mainWindow, "串口错误",
                                "发送失败:\n" + str(e), QMessageBox.Ok)
            return False

    def action_home_z():
        """Z 轴归零：发送 G28 Z"""
        send_gcode("G28 Z\n")

    def action_move_z_step():
        """Z 轴微调（相对运动 0.1mm）"""
        if send_gcode("G91\n"):
            send_gcode("G1 Z0.1 F300\n")
            send_gcode("G90\n")

    def action_set_light():
        """亮度控制（PWM）：读取 edtLightValue 并发送 M106 S{value}"""
        value_str = ui.edtLightValue.text().strip()
        if not value_str.isdigit():
            QMessageBox.warning(mainWindow, "错误",
                                "请输入 0-255 之间的整数！", QMessageBox.Ok)
            return
        value = int(value_str)
        if not (0 <= value <= 255):
            QMessageBox.warning(mainWindow, "错误",
                                "亮度值必须在 0-255 范围内！", QMessageBox.Ok)
            return
        send_gcode("M106 S{}\n".format(value))

    def get_param():
        ret = obj_cam_operation.Get_parameter()
        if ret != MV_OK:
            strError = "Get param failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
        else:
            ui.edtExposureTime.setText("{0:.2f}".format(obj_cam_operation.exposure_time))
            ui.edtGain.setText("{0:.2f}".format(obj_cam_operation.gain))
            ui.edtFrameRate.setText("{0:.2f}".format(obj_cam_operation.frame_rate))

    # ch: 设置参数 | en:set param
    def set_param():
        frame_rate = ui.edtFrameRate.text()
        exposure = ui.edtExposureTime.text()
        gain = ui.edtGain.text()

        if is_float(frame_rate)!=True or is_float(exposure)!=True or is_float(gain)!=True:
            strError = "Set param failed ret:" + ToHexStr(MV_E_PARAMETER)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)
            return MV_E_PARAMETER
        
        ret = obj_cam_operation.Set_parameter(frame_rate, exposure, gain)
        if ret != MV_OK:
            strError = "Set param failed ret:" + ToHexStr(ret)
            QMessageBox.warning(mainWindow, "Error", strError, QMessageBox.Ok)

        return MV_OK

    # ch: 设置控件状态 | en:set enable status
    def enable_controls():
        global isGrabbing
        global isOpen

        # 先设置group的状态，再单独设置各控件状态
        ui.groupGrab.setEnabled(isOpen)
        ui.groupParam.setEnabled(isOpen)

        ui.bnOpen.setEnabled(not isOpen)
        ui.bnClose.setEnabled(isOpen)

        ui.bnStart.setEnabled(isOpen and (not isGrabbing))
        ui.bnStop.setEnabled(isOpen and isGrabbing)
        ui.bnSoftwareTrigger.setEnabled(isGrabbing and ui.radioTriggerMode.isChecked())

        ui.bnSaveImage.setEnabled(isOpen and isGrabbing)
        ui.bnAutoCapture.setEnabled(isOpen and isGrabbing)

    # ch: 初始化app, 绑定控件与函数 | en: Init app, bind ui and api
    app = QApplication(sys.argv)
    mainWindow = QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(mainWindow)
    ui.bnEnum.clicked.connect(enum_devices)
    ui.bnOpen.clicked.connect(open_device)
    ui.bnClose.clicked.connect(close_device)
    ui.bnStart.clicked.connect(start_grabbing)
    ui.bnStop.clicked.connect(stop_grabbing)

    ui.bnSoftwareTrigger.clicked.connect(trigger_once)
    ui.radioTriggerMode.clicked.connect(set_software_trigger_mode)
    ui.radioContinueMode.clicked.connect(set_continue_mode)

    ui.bnGetParam.clicked.connect(get_param)
    ui.bnSetParam.clicked.connect(set_param)

    ui.bnSaveImage.clicked.connect(save_bmp)
    ui.bnAutoCapture.clicked.connect(start_auto_capture)
    ui.bnSetSavePath.clicked.connect(set_save_path)
    ui.bnRefreshPort.clicked.connect(refresh_serial_ports)
    ui.bnConnectSerial.clicked.connect(connect_serial)
    ui.bnHomeZ.clicked.connect(action_home_z)
    ui.bnMoveStep.clicked.connect(action_move_z_step)
    ui.bnSetLight.clicked.connect(action_set_light)

    load_settings()
    mainWindow.show()

    app.exec_()

    close_device()

    # 关闭串口
    if is_serial_connected and serial_conn is not None:
        try:
            serial_conn.close()
            print("退出时已自动关闭串口")
        except Exception:
            pass

    # ch:反初始化SDK | en: finalize SDK
    MvCamera.MV_CC_Finalize()

    sys.exit()
    