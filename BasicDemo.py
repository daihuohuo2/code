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
from PyQt5.QtCore import QTimer, QObject, QEvent, Qt
from PyQt5.QtGui import QPainter, QColor, QPen, QFont
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


# ──────────────────────────────────────────────────────────────────
#  比例尺叠加层（透明子 Widget，覆盖在 widgetDisplay 正上方）
# ──────────────────────────────────────────────────────────────────
class ScaleBarOverlay(QWidget):
    """透明比例尺叠加层，绘制在相机预览区右上方。"""

    # 候选比例尺长度（mm）
    NICE_LENGTHS_MM = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5,
                       1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]

    def __init__(self, parent_widget):
        super().__init__(parent_widget)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(parent_widget.rect())
        self._pixels_per_mm = 100.0   # 相机图像像素/mm（标定值）
        self._img_width = 0            # 相机采集图像宽度（0 = 未知）
        self._bar_visible = False
        self.raise_()

    def set_pixels_per_mm(self, value):
        self._pixels_per_mm = max(value, 0.001)
        self.update()

    def set_img_width(self, w):
        self._img_width = w
        self.update()

    def set_visible(self, visible):
        self._bar_visible = visible
        self.update()

    def update_size(self):
        """跟随父控件尺寸调整自身大小。"""
        self.setGeometry(self.parentWidget().rect())
        self.update()

    def paintEvent(self, event):
        if not self._bar_visible or self._pixels_per_mm <= 0:
            return

        display_w = self.width()
        display_h = self.height()
        if display_w <= 0 or display_h <= 0:
            return

        # 计算显示像素/mm（考虑图像缩放比例）
        if self._img_width > 0:
            scale_factor = display_w / self._img_width
        else:
            scale_factor = 1.0
        display_ppmm = self._pixels_per_mm * scale_factor

        # 选取使比例尺约占显示宽度 20% 的最大"美观"长度
        target_px = display_w * 0.20
        bar_len_mm = self.NICE_LENGTHS_MM[0]
        bar_len_px = bar_len_mm * display_ppmm
        for L in self.NICE_LENGTHS_MM:
            px = L * display_ppmm
            if px > target_px:
                break
            bar_len_mm = L
            bar_len_px = px
        bar_len_px = max(bar_len_px, 4)

        # 格式化标签
        if bar_len_mm >= 1.0:
            label = "{:.0f} mm".format(bar_len_mm) if bar_len_mm == int(bar_len_mm) else "{} mm".format(bar_len_mm)
        else:
            label = "{:.0f} µm".format(bar_len_mm * 1000)

        # 绘制位置（左下角留边距）
        margin = 16
        bar_h = 8
        x0 = margin
        y0 = display_h - margin - bar_h - 18  # 18 px 留给文字
        x1 = x0 + int(bar_len_px)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 黑色阴影底层（提升可读性）
        shadow_pen = QPen(QColor(0, 0, 0, 180))
        shadow_pen.setWidth(3)
        painter.setPen(shadow_pen)
        painter.drawLine(x0, y0 + bar_h, x1, y0 + bar_h)  # 底边阴影

        # 绘制白色刻度条
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 160))
        painter.drawRect(x0 - 2, y0 - 2, int(bar_len_px) + 4, bar_h + 4)
        painter.setBrush(QColor(255, 255, 255, 230))
        painter.drawRect(x0, y0, int(bar_len_px), bar_h)

        # 两端刻度竖线
        tick_pen = QPen(QColor(255, 255, 255, 230), 2)
        painter.setPen(tick_pen)
        tick_h = bar_h + 4
        painter.drawLine(x0, y0 - 2, x0, y0 + tick_h)
        painter.drawLine(x1, y0 - 2, x1, y0 + tick_h)

        # 绘制标签文字
        font = QFont("Arial", 9, QFont.Bold)
        painter.setFont(font)
        # 黑色阴影
        painter.setPen(QColor(0, 0, 0, 200))
        painter.drawText(x0 + 1, y0 - 3, label)
        # 白色前景
        painter.setPen(QColor(255, 255, 255, 240))
        painter.drawText(x0, y0 - 4, label)
        painter.end()


