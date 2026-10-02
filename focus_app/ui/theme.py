"""공통 스타일. 시스템 팔레트(palette(...))와 반투명 회색을 써서 라이트/다크 모드를 모두 따릅니다.

디자인 원칙
* 모서리는 둥글게: 버튼·입력칸 10px, 카드 14px, 칩·작은 버튼은 알약 모양
* 강조색은 초록 하나(ACCENT). 체크박스·라디오·포커스 테두리·기본 버튼이 모두 같은 색
* 각 대화상자의 기본 버튼(저장·추가·확인·시작)은 초록으로 채우고, 나머지 버튼은 옅은 회색
* 화면 확대·축소는 이 스타일의 pt/px 값을 비율대로 바꿔 다시 적용합니다 (``build_stylesheet``).
  그래서 글자 크기·여백은 위젯에 직접 쓰지 말고 여기에 objectName으로 둡니다.
"""

from __future__ import annotations

import re
from pathlib import Path

ACCENT = "#2e9e5b"  # 집중 시작 / 진행 중 강조색
ACCENT_HOVER = "#36b268"
ACCENT_PRESSED = "#278a4f"
WARN = "#d9822b"
DANGER = "#c0392b"

# 라이트/다크 어디서나 자연스러운 반투명 회색 (배경 위에 겹쳐 그림)
SOFT = "rgba(127, 127, 127, 0.14)"
SOFT_HOVER = "rgba(127, 127, 127, 0.24)"
SOFT_PRESSED = "rgba(127, 127, 127, 0.32)"
LINE = "rgba(127, 127, 127, 0.32)"

R_CONTROL = 10  # 버튼·입력칸
R_CARD = 14  # 카드·목록 틀

# QSS의 url()은 슬래시 경로를 씀. exe 배포본에서도 focus_app/assets가 함께 들어감
_ASSETS = (Path(__file__).resolve().parent.parent / "assets").as_posix()

