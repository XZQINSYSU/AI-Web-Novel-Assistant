# styles.py

MODERN_QSS = """
* {
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 14px;
}
QMainWindow, QDialog {
    background-color: #F2F4F8;
}
QWidget {
    color: #333333;
}
QPushButton {
    background-color: #FFFFFF;
    border: 1px solid #DCDFE6;
    border-radius: 6px;
    padding: 8px 16px;
    color: #606266;
    font-weight: 500;
}
QPushButton:hover {
    color: #409EFF;
    border-color: #C6E2FF;
    background-color: #ECF5FF;
}
QPushButton:pressed {
    color: #3A8EE6;
    border-color: #3A8EE6;
}
QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox {
    border: 1px solid #DCDFE6;
    border-radius: 6px;
    padding: 8px;
    background-color: #FFFFFF;
    selection-background-color: #409EFF;
}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #409EFF;
}
QTreeWidget {
    border: 1px solid #E4E7ED;
    border-radius: 8px;
    background-color: #FFFFFF;
    padding: 5px;
}
QTreeWidget::item {
    padding: 6px;
    border-radius: 4px;
}
QTreeWidget::item:selected {
    background-color: #ECF5FF;
    color: #409EFF;
}
QGroupBox {
    border: 1px solid #EBEEF5;
    border-radius: 8px;
    margin-top: 20px;
    background-color: #FFFFFF;
    padding-top: 15px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    color: #909399;
    font-weight: bold;
    left: 10px;
}
QSplitter::handle {
    background-color: #E4E7ED;
    width: 3px;
    margin: 0 5px;
    border-radius: 1px;
}
QScrollBar:vertical {
    border: none;
    background: #F5F7FA;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #C0C4CC;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #909399;
}
QListWidget {
    border: 1px solid #E4E7ED;
    border-radius: 6px;
    background-color: #FFFFFF;
}
QListWidget::item {
    padding: 10px;
    border-bottom: 1px solid #F2F4F8;
}
QListWidget::item:selected {
    background-color: #ECF5FF;
    color: #409EFF;
    border-radius: 4px;
}
"""