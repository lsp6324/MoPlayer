"""Cursor ownership for the Qt video host and its native VLC child windows.

VLC 3.0 creates distinct classes for each video output:
https://github.com/videolan/vlc/blob/3.0.21/modules/video_output/win32/events.c
Only those classes below this player's HWND are changed; no global cursor
visibility counter, input hook, or window-procedure replacement is used.
"""
import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication


class VideoCursor:
    def __init__(self, surface):
        self.surface = surface
        self.hidden = False
        self.original_cursor = None
        self.native_classes = {}
        self.user = None
        if QApplication.platformName() == 'windows':
            import ctypes
            from ctypes import wintypes as w
            self.ctypes, self.w = ctypes, w
            self.user = ctypes.WinDLL('user32', use_last_error=True)
            self.enum_proc = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
            signatures = {
                'EnumChildWindows': ([w.HWND, self.enum_proc, w.LPARAM], w.BOOL),
                'GetClassNameW': ([w.HWND, w.LPWSTR, ctypes.c_int], ctypes.c_int),
                'GetClassLongPtrW': ([w.HWND, ctypes.c_int], ctypes.c_size_t),
                'SetClassLongPtrW': ([w.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_size_t),
                'GetWindowThreadProcessId': ([w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
                'GetCursorPos': ([ctypes.POINTER(w.POINT)], w.BOOL),
                'WindowFromPoint': ([w.POINT], w.HWND),
                'IsChild': ([w.HWND, w.HWND], w.BOOL),
                'SetCursor': ([w.HANDLE], w.HANDLE),
                'LoadCursorW': ([w.HINSTANCE, ctypes.c_void_p], w.HANDLE),
            }
            for name, (arguments, result) in signatures.items():
                function = getattr(self.user, name)
                function.argtypes, function.restype = arguments, result

    def class_name(self, hwnd):
        name = self.ctypes.create_unicode_buffer(256)
        self.user.GetClassNameW(hwnd, name, len(name))
        return name.value

    def set_hidden(self, hidden):
        changed = hidden != self.hidden
        if changed:
            if hidden:
                self.original_cursor = (QCursor(self.surface.cursor())
                    if self.surface.testAttribute(Qt.WA_SetCursor) else None)
                self.surface.setCursor(Qt.BlankCursor)
            elif self.original_cursor is not None:
                self.surface.setCursor(self.original_cursor)
            else:
                self.surface.unsetCursor()
            self.hidden = hidden
        if self.user is None:
            return
        root = int(self.surface.winId())
        # A media change can destroy/recreate the native output while idle.
        # Match the unique class name as well as HWND to reject reused handles.
        for hwnd, (name, cursor) in list(self.native_classes.items()):
            if self.class_name(hwnd) != name:
                self.native_classes.pop(hwnd)
            elif not hidden:
                self.user.SetClassLongPtrW(hwnd, -12, cursor)  # GCLP_HCURSOR
                self.native_classes.pop(hwnd)
        if hidden:
            def collect(hwnd, unused):
                nonlocal changed
                name = self.class_name(hwnd)
                process = self.w.DWORD()
                self.user.GetWindowThreadProcessId(hwnd, self.ctypes.byref(process))
                if (process.value == os.getpid() and
                        name.startswith(('VLC video main ', 'VLC video output '))):
                    if hwnd not in self.native_classes:
                        original = next((saved for class_name, saved in self.native_classes.values()
                                         if class_name == name), self.user.GetClassLongPtrW(hwnd, -12))
                        self.native_classes[hwnd] = (name, original)
                    if self.user.GetClassLongPtrW(hwnd, -12):
                        self.user.SetClassLongPtrW(hwnd, -12, 0)
                        changed = True
                return True
            self.user.EnumChildWindows(root, self.enum_proc(collect), 0)
        if changed:
            # Refresh only when the real pointer is over this video HWND tree.
            # This never moves the pointer or alters another application's cursor.
            point = self.w.POINT()
            if self.user.GetCursorPos(self.ctypes.byref(point)):
                hit = self.user.WindowFromPoint(point)
                if hit == root or self.user.IsChild(root, hit):
                    cursor = None if hidden else self.user.GetClassLongPtrW(hit, -12)
                    if not hidden and not cursor:
                        cursor = self.user.LoadCursorW(None, 32512)  # IDC_ARROW
                    self.user.SetCursor(cursor)