_TEMPLATE = f"""
QWidget {{ font-size: 10pt; }}

/* ---------------------------------------------------------------- 글자 */
QLabel#appTitle {{ font-size: 16pt; font-weight: 600; }}
QLabel#sectionTitle {{ font-size: 11pt; font-weight: 600; }}
QLabel#modeTitle {{ font-size: 15pt; font-weight: 600; }}
QLabel#muted {{ color: palette(placeholder-text); }}
QLabel#hint {{ color: palette(placeholder-text); font-size: 9pt; }}
QLabel#warnText {{ color: {WARN}; font-size: 9pt; }}
QLabel#timer {{ font-size: 54pt; font-weight: 300; }}
QLabel#runningMode {{ font-size: 17pt; font-weight: 600; color: {ACCENT}; }}
QLabel#modeRowTitle {{ font-size: 11pt; font-weight: 600; background: transparent; }}
QLabel#endIcon {{ font-size: 34pt; }}
QLabel#unlockCode {{
    font-family: Consolas, monospace;
    font-size: 16pt;
    background: rgba(127, 127, 127, 0.14);
    border: 1px solid rgba(127, 127, 127, 0.32);
    padding: 16px;
    border-radius: 14px;
    letter-spacing: 1px;
}}
QLineEdit#unlockInput {{ font-family: Consolas, monospace; font-size: 16pt; }}
QLabel#unlockExample {{ font-family: Consolas, monospace; color: palette(placeholder-text); }}

/* ---------------------------------------------------------------- 카드·띠 */
QFrame#card {{
    background: palette(base);
    border: 1px solid {LINE};
    border-radius: {R_CARD}px;
}}
QFrame#banner {{
    background: rgba(217, 130, 43, 0.15);
    border: 1px solid {WARN};
    border-radius: 12px;
}}
QFrame#card[leftPanel="true"] {{ min-width: 220px; max-width: 220px; }}
QFrame#notice {{
    background: rgba(46, 158, 91, 0.15);
    border: 1px solid {ACCENT};
    border-radius: 12px;
}}

/* ---------------------------------------------------------------- 버튼 */
QPushButton {{
    background: {SOFT};
    border: 1px solid {LINE};
    border-radius: {R_CONTROL}px;
    padding: 7px 16px;
    min-height: 18px;
}}
QPushButton:hover {{ background: {SOFT_HOVER}; }}
QPushButton:pressed {{ background: {SOFT_PRESSED}; }}
QPushButton:disabled {{
    color: palette(placeholder-text);
    background: rgba(127, 127, 127, 0.06);
    border-color: rgba(127, 127, 127, 0.16);
}}
/* 대화상자의 기본 동작(저장·추가·확인 등)은 초록으로 채움 */
QPushButton:default {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: white;
    font-weight: 600;
}}
QPushButton:default:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton:default:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton:default:disabled {{
    background: rgba(46, 158, 91, 0.30);
    border-color: transparent;
    color: rgba(255, 255, 255, 0.65);
}}

QPushButton#primary {{
    background: {ACCENT};
    color: white;
    border: none;
    font-size: 12pt;
    font-weight: 600;
    padding: 12px 30px;
    border-radius: 22px;
}}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#primary:disabled {{ background: palette(mid); color: palette(placeholder-text); }}

QPushButton#secondary {{
    border: 1px solid {ACCENT};
    color: {ACCENT};
    background: transparent;
    font-weight: 600;
    padding: 7px 16px;
    border-radius: 17px;
}}
QPushButton#secondary:hover {{ background: rgba(46, 158, 91, 0.14); }}
QPushButton#secondary:pressed {{ background: rgba(46, 158, 91, 0.24); }}
QPushButton#secondary:disabled {{ border-color: {LINE}; color: palette(placeholder-text); }}

QPushButton#chip {{
    padding: 6px 14px;
    border: 1px solid {LINE};
    border-radius: 16px;
    background: transparent;
}}
QPushButton#chip:hover {{ background: {SOFT}; }}
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
    border-radius: 14px;
    color: palette(placeholder-text);
    font-size: 11pt;
}}
QPushButton#iconButton:hover {{ color: {DANGER}; background: rgba(192, 57, 43, 0.12); }}

QPushButton#linkButton {{
    border: none;
    background: transparent;
    color: palette(link);
    padding: 5px 10px;
    border-radius: {R_CONTROL}px;
}}
QPushButton#linkButton:hover {{ background: {SOFT}; }}
/* 링크·아이콘 버튼은 대화상자의 기본 버튼이 되더라도 모양을 바꾸지 않음 */
QPushButton#linkButton:default {{ background: transparent; border: none; color: palette(link); font-weight: normal; }}
QPushButton#iconButton:default {{ background: transparent; border: none; font-weight: normal; }}

QPushButton#danger {{
    border: 1px solid {DANGER};
    color: {DANGER};
    background: transparent;
    padding: 10px 24px;
    border-radius: 20px;
    font-weight: 600;
}}
QPushButton#danger:hover {{ background: rgba(192, 57, 43, 0.12); }}

/* ---------------------------------------------------------------- 입력칸 */
QLineEdit {{
    background: palette(base);
    border: 1px solid {LINE};
    border-radius: {R_CONTROL}px;
    padding: 7px 12px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}

QComboBox {{
    background: palette(base);
    border: 1px solid {LINE};
    border-radius: {R_CONTROL}px;
    padding: 6px 12px;
    min-height: 18px;
}}
QComboBox:focus, QComboBox:on {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({_ASSETS}/arrow_down.png); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ selection-background-color: rgba(46, 158, 91, 0.25); selection-color: palette(text); }}

QSpinBox {{
    background: palette(base);
    border: 1px solid {LINE};
    border-radius: {R_CONTROL}px;
    padding: 6px 30px 6px 12px;
    min-height: 18px;
    selection-background-color: {ACCENT};
}}
QSpinBox:focus {{ border: 1px solid {ACCENT}; }}
QSpinBox:disabled {{ color: palette(placeholder-text); }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border;
    width: 26px;
    border: none;
    background: transparent;
}}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: {R_CONTROL}px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: {R_CONTROL}px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {SOFT_HOVER}; }}
QSpinBox::up-arrow {{ image: url({_ASSETS}/arrow_up.png); width: 12px; height: 12px; }}
QSpinBox::down-arrow {{ image: url({_ASSETS}/arrow_down.png); width: 12px; height: 12px; }}

/* ---------------------------------------------------------------- 체크박스·라디오 (강조색 통일) */
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QListWidget#pickList::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid #8a8f98;
    border-radius: 6px;
    background: transparent;
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked, QListWidget#pickList::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: url({_ASSETS}/check.png);
}}
QCheckBox::indicator:checked:disabled, QListWidget#pickList::indicator:checked:disabled {{
    background: #5b7a66;
    border-color: #5b7a66;
}}
QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid #8a8f98;
    border-radius: 10px;
    background: transparent;
}}
QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
/* 두꺼운 초록 테두리 + 가운데 흰 점 = 선택됨 */
QRadioButton::indicator:checked {{
    border: 5px solid {ACCENT};
    width: 10px;
    height: 10px;
    background: white;
}}

/* ---------------------------------------------------------------- 목록 */
QListWidget#modeList {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget#modeList::item {{
    padding: 0;
    margin: 2px 0;
    border-radius: 12px;
}}
QListWidget#modeList::item:hover {{ background: palette(alternate-base); }}
QListWidget#modeList::item:selected {{
    background: rgba(46, 158, 91, 0.22);
    border-left: 4px solid {ACCENT};
}}

QListWidget#pickList {{
    qproperty-iconSize: 24px 24px;
    border: 1px solid {LINE};
    border-radius: {R_CARD}px;
    background: palette(base);
    outline: none;
    padding: 6px;
}}
QListWidget#pickList::item {{ border-radius: {R_CONTROL}px; padding: 2px 4px; }}
QListWidget#pickList::item:hover {{ background: palette(alternate-base); }}

QListWidget#appList {{
    qproperty-iconSize: 20px 20px;
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget#appList::item {{ border-radius: {R_CONTROL}px; }}
QListWidget#appList::item:hover {{ background: palette(alternate-base); }}

/* 시간 버튼 편집 등 일반 목록 */
QListWidget {{
    border: 1px solid {LINE};
    border-radius: {R_CONTROL}px;
    background: palette(base);
    padding: 4px;
    outline: none;
}}
QListWidget::item {{ border-radius: 8px; padding: 6px 8px; }}
QListWidget::item:selected {{ background: rgba(46, 158, 91, 0.25); color: palette(text); }}

QTextBrowser {{
    border: 1px solid {LINE};
    border-radius: {R_CONTROL}px;
    background: palette(base);
    padding: 6px;
}}

/* ---------------------------------------------------------------- 스크롤바 (얇고 둥글게) */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
QScrollBar::handle:vertical {{ background: rgba(127, 127, 127, 0.45); border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:horizontal {{ background: rgba(127, 127, 127, 0.45); border-radius: 3px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: rgba(127, 127, 127, 0.70); }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------------------------------------------------------------- 진행 막대 */
QProgressBar {{
    border: none;
    background: {SOFT_HOVER};
    border-radius: 4px;
    max-height: 8px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
"""

