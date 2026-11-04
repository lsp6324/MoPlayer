"""Shared desktop theme, including custom-painted list rows."""
from string import Template
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QAbstractButton, QApplication

TOKENS = {
    'bg': '#1a1d23', 'surface': '#1a1d23', 'surface_plain': '#22262e',
    'library_bg': '#22262e',
    'surface_dim': '#191c21', 'hover': '#2a303a', 'pressed': '#303949',
    'line': '#303640', 'line_soft': '#272c34', 'line_strong': '#414957',
    'text': '#e3e7ee', 'text_strong': '#f2f4f8', 'text_mid': '#cbd2dd',
    'text_dim': '#a6aebc', 'text_faint': '#919bac', 'disabled': '#667080',
    'accent': '#77a7ff', 'accent_dark': '#91b8ff', 'accent_soft': '#25344b',
    'accent_tint': '#202d42', 'accent_line': '#526d94', 'accent_ring': '#77a7ff',
    'progress': '#77a7ff', 'track': '#343c49', 'scroll': '#4a5362',
    'button_fill': '#477ce5', 'button_hover': '#568bf1',
    'selected': '#263a57', 'thumb': '#101216', 'status': '#a6aebc',
    'radius_sm': '6px', 'radius_md': '10px', 'font_body': '13px',
    'font_small': '12px', 'font_mini': '12px', 'font_brand': '14px',
}
LIGHT_TOKENS = dict(TOKENS, **{
    'bg': '#f8f9fb', 'surface': '#f8f9fb', 'surface_plain': '#ffffff',
    'library_bg': '#edf0f4',
    'surface_dim': '#eef0f4', 'hover': '#e9edf3', 'pressed': '#dce5f3',
    'line': '#d8dde5', 'line_soft': '#e5e8ee', 'line_strong': '#c7ced9',
    'text': '#303744', 'text_strong': '#1d2531', 'text_mid': '#434e5e',
    'text_dim': '#616d7e', 'text_faint': '#6d798b', 'disabled': '#969eab',
    'accent': '#285fbd', 'accent_dark': '#194caa', 'accent_soft': '#e4ecfa',
    'accent_tint': '#e7eefb', 'accent_line': '#a3b7d6', 'accent_ring': '#3875da',
    'progress': '#3975da', 'track': '#dae1ed', 'scroll': '#b6c0ce',
    'selected': '#e1ebfb', 'status': '#616d7e',
})

