"""Startup reopens the last imported folder and always lands on the file page."""
import time

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from application.catalog import CatalogFilter
from application.library import LibraryController
from core import Store
from infrastructure.library_preferences import LibraryPreferences
from infrastructure.library_repository import LibraryRepository
from library_view import LibraryView


class Thumbnails(QObject):
    changed = Signal()
    errors = set()

    def request(self, video_id):
        return None


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_last_folder_follows_the_most_recent_import(tmp_path):
    store = Store(tmp_path / 'data')
    try:
        controller = LibraryController(LibraryRepository(store), None, lambda work, ready: None)
        assert controller.last_folder() is None
        first, second = tmp_path / 'first', tmp_path / 'second'
        first.mkdir()
        second.mkdir()
        controller.repository.remember_folder(first)
        time.sleep(0.01)
        controller.repository.remember_folder(second)
        assert controller.last_folder() == second.absolute()
    finally:
        store.db.close()


def test_startup_opens_the_file_page_even_when_the_library_was_last(tmp_path, qapp):
    """A saved library page must not win over the file page on restart."""
    preferences = LibraryPreferences(tmp_path)
    preferences.save('catalog', CatalogFilter(sort='score'), 'grid')
    store = Store(tmp_path / 'data')
    try:
        controller = LibraryController(LibraryRepository(store), None, lambda work, ready: None)
        host = QWidget()
        host.theme = 'light'
        view = LibraryView(controller, Thumbnails(), lambda: None, host, preferences=preferences)
        try:
            QTest.qWait(60)
            assert view.mode == 'files'
            assert not controller.catalog_pending, 'startup must not query the library'
            assert view.catalog_panel.list.presentation == 'grid'
            assert view.catalog_panel.filters == CatalogFilter(sort='score')
        finally:
            view.shutdown()
    finally:
        store.db.close()