ZOOM_LEVELS = (80, 90, 100, 110, 125, 150, 175, 200)  # 화면 크기 단계 (%)
_SIZE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(pt|px)(?![\w-])")


_zoom = 100  # 지금 화면 크기 (%). WindowStateManager가 바꿈


def clamp_zoom(percent: int) -> int:
    return max(ZOOM_LEVELS[0], min(ZOOM_LEVELS[-1], int(percent)))


def set_zoom(percent: int) -> None:
    global _zoom
    _zoom = clamp_zoom(percent)


def px(value: int) -> int:
    """코드에서 정하는 크기(목록 항목 높이 등)를 지금 화면 크기에 맞춤."""
    return round(value * _zoom / 100)


def build_stylesheet(zoom: int = 100) -> str:
    """화면 크기(%)에 맞춰 글자 크기와 여백·모서리를 키우거나 줄인 스타일. 1px 선은 그대로 둡니다."""
    factor = clamp_zoom(zoom) / 100

    def scale(m: re.Match) -> str:
        value, unit = float(m.group(1)), m.group(2)
        if factor == 1 or (unit == "px" and value <= 1):
            return m.group(0)
        if unit == "pt":
            return f"{round(value * factor, 1):g}pt"
        return f"{max(1, round(value * factor))}px"

    return _SIZE.sub(scale, _TEMPLATE)


STYLESHEET = build_stylesheet(100)
