# main.py
import sys
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog
from PyQt6.QtCore import QSettings
from styles import MODERN_QSS
from ui_components import WelcomeDialog, SettingsDialog
from main_window import MainWindow

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyleSheet(MODERN_QSS)

    settings = QSettings("AIWriter", "Settings")
    if not settings.value("api_key", ""):
        QMessageBox.information(None, "初始化", "检测到您首次使用或未配置 API Key，请先进行全局设置。")
        SettingsDialog().exec()

    while True:
        welcome = WelcomeDialog()
        if welcome.exec() == QDialog.DialogCode.Accepted and welcome.selected_path:
            project_path = welcome.selected_path
            window = MainWindow(project_path)
            window.show()
            app.exec()

            if getattr(window, 'switch_project', False):
                continue
            else:
                break
        else:
            break

    sys.exit(0)