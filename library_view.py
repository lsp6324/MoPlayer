"""Left library panel: widgets, selection and scroll positions live here."""
from PySide6.QtCore import Qt, Signal, QPoint, QModelIndex, QPersistentModelIndex
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QStackedWidget,
                               QListView, QAbstractItemView, QFileDialog)
from application.library import LibrarySelection
from library_views import DropTree, TreeModel, VideoListModel, VideoDelegate
from ui import PathLabel, label, button


class LibraryView(QFrame):
    folderRequested = Signal(str)
    pathDropped = Signal(str)
    videoRequested = Signal(object)
    unfavoriteRequested = Signal(str)

    def __init__(self, controller, thumbnails, current_video, theme_owner):
        super().__init__(theme_owner)
        self.controller = controller
        self.mode = 'files'
        self.setObjectName('libraryCard')
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 12, 12)
        layout.setSpacing(8)
        navigation = QHBoxLayout()
        navigation.setSpacing(4)
        self.tabs = {}
        for text, mode in [('文件', 'files'), ('最近', 'videos'), ('收藏', 'stars')]:
            tab = button(text, lambda checked=False, mode=mode: self.show_mode(mode), role='tab')
            tab.setCheckable(True)
            tab.setChecked(mode == 'files')
            self.tabs[mode] = tab
            navigation.addWidget(tab)
        navigation.addStretch()
        layout.addLayout(navigation)
        folder_row = QHBoxLayout()
        self.folder_label = PathLabel('')
        self.file_count = label('', 'badge')
        folder_row.addWidget(self.folder_label, 1)
        folder_row.addWidget(self.file_count)
        self.import_button = button('', self.choose_folder, 'plus', 'nav')
        self.import_button.setFixedSize(36, 36)
        self.import_button.setToolTip('导入文件夹')
        self.import_button.setAccessibleName('导入文件夹')
        folder_row.addWidget(self.import_button)
        layout.addLayout(folder_row)
        self.stack = QStackedWidget()
        self.tree = DropTree(controller.can_import)
        self.tree.setToolTip('拖入一个文件夹，或拖入单个视频以打开播放')
        self.tree.setObjectName('libraryTree')
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setIndentation(16)
        self.tree.dropped.connect(self.pathDropped)
        self.tree.doubleClicked.connect(self._open_tree)
        self.stack.addWidget(self.tree)
        self.lists = {}
        for mode in ('videos', 'stars'):
            view = QListView()
            view.setObjectName('sidebarList')
            view.setMouseTracking(True)
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            view.setEditTriggers(QAbstractItemView.NoEditTriggers)
            view.setModel(VideoListModel(view))
            view.doubleClicked.connect(lambda index: self.videoRequested.emit(LibrarySelection(index.data(Qt.UserRole))))
            self.lists[mode] = view
            self.stack.addWidget(view)
        for view in (self.tree, *self.lists.values()):
            view.setItemDelegate(VideoDelegate(thumbnails, view, current_video=current_video, theme_owner=theme_owner))
            thumbnails.changed.connect(view.viewport().update)
        layout.addWidget(self.stack, 1)
        self.cancel_button = button('取消扫描', lambda: controller.cancel(), role='quiet')
        self.cancel_button.hide()
        self.remove_favorite = button('取消收藏', self._remove_favorite, 'star', 'quiet')
        self.remove_favorite.hide()
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.remove_favorite)
        controller.subscribe(self.render)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '选择视频文件夹')
        if folder:
            self.folderRequested.emit(folder)

    def show_mode(self, mode):
        if mode not in self.tabs:
            raise ValueError(mode)
        if mode != 'files':
            self.controller.load_list(mode)
        self.mode = mode
        for key, tab in self.tabs.items():
            tab.setChecked(key == mode)
        self.stack.setCurrentWidget(self.tree if mode == 'files' else self.lists[mode])
        self.folder_label.setVisible(mode == 'files')
        self.file_count.setVisible(mode == 'files')
        self.remove_favorite.setVisible(mode == 'stars')

    @staticmethod
    def _sync_list(view, rows):
        model = view.model()
        selected = view.currentIndex().data(Qt.UserRole)
        anchor = QPersistentModelIndex(view.indexAt(QPoint(1, 1)))
        offset = view.visualRect(anchor).top() if anchor.isValid() else 0
        scroll = view.verticalScrollBar().value()
        model.sync(rows)
        if selected and not model.index_for_id(selected).isValid():
            view.clearSelection()
            view.setCurrentIndex(QModelIndex())
        if anchor.isValid():
            view.scrollTo(QModelIndex(anchor), QAbstractItemView.PositionAtTop)
            view.verticalScrollBar().setValue(view.verticalScrollBar().value() - offset)
        else:
            view.verticalScrollBar().setValue(scroll)

    def render(self, change):
        if change.kind == 'scanning':
            self.cancel_button.setVisible(self.controller.scanning)
            return
        snapshot = self.controller.browsing
        if change.kind == 'folder':
            old_model = self.tree.model()
            model = TreeModel(snapshot, self.controller.details, self.tree)
            self.tree.setModel(model)
            if old_model is not None:
                old_model.deleteLater()
            self.tree.expand(model.index(0, 0))
            self.folder_label.setText(snapshot.root)
        elif snapshot is not None and change.video_ids:
            self.tree.model().sync(snapshot, self.controller.details, change.video_ids)
        if snapshot is not None:
            self.file_count.setText(f'{sum(len(snapshot.visible_files(folder)) for folder in self.tree.model().children)} 部')
        for mode, view in self.lists.items():
            self._sync_list(view, self.controller.list_rows(mode))

    def _open_tree(self, index):
        vid = index.data(Qt.UserRole)
        if vid:
            _, folder, number = index.internalPointer()
            self.videoRequested.emit(LibrarySelection(vid, self.controller.browsing, (folder, number)))

    def selection(self):
        view = self.tree if self.mode == 'files' else self.lists[self.mode]
        selection = view.selectionModel()
        indexes = selection.selectedIndexes() if selection is not None else ()
        index = next((index for index in indexes if index.data(Qt.UserRole)), QModelIndex())
        if not index.isValid():
            return None
        vid = index.data(Qt.UserRole)
        if self.mode == 'files':
            _, folder, number = index.internalPointer()
            return LibrarySelection(vid, self.controller.browsing, (folder, number))
        return LibrarySelection(vid)

    def _remove_favorite(self):
        selected = self.selection()
        if selected is not None:
            self.unfavoriteRequested.emit(selected.video_id)

    def playback_changed(self, previous, current):
        ids = (previous, current)
        if self.tree.model() is not None:
            self.tree.model().notify(ids)
        for view in self.lists.values():
            view.model().notify(ids)
        if self.tree.currentIndex().data(Qt.UserRole) != current:
            self.tree.clearSelection()

    def apply_palette(self, palette):
        for view in (self.tree, *self.lists.values()):
            view.setPalette(palette)
            view.viewport().setAutoFillBackground(False)
            view.viewport().update()
