"""Existing-folder takeover: explicit rules, immutable preview and confirmation."""
from pathlib import Path
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QSpinBox, QCheckBox, QStackedWidget, QWidget,
    QFrame, QTableView, QHeaderView, QFileDialog, QPlainTextEdit)
from application.takeover import TakeoverRules
from application.archive_folders import ArchiveFolders


class TakeoverModel(QAbstractTableModel):
    def __init__(self, parent):
        super().__init__(parent)
        self.plan, self.rows, self.selected = None, [], set()
        self.include_conflicts, self.only_conflicts = False, False

    def present(self, plan):
        self.beginResetModel()
        self.plan = plan
        self.rows = [item for item in plan.items if not self.only_conflicts or item.conflicts] if plan else []
        self.selected = {item.file.identity for item in plan.items if not item.conflicts or self.include_conflicts} if plan else set()
        self.endResetModel()

    def filter_conflicts(self, enabled):
        self.beginResetModel()
        self.only_conflicts = enabled
        self.rows = [item for item in self.plan.items if not enabled or item.conflicts] if self.plan else []
        self.endResetModel()

    def allow_conflicts(self, enabled):
        self.include_conflicts = enabled
        if self.plan:
            for item in self.plan.items:
                if item.conflicts:
                    if enabled:
                        self.selected.add(item.file.identity)
                    else:
                        self.selected.discard(item.file.identity)
        self.layoutChanged.emit()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 4

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return ('文件', '识别结果', '接管方式', '入口')[section]

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        item = self.rows[index.row()]
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 0 and (not item.conflicts or self.include_conflicts):
            flags |= Qt.ItemIsUserCheckable
        return flags

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self.rows[index.row()]
        if role == Qt.CheckStateRole and index.column() == 0:
            return Qt.Checked if item.file.identity in self.selected else Qt.Unchecked
        if role == Qt.ToolTipRole:
            return '\n'.join((*item.conflicts, *(path.path for path in item.file.paths)))
        if role == Qt.ForegroundRole and item.conflicts:
            return self.parent().palette().color(QPalette.PlaceholderText)
        if role == Qt.DisplayRole:
            markers = item.markers
            details = list(item.labels)
            if markers.score is not None:
                details.append(f'{markers.score} 分')
            if markers.favorite:
                details.append('★ 收藏')
            action = '冲突：仅入库' if item.conflicts and self.include_conflicts else '冲突：待确认' if item.conflicts else '保留现有标记' if item.kept_existing else '纳入库并导入标记' if details else '仅纳入库'
            return (Path(item.file.paths[0].path).name, '、'.join(details) or '无标记', action, str(len(item.file.paths)))[index.column()]

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.CheckStateRole or index.column() != 0 or not self.flags(index) & Qt.ItemIsUserCheckable:
            return False
        key = self.rows[index.row()].file.identity
        if value == Qt.Checked or value == Qt.Checked.value:
            self.selected.add(key)
        else:
            self.selected.discard(key)
        self.dataChanged.emit(index, index, [Qt.CheckStateRole])
        return True


