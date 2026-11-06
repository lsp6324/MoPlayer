"""Observable receipt positioning, replacement, timeout and success semantics."""
import time
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
from moplayer.gui.action_notice import ActionNotice


@pytest.fixture
def notice():
    app = QApplication.instance() or QApplication([])
    host = QMainWindow()
    surface = QWidget()
    host.setCentralWidget(surface)
    host.resize(900, 600)
    obstacle = QWidget(host, Qt.Tool | Qt.FramelessWindowHint)
    panel = ActionNotice(surface, obstacle)
    panel.set_accent('#72aaff')
    host.show()
    app.setActiveWindow(host)
    app.processEvents()
    yield panel, host, obstacle
    panel.clear()
    obstacle.close()
    host.close()
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_receipt_is_in_upper_right_without_taking_focus(notice):
    panel, host, _ = notice
    active = QApplication.activeWindow()
    panel.present('已归档', '8分 / 风景')
    QApplication.processEvents()
    bounds = QRect(panel.surface.mapToGlobal(QPoint()), panel.surface.size())
    assert panel.isVisible()
    # The offscreen backend activates tool windows regardless of native flags.
    if QApplication.platformName() != 'offscreen':
        assert QApplication.activeWindow() is active
    assert panel.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert bounds.right() - panel.geometry().right() == 24
    assert panel.geometry().top() - bounds.top() == 24
    assert panel.windowFlags() & Qt.WindowTransparentForInput
    host.move(host.pos() + QPoint(50, 30))
    QApplication.processEvents()
    bounds = QRect(panel.surface.mapToGlobal(QPoint()), panel.surface.size())
    assert panel.isVisible() and bounds.contains(panel.geometry())


def test_latest_receipt_replaces_previous_and_gets_two_seconds(notice):
    panel, _, _ = notice
    panel.present('标签已保存', '第一条')
    QTest.qWait(1100)
    start = time.monotonic()
    panel.present('已归档', '第二条')
    assert panel.title_label.text() == '已归档'
    assert panel.detail_label.text() == '第二条'
    QTest.qWait(1150)
    assert panel.isVisible(), '旧回执的到期时间不能隐藏新回执'
    while panel.isVisible() and time.monotonic() - start < 2.4:
        QTest.qWait(20)
    assert not panel.isVisible()
    assert 1.95 <= time.monotonic() - start < 2.4


def test_receipt_avoids_title_elides_long_paths_and_hides_with_owner(notice):
    panel, host, obstacle = notice
    panel.present('已归档', '非常长的分类目录 / ' * 40)
    assert '…' in panel.detail_label.text()
    assert panel.accessibleDescription() == '非常长的分类目录 / ' * 40
    obstacle.setGeometry(host.x() + 60, host.y() + 24, 700, 96)
    obstacle.show()
    QApplication.processEvents()
    assert panel.geometry().top() >= obstacle.geometry().bottom() + 16
    assert not panel.geometry().intersects(obstacle.geometry())
    host.hide()
    QApplication.processEvents()
    assert not panel.isVisible()
