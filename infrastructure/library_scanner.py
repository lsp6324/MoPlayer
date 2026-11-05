"""Adapter for the existing scan and playback-order rules; no UI ownership."""
from application.library import NavigationStep
from core import ScanRequired, scan


class LibraryScanner:
    def __init__(self, store):
        self.store = store

    def scan(self, folder, cancel):
        return scan(folder, self.store, cancel)

    def step(self, context, location, direction):
        try:
            return NavigationStep(context.step(location, direction))
        except ScanRequired:
            return NavigationStep(needs_scan=True)

    def step_loaded(self, context, location, direction, cancel):
        return context.step_loaded(location, direction, self.store, cancel)
