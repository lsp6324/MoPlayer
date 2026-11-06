"""Compatibility entry for the current native tag-hierarchy verification.

Tags now live in an autosaving popover, with an explicit score action. The old
script waited for a modal tag dialog and automatic score prompt, and expected
tag prefixes in filenames; those behaviors have intentionally been removed.

Keep the command usable by running the shared real-window checks for hierarchy
filtering, tag selection, context-menu rename, global references, title/card
refresh, playback and frozen queues. Storage identity and interrupted rename
recovery are covered independently in test_tag_hierarchy and test_tag_rename.
"""
from tools.verify.verify_catalog import run

__all__ = ['run']
