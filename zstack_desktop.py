"""Standalone launcher for the offline Z-stack desktop dialog."""

import os
import sys

from PyQt5.QtWidgets import QApplication

from config_manager import ConfigManager
from dialogs.offline_zstack_dialog import OfflineZStackDialog


def main():
    app = QApplication(sys.argv)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    settings_file = os.path.join(script_dir, "setting.ini")
    config_manager = ConfigManager(settings_file, script_dir)
    config_manager.load()

    window = OfflineZStackDialog(config_manager)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
