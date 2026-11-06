"""Source and PyInstaller entry point; application code lives in src/moplayer."""
from pathlib import Path
import sys

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from moplayer.app import cli

if __name__ == '__main__':
    cli()