class TakeoverDialog(QDialog):
    def __init__(self, parent, *, workflow, folders=ArchiveFolders(), show_library=lambda: None):
        super().__init__(parent)
        self.setPalette(parent.palette())
        self.workflow, self.show_library = workflow, show_library
        self.pending, self.closing, self.imported = False, False, False
        self.setWindowTitle('接管已有文件夹')
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModal)
        self.resize(1000, 640)
        self.setMinimumSize(780, 480)
        self.setMaximumHeight(max(480, parent.screen().availableGeometry().height() - 70))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title = QLabel('接管已有文件夹')
        title.setProperty('role', 'sectionTitle')
        layout.addWidget(title)
        hint = QLabel('选择目录与识别方式 → 扫描预览 → 确认接管')
        hint.setProperty('role', 'muted')
        layout.addWidget(hint)
        body = QHBoxLayout()
        body.setSpacing(18)
        self.configuration = QFrame()
        self.configuration.setFixedWidth(270)
        settings = QVBoxLayout(self.configuration)
        settings.setContentsMargins(0, 0, 0, 0)
        settings.addWidget(QLabel('已有文件夹'))
        self.path = QLineEdit()
        self.path.setObjectName('takeoverRoot')
        self.path.setPlaceholderText('选择或输入完整文件夹路径')
        settings.addWidget(self.path)
        choose = QPushButton('选择文件夹')
        choose.clicked.connect(self.choose_folder)
        settings.addWidget(choose)
        settings.addSpacing(8)
        settings.addWidget(QLabel('识别方式'))
        self.mode = QComboBox()
        self.mode.setObjectName('takeoverMode')
        for caption, value in (('仅纳入库', 'library'), ('按目录层级识别标签', 'tags'), ('识别 MoPlayer 分类目录', 'archive')):
            self.mode.addItem(caption, value)
        settings.addWidget(self.mode)
        self.rule_pages = QStackedWidget()
        plain = QLabel('将目录中的视频和图片纳入库。文件名与目录保持原样，不推断任何标记。')
        plain.setWordWrap(True)
        self.rule_pages.addWidget(plain)
        tag_page = QWidget()
        tags = QFormLayout(tag_page)
        tags.setContentsMargins(0, 4, 0, 0)
        self.first, self.last = QSpinBox(), QSpinBox()
        self.first.setRange(1, 99)
        self.last.setRange(0, 99)
        self.first.setValue(1)
        self.last.setSpecialValueText('最末层')
        for field in (self.first, self.last):
            field.setMinimumWidth(100)
        tags.addRow('开始层级', self.first)
        tags.addRow('结束层级', self.last)
        explanation = QLabel('从所选文件夹内部的第 1 层开始计算；连续层级作为父子标签，所选文件夹本身不作标签。')
        explanation.setWordWrap(True)
        tags.addRow(explanation)
        self.rule_pages.addWidget(tag_page)
        archive_page = QWidget()
        archive = QVBoxLayout(archive_page)
        archive.setContentsMargins(0, 4, 0, 0)
        self.favorite, self.score, self.tags = QCheckBox('收藏层'), QCheckBox('评分层'), QCheckBox('标签层')
        checks = QHBoxLayout()
        for field, checked in ((self.favorite, folders.favorite), (self.score, folders.score), (self.tags, folders.tags)):
            field.setChecked(checked)
            checks.addWidget(field)
        archive.addLayout(checks)
        self.order = QComboBox()
        self.order.addItem('收藏 → 评分 → 标签', True)
        self.order.addItem('评分 → 收藏 → 标签', False)
        self.order.setCurrentIndex(0 if folders.favorite_first else 1)
        archive.addWidget(self.order)
        self.example = QLabel()
        self.example.setWordWrap(True)
        archive.addWidget(self.example)
        self.rule_pages.addWidget(archive_page)
        settings.addWidget(self.rule_pages)
        settings.addStretch()
        safety = QLabel('接管只建立库记录和标记。\n本次不移动、不改名，也不执行归档。\n\n已有标记优先保留；首次入库日期记为本次接管时间，播放记录不作推断。')
        safety.setWordWrap(True)
        safety.setProperty('role', 'muted')
        settings.addWidget(safety)
        body.addWidget(self.configuration)
        preview = QVBoxLayout()
        self.summary = QLabel('先选择文件夹，再扫描预览。扫描不会改动文件或库记录。')
        self.summary.setWordWrap(True)
        preview.addWidget(self.summary)
        filters = QHBoxLayout()
        self.only_conflicts = QCheckBox('仅看冲突')
        filters.addWidget(self.only_conflicts)
        filters.addStretch()
        self.selection_count = QLabel('已选 0 项')
        filters.addWidget(self.selection_count)
        preview.addLayout(filters)
        self.model = TakeoverModel(self)
        self.table = QTableView()
        self.table.setObjectName('takeoverPreview')
        self.table.setModel(self.model)
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 175)
        self.table.setColumnWidth(2, 130)
        self.table.setColumnWidth(3, 42)
        preview.addWidget(self.table, 1)
        self.conflicts = QCheckBox('包含冲突项：只纳入库，保留原标记，不导入推断标记')
        preview.addWidget(self.conflicts)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(90)
        self.details.hide()
        preview.addWidget(self.details)
        body.addLayout(preview, 1)
        layout.addLayout(body, 1)
        self.status = QLabel('')
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        self.scan = QPushButton('扫描并预览')
        self.scan.setObjectName('takeoverScan')
        self.scan.clicked.connect(self.start_scan)
        footer.addWidget(self.scan)
        footer.addStretch()
        self.cancel = QPushButton('取消')
        self.cancel.clicked.connect(self.reject)
        footer.addWidget(self.cancel)
        self.confirm = QPushButton('确认接管')
        self.confirm.setObjectName('takeoverConfirm')
        self.confirm.setProperty('role', 'action')
        self.confirm.setEnabled(False)
        self.confirm.clicked.connect(self.submit)
        footer.addWidget(self.confirm)
        for field in (self.scan, self.cancel, self.confirm):
            field.setAutoDefault(False)
        layout.addLayout(footer)
        self.only_conflicts.toggled.connect(self.model.filter_conflicts)
        self.conflicts.toggled.connect(self.allow_conflicts)
        self.model.dataChanged.connect(self.update_selection)
        self.path.textChanged.connect(self.invalidate)
        self.mode.currentIndexChanged.connect(self.change_mode)
        self.first.valueChanged.connect(self.invalidate)
        self.last.valueChanged.connect(self.invalidate)
        for field in (self.favorite, self.score, self.tags):
            field.toggled.connect(self.invalidate)
        self.order.currentIndexChanged.connect(self.invalidate)
        self.change_mode()

    def rules(self):
        return TakeoverRules(self.mode.currentData(), self.first.value(), self.last.value(),
            ArchiveFolders(self.tags.isChecked(), self.score.isChecked(), self.favorite.isChecked(), self.order.currentData()))

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, '选择要接管的已有文件夹', self.path.text())
        if path:
            self.path.setText(path)

    def change_mode(self):
        self.rule_pages.setCurrentIndex(self.mode.currentIndex())
        self.invalidate()

    def invalidate(self):
        self.path.setToolTip(self.path.text())
        self.model.present(None)
        self.details.hide()
        self.summary.setText('设置已改变，请扫描预览。')
        self.status.clear()
        folders = ArchiveFolders(self.tags.isChecked(), self.score.isChecked(), self.favorite.isChecked(), self.order.currentData())
        self.example.setText('示例：' + ' / '.join((*folders.directories(8, True, [('风景', '山川')])[0], '文件.mp4')))
        self.update_selection()

    def update_selection(self):
        count = len(self.model.selected)
        self.selection_count.setText(f'已选 {count} 项')
        self.confirm.setEnabled(bool(count) and not self.pending)

    def allow_conflicts(self, enabled):
        self.model.allow_conflicts(enabled)
        self.update_selection()

    def start_scan(self):
        if self.pending:
            self.workflow.cancel()
            self.status.setText('正在停止扫描……')
            return
        try:
            rules = self.rules()
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.model.present(None)
        self.pending = True
        self.configuration.setEnabled(False)
        self.confirm.setEnabled(False)
        self.conflicts.setEnabled(False)
        self.scan.setText('停止扫描')
        self.status.setText('正在只读扫描文件与目录结构……')
        operation = self.workflow.preview(self.path.text().strip(), rules)
        def ready(outcome):
            self.pending = False
            self.configuration.setEnabled(True)
            self.conflicts.setEnabled(True)
            self.scan.setText('重新扫描')
            if self.closing:
                super(TakeoverDialog, self).reject()
                return
            if outcome.succeeded:
                plan = outcome.value
                self.model.present(plan)
                count = sum(bool(item.conflicts) for item in plan.items)
                paths = sum(len(item.file.paths) for item in plan.items)
                self.summary.setText(f'{len(plan.items)} 个文件 · {paths} 个入口 · {count} 项冲突\n同一文件的硬链接已合并；普通副本分别保留。')
                lines = list(plan.warnings)
                for item in plan.items:
                    if item.conflicts:
                        lines.append(Path(item.file.paths[0].path).name + '：' + '；'.join(item.conflicts))
                self.details.setPlainText('\n'.join(lines))
                self.details.setVisible(bool(lines))
                self.status.setText('预览已就绪。请核对识别结果，勾选要接管的文件后确认。')
            else:
                self.status.setText(str(outcome.error) if outcome.error else '扫描已取消，库记录未改变。')
            self.update_selection()
        operation.on_finished(ready)

    def submit(self):
        if self.imported:
            self.show_library()
            self.accept()
            return
        if self.pending or self.model.plan is None:
            return
        self.pending = True
        for field in (self.configuration, self.table, self.conflicts, self.scan, self.confirm, self.only_conflicts):
            field.setEnabled(False)
        self.status.setText('正在提交接管记录，请等待完成。文件保持原位。')
        operation = self.workflow.apply(self.model.plan, frozenset(self.model.selected), include_conflicts=self.conflicts.isChecked())
        def ready(outcome):
            self.pending = False
            if outcome.succeeded:
                self.imported = True
                self.status.setText(f'接管完成：已将 {len(outcome.value)} 个文件纳入库，所有本地文件保持原位。')
                self.scan.hide()
                self.confirm.setText('查看库')
                self.confirm.setEnabled(True)
                self.cancel.setText('关闭')
            else:
                prefix = '接管记录已保存，但界面刷新未完成：' if outcome.value else ''
                self.status.setText(prefix + str(outcome.error) if outcome.error else '接管未执行，请稍后重试。')
                for field in (self.configuration, self.table, self.conflicts, self.scan, self.only_conflicts):
                    field.setEnabled(True)
                self.update_selection()
        operation.on_finished(ready)

    def reject(self):
        if self.pending:
            if self.workflow.scanning is not None:
                self.closing = True
                self.workflow.cancel()
            return
        super().reject()

    def closeEvent(self, event):
        if self.pending:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
