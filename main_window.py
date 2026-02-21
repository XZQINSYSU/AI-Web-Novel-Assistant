# main_window.py
import os
import docx
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QTextEdit, QPushButton, QScrollArea, QSplitter, QMessageBox,
                             QFileDialog, QTreeWidget, QTreeWidgetItem, QMenu, QStackedWidget,
                             QInputDialog, QToolBar, QCheckBox)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QShortcut, QKeySequence, QAction, QTextDocument
from PyQt6.QtPrintSupport import QPrinter
from data_manager import NovelProject
from ai_worker import AutoPilotWorker,AIWorker,CorrectionWorker
from ui_components import SettingsDialog, CharacterWidget
from PyQt6.QtWidgets import QToolButton, QMenu, QListWidget, QDockWidget # 新增引用

class MainWindow(QMainWindow):
    def __init__(self, project_path):
        super().__init__()
        self.project = NovelProject(project_path)
        self.settings = QSettings("AIWriter", "Settings")
        self.character_widgets = []
        self.current_vol_index = -1
        self.current_chap_index = -1
        self.switch_project = False
        self.is_generating = False

        self.gen_v_idx = -1  # 正在生成的卷索引
        self.gen_c_idx = -1  # 正在生成的章索引
        self.gen_content_buffer = ""  # 正文生成的内存缓冲区
        self.gen_reasoning_buffer = ""  # 思考过程的内存缓冲区

        self.setWindowTitle(f"AI 网文辅助创作系统 - 📖 [{self.project.meta['title']}] (按 Ctrl+S 保存)")
        self.resize(1400, 850)

        self.init_menu_and_toolbar()
        self.init_ui()
        self.setup_shortcuts()
        self.refresh_tree()

    def init_menu_and_toolbar(self):
        # 菜单栏
        menubar = self.menuBar()
        file_menu = menubar.addMenu('文件')

        settings_action = QAction('⚙️ 全局/大模型设置', self)
        settings_action.triggered.connect(self.open_settings)
        file_menu.addAction(settings_action)

        # 显眼的顶部工具栏 (任何时候都可以快速调出设置)
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # ====== 返回首页按钮 ======
        btn_home = QPushButton("🏠 返回首页")
        btn_home.setStyleSheet(
            "background-color: transparent; border: 1px solid #DCDFE6; font-weight:bold; color: #E6A23C;")
        btn_home.clicked.connect(self.return_to_home)
        toolbar.addWidget(btn_home)

        # ====== 一键成书按钮 ======
        btn_export = QPushButton("📚 一键成书")
        btn_export.setStyleSheet(
            "background-color: transparent; border: 1px solid #DCDFE6; font-weight:bold; color: #67C23A;")
        btn_export.clicked.connect(self.export_book)
        toolbar.addWidget(btn_export)

        toolbar.addSeparator()

        btn_settings = QPushButton("⚙️ 设置模型参数")
        btn_settings.setStyleSheet("background-color: transparent; border: 1px solid #DCDFE6; font-weight:bold;")
        btn_settings.clicked.connect(self.open_settings)
        toolbar.addWidget(btn_settings)

        toolbar.addSeparator()

        lbl_status = QLabel("  💡 提示：在左侧树状图右键可新建卷/章。")
        lbl_status.setStyleSheet("color: #909399; font-size: 13px;")
        toolbar.addWidget(lbl_status)

        # ====== 【修复】找回丢失的自动挂机按钮 ======
        self.btn_auto_pilot = QPushButton("🤖 开启自动挂机")
        self.btn_auto_pilot.setStyleSheet(
            "background-color: transparent; border: 1px solid #DCDFE6; font-weight:bold; color: #9C27B0;")
        self.btn_auto_pilot.clicked.connect(self.toggle_auto_pilot)
        toolbar.addWidget(self.btn_auto_pilot)

        # ====== 全文一键纠错菜单 ======
        self.btn_full_correct = QToolButton()
        self.btn_full_correct.setText("🩺 全文一键纠错")
        self.btn_full_correct.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_full_correct.setStyleSheet(
            "background-color: transparent; border: 1px solid #DCDFE6; font-weight:bold; color: #F56C6C; padding: 5px;")

        self.full_correct_menu = QMenu(self)
        self.full_correct_menu.addAction("错别字/语病纠错", lambda: self.start_correction("full", "typo"))
        self.full_correct_menu.addAction("设定/逻辑纠错", lambda: self.start_correction("full", "setting"))
        self.full_correct_menu.addAction("🌟 全部纠错", lambda: self.start_correction("full", "all"))
        self.btn_full_correct.setMenu(self.full_correct_menu)

        toolbar.addWidget(self.btn_full_correct)

        # ====== 侧边栏开关 ======
        self.btn_toggle_log = QPushButton("📋 纠错日志")
        self.btn_toggle_log.setStyleSheet("background-color: transparent; border: none; color: #909399;")
        self.btn_toggle_log.setCheckable(True)
        self.btn_toggle_log.clicked.connect(self.toggle_log_sidebar)
        toolbar.addWidget(self.btn_toggle_log)

    def open_settings(self):
        SettingsDialog(self).exec()

    def init_ui(self):
        central_widget = QWidget()
        central_widget.setStyleSheet("background-color: #FFFFFF;")  # 让主内容区保持白色清爽
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # ====== 左侧：文件树导航 ======
        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("📚 小说大纲目录 (右键操作)")
        self.tree.header().setStyleSheet("font-weight: bold; font-size: 15px; color: #303133;")
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.itemClicked.connect(self.on_tree_select)

        tree_layout.addWidget(self.tree)

        # ====== 中间：设定面板区 (Stacked) ======
        self.stacked_widget = QStackedWidget()

        # 页面0: 全局设定
        self.page_global = QWidget()
        gl_layout = QVBoxLayout(self.page_global)
        gl_layout.setContentsMargins(10, 0, 10, 0)
        gl_layout.addWidget(QLabel("<span style='font-size:16px; font-weight:bold;'>🌍 全局故事梗概</span>"))
        self.story_synopsis_input = QTextEdit(self.project.meta["global_synopsis"])
        gl_layout.addWidget(self.story_synopsis_input)

        gl_layout.addWidget(
            QLabel("<span style='font-size:16px; font-weight:bold; margin-top:10px;'>👥 核心人物设定</span>"))
        self.char_list_layout = QVBoxLayout()
        scroll_char = QScrollArea()
        scroll_char.setWidgetResizable(True)
        scroll_char.setStyleSheet("border: none;")
        char_container = QWidget()
        char_container.setLayout(self.char_list_layout)
        scroll_char.setWidget(char_container)
        gl_layout.addWidget(scroll_char)

        btn_add_char = QPushButton("➕ 添加新人物")
        btn_add_char.setStyleSheet("border-style: dashed; background-color: #FAFAFA;")
        btn_add_char.clicked.connect(self.add_character)
        gl_layout.addWidget(btn_add_char)

        btn_save_global = QPushButton("💾 保存全局设定")
        btn_save_global.setStyleSheet("background-color: #409EFF; color: white; font-weight: bold; border: none;")
        btn_save_global.clicked.connect(self.save_global_meta)
        gl_layout.addWidget(btn_save_global)

        # 页面1: 卷设定
        self.page_volume = QWidget()
        vl_layout = QVBoxLayout(self.page_volume)
        self.lbl_vol_title = QLabel("<b>当前卷: </b>")
        self.lbl_vol_title.setStyleSheet("font-size: 16px; color: #303133;")
        vl_layout.addWidget(self.lbl_vol_title)
        self.vol_synopsis_input = QTextEdit()
        self.vol_synopsis_input.setPlaceholderText("本卷的核心主线、剧情走向梗概...")
        vl_layout.addWidget(self.vol_synopsis_input)
        btn_save_vol = QPushButton("💾 保存卷设定")
        btn_save_vol.setStyleSheet("background-color: #409EFF; color: white; font-weight: bold; border: none;")
        btn_save_vol.clicked.connect(self.save_vol_meta)
        vl_layout.addWidget(btn_save_vol)

        # 页面2: 章设定
        self.page_chapter = QWidget()
        cl_layout = QVBoxLayout(self.page_chapter)
        self.lbl_chap_title = QLabel("<b>当前章: </b>")
        self.lbl_chap_title.setStyleSheet("font-size: 16px; color: #303133;")
        cl_layout.addWidget(self.lbl_chap_title)
        self.chap_synopsis_input = QTextEdit()
        self.chap_synopsis_input.setPlaceholderText("本章细纲、出场人物、名场面要求...")
        cl_layout.addWidget(self.chap_synopsis_input)
        btn_save_chap = QPushButton("💾 保存章设定")
        btn_save_chap.setStyleSheet("background-color: #409EFF; color: white; font-weight: bold; border: none;")
        btn_save_chap.clicked.connect(self.save_chap_meta)
        cl_layout.addWidget(btn_save_chap)

        self.stacked_widget.addWidget(self.page_global)
        self.stacked_widget.addWidget(self.page_volume)
        self.stacked_widget.addWidget(self.page_chapter)

        # ====== 右侧：写作输出区 ======
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)

        # 1. 顶部操作按钮行 (放在同一个水平布局里)
        btn_action_layout = QHBoxLayout()

        self.btn_start = QPushButton("🚀 根据设定撰写本章")
        self.btn_start.setEnabled(False)  # 必须选中章节才能写
        self.btn_start.setStyleSheet(
            "font-size: 16px; font-weight: bold; background-color: #A0CFFF; color: white; border: none; padding: 12px; border-radius: 6px;"
        )
        self.btn_start.clicked.connect(self.start_generation)
        btn_action_layout.addWidget(self.btn_start)

        # 章节一键纠错按钮
        self.btn_chap_correct = QToolButton()
        self.btn_chap_correct.setText("🔧 章节一键纠错")
        self.btn_chap_correct.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_chap_correct.setStyleSheet(
            "font-size: 14px; font-weight: bold; background-color: #E6A23C; color: white; border: none; padding: 10px; border-radius: 6px;")
        self.btn_chap_correct.setEnabled(False)  # 初始化时未选章节不可用

        self.chap_correct_menu = QMenu(self)
        self.chap_correct_menu.addAction("错别字/语病纠错", lambda: self.start_correction("chapter", "typo"))
        self.chap_correct_menu.addAction("设定/逻辑纠错", lambda: self.start_correction("chapter", "setting"))
        self.chap_correct_menu.addAction("🌟 全部纠错", lambda: self.start_correction("chapter", "all"))
        self.btn_chap_correct.setMenu(self.chap_correct_menu)
        btn_action_layout.addWidget(self.btn_chap_correct)

        # 将按钮行加入右侧主布局
        right_layout.addLayout(btn_action_layout)

        # 2. 思考过程显示区
        self.btn_toggle_thinking = QPushButton("🔽 收起思考过程")
        self.btn_toggle_thinking.setStyleSheet(
            "background-color: transparent; border: none; color: #909399; text-align: left;")
        self.btn_toggle_thinking.clicked.connect(self.toggle_thinking)
        right_layout.addWidget(self.btn_toggle_thinking)

        self.thinking_output = QTextEdit()
        self.thinking_output.setReadOnly(True)
        self.thinking_output.setStyleSheet(
            "background-color: #F8F9FA; color: #8A8F99; border: 1px solid #E4E7ED; border-radius: 6px;")
        self.thinking_output.setFixedHeight(120)
        right_layout.addWidget(self.thinking_output)

        # 3. 正文显示区
        right_layout.addWidget(
            QLabel("<span style='font-size:16px; font-weight:bold;'>✍️ 小说正文区 (按 Ctrl+S 实时保存到 docx)</span>"))

        self.content_output = QTextEdit()
        self.content_output.setStyleSheet("""
                    font-size: 16px; 
                    line-height: 1.8; 
                    padding: 15px; 
                    color: #2C3E50;
                    background-color: #FAFAFA;
                """)
        right_layout.addWidget(self.content_output)

        # ====== 【新增】日志侧边栏 (作为一个可隐藏的 QListWidget) ======
        self.log_list = QListWidget()
        self.log_list.setStyleSheet(
            "background-color: #FAFAFA; border: 1px solid #E4E7ED; color: #606266; padding: 5px;")
        self.log_list.setWordWrap(True)  # 【新增】开启自动换行，防止日志过长难以查看
        self.log_list.hide()  # 默认隐藏

        # 将原有的 right_widget 包装进另一个 Splitter，使其能和日志栏左右拖拽
        right_splitter = QSplitter(Qt.Orientation.Horizontal)
        right_splitter.addWidget(right_widget)
        right_splitter.addWidget(self.log_list)
        right_splitter.setSizes([800, 200])  # 设定初始比例

        # 最后把所有大板块拼装进最外层的 splitter
        splitter.addWidget(tree_container)
        splitter.addWidget(self.stacked_widget)
        splitter.addWidget(right_splitter)  # 这里用新的 right_splitter 替换掉了单纯的 right_widget
        splitter.setSizes([250, 300, 850])

        # 初始化加载人物
        for char_data in self.project.meta.get("characters", []):
            self.add_character(char_data)

    def setup_shortcuts(self):
        shortcut_save = QShortcut(QKeySequence("Ctrl+S"), self)
        shortcut_save.activated.connect(self.save_all)
        shortcut_delete = QShortcut(QKeySequence("Delete"), self.tree)
        shortcut_delete.activated.connect(lambda: self.ui_delete_item(self.tree.currentItem()))

    # --- UI 辅助与交互逻辑 ---
    def add_character(self, init_data=None):
        widget = CharacterWidget(self.remove_character, init_data)
        self.char_list_layout.addWidget(widget)
        self.character_widgets.append(widget)

    def remove_character(self, widget):
        self.char_list_layout.removeWidget(widget)
        widget.deleteLater()
        self.character_widgets.remove(widget)

    def toggle_thinking(self):
        is_visible = self.thinking_output.isVisible()
        self.thinking_output.setVisible(not is_visible)
        self.btn_toggle_thinking.setText("🔽 收起思考过程" if not is_visible else "▶️ 展开思考过程")

    # === 日志侧边栏切换 ===
    def toggle_log_sidebar(self, checked):
        if checked:
            self.log_list.show()
        else:
            self.log_list.hide()

    def update_ui_state(self):
        # 1. 检查当前视角的章节是否正在被大模型撰写、纠错或正在自动挂机
        is_auto_piloting = getattr(self, 'is_auto_piloting', False)
        is_correcting = getattr(self, 'is_correcting', False)
        is_generating = getattr(self, 'is_generating', False)

        is_viewing_gen_chapter = ((is_generating or is_auto_piloting) and
                                  self.current_vol_index == getattr(self, 'gen_v_idx', -1) and
                                  self.current_chap_index == getattr(self, 'gen_c_idx', -1))

        # 只要正在生成当前章，或者处于全局挂机、全文/单章纠错状态，严格锁定文本框为只读
        self.content_output.setReadOnly(is_viewing_gen_chapter or is_auto_piloting or is_correcting)

        # 2. 动态改变生成按钮的颜色和文案
        if is_generating:
            self.btn_start.setEnabled(True)
            if is_viewing_gen_chapter:
                self.btn_start.setText("🛑 停止生成 (正在输出当前章)")
                self.btn_start.setStyleSheet(
                    "font-size: 15px; font-weight: bold; background-color: #F56C6C; color: white; border: none; padding: 12px; border-radius: 6px;")
            else:
                self.btn_start.setText("🛑 停止后台生成 (其他章正在码字)")
                self.btn_start.setStyleSheet(
                    "font-size: 15px; font-weight: bold; background-color: #E6A23C; color: white; border: none; padding: 12px; border-radius: 6px;")
        elif is_auto_piloting:
            # 【重要】确保挂机时单章生成按钮依然是禁用状态
            self.btn_start.setEnabled(False)
            self.btn_start.setText("🤖 挂机模式进行中...")
            self.btn_start.setStyleSheet(
                "font-size: 16px; font-weight: bold; background-color: #A0CFFF; color: white; border: none; padding: 12px; border-radius: 6px;")
        else:
            if self.current_chap_index != -1:
                self.btn_start.setText("🚀 根据设定撰写本章")
                self.btn_start.setEnabled(True)
                self.btn_start.setStyleSheet(
                    "font-size: 16px; font-weight: bold; background-color: #67C23A; color: white; border: none; padding: 12px; border-radius: 6px;")
            else:
                self.btn_start.setText("🚀 根据设定撰写本章")
                self.btn_start.setEnabled(False)
                self.btn_start.setStyleSheet(
                    "font-size: 16px; font-weight: bold; background-color: #A0CFFF; color: white; border: none; padding: 12px; border-radius: 6px;")

        # ====== 纠错按钮状态更新 ====== (保留下半部分的这一行，不做修改)
        has_chap_selected = (self.current_chap_index != -1)
        is_correcting = getattr(self, 'is_correcting', False)

        if is_correcting:
            # 纠错进行中：把全文纠错按钮魔改成红色的“停止”按钮
            self.btn_full_correct.setEnabled(True)
            self.btn_full_correct.setText("🛑 停止纠错")
            self.btn_full_correct.setMenu(None)  # 摘掉下拉菜单，变成普通可点击按钮
            self.btn_full_correct.setStyleSheet(
                "background-color: #F56C6C; border: 1px solid #DCDFE6; font-weight:bold; color: white; padding: 5px;"
            )
            # 绑定停止事件（先静默解绑以防重复绑定）
            try:
                self.btn_full_correct.clicked.disconnect()
            except Exception:
                pass
            self.btn_full_correct.clicked.connect(self.cancel_correction)

            # 把另一个纠错按钮彻底锁死
            self.btn_chap_correct.setEnabled(False)
            self.btn_chap_correct.setText("🔧 纠错运行中...")
        else:
            # 恢复正常：把菜单装回去，改回原来的颜色
            self.btn_full_correct.setEnabled(True)
            self.btn_full_correct.setText("🩺 全文一键纠错")
            self.btn_full_correct.setMenu(self.full_correct_menu)
            self.btn_full_correct.setStyleSheet(
                "background-color: transparent; border: 1px solid #DCDFE6; font-weight:bold; color: #F56C6C; padding: 5px;"
            )
            # 解除点击事件的绑定，恢复菜单展开默认行为
            try:
                self.btn_full_correct.clicked.disconnect()
            except Exception:
                pass

            self.btn_chap_correct.setEnabled(has_chap_selected)
            self.btn_chap_correct.setText("🔧 章节一键纠错")
            self.btn_chap_correct.setMenu(self.chap_correct_menu)
            self.btn_chap_correct.setStyleSheet(
                "font-size: 14px; font-weight: bold; background-color: #E6A23C; color: white; border: none; padding: 10px; border-radius: 6px;"
            )

    def start_correction(self, scope, mode):
        api_key = self.settings.value("api_key", "")
        if not api_key:
            QMessageBox.warning(self, "错误", "缺少 API Key！")
            return

        if scope == "chapter" and (self.current_vol_index == -1 or self.current_chap_index == -1):
            QMessageBox.warning(self, "错误", "请先在左侧选择要纠错的章节！")
            return

        warning_msg = "全文纠错将扫描全书摘要，可能消耗大量 Token 且耗时较长，请耐心等待。确认开始吗？" if scope == "full" else "即将使用 AI 检查并修改当前章节原文，确认开始吗？"
        if QMessageBox.question(self, '启动纠错', warning_msg) != QMessageBox.StandardButton.Yes:
            return

        self.save_all()  # 强制保存当前最新状态
        self.is_correcting = True
        self.update_ui_state()

        # 自动展开并清空侧边栏准备记录
        self.btn_toggle_log.setChecked(True)
        self.toggle_log_sidebar(True)
        self.log_list.addItem(f"=== 开始新的纠错任务 ({'全书' if scope == 'full' else '单章'}) ===")
        self.log_list.scrollToBottom()

        base_url = self.settings.value("base_url", "https://api.deepseek.com")
        model = self.settings.value("model", "deepseek-reasoner")
        temp = float(self.settings.value("temperature", 0.7))

        self.correct_worker = CorrectionWorker(api_key, base_url, model, temp, self.project, scope, mode)
        if scope == "chapter":
            self.correct_worker.set_target(self.current_vol_index, self.current_chap_index)

        self.correct_worker.status_signal.connect(lambda msg: self.statusBar().showMessage(msg))
        self.correct_worker.log_signal.connect(self.append_correction_log)
        self.correct_worker.update_text_signal.connect(self.apply_corrected_text)
        self.correct_worker.finished_signal.connect(self.correction_finished)
        self.correct_worker.error_signal.connect(self.handle_error)

        # ====== 【新增】连接思考过程信号，并在启动时清空且展开思考面板 ======
        self.correct_worker.reasoning_signal.connect(self.append_thinking)
        self.thinking_output.clear()
        if not self.thinking_output.isVisible():
            self.toggle_thinking()

        self.correct_worker.start()

    def append_correction_log(self, log_msg):
        self.log_list.addItem(log_msg)
        self.log_list.scrollToBottom()

    def apply_corrected_text(self, v_idx, c_idx, new_content, new_summary):
        vol_name = self.project.meta["volumes"][v_idx]["name"]
        chap = self.project.meta["volumes"][v_idx]["chapters"][c_idx]
        chap_name = chap["name"]

        # 后台落盘
        self.project.save_chapter_content(vol_name, chap_name, new_content)
        if new_summary and new_summary != chap.get("ai_synopsis", ""):
            chap["ai_synopsis"] = new_summary
            self.project.save_meta()

        # 如果当前 UI 正好停留在被修改的这一章，实时刷新文本框
        if self.current_vol_index == v_idx and self.current_chap_index == c_idx:
            self.content_output.setText(new_content)
            self.statusBar().showMessage(f"✨ 当前章节 [{chap_name}] 纠错并刷新完毕！", 3000)

    def correction_finished(self):
        self.is_correcting = False
        self.update_ui_state()  # 这一步会让按钮从“停止”重新变回“一键纠错”

        # 判断是被手动停止的还是自然跑完的
        if hasattr(self, 'correct_worker') and self.correct_worker._is_cancelled:
            self.statusBar().showMessage("🛑 纠错任务已手动终止！", 3000)
            self.log_list.addItem("=== 纠错已手动终止 ===")
        else:
            self.statusBar().showMessage("✅ 纠错任务全部完成！", 3000)
            self.log_list.addItem("=== 纠错任务结束 ===")

        self.log_list.scrollToBottom()

    # --- 目录树逻辑 ---
    def refresh_tree(self):
        self.tree.clear()
        root = QTreeWidgetItem(self.tree, [self.project.meta["title"]])
        root.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon))
        root.setData(0, Qt.ItemDataRole.UserRole, {"type": "root"})

        for v_idx, vol in enumerate(self.project.meta["volumes"]):
            v_node = QTreeWidgetItem(root, [vol["name"]])
            v_node.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_FileDialogDetailedView))
            v_node.setData(0, Qt.ItemDataRole.UserRole, {"type": "volume", "v_idx": v_idx})

            for c_idx, chap in enumerate(vol["chapters"]):
                c_node = QTreeWidgetItem(v_node, [chap["name"]])
                c_node.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_FileIcon))
                c_node.setData(0, Qt.ItemDataRole.UserRole, {"type": "chapter", "v_idx": v_idx, "c_idx": c_idx})
        self.tree.expandAll()

    def show_context_menu(self, position):
        item = self.tree.itemAt(position)
        menu = QMenu()
        menu.setStyleSheet(
            "QMenu { background-color: white; border: 1px solid #DCDFE6; } QMenu::item:selected { background-color: #ECF5FF; color: #409EFF; }")

        if not item or item.data(0, Qt.ItemDataRole.UserRole)["type"] == "root":
            action_add_vol = menu.addAction("📁 新建卷")
            action_add_vol.triggered.connect(self.ui_add_volume)
        elif item.data(0, Qt.ItemDataRole.UserRole)["type"] == "volume":
            action_add_chap = menu.addAction("📄 在此卷下新建章")
            v_idx = item.data(0, Qt.ItemDataRole.UserRole)["v_idx"]
            action_add_chap.triggered.connect(lambda: self.ui_add_chapter(v_idx))
            # 【新增】卷的修改与删除
            action_rename = menu.addAction("✏️ 重命名卷")
            action_rename.triggered.connect(lambda: self.ui_rename_item(item))
            action_delete = menu.addAction("🗑️ 删除卷")
            action_delete.triggered.connect(lambda: self.ui_delete_item(item))

        elif item.data(0, Qt.ItemDataRole.UserRole)["type"] == "chapter":
            # 【新增】章的修改与删除
            action_rename = menu.addAction("✏️ 重命名章")
            action_rename.triggered.connect(lambda: self.ui_rename_item(item))
            action_delete = menu.addAction("🗑️ 删除章")
            action_delete.triggered.connect(lambda: self.ui_delete_item(item))

        menu.exec(self.tree.viewport().mapToGlobal(position))

    def ui_add_volume(self):
        text, ok = QInputDialog.getText(self, "新建卷", "请输入卷名:")
        if ok and text:
            self.project.add_volume(text)
            self.refresh_tree()

    def ui_add_chapter(self, v_idx):
        text, ok = QInputDialog.getText(self, "新建章", "请输入章名:")
        if ok and text:
            self.project.add_chapter(v_idx, text)
            self.refresh_tree()

    def ui_rename_item(self, item):
        if not item: return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data["type"] == "root": return

        old_name = item.text(0)
        item_type = "卷" if data["type"] == "volume" else "章"

        new_name, ok = QInputDialog.getText(self, f"重命名{item_type}", f"请输入新的{item_type}名:", text=old_name)
        if ok and new_name and new_name.strip() != old_name:
            new_name = new_name.strip()
            # 执行数据重命名
            if data["type"] == "volume":
                self.project.rename_volume(data["v_idx"], new_name)
            elif data["type"] == "chapter":
                self.project.rename_chapter(data["v_idx"], data["c_idx"], new_name)

            # 刷新树与右侧标题显示
            self.refresh_tree()
            if data["type"] == "volume" and self.current_vol_index == data["v_idx"]:
                self.lbl_vol_title.setText(f"<b>当前卷: {new_name}</b>")
            elif data["type"] == "chapter" and self.current_vol_index == data["v_idx"] and self.current_chap_index == \
                    data["c_idx"]:
                vol_name = self.project.meta["volumes"][data["v_idx"]]["name"]
                self.lbl_chap_title.setText(f"<b>当前章: {vol_name} - {new_name}</b>")

    def ui_delete_item(self, item):
        if not item: return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data["type"] == "root": return

        if self.is_generating:
            if (data["type"] == "volume" and data["v_idx"] == self.gen_v_idx) or \
                    (data["type"] == "chapter" and data["v_idx"] == self.gen_v_idx and data["c_idx"] == self.gen_c_idx):
                QMessageBox.warning(self, "操作受限", "该卷/章正在后台疯狂码字中，请先停止生成后再尝试删除！")
                return

        item_type = "卷" if data["type"] == "volume" else "章"
        item_name = item.text(0)

        # 读取用户是否开启了“删除前确认”设置
        needs_confirm = self.settings.value("confirm_delete", True, type=bool)

        if needs_confirm:
            msgBox = QMessageBox(self)
            msgBox.setWindowTitle("确认删除")
            msgBox.setText(f"确定要删除{item_type}【{item_name}】吗？\n删除操作同时会移除本地文件，且不可恢复！")
            msgBox.setIcon(QMessageBox.Icon.Warning)
            msgBox.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msgBox.setDefaultButton(QMessageBox.StandardButton.No)

            # 植入“不再提醒”的 CheckBox
            cb = QCheckBox("以后不再提醒")
            msgBox.setCheckBox(cb)

            if msgBox.exec() != QMessageBox.StandardButton.Yes:
                return  # 用户取消了删除

            # 如果勾选了不再提醒，更新全局设置
            if cb.isChecked():
                self.settings.setValue("confirm_delete", False)

        # 执行删除
        if data["type"] == "volume":
            self.project.delete_volume(data["v_idx"])
        elif data["type"] == "chapter":
            self.project.delete_chapter(data["v_idx"], data["c_idx"])

        # 删除后，重置右侧编辑面板回到全局设定页
        self.stacked_widget.setCurrentIndex(0)
        self.current_vol_index = -1
        self.current_chap_index = -1
        self.update_ui_state()
        self.refresh_tree()

    def on_tree_select(self, item):
        # 【新增】在切换目录之前，先静默保存当前选中的卷/章信息，防止内容丢失
        self.save_all(silent=True)

        data = item.data(0, Qt.ItemDataRole.UserRole)
        self.current_vol_index = -1
        self.current_chap_index = -1

        if data["type"] == "root":
            self.stacked_widget.setCurrentIndex(0)

        elif data["type"] == "volume":
            v_idx = data["v_idx"]
            self.current_vol_index = v_idx
            vol_data = self.project.meta["volumes"][v_idx]
            self.lbl_vol_title.setText(f"<b>当前卷: {vol_data['name']}</b>")
            self.vol_synopsis_input.setText(vol_data.get("synopsis", ""))
            self.stacked_widget.setCurrentIndex(1)

        elif data["type"] == "chapter":
            v_idx = data["v_idx"]
            c_idx = data["c_idx"]
            self.current_vol_index = v_idx
            self.current_chap_index = c_idx

            vol_data = self.project.meta["volumes"][v_idx]
            chap_data = vol_data["chapters"][c_idx]

            self.lbl_chap_title.setText(f"<b>当前章: {vol_data['name']} - {chap_data['name']}</b>")
            self.chap_synopsis_input.setText(chap_data.get("synopsis", ""))
            self.stacked_widget.setCurrentIndex(2)

            # 【关键修复】：增加对挂机状态 is_auto_piloting 的判断，否则挂机时会被当作普通查看，导致思考过程被 clear()
            is_active_gen = getattr(self, 'is_generating', False) or getattr(self, 'is_auto_piloting', False)

            if is_active_gen and getattr(self, 'gen_v_idx', -1) == v_idx and getattr(self, 'gen_c_idx', -1) == c_idx:
                # 如果切回了正在生成的章，展示内存中的实时流
                self.content_output.setText(self.gen_content_buffer)
                self.thinking_output.setText(self.gen_reasoning_buffer)
                # 滚动条移到最底端
                self.content_output.moveCursor(self.content_output.textCursor().MoveOperation.End)
                self.thinking_output.moveCursor(self.thinking_output.textCursor().MoveOperation.End)
            else:
                # 查看其他章节，读取本地记录
                content = self.project.read_chapter_content(vol_data["name"], chap_data["name"])
                self.content_output.setText(content)
                self.thinking_output.clear()
        self.update_ui_state()

    def return_to_home(self):
        reply = QMessageBox.question(self, '返回首页', '确定要退出当前项目并返回首页吗？\n(系统将自动保存当前进度)',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.save_all()  # 自动保存当前数据
            self.switch_project = True  # 设置标志位为 True
            self.close()  # 关闭当前主窗口

    # --- 数据保存逻辑 ---
    def save_global_meta(self, silent=False):
        self.project.meta["global_synopsis"] = self.story_synopsis_input.toPlainText().strip()
        chars = []
        for w in self.character_widgets:
            d = w.get_data()
            if any(d.values()):
                chars.append(d)
        self.project.meta["characters"] = chars
        self.project.save_meta()
        if not silent:
            QMessageBox.information(self, "提示", "全局设定保存成功！")

    def save_vol_meta(self, silent=False):
        if self.current_vol_index != -1:
            self.project.meta["volumes"][self.current_vol_index][
                "synopsis"] = self.vol_synopsis_input.toPlainText().strip()
            self.project.save_meta()
            if not silent:
                QMessageBox.information(self, "提示", "当前卷设定保存成功！")

    def save_chap_meta(self, silent=False):
        if self.current_chap_index != -1:
            self.project.meta["volumes"][self.current_vol_index]["chapters"][self.current_chap_index][
                "synopsis"] = self.chap_synopsis_input.toPlainText().strip()
            self.project.save_meta()
            if not silent:
                QMessageBox.information(self, "提示", "当前章设定保存成功！")

    def save_all(self, silent=True):
        # 1. 如果在全局页，保存全局；如果在卷页，保存卷；如果在章页，保存章梗概和正文
        idx = self.stacked_widget.currentIndex()
        if idx == 0:
            self.save_global_meta(silent=silent)
        elif idx == 1:
            self.save_vol_meta(silent=silent)
        elif idx == 2:
            self.save_chap_meta(silent=silent)
            # 保存 docx 正文
            if self.current_vol_index != -1 and self.current_chap_index != -1:
                vol_name = self.project.meta["volumes"][self.current_vol_index]["name"]
                chap_name = self.project.meta["volumes"][self.current_vol_index]["chapters"][self.current_chap_index][
                    "name"]
                self.project.save_chapter_content(vol_name, chap_name, self.content_output.toPlainText())

        # 无论是快捷键还是切换章节触发，都在底部状态栏提供无感提示
        self.statusBar().showMessage("✅ 小说正文及设定已自动保存！", 3000)

    def export_book(self):
        # 1. 强制保存当前最新进度
        self.save_all()

        # 2. 弹出保存文件对话框
        file_path, filter_type = QFileDialog.getSaveFileName(
            self,
            "一键成书 - 选择导出位置",
            f"{self.project.meta['title']}.docx",
            "Word 文档 (*.docx);;Markdown 文档 (*.md);;纯文本 (*.txt);;PDF 文档 (*.pdf)"
        )

        if not file_path:
            return

        # 3. 根据后缀名调用相应的导出方法
        try:
            ext = os.path.splitext(file_path)[1].lower()
            title = self.project.meta['title']

            if ext == '.docx':
                self._export_docx(file_path, title)
            elif ext == '.md':
                self._export_md(file_path, title)
            elif ext == '.txt':
                self._export_txt(file_path, title)
            elif ext == '.pdf':
                self._export_pdf(file_path, title)

            QMessageBox.information(self, "导出成功", f"恭喜！小说已成功导出至：\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出过程中发生错误：\n{str(e)}")

    def _export_docx(self, file_path, title):
        doc = docx.Document()
        doc.add_heading(title, 0)  # 书名作为主标题

        for vol in self.project.meta["volumes"]:
            doc.add_heading(vol["name"], level=1)  # 卷名作为一级标题
            for chap in vol["chapters"]:
                doc.add_heading(chap["name"], level=2)  # 章名作为二级标题
                content = self.project.read_chapter_content(vol["name"], chap["name"])
                for line in content.split('\n'):
                    if line.strip():
                        doc.add_paragraph(line.strip())
        doc.save(file_path)

    def _export_txt(self, file_path, title):
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"《{title}》\n\n")
            for vol in self.project.meta["volumes"]:
                f.write(f"【{vol['name']}】\n\n")
                for chap in vol["chapters"]:
                    f.write(f"  {chap['name']}\n\n")
                    content = self.project.read_chapter_content(vol["name"], chap["name"])
                    f.write(f"{content}\n\n")

    def _export_md(self, file_path, title):
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"# {title}\n\n")
            for vol in self.project.meta["volumes"]:
                f.write(f"## {vol['name']}\n\n")
                for chap in vol["chapters"]:
                    f.write(f"### {chap['name']}\n\n")
                    content = self.project.read_chapter_content(vol["name"], chap["name"])
                    f.write(f"{content}\n\n")

    def _export_pdf(self, file_path, title):
        # PDF 导出利用 PyQt6 自带的富文本转换为 HTML 再渲染打印的机制
        html_content = f"<h1 style='text-align: center;'>{title}</h1>"
        for vol in self.project.meta["volumes"]:
            html_content += f"<h2 style='color: #2C3E50;'>{vol['name']}</h2>"
            for chap in vol["chapters"]:
                html_content += f"<h3>{chap['name']}</h3>"
                content = self.project.read_chapter_content(vol["name"], chap["name"])
                for line in content.split('\n'):
                    if line.strip():
                        html_content += f"<p style='text-indent: 2em; line-height: 1.5;'>{line.strip()}</p>"

        document = QTextDocument()
        document.setHtml(html_content)

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(file_path)

        # 渲染生成 PDF
        document.print(printer)
    # --- 核心大模型生成逻辑 (包含复杂的上下文组装) ---
    def build_prompts(self):
        meta = self.project.meta

        # 1. 组装全局设定
        global_story = meta.get("global_synopsis", "未提供。")
        char_texts = [f"【{c['name']}】 性别:{c['gender']} 性格:{c['personality']} 经历:{c['experience']}" for c in
                      meta.get("characters", [])]
        char_setting = "\n".join(char_texts) if char_texts else "未提供明确人物。"

        system_prompt = f"""你是一位经验丰富的网文大神作家。请根据全局设定和上下文连贯地撰写小说正文。

    【全局故事大纲】
    {global_story}

    【核心人物设定】
    {char_setting}

    【写作要求】
    1. 严格遵循世界观、人设和剧情逻辑。
    2. 动作、神态、心理描写生动，符合网文爽感节奏。
    3. 直接输出正文，禁止任何解释性废话和多余的寒暄。
    4. 【重要】在正文输出完毕后，必须另起一行并严格以 `[AI_SUMMARY]` 作为分割符，然后输出约300字的本章详细梗概（必须包含具体发生的情节、人物发展、新出现的物品/人物以及埋下的伏笔）。此部分仅用于系统内部记录。"""

        # 2. 组装历史上下文与上一章内容
        past_context = ""
        prev_chapter_content = ""

        v_idx = self.current_vol_index
        c_idx = self.current_chap_index

        prev_v_idx, prev_c_idx = -1, -1
        if c_idx > 0:
            prev_v_idx, prev_c_idx = v_idx, c_idx - 1
        elif v_idx > 0:
            for i in range(v_idx - 1, -1, -1):
                if len(meta["volumes"][i]["chapters"]) > 0:
                    prev_v_idx = i
                    prev_c_idx = len(meta["volumes"][i]["chapters"]) - 1
                    break

        if prev_v_idx != -1 and prev_c_idx != -1:
            pv_name = meta["volumes"][prev_v_idx]["name"]
            pc_name = meta["volumes"][prev_v_idx]["chapters"][prev_c_idx]["name"]
            prev_chapter_content = self.project.read_chapter_content(pv_name, pc_name)
            if len(prev_chapter_content) > 1500:
                prev_chapter_content = "...(前文省略)...\n" + prev_chapter_content[-1500:]

        # 【修改处】提取过往所有梗概时，优先使用 ai_synopsis
        history_str = ""
        for i in range(v_idx + 1):
            vol = meta["volumes"][i]
            history_str += f"\n> {vol['name']} (梗概: {vol.get('synopsis', '无')})\n"

            chap_limit = c_idx if i == v_idx else len(vol["chapters"])
            for j in range(chap_limit):
                chap = vol["chapters"][j]

                # 优先读取 AI 之前生成的梗概，如果没有则降级读取用户的细纲
                ai_syn = chap.get("ai_synopsis", "")
                user_syn = chap.get("synopsis", "无")
                display_syn = ai_syn if ai_syn.strip() else user_syn

                history_str += f"  - {chap['name']}: {display_syn}\n"

        if len(history_str) > 15000:
            history_str = "【注意：因前文过长，此处仅提供过往卷梗概】\n"
            for i in range(v_idx + 1):
                vol = meta["volumes"][i]
                history_str += f"\n> {vol['name']} (梗概: {vol.get('synopsis', '无')})\n"

        if not history_str.strip():
            history_str = "本书刚刚开篇，无过往历史。"

        curr_vol = meta["volumes"][v_idx]
        curr_chap = curr_vol["chapters"][c_idx]

        user_prompt = f"""请为我撰写最新章节的正文。

【过往剧情轨迹参考】
{history_str.strip()}

"""
        if prev_chapter_content.strip():
            user_prompt += f"【紧接上一章的末尾内容】(请保证剧情和对话的连贯过渡)\n{prev_chapter_content.strip()}\n\n"

        user_prompt += f"""【本次写作任务】
当前所处卷：{curr_vol['name']}
本卷核心梗概：{curr_vol.get('synopsis', '无')}

当前需撰写章节：{curr_chap['name']}
本章细纲要求：{curr_chap.get('synopsis', '无')}

【行动指令】
请根据本章细纲要求，顺着上一章的情节展开，扩写为文笔流畅的完整正文！
【重要】在正文输出完毕后，必须另起一行并严格以 `[AI_SUMMARY]` 作为分割符，然后输出约300字高度结构化的【本章复盘与记忆锚点】
    在 `[AI_SUMMARY]` 之后，必须严格按照以下3个维度输出（客观、精炼，纯作内部记忆使用）：
    1. 核心剧情脉络：按时间顺序简述本章发生的实质性事件（起因、经过、结果）。
    2. 人物状态更新：记录本章主角及配角的行为及心态。
    3. 物品设定更新：记录本章所有物品状态

"""

        return system_prompt, user_prompt

    def start_generation(self):
        if getattr(self, 'is_generating', False):
            if hasattr(self, 'worker') and self.worker.isRunning():
                self.worker.cancel()
            self.btn_start.setText("🛑 正在停止...")
            self.btn_start.setEnabled(False)
            return
        api_key = self.settings.value("api_key", "")
        if not api_key:
            QMessageBox.warning(self, "错误", "缺少 API Key，请点击上方【⚙️ 设置模型参数】按钮进行配置！")
            self.open_settings()
            return

        # 生成前强制保存当前的梗概设定，以免提示词没用到最新内容
        self.save_all()
        system_prompt, user_prompt = self.build_prompts()

        # === 设置后台生成的环境和缓冲区 ===
        self.is_generating = True
        self.gen_v_idx = self.current_vol_index
        self.gen_c_idx = self.current_chap_index
        self.gen_content_buffer = ""
        self.gen_reasoning_buffer = ""

        self.content_output.clear()
        self.thinking_output.clear()

        self.hit_summary_delimiter = False
        self.content_output.clear()
        self.thinking_output.clear()
        # 刷新界面状态 (树状图不锁定，仅锁定正文输入框，按钮变红)
        self.update_ui_state()

        base_url = self.settings.value("base_url", "https://api.deepseek.com")
        model = self.settings.value("model", "deepseek-reasoner")
        temperature = float(self.settings.value("temperature", 1.5))
        max_tokens = int(self.settings.value("max_tokens", 6000))

        self.worker = AIWorker(api_key, base_url, model, temperature, max_tokens, system_prompt, user_prompt)
        self.worker.reasoning_signal.connect(self.append_thinking)
        self.worker.content_signal.connect(self.append_content)
        self.worker.error_signal.connect(self.handle_error)
        self.worker.finished_signal.connect(self.generation_finished)
        self.worker.start()

    def append_thinking(self, text):
        self.gen_reasoning_buffer += text  # 永远写进后台缓冲区
        # 只有当用户正停留在该章时，才实时渲染在屏幕上
        if self.current_vol_index == self.gen_v_idx and self.current_chap_index == self.gen_c_idx:
            self.thinking_output.insertPlainText(text)
            self.thinking_output.ensureCursorVisible()

    def append_content(self, text):
        # [cite_start]【关键修复】：实时将 AI 吐出的文字拼接到后台缓冲区中 [cite: 196]
        self.gen_content_buffer += text

        if "[AI_SUMMARY]" in self.gen_content_buffer:
            if not getattr(self, 'hit_summary_delimiter', False):
                self.hit_summary_delimiter = True
                # 触发分割符时，将正文的最后一部分清理干净渲染到UI上，之后停止更新UI的正文部分
                if self.current_vol_index == self.gen_v_idx and self.current_chap_index == self.gen_c_idx:
                    main_content = self.gen_content_buffer.split("[AI_SUMMARY]")[0].strip()
                    self.content_output.setPlainText(main_content)
                    self.content_output.moveCursor(self.content_output.textCursor().MoveOperation.End)
        else:
            # 正常渲染正文
            if self.current_vol_index == self.gen_v_idx and self.current_chap_index == self.gen_c_idx:
                # 【核心修复】：先强制将光标移动到文本最末尾，再插入文本。防止鼠标乱点导致文字插错位置！
                cursor = self.content_output.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                self.content_output.setTextCursor(cursor)

                # 在末尾插入最新文本流
                self.content_output.insertPlainText(text)
                self.content_output.ensureCursorVisible()

    def handle_error(self, err_msg):
        QMessageBox.critical(self, "生成错误", f"请求发生异常：\n{err_msg}")
        # 【修改处】根据当前的模式，调用对应的结束/重置方法
        if getattr(self, 'is_auto_piloting', False):
            self.auto_pilot_finished()
        else:
            self.generation_finished()

    def generation_finished(self):
        if self.gen_v_idx != -1 and self.gen_c_idx != -1:
            vol_name = self.project.meta["volumes"][self.gen_v_idx]["name"]
            chap_data = self.project.meta["volumes"][self.gen_v_idx]["chapters"][self.gen_c_idx]
            chap_name = chap_data["name"]

            # 【核心修改】将缓冲区的内容根据标识符一分为二
            parts = self.gen_content_buffer.split("[AI_SUMMARY]")
            main_content = parts[0].strip()
            ai_summary = parts[1].strip() if len(parts) > 1 else ""

            # 1. 保存纯净的正文到 docx
            self.project.save_chapter_content(vol_name, chap_name, main_content)

            # 2. 如果成功生成了 AI 总结，将其隐式保存到 meta 并在后台落盘
            if ai_summary:
                chap_data["ai_synopsis"] = ai_summary
                self.project.save_meta()

            # 3. 如果用户还停留在这个章节，确保文本框里显示的是纯净的、没有尾巴的正文
            if self.current_vol_index == self.gen_v_idx and self.current_chap_index == self.gen_c_idx:
                self.content_output.setPlainText(main_content)

        # 清除后台生成标记
        self.is_generating = False
        self.gen_v_idx = -1
        self.gen_c_idx = -1

        # 刷新 UI 状态恢复原貌
        self.update_ui_state()
        self.statusBar().showMessage("✅ 章节正文生成完毕，AI内部线索梗概已入库！", 3000)

    #追加:自动挂机类函数
    def toggle_auto_pilot(self):
        if getattr(self, 'is_auto_piloting', False):
            # 停止挂机
            if hasattr(self, 'auto_worker') and self.auto_worker.isRunning():
                self.auto_worker.cancel()
                self.btn_auto_pilot.setText("🛑 正在停止挂机...")
                self.btn_auto_pilot.setEnabled(False)
            else:
                self.auto_pilot_finished()
            return

        # 开启挂机前检查
        api_key = self.settings.value("api_key", "")
        if not api_key:
            QMessageBox.warning(self, "错误", "缺少 API Key！")
            return

        reply = QMessageBox.question(self, '高能预警', '确定开启全自动挂机？\nAI将自动消耗大量Token补全所有设定和正文！',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes: return

        self.save_all()
        self.is_auto_piloting = True
        self.btn_auto_pilot.setText("🛑 停止自动挂机")
        self.btn_auto_pilot.setStyleSheet("background-color: #F56C6C; font-weight:bold; color: white;")

        # 禁用手动单章生成按钮
        self.btn_start.setEnabled(False)
        self.btn_start.setText("挂机模式进行中...")

        base_url = self.settings.value("base_url", "https://api.deepseek.com")
        model = self.settings.value("model", "deepseek-reasoner")  # 挂机推荐用强力模型
        temp = float(self.settings.value("temperature", 0.7))

        self.auto_worker = AutoPilotWorker(api_key, base_url, model, temp, self.project)

        # 信号对接：状态刷新
        self.auto_worker.status_signal.connect(lambda msg: self.statusBar().showMessage(msg))
        self.auto_worker.log_signal.connect(lambda msg: self.thinking_output.append(msg))

        # 信号对接：流式正文输出到当前界面（并拦截 [AI_SUMMARY] 详见你之前的代码逻辑）
        self.hit_summary_delimiter = False
        self.auto_worker.content_signal.connect(self.append_content)

        # 【新增】连接思考过程信号
        self.auto_worker.reasoning_signal.connect(self.append_thinking)

        # 【新增】连接切换章节信号 (必须用阻塞连接，确保UI切完再输出文字)
        self.auto_worker.start_chapter_signal.connect(self.auto_start_chapter,
                                                      Qt.ConnectionType.BlockingQueuedConnection)

        # 信号对接：后台数据结构修改
        self.auto_worker.add_volume_signal.connect(self.auto_add_volume, Qt.ConnectionType.BlockingQueuedConnection)
        self.auto_worker.add_chapter_signal.connect(self.auto_add_chapter, Qt.ConnectionType.BlockingQueuedConnection)
        self.auto_worker.save_content_signal.connect(self.auto_save_content, Qt.ConnectionType.BlockingQueuedConnection)

        self.auto_worker.update_chapter_signal.connect(self.auto_update_chapter,
                                                       Qt.ConnectionType.BlockingQueuedConnection)
        self.auto_worker.update_volume_signal.connect(self.auto_update_volume,
                                                      Qt.ConnectionType.BlockingQueuedConnection)

        self.auto_worker.finished_signal.connect(self.auto_pilot_finished)
        self.auto_worker.error_signal.connect(self.handle_error)

        # 【关键修复】：绝对不能在这里 clear() 文本框！
        # 否则稍后 auto_worker 切换章节时触发的 save_all 会把空文本框覆盖到前一章！
        self.auto_worker.start()

    def auto_update_volume(self, v_idx, synopsis):
        vol = self.project.meta["volumes"][v_idx]
        vol["synopsis"] = synopsis
        self.project.save_meta()

        # 如果当前 UI 正好停留在这一卷的设置界面，实时刷新文本框
        if self.current_vol_index == v_idx and self.stacked_widget.currentIndex() == 1:
            self.vol_synopsis_input.setText(synopsis)
    # --- 供 AutoPilotWorker 跨线程调用的 UI 和数据更新槽函数 ---
    def auto_update_chapter(self, v_idx, c_idx, ai_synopsis):
        chap = self.project.meta["volumes"][v_idx]["chapters"][c_idx]
        chap["ai_synopsis"] = ai_synopsis

        # 核心逻辑：如果用户原本就没有写 synopsis，那就把 AI 写的塞到台面上；
        # 如果用户写了，那就保留用户写的，AI 的扩写只放在隐式的 ai_synopsis 里供大模型看
        if not chap.get("synopsis", "").strip():
            chap["synopsis"] = ai_synopsis

        self.project.save_meta()

        # 如果当前 UI 正好停留在这一章，刷新一下文本框显示
        if self.current_vol_index == v_idx and self.current_chap_index == c_idx:
            self.chap_synopsis_input.setText(chap.get("synopsis", ""))

    def auto_add_volume(self, name, synopsis):
        self.project.add_volume(name, synopsis)
        self.refresh_tree()
        self.tree.scrollToBottom()

    def auto_add_chapter(self, v_idx, name, ai_synopsis):
        # 【修改处】将 ai_synopsis 同时也赋值给 synopsis 字段，这样就能在 UI 的“章设定”里看到了！
        self.project.add_chapter(v_idx, name, synopsis=ai_synopsis, ai_synopsis=ai_synopsis)
        self.refresh_tree()
        self.tree.scrollToBottom()

    def auto_start_chapter(self, v_idx, c_idx):
        self.gen_v_idx = v_idx
        self.gen_c_idx = c_idx
        self.gen_content_buffer = ""
        self.gen_reasoning_buffer = ""
        self.hit_summary_delimiter = False

        # 自动选中左侧树状图对应的章节节点
        root = self.tree.topLevelItem(0)
        if root and v_idx < root.childCount():
            v_node = root.child(v_idx)
            if c_idx < v_node.childCount():
                c_node = v_node.child(c_idx)
                # 选中树节点
                self.tree.setCurrentItem(c_node)
                # 触发点击事件，让右侧面板切换到该章的空白编辑状态
                self.on_tree_select(c_node)

    def auto_save_content(self, v_idx, c_idx, main_content, ai_summary):
        vol_name = self.project.meta["volumes"][v_idx]["name"]
        chap_name = self.project.meta["volumes"][v_idx]["chapters"][c_idx]["name"]

        # 保存本地 docx
        self.project.save_chapter_content(vol_name, chap_name, main_content)
        # 更新 meta 中的 AI 总结
        if ai_summary:
            self.project.meta["volumes"][v_idx]["chapters"][c_idx]["ai_synopsis"] = ai_summary
            self.project.save_meta()

        # 【关键修复】：取消这行 clear()，将清理工作交给 on_tree_select 去自然过渡
        self.hit_summary_delimiter = False

    def auto_pilot_finished(self):
        self.is_auto_piloting = False
        self.btn_auto_pilot.setText("🤖 开启自动挂机")
        self.btn_auto_pilot.setEnabled(True)
        self.btn_auto_pilot.setStyleSheet(
            "background-color: transparent; border: 1px solid #DCDFE6; font-weight:bold; color: #9C27B0;")
        self.update_ui_state()  # 恢复原有按钮状态

    def cancel_correction(self):
        """手动暂停/终止纠错任务"""
        if getattr(self, 'is_correcting', False):
            if hasattr(self, 'correct_worker') and self.correct_worker.isRunning():
                self.correct_worker.cancel()  # 触发 Worker 内的取消标记，并强行切断网络流
                self.log_list.addItem("⚠️ 接收到停止指令，正在等待当前请求安全中断...")
                self.log_list.scrollToBottom()
                self.statusBar().showMessage("🛑 正在停止纠错...", 3000)