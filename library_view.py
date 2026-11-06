"""Left library panel: widgets, selection and scroll positions live here."""
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QPoint, QModelIndex, QPersistentModelIndex, QTimer
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QStackedWidget,
                               QListView, QAbstractItemView, QFileDialog)
from application.library import LibrarySelection
from library_views import DropList, FolderModel, VideoListModel, VideoDelegate, FOLDER_ROLE, LOCATION_ROLE
from folder_navigation import FolderNavigation
from ui import label, button
from catalog_panel import CatalogPanel
from catalog_delegate import CatalogDelegate


@dataclass(frozen=True)
class _FolderPosition:
    selected: object
    anchor: object
    offset: int
    scroll: int


class LibraryView(QFrame):
    folderRequested = Signal(str)
    pathDropped = Signal(str)
    videoRequested = Signal(object)
    unfavoriteRequested = Signal(str)
    historyClearRequested = Signal()

    def __init__(self, controller, thumbnails, current_video, theme_owner, *, preferences=None):
        super().__init__(theme_owner)
        self.controller = controller
        self.preferences = preferences
        self.mode = 'files'
        self.current_folder = None
        self._folder_positions = {}
        self.setObjectName('libraryCard')
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 12, 12)
        layout.setSpacing(8)
        navigation = QHBoxLayout()
        navigation.setSpacing(4)
        self.tabs = {}
        for text, mode in [('文件', 'files'), ('库', 'catalog'), ('最近', 'videos'), ('收藏', 'stars')]:
            tab = button(text, lambda checked=False, mode=mode: self.show_mode(mode), role='tab')
            tab.setCheckable(True)
            tab.setChecked(mode == 'files')
            self.tabs[mode] = tab
            navigation.addWidget(tab)
        navigation.addStretch()
        self.file_count = label('', 'badge')
        navigation.addWidget(self.file_count)
        self.import_button = button('', self.choose_folder, 'plus', 'nav')
        self.import_button.setFixedSize(36, 36)
        self.import_button.setToolTip('导入文件夹')
        self.import_button.setAccessibleName('导入文件夹')
        navigation.addWidget(self.import_button)
        layout.addLayout(navigation)
        self.folder_navigation = FolderNavigation(self)
        self.folder_navigation.requested.connect(self.browse_folder)
        layout.addWidget(self.folder_navigation)
        self.folder_error = label('', 'muted')
        self.folder_error.setWordWrap(True)
        self.folder_error.hide()
        layout.addWidget(self.folder_error)
        self.stack = QStackedWidget()
        self.files = DropList(controller.can_import)
        self.files.setToolTip('双击文件夹进入，双击视频播放；也可拖入文件夹或单个视频')
        self.files.setObjectName('folderList')
        self.files.dropped.connect(self.pathDropped)
        self.files.doubleClicked.connect(self._open_file_entry)
        self.stack.addWidget(self.files)
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
        for view in (self.files, *self.lists.values()):
            delegate = (VideoDelegate(thumbnails, view, current_video=current_video, theme_owner=theme_owner)
                        if view is self.files else CatalogDelegate(thumbnails, view, current_video=current_video,
                                                                   theme_owner=theme_owner, plain_unlisted=True))
            view.setItemDelegate(delegate)
            thumbnails.changed.connect(view.viewport().update)
        self.catalog_panel = CatalogPanel(self, theme_owner=theme_owner)
        self.catalog_panel.list.setModel(VideoListModel(self.catalog_panel.list))
        self.catalog_panel.list.setItemDelegate(CatalogDelegate(thumbnails, self.catalog_panel.list,
                                               current_video=current_video, theme_owner=theme_owner,
                                               presentation=lambda: self.catalog_panel.list.presentation,
                                               tile_size=self.catalog_panel.list.gridSize))
        thumbnails.changed.connect(self.catalog_panel.list.viewport().update)
        self.lists['catalog'] = self.catalog_panel.list
        self.stack.addWidget(self.catalog_panel)
        self.catalog_panel.filtersChanged.connect(self._catalog_filters)
        self.catalog_panel.viewChanged.connect(lambda mode: self._remember_preferences())
        self.catalog_panel.openRequested.connect(self._open_catalog)
        self.catalog_panel.retryRequested.connect(lambda: self.controller.query_catalog(self.catalog_panel.filters))
        layout.addWidget(self.stack, 1)
        self.cancel_button = button('取消扫描', lambda: controller.cancel(), role='quiet')
        self.cancel_button.hide()
        self.remove_favorite = button('取消收藏', self._remove_favorite, 'star', 'quiet')
        self.remove_favorite.hide()
        self.clear_history_button = button('清空记录', self.historyClearRequested.emit, 'history', 'quiet')
        self.clear_history_button.setToolTip('清空“最近”里的播放记录')
        self.clear_history_button.hide()
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.remove_favorite)
        layout.addWidget(self.clear_history_button)
        controller.subscribe(self.render)
        if preferences is not None:
            _page, filters, view_mode = preferences.load()
            self.catalog_panel.present_filter(filters)
            self.catalog_panel.set_view(view_mode, notify=False)
            self.controller.catalog_filter = filters
            # The filter, sort and view survive a restart, but the app always
            # opens on the file page: the window reopens the last folder there.
            QTimer.singleShot(0, lambda: self.show_mode('files', persist=False))

    def _remember_preferences(self):
        if self.preferences is not None:
            try:
                self.preferences.save(self.mode, self.catalog_panel.filters, self.catalog_panel.list.presentation)
            except OSError as error:
                self.tabs['catalog'].setToolTip('浏览偏好保存失败：' + str(error))

    def _catalog_filters(self, filters):
        self._remember_preferences()
        self.controller.query_catalog(filters)

    def _open_catalog(self, video_id):
        selected = self.controller.catalog_selection(video_id)
        if selected is not None:
            self.videoRequested.emit(selected)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '选择视频文件夹')
        if folder:
            self.folderRequested.emit(folder)

    def show_mode(self, mode, *, persist=True):
        if mode not in self.tabs:
            raise ValueError(mode)
        if mode == 'catalog':
            if not self.controller.catalog_loaded and not self.controller.catalog_pending:
                self.controller.query_catalog(self.catalog_panel.filters)
        elif mode != 'files':
            self.controller.load_list(mode)
        self.mode = mode
        for key, tab in self.tabs.items():
            tab.setChecked(key == mode)
        self.stack.setCurrentWidget(self.files if mode == 'files' else self.catalog_panel if mode == 'catalog' else self.lists[mode])
        self.folder_navigation.setVisible(mode == 'files')
        self.folder_error.setVisible(mode == 'files' and bool(self.folder_error.text()))
        self.file_count.setVisible(mode == 'files')
        self.remove_favorite.setVisible(mode == 'stars')
        self.clear_history_button.setVisible(mode == 'videos')
        if persist:
            self._remember_preferences()

    @staticmethod
    def _sync_view(view, sync):
        model = view.model()
        selected = model.key(view.currentIndex()) if view.selectionModel().hasSelection() else None
        anchor = QPersistentModelIndex(view.indexAt(QPoint(1, 1)))
        offset = view.visualRect(anchor).top() if anchor.isValid() else 0
        scroll = view.verticalScrollBar().value()
        sync()
        if selected is not None:
            restored = model.index_for_key(selected)
            if not restored.isValid():
                view.clearSelection()
                view.setCurrentIndex(QModelIndex())
            elif model.key(view.currentIndex()) != model.key(restored):
                view.setCurrentIndex(restored)
        if anchor.isValid():
            view.scrollTo(QModelIndex(anchor), QAbstractItemView.PositionAtTop)
            view.verticalScrollBar().setValue(view.verticalScrollBar().value() - offset)
        else:
            view.verticalScrollBar().setValue(scroll)

    def render(self, change):
        if change.kind == 'scanning':
            self.cancel_button.setVisible(self.controller.scanning)
            self._catalog_status()
            return
        snapshot = self.controller.browsing
        if change.kind == 'folder':
            self._folder_positions.clear()
            self.current_folder = None
            self.browse_folder(change.location[0] if change.location else snapshot.root)
            if change.location:
                index = self.files.model().index_for_location(change.location)
                self.files.setCurrentIndex(index)
                self.files.scrollTo(index)
            self.folder_error.clear()
            self.folder_error.hide()
        elif change.kind == 'directory':
            self._remember_folder()
            self.current_folder = None
            self.browse_folder(snapshot.root)
        elif change.kind == 'contents':
            folder = self.current_folder or snapshot.root
            while folder not in snapshot.folders and folder != snapshot.root:
                folder = str(Path(folder).parent)
            if folder != self.current_folder:
                self.browse_folder(folder)
            else:
                self._sync_view(self.files, lambda: self.files.model().sync(snapshot, self.controller.details, ()))
            self._update_count()
        elif snapshot is not None and change.video_ids:
            self._sync_view(self.files, lambda: self.files.model().sync(snapshot, self.controller.details, change.video_ids))
            self._update_count()
        for mode, view in self.lists.items():
            self._sync_view(view, lambda mode=mode, view=view: view.model().sync(self.controller.list_rows(mode)))
        self.catalog_panel.present_schema(self.controller.catalog_schema)
        self._catalog_status()

    def _catalog_status(self):
        if self.catalog_panel.filters != self.controller.catalog_filter:
            self.catalog_panel.present_filter(self.controller.catalog_filter)
            self._remember_preferences()
        self.catalog_panel.present_status(len(self.controller.catalog_ids), self.controller.catalog_total,
                                          self.controller.catalog_pending, self.controller.catalog_error)

    def _remember_folder(self):
        if self.current_folder is None:
            return
        view, model = self.files, self.files.model()
        anchor = view.indexAt(QPoint(1, 1))
        self._folder_positions[self.current_folder] = _FolderPosition(
            model.key(view.currentIndex()) if view.selectionModel().hasSelection() else None,
            model.key(anchor), view.visualRect(anchor).top() if anchor.isValid() else 0,
            view.verticalScrollBar().value())

    def browse_folder(self, folder):
        snapshot = self.controller.browsing
        if snapshot is None:
            return
        if folder not in snapshot.folders:
            self.controller.browse_directory(folder).on_finished(self._directory_ready)
            return
        self.controller.cancel('browse')
        self.folder_error.clear()
        self.folder_error.hide()
        if folder == self.current_folder:
            return
        self._remember_folder()
        old_model = self.files.model()
        model = FolderModel(snapshot, folder, self.controller.details, self.files)
        self.files.setModel(model)
        if old_model is not None:
            old_model.deleteLater()
        self.current_folder = folder
        self.folder_navigation.set_path(folder)
        self._update_count()
        self.files.doItemsLayout()
        position = self._folder_positions.get(folder)
        if position is not None:
            selected = model.index_for_key(position.selected)
            self.files.setCurrentIndex(selected)
            anchor = model.index_for_key(position.anchor)
            if anchor.isValid():
                self.files.scrollTo(anchor, QAbstractItemView.PositionAtTop)
                self.files.verticalScrollBar().setValue(self.files.verticalScrollBar().value() - position.offset)
            else:
                self.files.verticalScrollBar().setValue(position.scroll)

    def _directory_ready(self, outcome):
        if outcome.error:
            self.folder_error.setText('无法打开目录：' + str(outcome.error))
        elif outcome.succeeded:
            errors = outcome.value.errors
            self.folder_error.setText(f'已跳过 {len(errors)} 个无法访问的条目。' if errors else '')
        self.folder_error.setVisible(self.mode == 'files' and bool(self.folder_error.text()))

    def _update_count(self):
        snapshot = self.controller.browsing
        if snapshot is not None and self.current_folder in snapshot.folders:
            self.file_count.setText(f'{len(snapshot.visible_files(self.current_folder))} 部')

    def _open_file_entry(self, index):
        folder = index.data(FOLDER_ROLE)
        if folder:
            self.browse_folder(folder)
            return
        vid = index.data(Qt.UserRole)
        if vid:
            self.videoRequested.emit(LibrarySelection(vid, self.controller.browsing, index.data(LOCATION_ROLE)))

    def selection(self):
        view = self.files if self.mode == 'files' else self.lists[self.mode]
        selection = view.selectionModel()
        indexes = selection.selectedIndexes() if selection is not None else ()
        index = next((index for index in indexes if index.data(Qt.UserRole)), QModelIndex())
        if not index.isValid():
            return None
        vid = index.data(Qt.UserRole)
        if self.mode == 'files':
            return LibrarySelection(vid, self.controller.browsing, index.data(LOCATION_ROLE))
        if self.mode == 'catalog':
            return self.controller.catalog_selection(vid, allow_pending=True)
        return LibrarySelection(vid)

    def _remove_favorite(self):
        selected = self.selection()
        if selected is not None:
            self.unfavoriteRequested.emit(selected.video_id)

    def playback_changed(self, previous, current):
        ids = (previous, current)
        if self.files.model() is not None:
            self.files.model().notify(ids)
        for view in self.lists.values():
            view.model().notify(ids)

    def apply_palette(self, palette):
        self.catalog_panel.apply_colors()
        for view in (self.files, *self.lists.values()):
            view.setPalette(palette)
            view.viewport().setAutoFillBackground(False)
            view.viewport().update()

    def shutdown(self):
        self.catalog_panel.shutdown()
