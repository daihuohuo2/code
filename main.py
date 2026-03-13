import sys

from PyQt5.QtWidgets import QApplication

from main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    exit_code = app.exec_()
    window.cleanup()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