class _ResizeFilter(QObject):
    """事件过滤器：监听 widgetDisplay 的 Resize 事件，同步更新叠加层尺寸。"""
    def __init__(self, overlay):
        super().__init__()
        self._overlay = overlay

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self._overlay.update_size()
        return False


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
    global autofocus_running
    autofocus_running = False
    global auto_calib_running
    auto_calib_running = False
    global dark_frame_captured
    dark_frame_captured = False
    global serial_conn
    serial_conn = None
    global is_serial_connected
    is_serial_connected = False
    global pixels_per_mm          # 相机图像像素/mm（比例尺标定值）
    pixels_per_mm = 100.0
    global scale_overlay           # ScaleBarOverlay 实例（setupUi 后创建）
    scale_overlay = None
    global _cam_img_width          # 最近一帧的相机图像宽度（用于显示缩放比）
    _cam_img_width = 0

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
            # 延迟 800ms 后尝试获取图像分辨率，用于比例尺显示缩放
            QTimer.singleShot(800, _poll_cam_img_width)

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
        """从 setting.ini 读取保存路径、串口设置及比例尺标定值"""
        global save_path, pixels_per_mm
        config = configparser.ConfigParser()
        if os.path.exists(SETTINGS_FILE):
            config.read(SETTINGS_FILE, encoding='utf-8')
            save_path = config.get('Settings', 'save_path', fallback='')
            saved_baud    = config.get('Serial', 'baud_rate', fallback='115200')
            saved_timeout = config.get('Serial', 'timeout',   fallback='1.0')
            saved_port    = config.get('Serial', 'port',      fallback='')
            try:
                pixels_per_mm = float(config.get('Scale', 'pixels_per_mm', fallback='100.0'))
                if pixels_per_mm <= 0:
                    pixels_per_mm = 100.0
            except ValueError:
                pixels_per_mm = 100.0
        else:
            save_path     = ''
            saved_baud    = '115200'
            saved_timeout = '1.0'
            saved_port    = ''
            pixels_per_mm = 100.0
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
        # 恢复比例尺标定值到 UI
        ui.edtPixelsPerMm.setText("{:.4f}".format(pixels_per_mm))
        scale_overlay.set_pixels_per_mm(pixels_per_mm)
        _update_scale_info_label()
        print("Settings loaded. Save path: '{}'".format(save_path or SCRIPT_DIR))

    def save_settings():
        """将保存路径、串口设置及比例尺标定值写入 setting.ini"""
        config = configparser.ConfigParser()
        config['Settings'] = {'save_path': save_path}
        config['Serial'] = {
            'port':      ui.cmbSerialPort.currentText() if ui.cmbSerialPort.count() > 0 else '',
            'baud_rate': ui.cmbBaudRate.currentText(),
            'timeout':   ui.edtSerialTimeout.text().strip(),
        }
        config['Scale'] = {
            'pixels_per_mm': str(pixels_per_mm),
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

    # ---- 自动对焦（对比度解析 + 混合PID）----
    def _compute_sharpness():
        """计算当前帧的锏度分数：拉普拉斯方差 + Tenengrad 加权平均"""
        try:
            import numpy as np
            data, w, h = obj_cam_operation.Get_frame_numpy()
            if data is None or w == 0 or h == 0:
                return 0.0
            # 只取前 w*h 字节（Mono8 / Bayer8 均适用）
            if len(data) < w * h:
                return 0.0
            gray = data[:w * h].reshape(h, w).astype(np.float32)
            # Tenengrad（简化 Sobel）
            dx = gray[:, 1:] - gray[:, :-1]
            dy = gray[1:, :] - gray[:-1, :]
            tenengrad = float(np.mean(dx ** 2) + np.mean(dy ** 2))
            # 拉普拉斯方差
            lap = (gray[:-2, 1:-1] + gray[2:, 1:-1] +
                   gray[1:-1, :-2] + gray[1:-1, 2:] -
                   4 * gray[1:-1, 1:-1])
            lap_var = float(np.var(lap))
            return 0.5 * tenengrad + 0.5 * lap_var
        except Exception as e:
            print("[AF] 锏度计算异常:", e)
            return 0.0

    def _af_move_z(step_mm):
        """相对移动 Z 轴 step_mm 毫米，返回是否成功"""
        if not send_gcode("G91\n"):
            return False
        if not send_gcode("G1 Z{:.4f} F300\n".format(step_mm)):
            return False
        if not send_gcode("G90\n"):
            return False
        time.sleep(0.25)
        return True

    def _autofocus_worker():
        """
        自动对焦后台线程：
          Phase 1 — 粗搜索：大步长扫描找到大致最优位置
          Phase 2 — 中等精度搜索：缩小范围细化
          Phase 3 — 混合 PID：寻找锏度梯度为零的位置
        """
        global autofocus_running

        def set_status(msg):
            QTimer.singleShot(0, lambda: ui.lblAutoFocusStatus.setText(msg))

        try:
            set_status("对焦中… 粗搜索")
            print("[AF] ===== 开始自动对焦 =====")

            # ----------------------------------------
            # Phase 1: 粗搜索  ±3mm 步长 1mm
            # ----------------------------------------
            COARSE_STEP = 1.0
            COARSE_HALF = 3
            current_pos = 0.0

            if not _af_move_z(-COARSE_STEP * COARSE_HALF):
                set_status("对焦失败：串口错误")
                return
            current_pos = -COARSE_STEP * COARSE_HALF

            scores_c, pos_c = [], []
            total_c = COARSE_HALF * 2 + 1
            for i in range(total_c):
                if not autofocus_running:
                    set_status("已停止")
                    return
                time.sleep(0.15)
                s = _compute_sharpness()
                scores_c.append(s)
                pos_c.append(current_pos)
                print("[AF]粗搜索 pos={:.1f}mm s={:.1f}".format(current_pos, s))
                set_status("对焦中… 粗搜索 {}/{}".format(i + 1, total_c))
                if i < total_c - 1:
                    _af_move_z(COARSE_STEP)
                    current_pos += COARSE_STEP

            best_c = int(max(range(len(scores_c)), key=lambda k: scores_c[k]))
            best_pos = pos_c[best_c]
            print("[AF]粗搜索最佳: {:.1f}mm  s={:.1f}".format(best_pos, scores_c[best_c]))
            _af_move_z(best_pos - current_pos)
            current_pos = best_pos

            # ----------------------------------------
            # Phase 2: 中等搜索  ±0.8mm 步长 0.2mm
            # ----------------------------------------
            set_status("对焦中… 中等搜索")
            MEDIUM_STEP = 0.2
            MEDIUM_HALF = 4
            _af_move_z(-MEDIUM_STEP * MEDIUM_HALF)
            current_pos -= MEDIUM_STEP * MEDIUM_HALF

            scores_m, pos_m = [], []
            total_m = MEDIUM_HALF * 2 + 1
            for i in range(total_m):
                if not autofocus_running:
                    set_status("已停止")
                    return
                time.sleep(0.12)
                s = _compute_sharpness()
                scores_m.append(s)
                pos_m.append(current_pos)
                print("[AF]中等搜索 pos={:.2f}mm s={:.1f}".format(current_pos, s))
                set_status("对焦中… 中等搜索 {}/{}".format(i + 1, total_m))
                if i < total_m - 1:
                    _af_move_z(MEDIUM_STEP)
                    current_pos += MEDIUM_STEP

            best_m = int(max(range(len(scores_m)), key=lambda k: scores_m[k]))
            best_pos = pos_m[best_m]
            print("[AF]中等搜索最佳: {:.2f}mm  s={:.1f}".format(best_pos, scores_m[best_m]))
            _af_move_z(best_pos - current_pos)
            current_pos = best_pos

            # ----------------------------------------
            # Phase 3: 混合 PID 精细调节
            #  误差 = 锏度梯度（如在最佳点，梯度=0）
            # ----------------------------------------
            set_status("对焦中… PID 精细")
            print("[AF] PID 精细开始")
            Kp, Ki, Kd = 0.06, 0.004, 0.018
            integral = 0.0
            prev_error = 0.0
            PROBE = 0.05        # 探测步长 mm
            MAX_ITER = 20
            CONV_THR = 0.004    # 步长小于此值则认为收敛

            for it in range(MAX_ITER):
                if not autofocus_running:
                    break
                # 正向探测
                _af_move_z(PROBE)
                current_pos += PROBE
                time.sleep(0.1)
                s_plus = _compute_sharpness()
                # 负向探测
                _af_move_z(-2 * PROBE)
                current_pos -= 2 * PROBE
                time.sleep(0.1)
                s_minus = _compute_sharpness()
                # 回到中间
                _af_move_z(PROBE)
                current_pos += PROBE

                gradient = (s_plus - s_minus) / (2 * PROBE)
                error = gradient
                integral = max(-0.5, min(0.5, integral + error * 0.01))
                derivative = error - prev_error
                control = Kp * error + Ki * integral + Kd * derivative
                step = max(-0.15, min(0.15, control))
                print("[AF] PID迭 {}: grad={:.1f} step={:.4f}mm".format(it + 1, gradient, step))

                prev_error = error
                if abs(step) < CONV_THR:
                    print("[AF] PID 收敛!")
                    break
                _af_move_z(step)
                current_pos += step

            s_final = _compute_sharpness()
            print("[AF] ===== 对焦完成 最终锏度={:.1f} =====".format(s_final))
            set_status("对焦完成 \u2713  锏度:{:.0f}".format(s_final))

        except Exception as e:
            print("[AF] 异常:", e)
            set_status("对焦失败: " + str(e))
        finally:
            autofocus_running = False
            QTimer.singleShot(0, lambda: ui.bnAutoFocus.setEnabled(True))
            QTimer.singleShot(0, lambda: ui.bnStopAutoFocus.setEnabled(False))

    def start_autofocus():
        """启动自动对焦线程"""
        global autofocus_running
        if not is_serial_connected:
            QMessageBox.warning(mainWindow, "错误", "请先连接串口！", QMessageBox.Ok)
            return
        if autofocus_running:
            QMessageBox.warning(mainWindow, "提示", "对焦正在进行！", QMessageBox.Ok)
            return
        autofocus_running = True
        ui.bnAutoFocus.setEnabled(False)
        ui.bnStopAutoFocus.setEnabled(True)
        t = threading.Thread(target=_autofocus_worker, daemon=True)
        t.start()

    def stop_autofocus():
        """请求停止对焦"""
        global autofocus_running
        autofocus_running = False
        ui.lblAutoFocusStatus.setText("停止中…")

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

    # ── 比例尺功能 ────────────────────────────────────────────────

    def _poll_cam_img_width():
        """采集开始后单次轮询，获取相机图像宽度供比例尺缩放使用。"""
        global _cam_img_width
        if obj_cam_operation and isGrabbing:
            try:
                _, w, _h = obj_cam_operation.Get_frame_numpy()
                if w > 0:
                    _cam_img_width = w
                    scale_overlay.set_img_width(w)
            except Exception:
                pass

    def _apply_scale_calib():
        """读取 edtPixelsPerMm 输入，更新标定值并刷新叠加层。"""
        global pixels_per_mm, _cam_img_width
        try:
            v = float(ui.edtPixelsPerMm.text().strip())
            if v <= 0.0:
                raise ValueError("非正数")
        except ValueError:
            QMessageBox.warning(mainWindow, "输入错误",
                                "请输入有效的正数（像素/mm）。", QMessageBox.Ok)
            return
        pixels_per_mm = v
        # 尝试获取当前帧图像宽度（用于计算显示缩放系数）
        if obj_cam_operation and isGrabbing:
            try:
                _, w, _h = obj_cam_operation.Get_frame_numpy()
                if w > 0:
                    _cam_img_width = w
                    scale_overlay.set_img_width(w)
            except Exception:
                pass
        scale_overlay.set_pixels_per_mm(pixels_per_mm)
        _update_scale_info_label()
        save_settings()

    def _toggle_scale_bar(state):
        """复选框状态变化时切换叠加层可见性。"""
        scale_overlay.set_visible(state == Qt.Checked)

    def _update_scale_info_label():
        """刷新状态标签：显示 1mm 对应像素数及每像素微米数。"""
        if scale_overlay is None or pixels_per_mm <= 0:
            ui.lblScaleBarInfo.setText("未标定")
            return
        info = "1mm={:.1f}px | {:.3f}µm/px".format(
            pixels_per_mm, 1000.0 / pixels_per_mm)
        ui.lblScaleBarInfo.setText(info)

    # ── 自动标定 ─────────────────────────────────────────────────

    def _phase_correlation_shift(frame1, frame2):
        """
        使用相位相关法计算两帧之间的亚像素位移幅度。
        返回 (dx, dy)：正值表示帧2相对帧1在对应方向的位移（像素）。
        若无法计算则返回 (0.0, 0.0)。
        """
        try:
            import numpy as np
            f1 = frame1.astype(np.float64) - np.mean(frame1)
            f2 = frame2.astype(np.float64) - np.mean(frame2)
            F1 = np.fft.fft2(f1)
            F2 = np.fft.fft2(f2)
            # 归一化互功率谱
            R = F1 * np.conj(F2)
            eps = np.abs(R).max() * 1e-10 + 1e-30
            R = R / (np.abs(R) + eps)
            # 逆变换并找峰值
            r = np.fft.ifft2(R).real
            idx = np.unravel_index(np.argmax(r), r.shape)
            dy, dx = int(idx[0]), int(idx[1])
            h, w = frame1.shape[:2]
            # 处理环绕（移位量 > 图像半边）
            if dy > h // 2:
                dy -= h
            if dx > w // 2:
                dx -= w
            return float(dx), float(dy)
        except Exception as e:
            print("[AutoCalib] 相位相关异常:", e)
            return 0.0, 0.0

    def _auto_calib_worker(move_mm, axis):
        """
        自动标定后台线程：
          1. 采集初始帧
          2. 沿指定轴移动已知距离
          3. 采集移动后帧
          4. 用相位相关计算像素位移
          5. pixels_per_mm = |位移| / move_mm，更新标定值
        axis: 'X' 或 'Y'，决定使用 dx 还是 dy
        """
        global auto_calib_running

        def set_status(msg):
            QTimer.singleShot(0, lambda m=msg: ui.lblAutoCalibStatus.setText(m))

        try:
            import numpy as np

            # ── 帧1 ──
            set_status("标定中… 采集初始帧")
            print("[AutoCalib] 采集帧1")
            data1, w, h = obj_cam_operation.Get_frame_numpy()
            if data1 is None or w == 0 or h == 0 or len(data1) < w * h:
                set_status("标定失败：无法获取初始帧")
                return
            frame1 = data1[:w * h].reshape(h, w).astype(np.float32)

            # ── 移动已知距离 ──
            set_status("标定中… 移动 {:.3f}mm ({})轴".format(move_mm, axis))
            print("[AutoCalib] 移动 {}轴 {:.3f}mm".format(axis, move_mm))
            if not send_gcode("G91\n"):
                set_status("标定失败：串口错误（G91）")
                return
            if not send_gcode("G1 {}{:.4f} F300\n".format(axis, move_mm)):
                set_status("标定失败：串口错误（移动）")
                return
            if not send_gcode("G90\n"):
                set_status("标定失败：串口错误（G90）")
                return
            # 等待运动完成（依据距离动态估算）
            wait_s = max(0.5, abs(move_mm) / 10.0 + 0.4)
            time.sleep(wait_s)

            # ── 帧2 ──
            set_status("标定中… 采集移动后帧")
            print("[AutoCalib] 采集帧2")
            data2, w2, h2 = obj_cam_operation.Get_frame_numpy()
            if data2 is None or w2 == 0 or h2 == 0 or len(data2) < w2 * h2:
                set_status("标定失败：无法获取移动后帧")
                return
            frame2 = data2[:w2 * h2].reshape(h2, w2).astype(np.float32)

            # ── 相位相关 ──
            set_status("标定中… 计算像素位移")
            dx, dy = _phase_correlation_shift(frame1, frame2)
            shift_px = abs(dx) if axis.upper() == 'X' else abs(dy)
            print("[AutoCalib] dx={:.2f}px  dy={:.2f}px  使用{}方向={:.2f}px".format(
                dx, dy, axis, shift_px))

            if shift_px < 1.0:
                set_status("标定失败：位移过小({:.2f}px)\n请增大移动距离或确保视野有纹理".format(shift_px))
                return

            # ── 计算并更新 pixels/mm ──
            ppmm = shift_px / abs(move_mm)
            print("[AutoCalib] pixels/mm = {:.4f}".format(ppmm))

            def _update_ui():
                global pixels_per_mm
                pixels_per_mm = ppmm
                ui.edtPixelsPerMm.setText("{:.4f}".format(ppmm))
                _apply_scale_calib()
                ui.lblAutoCalibStatus.setText(
                    "标定完成 ✓\n{:.2f} px/mm | {:.3f} µm/px".format(
                        ppmm, 1000.0 / ppmm))
            QTimer.singleShot(0, _update_ui)

        except Exception as e:
            print("[AutoCalib] 异常:", e)
            set_status("标定失败: " + str(e))
        finally:
            auto_calib_running = False
            QTimer.singleShot(0, lambda: ui.bnAutoCalib.setEnabled(True))

    # ── 底噪扣除 ──────────────────────────────────────────────

    def capture_dark_frame():
        """采集当前帧作为底噪（暗帧），存入 obj_cam_operation.dark_frame"""
        global dark_frame_captured
        if not isGrabbing:
            QMessageBox.warning(mainWindow, "错误", "请先开始采集！", QMessageBox.Ok)
            return
        try:
            import numpy as np
            data, w, h = obj_cam_operation.Get_frame_numpy()
            if data is None or w == 0 or h == 0:
                QMessageBox.warning(mainWindow, "错误",
                                    "无法获取当前帧，请确认相机正在输出图像。",
                                    QMessageBox.Ok)
                return
            frame_len = w * h  # Mono8/Bayer8
            if len(data) < frame_len:
                QMessageBox.warning(mainWindow, "错误",
                                    "帧数据长度不匹配（{} < {}*{}）。".format(
                                        len(data), w, h), QMessageBox.Ok)
                return
            # 取前 w*h 字节（支持 Mono8 / BayerXX8）
            dark = data[:frame_len].astype(np.int16)
            # 存入完整帧长度（SDK 帧长度可能包含额外对齐字节）
            full_dark = data.astype(np.int16)   # 长度 = nFrameLen
            obj_cam_operation.dark_frame = full_dark
            dark_frame_captured = True
            ui.chkDarkSub.setEnabled(True)
            ui.bnClearDark.setEnabled(True)
            mean_val = float(np.mean(dark))
            ui.lblDarkSubStatus.setText(
                "帧大小: {}x{}\n均值: {:.1f}\n底噪帧已就绪".format(w, h, mean_val))
            print("[DarkSub] 底噪帧已采集: {}x{}, 均值={:.1f}".format(w, h, mean_val))
        except Exception as e:
            print("[DarkSub] 采集异常:", e)
            QMessageBox.warning(mainWindow, "错误",
                                "采集底噪帧失败:\n" + str(e), QMessageBox.Ok)

    def toggle_dark_sub(state):
        """复选框状态变化时切换底噪扣除开关"""
        if obj_cam_operation and isGrabbing:
            enabled = (state == Qt.Checked)
            obj_cam_operation.apply_dark_sub = enabled
            _update_dark_sub_status_label(dark_frame_captured, enabled)
            print("[DarkSub] 底噪扣除{}".format("已启用" if enabled else "已禁用"))
    def _update_dark_sub_status_label(captured, enabled):
        """^统一刷新底噪状态标签"""
        if not captured:
            ui.lblDarkSubStatus.setText("未采集")
        elif enabled:
            ui.lblDarkSubStatus.setText("底噪帧已就绪\n已开启 ✔")
        else:
            ui.lblDarkSubStatus.setText("底噪帧已就绪\n未开启")

    def clear_dark_frame():
        """清除底噪帧并禁用扣除"""
        global dark_frame_captured
        if obj_cam_operation:
            obj_cam_operation.dark_frame = None
            obj_cam_operation.apply_dark_sub = False
        dark_frame_captured = False
        ui.chkDarkSub.setChecked(False)
        ui.chkDarkSub.setEnabled(False)
        ui.bnClearDark.setEnabled(False)
        ui.lblDarkSubStatus.setText("未采集")
        print("[DarkSub] 底噪帧已清除")

    def start_auto_calib():
        """读取 UI 输入并启动自动标定线程"""
        global auto_calib_running
        if not isGrabbing:
            QMessageBox.warning(mainWindow, "错误", "请先开始采集！", QMessageBox.Ok)
            return
        if not is_serial_connected:
            QMessageBox.warning(mainWindow, "错误", "请先连接串口！", QMessageBox.Ok)
            return
        if auto_calib_running:
            QMessageBox.warning(mainWindow, "提示", "标定正在进行中！", QMessageBox.Ok)
            return
        move_str = ui.edtCalibMoveMm.text().strip()
        try:
            move_mm = float(move_str)
            if abs(move_mm) < 0.01:
                raise ValueError("移动量过小")
        except ValueError:
            QMessageBox.warning(mainWindow, "输入错误",
                                "请输入有效的移动距离（mm），最小 0.01mm。",
                                QMessageBox.Ok)
            return
        # 询问标定轴
        axis, ok = QInputDialog.getItem(
            mainWindow, "选择标定轴",
            "请选择移动轴（相机水平方向通常对应 X）：",
            ["X", "Y"], 0, False)
        if not ok:
            return
        auto_calib_running = True
        ui.bnAutoCalib.setEnabled(False)
        ui.lblAutoCalibStatus.setText("标定中…")
        t = threading.Thread(
            target=_auto_calib_worker, args=(move_mm, axis), daemon=True)
        t.start()

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
        ui.bnAutoFocus.setEnabled(isOpen and isGrabbing and not autofocus_running)
        ui.bnStopAutoFocus.setEnabled(autofocus_running)
        ui.bnAutoCalib.setEnabled(isOpen and isGrabbing and not auto_calib_running)
        ui.bnCaptureDark.setEnabled(isOpen and isGrabbing)
        if not (isOpen and isGrabbing):
            # 停止采集时同时禁用扣除，但保留已采集帧的按钮状态
            if obj_cam_operation:
                obj_cam_operation.apply_dark_sub = False
            ui.chkDarkSub.setChecked(False)

    # ch: 初始化app, 绑定控件与函数 | en: Init app, bind ui and api
    app = QApplication(sys.argv)
    mainWindow = QMainWindow()
    ui = Ui_MainWindow()
    ui.setupUi(mainWindow)

    # 创建比例尺叠加层（必须在 setupUi 之后，widgetDisplay 已存在）
    scale_overlay = ScaleBarOverlay(ui.widgetDisplay)
    _resize_filter = _ResizeFilter(scale_overlay)
    ui.widgetDisplay.installEventFilter(_resize_filter)

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
    ui.bnAutoFocus.clicked.connect(start_autofocus)
    ui.bnStopAutoFocus.clicked.connect(stop_autofocus)
    ui.bnRefreshPort.clicked.connect(refresh_serial_ports)
    ui.bnConnectSerial.clicked.connect(connect_serial)
    ui.bnHomeZ.clicked.connect(action_home_z)
    ui.bnMoveStep.clicked.connect(action_move_z_step)
    ui.bnSetLight.clicked.connect(action_set_light)
    ui.bnSetScaleCalib.clicked.connect(_apply_scale_calib)
    ui.bnAutoCalib.clicked.connect(start_auto_calib)
    ui.bnCaptureDark.clicked.connect(capture_dark_frame)
    ui.chkDarkSub.stateChanged.connect(toggle_dark_sub)
    ui.bnClearDark.clicked.connect(clear_dark_frame)
    ui.chkShowScaleBar.stateChanged.connect(_toggle_scale_bar)

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
    