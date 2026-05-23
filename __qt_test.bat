@echo off
set QT_PLUGIN_PATH=C:\Users\21166\Desktop\CODE?~1\.venv\Lib\site-packages\PyQt5\Qt5\plugins
set QT_QPA_PLATFORM_PLUGIN_PATH=C:\Users\21166\Desktop\CODE?~1\.venv\Lib\site-packages\PyQt5\Qt5\plugins\platforms
C:\Users\21166\Desktop\CODE?~1\.venv\Scripts\python.exe -c "from PyQt5.QtWidgets import QApplication; app=QApplication([]); print('QT_OK')"
