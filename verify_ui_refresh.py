"""Real VLC/Qt integration checks, restricted to a noninteractive desktop."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback

from application.operations import Operation
from unittest.mock import Mock

def require_private_desktop():
    expected = os.environ.get('MOPLAYER_ISOLATED_DESKTOP', '')
    if not expected.startswith('MoPlayerVerify-'):
        raise RuntimeError('Run through run_isolated_desktop.py, never on the interactive desktop')
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32')
    user.GetThreadDesktop.argtypes = [wintypes.DWORD]
    user.GetThreadDesktop.restype = wintypes.HANDLE
    user.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    user.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user.OpenInputDesktop.restype = wintypes.HANDLE
    user.CloseDesktop.argtypes = [wintypes.HANDLE]
    def name(handle):
        result, needed = ctypes.create_unicode_buffer(256), wintypes.DWORD()
        if not user.GetUserObjectInformationW(handle, 2, result, ctypes.sizeof(result), ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        return result.value
    current = name(user.GetThreadDesktop(kernel.GetCurrentThreadId()))
    active = user.OpenInputDesktop(0, False, 1)
    if not active:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if current != expected or current == name(active):
            raise RuntimeError('Refusing to show windows on the interactive desktop')
    finally:
        user.CloseDesktop(active)
    return current


def run(destination):
    desktop = require_private_desktop()
    from PySide6.QtCore import Qt, QPoint, QThreadPool, QTimer, QPersistentModelIndex
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    from app import Window, BUNDLE
    from runtime import load_vlc
    vlc = load_vlc()
    from core import scan
    output = Path(destination).absolute()
    output.mkdir(parents=True, exist_ok=True)
    report = {'desktop': desktop, 'checks': []}
    application = QApplication.instance() or QApplication([])
    print('QApplication ready', flush=True)
    # The synthetic clip uses a digital-silence audio track.
    window = Window(output / 'data')
    print('Window constructed', flush=True)
    window.resize(1100, 720)
    def check(name, passed):
        report['checks'].append({'name': name, 'ok': bool(passed)})
        if not passed:
            raise AssertionError(name)
    def wait(predicate, seconds=12):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            application.processEvents()
            if predicate():
                return True
            QTest.qWait(20)
        return False
    def snapshot(name):
        application.processEvents()
        window.grab().save(str(output / (name + '.png')))
        for number, surface in enumerate([*window.playback_options.panels, window.video_fullscreen.overlay, window.video_fullscreen.title]):
            if surface.isVisible():
                surface.grab().save(str(output / f'{name}-surface-{number}.png'))
    def button_matches(state):
        from ui import icon
        symbol = 'pause' if state == vlc.State.Playing else 'play'
        action = '暂停' if state == vlc.State.Playing else '播放'
        return (window.player.get_state() == state and
                window.play_button.property('iconName') == symbol and
                window.play_button.accessibleName() == action and
                window.play_button.icon().pixmap(24, 24).toImage() == icon(symbol, '#ffffff').pixmap(24, 24).toImage())
    def hit_layer(widget):
        # Read native z-order on this thread's private desktop. No global input.
        user = ctypes.WinDLL('user32')
        user.WindowFromPoint.argtypes = [wintypes.POINT]
        user.WindowFromPoint.restype = wintypes.HWND
        user.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
        user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        bounds = wintypes.RECT()
        user.GetClientRect(int(widget.winId()), ctypes.byref(bounds))
        point = wintypes.POINT(bounds.right // 2, bounds.bottom // 2)
        user.ClientToScreen(int(widget.winId()), ctypes.byref(point))
        hit = user.WindowFromPoint(point)
        return hit == int(widget.winId()) or bool(user.IsChild(int(widget.winId()), hit))
    def smooth_surface(widget):
        # Check both the compositor contract and the rendered alpha pixels.
        # A binary QRegion can pass a corner-exclusion test while still jagged.
        user = ctypes.WinDLL('user32')
        user.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user.GetWindow.restype = wintypes.HWND
        hwnd = int(widget.winId())
        style = user.GetWindowLongPtrW(hwnd, -16)
        extended = user.GetWindowLongPtrW(hwnd, -20)
        image = widget.grab().toImage()
        image.save(str(output / (widget.objectName() + '-alpha.png')))
        ratio = image.devicePixelRatio()
        extent = min(round((widget.radius + 3) * ratio), image.width() // 2, image.height() // 2)
        corners = [(0, 0, 1, 1), (image.width()-1, 0, -1, 1),
                   (0, image.height()-1, 1, -1), (image.width()-1, image.height()-1, -1, -1)]
        antialiased = True
        for x0, y0, dx, dy in corners:
            alpha = {image.pixelColor(x0 + dx*x, y0 + dy*y).alpha()
                     for x in range(extent) for y in range(extent)}
            antialiased &= (image.pixelColor(x0, y0).alpha() == 0 and
                            255 in alpha and len([a for a in alpha if 0 < a < 255]) >= 4)
        return (widget.isWindow() and widget.mask().isEmpty() and
                bool(extended & 0x80000) and not bool(extended & 8) and
                not bool(style & 0x40000000) and
                user.GetWindow(hwnd, 4) == int(window.winId()) and antialiased)
    try:
        window.show()
        print('Window shown', flush=True)
        window.activateWindow()
        check('private native window active', wait(window.isActiveWindow))
        snapshot('empty')
        ffmpeg = BUNDLE / 'ffmpeg.exe'
        if not ffmpeg.is_file():
            import imageio_ffmpeg
            ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
        sample_dir = output / 'sample'
        sample_dir.mkdir(exist_ok=True)
        sample = sample_dir / 'preview.mp4'
        subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
            'color=c=0x365d8d:size=960x540:rate=30', '-f', 'lavfi', '-i',
            'anullsrc=channel_layout=stereo:sample_rate=44100', '-t', '45', '-c:a', 'aac', '-c:v', 'libx264',
            '-threads', '2', '-y', str(sample)], check=True, capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
        import shutil
        shutil.copyfile(sample, sample_dir / 'second.mp4')
        context, _ = scan(sample_dir, window.store, threading.Event())
        window.library_controller.adopt_snapshot(context)
        window.library_view.tree.expandAll()
        window.start(context, (str(sample_dir), 0))
        check('real VLC playback advances', wait(lambda: window.player.get_state() == vlc.State.Playing and window.player.get_time() > 500))
        check('transport shows actual pause action while playing', wait(lambda: button_matches(vlc.State.Playing)))
        def timeline_moves_between_decoder_polls():
            window.timer.stop()
            window.tick()
            start = window.seekbar.visual_fraction
            QTest.qWait(120)
            end = window.seekbar.visual_fraction
            window.timer.start()
            return end > start and window.seekbar.animation.isActive()
        check('timeline animates between decoder polls', timeline_moves_between_decoder_polls())
        window.play_button.click()
        check('pause acknowledged', wait(lambda: window.player.get_state() == vlc.State.Paused))
        check('transport shows actual play action after pause', wait(lambda: button_matches(vlc.State.Paused)))
        window.tick()
        paused_fraction = window.seekbar.visual_fraction
        QTest.qWait(120)
        check('paused timeline stays still', window.seekbar.visual_fraction == paused_fraction and not window.seekbar.animation.isActive())
        library = window.library_view
        library.show_mode('videos')
        recent = library.lists['videos']
        recent.setCurrentIndex(recent.model().index_for_id(window.current))
        selected = QPersistentModelIndex(recent.currentIndex())
        check('recent page uses stable video identity', selected.data(Qt.UserRole) == window.current)
        window.catalog.set_score(window.current, 5)
        window.library_controller.refresh([window.current])
        check('metadata refresh keeps selected native list row', selected.isValid() and recent.currentIndex().data(Qt.UserRole) == window.current)
        window.catalog.set_score(window.current, None)
        window.library_controller.refresh([window.current])
        window.favorite_button.click()
        library.show_mode('stars')
        stars = library.lists['stars']
        stars.setCurrentIndex(stars.model().index_for_id(window.current))
        check('favorite page has its own model and selection', stars.model() is not recent.model() and stars.currentIndex().data(Qt.UserRole) == window.current)
        library.remove_favorite.click()
        check('unfavorite updates native list without changing playback', stars.model().rowCount() == 0 and window.current == selected.data(Qt.UserRole) and window.player.get_state() == vlc.State.Paused)
        library.show_mode('files')
        other_folder = output / 'other-folder'
        other_folder.mkdir(exist_ok=True)
        browsing = window.load_folder(str(other_folder))
        check('native directory scan completes through controller', wait(lambda: not browsing.pending) and browsing.outcome.succeeded and window.library_controller.browsing.root == str(other_folder))
        check('browsing another directory preserves paused playback context', window.context is context and window.current == selected.data(Qt.UserRole) and window.player.get_state() == vlc.State.Paused)
        browsing = window.load_folder(str(sample_dir))
        check('native file tree can return to original directory', wait(lambda: not browsing.pending) and browsing.outcome.succeeded and library.tree.model().rowCount(library.tree.model().index(0, 0)) == 2)
        before_seek = max(0, window.player.get_time())
        target = min(window.player.get_length(), before_seek + 5000)
        QTest.keyClick(window.surface, Qt.Key_D)
        check('keyboard jump updates timeline and shows independent seek surface',
              abs(window.seekbar.visual_fraction - target / window.player.get_length()) < .0001 and
              window.seek_notice.overlay.isVisible() and
              window.player.video_get_marquee_int(vlc.VideoMarqueeOption.Enable) == 0)
        check('keyboard jump confirmation preserves paused timeline',
              wait(lambda: window.playback.pending_seek is None and abs(window.player.get_time() - target) < 100) and
              abs(window.seekbar.visual_fraction - target / window.player.get_length()) < .003 and
              not window.seekbar.animation.isActive())
        handle = int(window.surface.winId())
        frame = output / 'decoded-frame.png'
        check('VLC decoded frame snapshot', window.player.video_take_snapshot(0, str(frame), 320, 180) == 0 and wait(frame.exists))
        snapshot('playing')
        options = window.playback_options
        options.volume_popup.open_above()
        application.processEvents()
        check('volume owned surface above video', options.volume_popup.isVisible() and options.volume_popup.owner is window and hit_layer(options.volume_popup))
        check('volume compositor alpha has smooth corners', smooth_surface(options.volume_popup))
        window.volume.setValue(35)
        check('VLC volume command applied', wait(lambda: window.player.audio_get_volume() == 35))
        options.toggle_mute()
        check('VLC mute enabled', wait(lambda: window.player.audio_get_mute() == 1))
        options.toggle_mute()
        check('VLC mute disabled', wait(lambda: window.player.audio_get_mute() == 0))
        options.speed_popup.open_above()
        application.processEvents()
        check('speed compositor alpha has smooth corners', smooth_surface(options.speed_popup))
        options.set_rate(1.5)
        check('VLC speed applied', abs(window.player.get_rate() - 1.5) < .01)
        window.rating_dialog()
        check('rating owned surface above video', wait(lambda: options.rating_popup.isVisible() and hit_layer(options.rating_popup)))
        check('rating compositor alpha has smooth corners', smooth_surface(options.rating_popup))
        snapshot('rating')
        options.rating_popup.commit(9)
        check('nine point rating persisted', window.store.video(window.current)['score'] == 9)
        window.favorite_button.click()
        check('favorite filled', window.favorite_button.property('iconName') == 'starFilled')
        window.favorite_button.click()
        check('favorite can be cancelled', window.store.video(window.current)['star'] == 0)
        window.tags_dialog()
        panel, editor = options.tags_popup, options.tags_popup.editor
        check('tag owned surface above video', wait(lambda: panel.isVisible() and hit_layer(panel)))
        check('tag compositor alpha has smooth corners', smooth_surface(panel))
        # Send to the actual native QWindow so its pre-dispatch event is covered.
        point = editor.entry.mapTo(panel, editor.entry.rect().center())
        QTest.mouseClick(panel.windowHandle(), Qt.LeftButton, pos=point)
        QTest.keyClicks(editor.entry, 'demo-tag')
        QTest.qWait(80)
        check('tag input accepts native-window click', panel.isVisible() and editor.entry.hasFocus() and editor.entry.text() == 'demo-tag')
        editor.add_button.click()
        check('new tag is unselected', 'demo-tag' in editor.schema and not editor.chosen())
        apply_tags = window.apply_tags
        window.apply_tags = Mock(return_value=Operation.success())
        def choose_tag_menu(label, child=None):
            errors = []
            def choose():
                menu = application.activePopupWidget()
                try:
                    if menu is None:
                        raise AssertionError('context menu did not open')
                    if label == 'escape':
                        QTest.keyClick(menu.windowHandle(), Qt.Key_Escape)
                    else:
                        action = next(action for action in menu.actions() if action.text() == label)
                        if child is not None:
                            menu.setActiveAction(action)
                            QTest.keyClick(menu.windowHandle(), Qt.Key_Right)
                            submenu = action.menu()
                            QTest.qWait(50)
                            if not submenu.isVisible():
                                raise AssertionError('submenu did not open')
                            action = next(action for action in submenu.actions() if action.text() == child)
                            QTest.mouseClick(submenu.windowHandle(), Qt.LeftButton, pos=submenu.actionGeometry(action).center())
                        else:
                            QTest.mouseClick(menu.windowHandle(), Qt.LeftButton, pos=menu.actionGeometry(action).center())
                except Exception as error:
                    errors.append(str(error))
                finally:
                    if menu is not None:
                        menu.close()
            QTimer.singleShot(20, choose)
            editor.menu('demo-tag', editor.mapToGlobal(QPoint(40, 100)))
            QTest.qWait(300)
            if errors:
                raise AssertionError(errors)
        choose_tag_menu('设为父标签')
        check('parent menu native click preserves draft and surface',
              editor.schema['demo-tag']['is_parent'] and panel.isVisible() and window.apply_tags.call_count == 0)
        choose_tag_menu('escape')
        check('menu Escape cancels menu without closing tag surface', panel.isVisible() and window.apply_tags.call_count == 0)
        choose_tag_menu('取消父标签')
        check('unsetting parent keeps tag surface active', not editor.schema['demo-tag']['is_parent'] and panel.isVisible())
        editor.schema['target'] = {'name': 'target', 'kind': 'major', 'parent': None, 'is_parent': True}
        editor.rebuild()
        choose_tag_menu('移入父标签', 'target')
        check('native submenu click belongs to tag surface', editor.schema['demo-tag']['parent'] == 'target' and panel.isVisible())
        choose_tag_menu('移出父标签')
        check('detach menu keeps draft open', editor.schema['demo-tag']['parent'] is None and panel.isVisible() and window.apply_tags.call_count == 0)
        editor.schema.pop('target')
        editor.schema.pop('demo-tag')
        editor.rebuild()
        window.apply_tags = apply_tags
        snapshot('tags')
        # Opening another surface closes the active tag tool and must leave
        # activation inside the player, without an extra click to recover it.
        options.volume_popup.open_above()
        check('switching directly from editable tags to volume keeps surface visible',
              wait(lambda: not panel.isVisible() and options.volume_popup.isVisible() and hit_layer(options.volume_popup)))
        check('closing editable surface returns activation to player', wait(window.isActiveWindow))
        for label, surface in [('volume', options.volume_popup), ('speed', options.speed_popup),
                               ('rating', options.rating_popup), ('tags', options.tags_popup)]:
            surface.open_above()
            check('after parent menus: ' + label + ' can reopen', wait(lambda: surface.isVisible() and hit_layer(surface)))
            surface.dismiss()
        window.play_button.click()
        check('transport button resumes real playback', wait(lambda: button_matches(vlc.State.Playing)))
        from theme import apply_theme
        apply_theme(window, 'dark')
        check('appearance redraw preserves running transport action', button_matches(vlc.State.Playing))
        apply_theme(window, 'light')
        for cycle in range(3):
            window.enter_fullscreen()
            check(f'fullscreen {cycle}: active', wait(lambda: window.isFullScreen() and window.isActiveWindow()))
            check(f'fullscreen {cycle}: entering preserves playing icon pixels', button_matches(vlc.State.Playing))
            fullscreen = window.video_fullscreen
            fullscreen.timer.stop()
            center = window.canvas.mapToGlobal(window.canvas.rect().center())
            bottom = window.canvas.mapToGlobal(QPoint(window.canvas.width() // 2, window.canvas.height() - 2))
            fullscreen.last_cursor, fullscreen.last_activity = center, 0
            fullscreen.poll(center)
            check(f'fullscreen {cycle}: idle hidden', not fullscreen.overlay.isVisible())
            check(f'fullscreen {cycle}: title and Qt cursor hide with controls',
                  not fullscreen.title.isVisible() and fullscreen.cursor.hidden and
                  window.surface.cursor().shape() == Qt.BlankCursor)
            native_cursor = fullscreen.cursor
            saved_classes = dict(native_cursor.native_classes)
            check(f'fullscreen {cycle}: native video cursor classes hidden',
                  len(saved_classes) >= 2 and all(native_cursor.user.GetClassLongPtrW(hwnd, -12) == 0 for hwnd in saved_classes))
            if cycle == 0:
                video_geometry = window.surface.geometry()
                window.advance(1)
                check('fullscreen switch: next clip actually plays', wait(lambda: window.current == context.folders[str(sample_dir)][1][1][0] and button_matches(vlc.State.Playing)))
                fullscreen.poll(center)
                check('fullscreen switch: title updates without showing or shrinking video',
                      fullscreen.title.filename == 'second.mp4' and not fullscreen.title.isVisible() and
                      window.player_header.isHidden() and window.surface.geometry() == video_geometry)
                def recreated_cursor_hidden():
                    fullscreen.poll(center)
                    return len(native_cursor.native_classes) >= 2 and all(native_cursor.user.GetClassLongPtrW(hwnd, -12) == 0 for hwnd in native_cursor.native_classes)
                check('fullscreen switch: recreated video cursor classes stay hidden', wait(recreated_cursor_hidden))
                saved_classes = dict(native_cursor.native_classes)
            fullscreen.poll(bottom)
            application.processEvents()
            check(f'fullscreen {cycle}: bottom reveals native controls', fullscreen.overlay.isVisible() and hit_layer(fullscreen.overlay))
            check(f'fullscreen {cycle}: title and cursor restore with controls',
                  fullscreen.title.isVisible() and not fullscreen.cursor.hidden and
                  window.surface.cursor().shape() != Qt.BlankCursor and
                  fullscreen.title.filename == window.store.video(window.current)['name'])
            check(f'fullscreen {cycle}: native video cursor classes restored',
                  not native_cursor.native_classes and all(native_cursor.user.GetClassLongPtrW(hwnd, -12) == cursor for hwnd, (name, cursor) in saved_classes.items()))
            check(f'fullscreen {cycle}: compositor alpha has smooth corners', smooth_surface(fullscreen.overlay))
            fullscreen.last_activity = 0
            fullscreen.poll(bottom)
            check(f'fullscreen {cycle}: bottom stationary stays visible', fullscreen.overlay.isVisible())
            check(f'fullscreen {cycle}: timeline animation survives reparenting', timeline_moves_between_decoder_polls())
            window.play_button.click()
            check(f'fullscreen {cycle}: button pauses and updates icon', wait(lambda: button_matches(vlc.State.Paused)))
            window.play_button.click()
            check(f'fullscreen {cycle}: button resumes and updates icon', wait(lambda: button_matches(vlc.State.Playing)))
            window.rating_dialog()
            fullscreen.poll(bottom)
            check(f'fullscreen {cycle}: rating stays above controls and video', wait(lambda: options.rating_popup.isVisible() and hit_layer(options.rating_popup)))
            snapshot(f'fullscreen-{cycle}')
            options.dismiss()
            fullscreen.last_cursor, fullscreen.last_activity = center, 0
            fullscreen.was_interacting = False
            fullscreen.poll(center)
            exit_classes = dict(fullscreen.cursor.native_classes)
            check(f'fullscreen {cycle}: idle cursor hidden before exit',
                  fullscreen.cursor.hidden and len(exit_classes) >= 2)
            window.exit_fullscreen()
            application.processEvents()
            check(f'fullscreen {cycle}: handle and left sidebar restored', int(window.surface.winId()) == handle and window.library_view.isVisible() and window.playback_panel.parentWidget().objectName() == 'playerCard')
            check(f'fullscreen {cycle}: exit restores title layout and cursor',
                  window.player_header.isVisible() and not fullscreen.title.isVisible() and
                  not fullscreen.cursor.hidden and not fullscreen.cursor.native_classes and
                  all(native_cursor.user.GetClassLongPtrW(hwnd, -12) == cursor for hwnd, (name, cursor) in exit_classes.items()))
            check(f'fullscreen {cycle}: exit preserves playing icon pixels', button_matches(vlc.State.Playing))
        window.enter_fullscreen()
        check('ownership: fullscreen active', wait(lambda: window.isFullScreen() and window.isActiveWindow()))
        fullscreen = window.video_fullscreen
        bottom = window.canvas.mapToGlobal(QPoint(window.canvas.width() // 2, window.canvas.height() - 2))
        fullscreen.poll(bottom)
        window.tags_dialog()
        panel, editor = options.tags_popup, options.tags_popup.editor
        check('fullscreen tag surface presented', wait(lambda: panel.isVisible() and hit_layer(panel)))
        point = editor.entry.mapTo(panel, editor.entry.rect().center())
        QTest.mouseClick(panel.windowHandle(), Qt.LeftButton, pos=point)
        QTest.keyClicks(editor.entry, 'w a r x')
        QTest.qWait(80)
        check('fullscreen editable tool keeps focus and player activation', panel.isActiveWindow() and editor.entry.hasFocus() and editor.entry.text() == 'w a r x')
        editor.entry.setText('demo-tag')
        editor.add_button.click()
        apply_tags = window.apply_tags
        window.apply_tags = Mock(return_value=Operation.success())
        choose_tag_menu('设为父标签')
        check('fullscreen parent menu preserves tag surface and controls',
              panel.isVisible() and fullscreen.overlay.isVisible() and editor.schema['demo-tag']['is_parent'] and window.apply_tags.call_count == 0)
        editor.schema.pop('demo-tag')
        editor.rebuild()
        window.apply_tags = apply_tags
        middle = window.canvas.mapToGlobal(window.canvas.rect().center())
        fullscreen.last_cursor, fullscreen.last_activity = middle, 0
        fullscreen.poll(middle)
        check('fullscreen controls remain during owned editing', fullscreen.overlay.isVisible() and panel.isVisible())
        # A separate test window represents switching applications; all of this
        # happens on the guarded private desktop, without hardware input.
        other = QWidget()
        other.resize(300, 200)
        other.show()
        other.activateWindow()
        check('ownership: separate window active', wait(other.isActiveWindow))
        fullscreen.poll(middle)
        check('ownership: no surfaces remain over another window', wait(lambda: not fullscreen.overlay.isVisible() and not options.popup_visible()))
        check('ownership: unrelated window restores cursor and hides title', not fullscreen.title.isVisible() and not fullscreen.cursor.hidden)
        panel.open_above()
        check('ownership: inactive player cannot reopen a hover surface', not panel.isVisible())
        other.close()
        window.activateWindow()
        check('ownership: player reactivated', wait(window.isActiveWindow))
        fullscreen.poll(bottom)
        check('ownership: controls return over the player', wait(lambda: fullscreen.overlay.isVisible() and hit_layer(fullscreen.overlay)))
        fullscreen.last_cursor, fullscreen.last_activity = middle, 0
        fullscreen.was_interacting = False
        fullscreen.poll(middle)
        minimize_classes = dict(fullscreen.cursor.native_classes)
        check('ownership: idle cursor hidden before minimizing', fullscreen.cursor.hidden and len(minimize_classes) >= 2)
        window.showMinimized()
        check('ownership: minimizing hides all surfaces', wait(lambda: not fullscreen.overlay.isVisible() and not options.popup_visible()))
        fullscreen.poll(middle)
        check('ownership: minimizing restores cursor and hides title',
              not fullscreen.title.isVisible() and not fullscreen.cursor.hidden and
              all(fullscreen.cursor.user.GetClassLongPtrW(hwnd, -12) == cursor for hwnd, (name, cursor) in minimize_classes.items()))
        window.showFullScreen()
        window.activateWindow()
        check('ownership: fullscreen restored', wait(window.isActiveWindow))
        window.exit_fullscreen()
        check('private desktop never switched', require_private_desktop() == desktop)
    except Exception:
        report['error'] = traceback.format_exc()
        raise
    finally:
        window.tag_drafts.discard_all()
        window.close()
        QThreadPool.globalInstance().waitForDone()
        window.thumbnails.pool.waitForDone()
        window.store.db.close()
        (output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    target = Path(sys.argv[1]).absolute()
    target.mkdir(parents=True, exist_ok=True)
    with (target / 'console.txt').open('w', encoding='utf-8') as stream:
        sys.stdout = sys.stderr = stream
        import faulthandler
        faulthandler.enable(file=stream)
        try:
            result = run(target)
            print(f"Passed {len(result['checks'])} native checks")
        except Exception:
            traceback.print_exc()
            sys.exit(1)