STYLE_TEMPLATE = '''
QMainWindow { background:$bg; }
QWidget { font-family:"Microsoft YaHei UI"; font-size:$font_body; color:$text; background:transparent; }
QDialog,QMessageBox { background:$surface; }
QFrame#topBar,QFrame#libraryCard,QFrame#playerCard { background:transparent; border:none; border-radius:0; }
QFrame#libraryCard { background:$library_bg; }
QWidget#playerEmpty { background:#101216; }
QWidget#playbackPanel { border-top:1px solid $line_soft; }
QWidget#classifyBar { border:none; }
QFrame#floatingSurface,QFrame#playbackPopover { background:transparent; border:none; }
QFrame#playbackPopover QPushButton[role="tagChip"] { border:1px solid $line; border-radius:15px; background:transparent; padding:4px 12px; }
QFrame#playbackPopover QPushButton[role="tagChip"]:hover { background:$hover; }
QFrame#playbackPopover QPushButton[role="tagChip"]:checked { color:$accent; background:$accent_soft; border-color:$accent_line; }
QFrame#playbackPopover QPushButton[role="tagChip"][inherited="true"] { color:$accent; border-color:$accent_line; border-style:dashed; }
QFrame#playbackPopover QToolButton { background:transparent; border:none; color:$text_dim; padding:0; }
QFrame#playbackPopover QToolButton:hover { color:$accent; }
QFrame#tagDropSection[dropTarget="true"] { background:$accent_tint; border-radius:6px; }
QFrame#playbackPopover QPushButton#tagManager:checked { color:$accent; background:$accent_soft; }
QFrame#playbackPopover QLabel#tagError { color:$text_dim; font-size:$font_small; }
QPushButton[role="rateOption"] { background:transparent; border:1px solid transparent; padding:3px 12px; }
QPushButton[role="rateOption"]:hover { background:$hover; }
QPushButton[role="rateOption"]:checked,QPushButton[role="action"]:checked { color:$accent; background:$accent_soft; }
QLabel[role="brand"] { font-family:"Segoe UI"; font-size:$font_brand; font-weight:600; color:$text_strong; }
QLabel[role="sectionTitle"] { font-size:15px; font-weight:600; color:$text_strong; }
QLabel[role="muted"],QLabel[role="badge"] { color:$text_dim; font-size:$font_small; }
QLabel#nowPlaying { font-size:16px; font-weight:600; color:$text_strong; }
QLabel#mediaMetadata { font-size:$font_small; color:$text_dim; }
QLabel#directoryPath { color:$text_dim; font-size:$font_small; }
QLabel[role="timecode"] { font-family:"Segoe UI"; font-size:$font_small; color:$text_dim; }
QPushButton { border:1px solid $line; border-radius:$radius_sm; background:$surface_plain; padding:7px 12px; color:$text; }
QPushButton:hover { background:$hover; border-color:$line_strong; }
QPushButton:pressed { background:$pressed; }
QPushButton:focus { border-color:$accent_ring; }
QPushButton:disabled { color:$disabled; border-color:transparent; background:transparent; }
QPushButton[role="primary"],QPushButton#playButton { background:$button_fill; color:white; border:1px solid $button_fill; }
QPushButton[role="primary"]:hover,QPushButton#playButton:hover { background:$button_hover; border-color:$button_hover; }
QPushButton[role="nav"],QPushButton[role="round"],QPushButton[role="action"],QPushButton[role="quiet"] { background:transparent; border:1px solid transparent; }
QPushButton[role="nav"]:hover,QPushButton[role="round"]:hover,QPushButton[role="action"]:hover,QPushButton[role="quiet"]:hover { background:$hover; }
QPushButton[role="nav"]:focus,QPushButton[role="round"]:focus,QPushButton[role="action"]:focus,QPushButton[role="quiet"]:focus { border-color:$accent_ring; }
QPushButton[role="tab"] { background:transparent; border:1px solid transparent; color:$text_dim; padding:7px 12px; }
QPushButton[role="tab"]:hover { color:$text; background:$hover; }
QPushButton[role="tab"]:checked { color:$text_strong; background:$hover; }
QPushButton[role="tab"]:focus { border-color:$accent_ring; }
QPushButton#playButton { border-radius:22px; padding:0; }
QPushButton#playButton:disabled { background:$track; border-color:$track; }
QPushButton[role="nav"],QPushButton[role="round"] { padding:0; }
QPushButton[role="caption"] { background:transparent; border:none; border-radius:0; padding:0; }
QPushButton[role="caption"]:hover { background:$hover; }
QPushButton[role="caption"]:pressed { background:$pressed; }
QPushButton[role="caption"]:focus { border-bottom:2px solid $accent_ring; }
QPushButton#closeWindow:hover { background:#e94a53; }
QPushButton#closeWindow:pressed { background:#d83b45; }
QPushButton::menu-indicator { image:none; width:0; }
QTreeView#libraryTree,QListWidget#sidebarList { border:none; outline:none; background:transparent; padding:0; selection-background-color:transparent; }
QTreeView#libraryTree::branch { background:transparent; }
QTreeView#libraryTree::item { min-height:30px; }
QTreeView#libraryTree::item:selected { color:$accent; }
QListWidget { border:1px solid $line; background:$surface_plain; border-radius:$radius_sm; padding:4px; outline:none; }
QListWidget::item:selected { background:$selected; color:$text_strong; }
QLineEdit,QComboBox,QPlainTextEdit,QTextEdit { background:$surface_plain; border:1px solid $line; border-radius:$radius_sm; padding:8px; selection-background-color:$button_fill; selection-color:white; }
QLineEdit:focus,QComboBox:focus { border-color:$accent_ring; }
QComboBox::drop-down { border:none; width:26px; }
QComboBox QAbstractItemView { background:$surface_plain; color:$text; selection-background-color:$selected; selection-color:$text_strong; }
QSlider::groove:horizontal { height:4px; border-radius:2px; background:$track; }
QSlider::sub-page:horizontal { background:$progress; border-radius:2px; }
QSlider::handle:horizontal { width:10px; height:10px; margin:-4px 0; border-radius:6px; background:$progress; border:1px solid $progress; }
QSlider::handle:horizontal:hover { background:$text_strong; border-color:$text_strong; }
QSlider::sub-page:horizontal:disabled,QSlider::handle:horizontal:disabled { background:$track; border-color:$track; }
QScrollBar:vertical { background:transparent; width:6px; margin:2px 0; }
QScrollBar::handle:vertical { background:$scroll; min-height:28px; border-radius:3px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical { background:transparent; }
QScrollBar:horizontal { background:transparent; height:6px; }
QScrollBar::handle:horizontal { background:$scroll; min-width:28px; border-radius:3px; }
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal { width:0; }
QSplitter::handle { background:$library_bg; border-right:1px solid $line; }
QSplitter::handle:hover { border-right:1px solid $accent_line; }
QStatusBar { background:$bg; color:$status; font-size:$font_mini; padding:0 12px; }
QStatusBar::item { border:none; }
QLabel#backgroundPreview { background:$bg; border:1px solid $line; border-radius:$radius_sm; color:$text_dim; }
QMenu { background:$surface_plain; color:$text; border:1px solid $line; padding:6px; }
QMenu::item { padding:8px 26px 8px 12px; border-radius:4px; }
QMenu::item:selected { background:$hover; }
QMenu::separator { height:1px; background:$line; margin:5px 8px; }
QToolTip { background:$surface_plain; color:$text; border:1px solid $line; padding:7px; }
'''
STYLE = Template(STYLE_TEMPLATE).substitute(**TOKENS)


