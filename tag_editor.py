from copy import deepcopy  # 草稿不直接修改全局分类。
from PySide6.QtCore import Qt, QRect, QSize, QPoint, QMimeData, QTimer  # 实现胶囊换行、内部拖放与视口保持。
from PySide6.QtGui import QDrag  # 使用原生拖动手势归类标签。
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLayout, QWidget, QFrame, QScrollArea, QLabel, QLineEdit, QPushButton, QToolButton, QDialogButtonBox, QMenu, QInputDialog, QSizePolicy  # 构建参考图式的简洁标签卡片。
from core import natural, validate_tag, validate_layout, canonical_tags, tag_chain  # 共用任意层级的标签路径与循环校验。
from application.tag_labels import tag_label

MIME = 'application/x-moplayer-tag'  # 只接受本标签窗口内部的数据。

class FlowLayout(QLayout):  # 胶囊按可用宽度自动换行。
    def __init__(self, parent=None):  # 由对应标签区管理布局。
        super().__init__(parent)  # 初始化 Qt 布局。
        self.items = []  # 保持胶囊的自然排序。
        self.branches = {}
        self.setContentsMargins(0, 0, 0, 0)  # 胶囊区不增加多余边框。
        self.setSpacing(8)  # 横纵方向均保留适量间隔。

    def addItem(self, item):  # 接收普通控件布局项。
        self.items.append(item)  # 不创建额外列表模型。

    def add_branch(self, anchor, panel):
        self.addWidget(panel)
        self.branches[anchor] = self.items[-1]

    def count(self):  # 返回 Qt 所需项目数量。
        return len(self.items)  # 与胶囊控件一一对应。

    def itemAt(self, index):  # 供 Qt 查询有效布局项。
        return self.items[index] if 0 <= index < len(self.items) else None  # 无效索引返回空。

    def takeAt(self, index):  # 支持 Qt 正常移除项目。
        return self.items.pop(index) if 0 <= index < len(self.items) else None  # 不访问越界位置。

    def expandingDirections(self):  # 宽度由外层滚动区决定。
        return Qt.Orientation(0)  # 不强制扩展每个胶囊。

    def hasHeightForWidth(self):  # 换行后的高度依赖宽度。
        return True  # 让滚动区按实际行数计算高度。

    def heightForWidth(self, width):  # 先计算不改变位置的布局高度。
        return self.arrange(QRect(0, 0, width, 0), True)  # 使用与绘制相同的换行规则。

    def setGeometry(self, rect):  # 实际放置胶囊。
        super().setGeometry(rect)  # 保持 Qt 布局几何有效。
        self.arrange(rect, False)  # 宽度改变时重新换行。

    def sizeHint(self):  # 让父布局合理分配初始空间。
        return self.minimumSize()  # 不产生额外空白大面板。

    def minimumSize(self):  # 最小宽度只需容纳一个胶囊。
        size = QSize(0, 0)  # 空标签区可以收缩。
        for item in self.items:  # 使用每个胶囊的实际尺寸。
            if item in self.branches.values():
                continue
            size = size.expandedTo(item.minimumSize())  # 避免截断单个标签的点击区域。
        return size  # 换行高度另外计算。

    def arrange(self, rect, measure):  # 简单地从左到右排列并换行。
        width, rows, row, used = max(1, rect.width()), [], [], 0
        for item in self.items:
            if item in self.branches.values():
                continue
            size = QSize(min(width, item.sizeHint().width()), item.sizeHint().height())
            if row and used + self.spacing() + size.width() > width:
                rows.append(row)
                row, used = [], 0
            row.append((item, size))
            used += (self.spacing() if used else 0) + size.width()
        if row:
            rows.append(row)
        y = rect.y()
        for number, row in enumerate(rows):
            if number:
                y += self.spacing()
            x, height = rect.x(), max(size.height() for _, size in row)
            for item, size in row:
                if not measure:
                    item.setGeometry(QRect(QPoint(x, y), size))
                x += size.width() + self.spacing()
            y += height
            for item, _ in row:
                branch = self.branches.get(item.widget())
                if branch is None:
                    continue
                branch_height = branch.heightForWidth(width) if branch.hasHeightForWidth() else branch.sizeHint().height()
                y += self.spacing()
                if not measure:
                    branch.setGeometry(QRect(rect.x(), y, width, max(0, branch_height)))
                y += max(0, branch_height)
        return y - rect.y()

