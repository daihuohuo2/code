import sys

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices

from main_window import MainWindow


def main():
    app = QApplication(sys.argv)

    # Warn (non-blocking) if MVS camera SDK is not available
    try:
        from device_controller import MV_SDK_AVAILABLE, MV_SDK_ERROR_MSG
        if not MV_SDK_AVAILABLE:
            sdk_url = "https://www.hikrobotics.com/cn/machinevision/service/download?module=0"
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("相机 SDK 未找到")
            msg.setText(
                "海康威视 MVS 相机 SDK 未安装或无法加载，\n"
                "相机相关功能将不可用，其他功能正常使用。\n\n"
                "请前往官网下载并安装 MVS SDK：\n"
                + sdk_url
            )
            if MV_SDK_ERROR_MSG:
                msg.setDetailedText(MV_SDK_ERROR_MSG)
            open_btn = msg.addButton("打开下载页面", QMessageBox.ActionRole)
            msg.addButton("知道了", QMessageBox.AcceptRole)
            msg.exec_()
            if msg.clickedButton() == open_btn:
                QDesktopServices.openUrl(QUrl(sdk_url))
    except Exception:
        pass

    window = MainWindow()
    window.show()
    exit_code = app.exec_()
    window.cleanup()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