def theme_tokens(window=None):
    return LIGHT_TOKENS if getattr(window, 'theme', 'dark') == 'light' else TOKENS


def apply_theme(window, theme=None):
    from ui import icon
    window.theme = theme or window.appearance.theme
    colors = theme_tokens(window)
    window.setStyleSheet(Template(STYLE_TEMPLATE).substitute(**colors))
    palette = QPalette()
    for role, key in ((QPalette.Window, 'surface'), (QPalette.WindowText, 'text'),
                      (QPalette.Base, 'surface_plain'), (QPalette.AlternateBase, 'surface_dim'),
                      (QPalette.Text, 'text'), (QPalette.Button, 'surface_plain'),
                      (QPalette.ButtonText, 'text'), (QPalette.Highlight, 'selected'),
                      (QPalette.HighlightedText, 'text_strong'), (QPalette.PlaceholderText, 'text_dim')):
        palette.setColor(role, QColor(colors[key]))
    window.setPalette(palette)
    window.canvas.theme = window.theme
    window.canvas.update()
    for control in window.findChildren(QAbstractButton):
        if control is window.play_button:
            continue
        symbol = control.property('iconName')
        if symbol:
            primary = control.property('role') == 'primary'
            color = '#ffffff' if primary else colors['accent'] if symbol == 'starFilled' else colors['text_mid']
            control.setIcon(icon(symbol, color))
    window.sync_play_button(force=True)
    for view in (window.tree, window.sidebar_list):
        view.setPalette(palette)
        view.viewport().update()
    window.control_row.adapt()
    if hasattr(window, 'playback_options'):
        for panel in window.playback_options.panels:
            panel.setStyleSheet(Template(STYLE_TEMPLATE).substitute(**colors))
            panel.set_colors(colors['surface_plain'], colors['line'])
        rating = window.playback_options.rating_popup.hearts
        rating.outline_color = QColor(colors['text_faint'])
        rating.fill_color = QColor(colors['accent'])
        rating.update()
        window.playback_options.refresh_icon()
    window.apply_native_corners()
    if QApplication.platformName() != 'windows':
        return
    try:
        import ctypes
        dark = ctypes.c_int(window.theme == 'dark')
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(int(window.winId())), 20, ctypes.byref(dark), ctypes.sizeof(dark))
    except (AttributeError, OSError):
        pass