class TagChip(QPushButton):  # 本体统一选择，父标签箭头单独展开。
    def __init__(self, editor, name):  # 名称是全局标签身份。
        super().__init__()  # 外层布局管理控件生命周期。
        self.editor, self.name, self.start = editor, name, None  # 保存拖动起点与归类目标。
        row = editor.schema[name]  # 从当前草稿读取标签类型。
        self.parent_tag = bool(row.get('is_parent'))  # 普通根标签不再冒充父类。
        self.has_expand = self.parent_tag and not editor.search.text().strip()
        self.label = tag_label(name, editor.schema) if editor.search.text().strip() else name
        self.arrow = None
        self.setFixedHeight(34)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setCheckable(True)  # 蓝色状态表示该标签或其子类已被选择。
        self.setProperty('role', 'tagChip')
        self.setStyleSheet('QPushButton { border-radius:17px; padding:0 '+('28px' if self.has_expand else '0')+' 0 0; } QPushButton[implicitSelected="true"]:!checked { border-style:dashed; }')
        self.setCursor(Qt.PointingHandCursor)  # 明确可以点击。
        self.setAcceptDrops(self.parent_tag)  # 只有明确设定的父标签接收子类。
        self.setToolTip(name + '\n点击选择／取消；右键重命名／归类')
        self.clicked.connect(lambda checked=False: editor.activate(name))
        self.setContextMenuPolicy(Qt.CustomContextMenu)  # 类型修改统一从右键进入。
        self.customContextMenuRequested.connect(lambda point: editor.menu(name, self.mapToGlobal(point)))  # 菜单绑定当前标签。
        if self.has_expand:
            self.arrow = QToolButton(self)
            self.arrow.setObjectName('tagExpandArrow')
            self.arrow.setArrowType(Qt.DownArrow if name in editor.expanded else Qt.RightArrow)
            self.arrow.setFocusPolicy(Qt.StrongFocus)
            self.arrow.setAccessibleName(('收起' if name in editor.expanded else '展开') + name + '的子标签')
            self.arrow.setToolTip(self.arrow.accessibleName())
            self.arrow.clicked.connect(lambda checked=False: editor.toggle_expanded(name))
            self.arrow.setStyleSheet('QToolButton { border:0; border-left:1px solid palette(mid); border-radius:0; padding:0; background:transparent; }')
            self.arrow.setContextMenuPolicy(Qt.CustomContextMenu)
            self.arrow.customContextMenuRequested.connect(lambda point: editor.menu(name, self.arrow.mapToGlobal(point)))
        self.setText(self.label)

    def sizeHint(self):
        return QSize(min(350, self.fontMetrics().horizontalAdvance(self.label)) + 28 + (28 if self.has_expand else 0), 34)

    def minimumSizeHint(self):
        return QSize(0, 34)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.arrow is not None:
            self.arrow.setGeometry(max(0, self.width() - 29), 1, 28, self.height() - 2)
        self.setText(self.fontMetrics().elidedText(self.label, Qt.ElideMiddle, max(0, self.width() - 24 - (28 if self.has_expand else 0))))

    def mousePressEvent(self, event):  # 记录拖动前的真实点击位置。
        self.start = event.position().toPoint() if event.button() == Qt.LeftButton else None  # 右键不启动拖动。
        self.dragged = False  # 每次点击重新判断是否只是选择。
        super().mousePressEvent(event)  # 保留正常按钮按下反馈。

    def mouseMoveEvent(self, event):  # 普通标签可以直接拖入父标签，无需先选小类。
        if self.start is not None and event.buttons() & Qt.LeftButton and (event.position().toPoint() - self.start).manhattanLength() >= QApplication.startDragDistance():  # 父标签和普通标签都能拖动，仍区分点击手势。
            self.dragged, self.editor.dragging = True, True  # 拖动结束之前不重建源控件。
            mime = QMimeData()  # 使用独立内部标签格式。
            mime.setData(MIME, self.name.encode('utf-8'))  # 中文标签完整保留。
            drag = QDrag(self.editor)  # 以稳定的弹窗作为拖动来源。
            drag.setMimeData(mime)  # 目标只接受同一弹窗的数据。
            drag.setPixmap(self.grab())  # 拖动时显示实际标签胶囊。
            drag.exec(Qt.MoveAction, Qt.MoveAction)  # 不调用列表的源行清理逻辑。
            self.editor.dragging = False  # 可以安全刷新归类后的胶囊区。
            if self.editor.pending_refresh:  # 落下后再进行一次布局重建。
                self.editor.rebuild()  # 保留原展开集合和滚动位置。
            return  # 不将拖动继续视为普通点击。
        super().mouseMoveEvent(event)  # 其余移动保持原生反馈。

    def mouseReleaseEvent(self, event):  # 拖动结束不额外勾选或展开父类。
        if getattr(self, 'dragged', False):  # 本次已经完成拖动手势。
            self.setDown(False)  # 清除按下状态。
            event.accept()  # 不触发 clicked。
        else:  # 普通点击继续选择或展开。
            super().mouseReleaseEvent(event)  # 一次点击只执行一种动作。

    def dragEnterEvent(self, event):  # 父胶囊接收有效内部标签。
        self.editor.allow_drop(event, self.name)  # 悬停不展开父类。

    def dragMoveEvent(self, event):  # 持续拖动也不改变折叠状态。
        self.editor.allow_drop(event, self.name)  # 只更新可落下状态。

    def dropEvent(self, event):  # 落下后修改分类草稿。
        self.editor.drop_tag(event, self.name)  # 应用按钮确认后才迁移磁盘文件。

