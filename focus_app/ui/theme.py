"""공통 스타일. 시스템 팔레트(palette(...))를 써서 라이트/다크 모드를 모두 따릅니다."""

from __future__ import annotations

ACCENT = "#2e9e5b"  # 집중 시작 / 진행 중 강조색
ACCENT_HOVER = "#36b268"
WARN = "#d9822b"
DANGER = "#c0392b"

STYLESHEET = f"""
QWidget {{ font-size: 10pt; }}

QLabel#appTitle {{ font-size: 16pt; font-weight: 600; }}
QLabel#sectionTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#modeTitle {{ font-size: 15pt; font-weight: 600; }}
QLabel#muted {{ color: palette(placeholder-text); }}
QLabel#hint {{ color: palette(placeholder-text); font-size: 9pt; }}

QFrame#card {{
    background: palette(base);
    border: 1px solid palette(mid);
    border-radius: 10px;
}}

QListWidget#modeList {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget#modeList::item {{
    padding: 0;
    margin: 2px 0;
    border-radius: 8px;
}}
QListWidget#modeList::item:hover {{ background: palette(alternate-base); }}
QListWidget#modeList::item:selected {{
    background: rgba(46, 158, 91, 0.22);
    border-left: 4px solid {ACCENT};
}}

QListWidget#pickList {{
    border: 1px solid palette(mid);
    border-radius: 8px;
    background: palette(base);
    outline: none;
    padding: 4px;
}}
QListWidget#pickList::item {{ border-radius: 6px; padding: 2px 4px; }}
QListWidget#pickList::item:hover {{ background: palette(alternate-base); }}

QListWidget#appList {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget#appList::item {{ border-radius: 6px; }}
QListWidget#appList::item:hover {{ background: palette(alternate-base); }}

QPushButton {{ padding: 6px 14px; border-radius: 6px; }}

QPushButton#primary {{
    background: {ACCENT};
    color: white;
    border: none;
    font-size: 12pt;
    font-weight: 600;
    padding: 12px 28px;
    border-radius: 8px;
}}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: palette(mid); color: palette(placeholder-text); }}

QPushButton#secondary {{
    border: 1px solid {ACCENT};
    color: {ACCENT};
    background: transparent;
    font-weight: 600;
    padding: 6px 14px;
}}
QPushButton#secondary:hover {{ background: rgba(46, 158, 91, 0.15); }}
QPushButton#secondary:disabled {{ border-color: palette(mid); color: palette(placeholder-text); }}

QPushButton#chip {{
    padding: 6px 12px;
    border: 1px solid palette(mid);
    border-radius: 14px;
    background: transparent;
}}
QPushButton#chip:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: white;
    font-weight: 600;
}}

QPushButton#iconButton {{
    border: none;
    background: transparent;
    padding: 4px 8px;
    color: palette(placeholder-text);
    font-size: 11pt;
}}
QPushButton#iconButton:hover {{ color: {DANGER}; }}

QPushButton#linkButton {{
    border: none;
    background: transparent;
    color: palette(link);
    padding: 4px 6px;
}}
QPushButton#linkButton:hover {{ text-decoration: underline; }}

QPushButton#danger {{
    border: 1px solid {DANGER};
    color: {DANGER};
    background: transparent;
    padding: 10px 22px;
    border-radius: 8px;
    font-weight: 600;
}}

QLabel#timer {{ font-size: 54pt; font-weight: 300; }}
QLabel#runningMode {{ font-size: 17pt; font-weight: 600; color: {ACCENT}; }}

QFrame#banner {{
    background: rgba(217, 130, 43, 0.15);
    border: 1px solid {WARN};
    border-radius: 8px;
}}
QFrame#notice {{
    background: rgba(46, 158, 91, 0.15);
    border: 1px solid {ACCENT};
    border-radius: 8px;
}}

QProgressBar {{
    border: none;
    background: palette(mid);
    border-radius: 3px;
    max-height: 6px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
"""