class ChildPanel(QFrame):  # 已由用户展开的子标签区域也可直接接收拖动。
    def __init__(self, editor, name):  # 明确对应一个父标签。
        super().__init__()  # 使用外层内容布局管理。
        self.editor, self.name = editor, name  # 落点归属于当前层的父标签。
        self.setAcceptDrops(True)  # 用户可把标签拖进展开后的空白区域。
        self.setObjectName('childPanel')  # 用轻量背景区别父子区域。

    def dragEnterEvent(self, event):  # 接受本弹窗的有效标签。
        self.editor.allow_drop(event, self.name)  # 不改变其他父类的展开状态。

    def dragMoveEvent(self, event):  # 区域悬停只作为落点。
        self.editor.allow_drop(event, self.name)  # 不主动打开任何父类。

    def dropEvent(self, event):  # 与父胶囊使用同一个归类入口。
        self.editor.drop_tag(event, self.name)  # 避免两套不同的分类行为。

class TagEditor(QDialog):  # 参考图式胶囊标签卡，父类只在主动点击后展示子类。
    def __init__(self, tags, schema, parent=None):  # 只编辑传入的标签草稿。
        super().__init__(parent)  # 打开期间不强制暂停视频。
        self.schema = deepcopy(schema)  # 只有应用后才修改全局分类。
        self._origins = {name: name for name in schema}
        self.selected = set(tags)  # 读取当前视频已有标签。
        for name in self.selected:  # 兼容尚未进入公共字典的旧标签。
            self.schema.setdefault(name, {'name': name, 'kind': 'major', 'parent': None, 'is_parent': False})  # 普通根标签可以直接点击选择。
        for row in list(self.schema.values()):  # 已有子类的标签自动视为父标签。
            if row.get('parent') in self.schema:  # 兼容上一版本的层级数据。
                self.schema[row['parent']]['is_parent'] = True  # 不丢失真实父子关系。
        self.managing, self.delete_selection = False, set()
        self.expanded, self.chips = set(), {}  # 初次打开不展开任何父标签。
        self.panels = {}
        self.dragging, self.pending_refresh, self.serial = False, False, 0  # 拖动结束后再安全更新布局。
        self.setWindowTitle('标签管理')  # 与参考图的标题一致。
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)  # 使用简洁白色圆角卡片。
        self.setAttribute(Qt.WA_TranslucentBackground)  # 圆角之外保持透明。
        self.resize(550, 380)  # 胶囊换行后保持紧凑可用。
        self.setMinimumSize(480, 280)  # 长标签仍有足够点击空间。
        root = QVBoxLayout(self)  # 卡片填满弹窗。
        root.setContentsMargins(0, 0, 0, 0)  # 不增加系统窗体边距。
        card = QFrame()  # 白色卡片承载全部操作。
        card.setObjectName('tagCard')  # 局部样式不影响播放器主窗口。
        root.addWidget(card)  # 保留透明圆角边缘。
        self.setStyleSheet('#tagCard { background:white; border:1px solid #dce2ea; border-radius:12px; } QLabel { color:#596476; background:transparent; border:none; } QPushButton { background:white; color:#536174; border:1px solid #dce3ec; border-radius:17px; padding:0px; } QPushButton:checked { background:#edf4ff; border-color:#91b3e4; color:#2e63ad; } QPushButton:hover { border-color:#8faed9; } QLineEdit { background:white; color:#536174; border:1px solid #dce2ea; border-radius:6px; padding:9px; } QScrollArea { background:transparent; border:none; } #childPanel { background:#f7f9fc; border:1px solid #e8edf4; border-radius:8px; }')  # 只保留细边框和轻量蓝色选择反馈。
        layout = QVBoxLayout(card)  # 标题、标签、输入与确认保持单列。
        layout.setContentsMargins(20, 18, 20, 16)  # 接近参考图的白色留白。
        header = QHBoxLayout()  # 搜索放在标题旁，避免单独占一行。
        self.title = title = QPushButton('标签管理')
        title.setCheckable(True)
        title.setAutoDefault(False)  # 不增加宣传文案。
        title.setStyleSheet('font-size:17px;')  # 标题清晰但不过分突出。
        header.addWidget(title)  # 标题靠左。
        self.delete_button = QPushButton('删除')
        self.delete_button.setAutoDefault(False)
        self.delete_button.hide()
        header.addWidget(self.delete_button)
        header.addStretch()  # 搜索靠右。
        self.search = QLineEdit()  # 保留快速查找大量标签的能力。
        self.search.setPlaceholderText('搜索标签')  # 搜索不改变选择或展开状态。
        self.search.setFixedWidth(160)  # 不挤占胶囊区域。
        header.addWidget(self.search)  # 顶部只保留一个辅助操作。
        layout.addLayout(header)  # 与主标签区分隔。
        self.scroll = QScrollArea()  # 多标签时只滚动胶囊区域。
        self.scroll.setWidgetResizable(True)  # 宽度变化时自动换行。
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 不产生横向滚动条。
        layout.addWidget(self.scroll, 1)  # 标签区占主要空间。
        add_row = QHBoxLayout()  # 与参考图一致的新标签输入加号。
        self.entry, self.add_button = QLineEdit(), QPushButton('+')  # 不再显示类型下拉框。
        self.entry.setPlaceholderText('新标签')  # 简短明确的输入提示。
        self.add_button.setFixedSize(36, 36)  # 加号使用足够大的点击目标。
        self.add_button.setStyleSheet('border:none; font-size:24px; color:#788395;')  # 加号保持轻量外观。
        self.add_button.setToolTip('新增标签')  # 鼠标悬停说明动作。
        add_row.addWidget(self.entry, 1)  # 输入框尽量宽。
        add_row.addWidget(self.add_button)  # 加号固定在最右侧。
        layout.addLayout(add_row)  # 新增不会自动应用分类。
        self.hint = QLabel()  # 错误或归类反馈按需显示。
        self.hint.setWordWrap(True)  # 长提示不撑宽弹窗。
        self.hint.hide()  # 默认界面不堆叠多行说明。
        layout.addWidget(self.hint)  # 提示保持就地显示。
        footer = QHBoxLayout()  # 简单说明与确认操作放在底部。
        self.footer_hint = QLabel('点击标签选择 · 箭头在行下展开 · 右键重命名／归类')
        footer.addWidget(self.footer_hint)  # 交互提示使用具体操作。
        footer.addStretch()  # 操作按钮靠右。
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)  # 仍然集中确认，避免每次点击移动视频。
        self.buttons.button(QDialogButtonBox.Ok).setText('应用标签')  # 全部应用成功后仍自动评分。
        self.buttons.button(QDialogButtonBox.Cancel).setText('取消')  # Esc 也可取消草稿。
        for button in self.buttons.buttons():  # 底部按钮不用胶囊的大圆角尺寸。
            button.setStyleSheet('border-radius:5px; padding:6px 12px;')  # 保持清楚的操作入口。
            button.setAutoDefault(False)  # 输入回车不会提交整个分类。
        footer.addWidget(self.buttons)  # 确认按钮不会跟随标签区域滚动。
        layout.addLayout(footer)  # 所有必要操作在同一张卡片内。
        self.search.textChanged.connect(lambda text: self.rebuild())  # 搜索不展开父类。
        self.add_button.clicked.connect(self.add_tag)  # 加号新增普通标签。
        self.entry.returnPressed.connect(self.add_tag)  # 回车只执行新增。
        self.buttons.accepted.connect(self.accept)  # 应用前校验全局关系。
        self.buttons.rejected.connect(self.reject)  # 取消不修改磁盘或数据库。
        self.rebuild()  # 初始只展示根标签胶囊。

    def message(self, text):  # 提示不额外弹出错误窗口。
        self.hint.setText(text)  # 保留可执行的操作说明。
        self.hint.setVisible(bool(text))  # 没有提示时维持简洁卡片。

    def update_selection(self):  # 只更新选择颜色，不改变布局或滚动。
        if self.managing:
            for name, chip in self.chips.items():
                chip.setChecked(name in self.delete_selection)
            self.delete_button.setEnabled(bool(self.delete_selection))
            return
        parents = {parent for name in self.selected if name in self.schema for parent in tag_chain(name, self.schema)[:-1]}  # 多层子标签隐含选中所有祖先。
        for name, chip in self.chips.items():  # 同步根标签与展开后的子标签。
            chip.setChecked(name in self.selected)
            chip.setProperty('implicitSelected', name in parents and name not in self.selected)
            chip.style().unpolish(chip)
            chip.style().polish(chip)
            state = '本级已选' if name in self.selected else '本级未选；包含已选子标签' if name in parents else '未选'
            chip.setToolTip(tag_label(name, self.schema) + '\n' + state + '\n点击选择／取消；箭头只展开；右键重命名／归类')

    def rebuild(self):  # 结构变化只更新胶囊布局，保留展开集合和滚动位置。
        if self.dragging:  # 拖动来源控件不能在原生拖动循环中销毁。
            self.pending_refresh = True  # 落下后统一更新一次。
            return  # 不在悬停时展开或跳动。
        self.pending_refresh = False  # 即将处理已经记录的结构变化。
        position = self.scroll.verticalScrollBar().value()  # 保存当前列表浏览位置。
        self.serial += 1  # 过期布局回调不能覆盖新的用户操作。
        serial = self.serial  # 固定本次刷新代次。
        old = self.scroll.takeWidget()  # 将旧控件从滚动区分离。
        if old is not None:  # 第一次打开没有旧布局。
            old.deleteLater()  # 当前点击或拖动事件结束后再释放源胶囊。
        content = QWidget()  # 使用一个新的轻量内容容器。
        content.setStyleSheet('background:transparent;')  # 胶囊之间保持白色底。
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 10, 0, 8)  # 胶囊区域与标题保持适量距离。
        self.chips = {}  # 不保留旧控件指针。
        self.panels = {}
        query = self.search.text().strip().casefold()  # 搜索不影响分类或选择。
        roots = [name for name, row in self.schema.items() if query or not row.get('parent')]
        root_area = QWidget()
        root_flow = FlowLayout(root_area)

        def populate(flow, names, ancestors=()):
            for name in sorted(names, key=natural):
                if query and query not in tag_label(name, self.schema).casefold():
                    continue
                chip = TagChip(self, name)
                flow.addWidget(chip)
                self.chips[name] = chip
                if query or name not in self.expanded or not chip.parent_tag or name in ancestors:
                    continue
                panel = ChildPanel(self, name)
                panel_layout = QVBoxLayout(panel)
                panel_layout.setContentsMargins(12, 8, 8, 8)
                heading = QLabel(tag_label(name, self.schema))
                heading.setWordWrap(True)
                panel_layout.addWidget(heading)
                area = QWidget()
                child_flow = FlowLayout(area)
                children = [child for child, row in self.schema.items() if row.get('parent') == name]
                populate(child_flow, children, (*ancestors, name))
                panel_layout.addWidget(area)
                if not children:
                    panel_layout.addWidget(QLabel('将标签拖到这里'))
                flow.add_branch(chip, panel)
                self.panels[name] = panel

        populate(root_flow, roots)
        body.addWidget(root_area)
        body.addStretch()  # 内容不足时不把胶囊高度拉大。
        self.scroll.setWidget(content)  # 用新的布局替换原内容。
        self.update_selection()  # 恢复根标签与子标签的选择颜色。
        def restore():  # 等换行布局完成后再恢复滚动。
            if serial == self.serial:  # 新操作发生后丢弃旧恢复回调。
                self.scroll.verticalScrollBar().setValue(position)  # 不跳到顶部或新归类的小类。
        restore()  # 先恢复当前已计算的范围。
        QTimer.singleShot(0, self, restore)  # 草稿释放后不执行过期的滚动回调。

    def activate(self, name):  # 标签本体只改变选择。
        if self.managing:
            self.delete_selection.symmetric_difference_update({name})
            self.update_selection()
            return
        self.selected.symmetric_difference_update({name})
        self.update_selection()

    def toggle_expanded(self, name):
        if not self.schema.get(name, {}).get('is_parent'):
            return
        chip = self.chips.get(name)
        focused = chip is not None and chip.arrow is not None and chip.arrow.hasFocus()
        self.expanded.symmetric_difference_update({name})
        self.rebuild()
        if focused and name in self.chips and self.chips[name].arrow is not None:
            self.chips[name].arrow.setFocus(Qt.OtherFocusReason)

    def set_parent(self, name, enabled):  # 右键明确改变父标签身份。
        if not enabled and any(row.get('parent') == name for row in self.schema.values()):  # 有子标签时不偷偷打散全局关系。
            self.message('请先将子标签移出，再取消父标签。')  # 给出直接可执行的动作。
            return  # 保留现有子类。
        self.schema[name]['is_parent'] = enabled  # 设为父标签时保留它自身的上级关系。
        if not enabled:  # 取消父标签后不保留其子区。
            self.expanded.discard(name)  # 其他父类的展开状态保持不变。
        self.rebuild()  # 不因设为父标签就主动展开它。

    def assign_parent(self, name, parent):  # 拖放和右键归类共用一个入口。
        if name not in self.schema or parent not in self.schema or not self.schema[parent].get('is_parent') or name in tag_chain(parent, self.schema):  # 允许父类嵌套，只拒绝自身与后代作为目标。
            self.message('不能放入自身或其子孙标签，请选择其他父标签。')  # 防止循环关系。
            return False  # 不改变草稿。
        self.schema[name].update(kind='minor', parent=parent)  # 保留原父标签身份及其全部子孙，只修改上级。
        self.rebuild()  # 拖动期间会自动延迟至手势结束。
        return True  # 允许落下，不自动展开目标父类。

    def allow_drop(self, event, parent):  # 只接受同一标签窗口内部的普通标签。
        if event.source() is self and event.mimeData().hasFormat(MIME) and self.schema.get(parent, {}).get('is_parent'):  # 不接受资源管理器文件或其他窗口数据。
            event.acceptProposedAction()  # 只确认可以落下，不展开或移动。
        else:  # 无效来源不进行归类。
            event.ignore()  # 保持当前结构。

    def drop_tag(self, event, parent):  # 落下后才修改草稿父级。
        if event.source() is self and event.mimeData().hasFormat(MIME):  # 再次验证内部来源。
            name = bytes(event.mimeData().data(MIME)).decode('utf-8')  # 恢复完整中文标签身份。
            if self.assign_parent(name, parent):  # 目录与数据库仍等待应用确认。
                event.acceptProposedAction()  # 成功归类只更新这一项。
                return  # 不执行默认源控件删除。
        event.ignore()  # 未成功时保留原归属。

    def build_menu(self, name):
        menu = QMenu(self)  # 不在每个标签右侧放常驻控件。
        menu.addAction('重命名标签…', lambda: self.prompt_rename(name))
        menu.addSeparator()
        if self.schema[name].get('is_parent'):  # 父类本身也可作为独立标签选择。
            menu.addAction('取消父标签', lambda: self.set_parent(name, False))  # 有子类时会提示先移出。
        else:  # 普通标签可以一键成为父标签。
            menu.addAction('设为父标签', lambda: self.set_parent(name, True))  # 不需要类型下拉框。
        if self.schema[name].get('parent'):  # 普通子标签与子父标签都可以移回根区域。
            menu.addAction('移出父标签', lambda: self.detach(name))  # 保留自身的子孙标签。
        targets = [parent for parent, row in self.schema.items() if row.get('is_parent') and name not in tag_chain(parent, self.schema)]  # 菜单排除自身与子孙以避免循环。
        if targets:  # 父标签也能通过右键归入其他父标签。
            submenu = menu.addMenu('移入父标签')  # 与直接拖动使用同一安全入口。
            for parent in sorted(targets, key=natural):  # 按名称自然排序。
                submenu.addAction(tag_label(parent, self.schema), lambda checked=False, target=parent: self.assign_parent(name, target))
        menu.addSeparator()  # 将全局删除和普通归类操作区分开。
        menu.addAction('删除标签', lambda: self.delete_tag(name))  # 删除仍是草稿，应用后才同步所有视频。
        return menu

    def menu(self, name, position):
        menu = self.build_menu(name)
        menu.exec(position)
        menu.deleteLater()

    def prompt_rename(self, name):
        value, accepted = QInputDialog.getText(self, '重命名标签', '新标签名（保存后同步所有文件的引用）', QLineEdit.Normal, name)
        if accepted:
            self.rename_tag(name, value)

    @property
    def renames(self):
        return {origin: name for name, origin in self._origins.items() if origin and origin != name}

    def confirm_saved(self):
        self._origins = {name: name for name in self.schema}

    def rename_tag(self, name, value):
        try:
            value = validate_tag(value)
            if name not in self.schema:
                raise ValueError('标签已不存在。')
            if any(other != name and other.casefold() == value.casefold() for other in self.schema):
                raise ValueError('标签已存在，不能重名。')
            if value == name:
                return True
            row = self.schema.pop(name)
            row['name'] = value
            self.schema[value] = row
            self._origins[value] = self._origins.pop(name, None)
            for child in self.schema.values():
                if child.get('parent') == name:
                    child['parent'] = value
            for selection in (self.selected, self.expanded, self.delete_selection):
                if name in selection:
                    selection.remove(name)
                    selection.add(value)
            self.message('')
            self.rebuild()
            return True
        except ValueError as error:
            self.message(str(error))
            return False

    def detach(self, name):  # 把子标签移回普通根标签。
        self.schema[name].update(kind='major', parent=None)  # 移回根节点仍保留其父标签身份和子孙。
        self.rebuild()  # 保留已有展开集合。

    def delete_tag(self, name):  # 删除公共标签，但不删除任何视频内容。
        parent = self.schema[name].get('parent')  # 子标签提升到被删节点的上一级。
        for row in self.schema.values():  # 仅调整直接子节点，孙级关系保持原样。
            if row.get('parent') == name:  # 保留子节点原有父标签身份。
                row.update(parent=parent, kind='minor' if parent else 'major')  # 删除根父标签时子标签变为根节点。
        del self.schema[name]  # 从待应用的全局字典删除该标签。
        self._origins.pop(name, None)
        self.selected.discard(name)  # 当前视频不再选择已删除的标签。
        self.expanded.discard(name)  # 不自动展开提升后的子标签。
        self.message('')  # 明确全局影响且允许取消草稿。
        self.rebuild()  # 保持剩余展开状态和浏览位置。

    def add_tag(self):  # 加号与回车只新增草稿标签。
        try:  # 错误就地提示，不关闭弹窗。
            name = validate_tag(self.entry.text())  # 继续禁止路径穿越和设备名。
            if name.casefold() in {tag.casefold() for tag in self.schema}:  # 不创建大小写重复标签。
                raise ValueError('标签已存在。')  # 用户可以直接选择已有胶囊。
            self.schema[name] = {'name': name, 'kind': 'major', 'parent': None, 'is_parent': False}  # 新标签先作为普通可选胶囊。
            self._origins[name] = None
            # Adding to the catalog does not select the tag for this video.
            self.entry.clear()  # 支持连续新增。
            self.message('')  # 清除旧错误提示。
            self.rebuild()  # 不清除搜索或抢走滚动位置。
        except ValueError as error:  # 保留已有选择和分类。
            self.message(str(error))  # 不触发任何磁盘修改。

    def chosen(self):  # 应用时仍使用原有规范化标签规则。
        return canonical_tags(self.selected, self.schema)  # 子标签隐含父级，不增加重复硬链接。

    def accept(self):  # 统一确认才进行全局同步。
        try:  # 父子结构和路径安全仍由核心校验。
            validate_layout(list(self.schema.values()))  # 不接受循环或非法父级。
        except ValueError as error:  # 不丢失尚可修正的草稿。
            self.message(str(error))  # 就地显示原因。
            return  # 暂不应用。
        super().accept()  # 成功后继续原来的全局迁移和自动评分流程。

    def enable_management(self):
        self.setStyleSheet('QFrame#tagCard { border:none; background:transparent; } QScrollArea { border:none; background:transparent; } QPushButton { padding:5px 10px; }')
        self.title.setObjectName('tagManager')
        self.title.setProperty('role', 'quiet')
        self.title.toggled.connect(self.set_management)
        self.delete_button.clicked.connect(self.delete_selected)
        self.delete_button.setProperty('role', 'quiet')
        self.delete_button.setEnabled(False)

    def set_management(self, enabled):
        self.managing = enabled
        self.delete_selection.clear()
        self.delete_button.setVisible(enabled)
        self.update_selection()

    def delete_selected(self):
        # Schema edits go through TagMigration; no filesystem delete call here.
        for name in list(self.delete_selection):
            if name in self.schema:
                self.delete_tag(name)
        self.delete_selection.clear()
        self.update_selection()
