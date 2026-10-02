"""공통 스타일과 색. 앱 고유 팔레트(``apply_palette``)를 쓰고, 스타일은 palette(...)를 참조해 라이트/다크를 모두 따릅니다.

디자인 원칙
* 차분한 중립색(푸른 기가 도는 거의 검정 / 옅은 회색) 위에 강조색 하나: 인디고 → 바이올렛 그라데이션
* 강조색(ACCENT): 체크박스·라디오·포커스 테두리·선택 표시. 채우는 곳(기본 버튼·고른 시간·진행 막대)은 그라데이션
* 뜻이 있는 색은 따로: 실행 중·완료는 에메랄드(SUCCESS), 경고는 앰버(WARN), 위험은 로즈(DANGER)
* 모서리는 둥글게: 버튼·입력칸 9px, 카드 14px, 칩·작은 버튼은 알약 모양
  (알약 모양의 반지름은 버튼 높이의 절반보다 넉넉히 작게: 넘으면 Qt가 모서리를 아예 각지게 그림)
* 각 대화상자의 기본 버튼(저장·추가·확인·시작)은 그라데이션으로 채우고, 나머지 버튼은 옅은 회색
* 화면 확대·축소는 이 스타일의 pt/px 값을 비율대로 바꿔 다시 적용합니다 (``build_stylesheet``).
  그래서 글자 크기·여백은 위젯에 직접 쓰지 말고 여기에 objectName으로 둡니다.
"""

from __future__ import annotations

import re
from pathlib import Path

ACCENT = "#6366f1"  # 인디고: 선택·포커스·강조 글자
ACCENT_2 = "#8b5cf6"  # 바이올렛: 그라데이션 끝색
ACCENT_HOVER = "#7c7ff7"
ACCENT_PRESSED = "#4f46e5"
SUCCESS = "#10b981"  # 실행 중·완료
WARN = "#f59e0b"
DANGER = "#f43f5e"


def tint(color: str, alpha: float) -> str:
    """'#rrggbb' 색을 반투명으로 (옅은 배경·선택 표시용)."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _gradient(start: str, end: str) -> str:
    return f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {start}, stop:1 {end})"


GRADIENT = _gradient(ACCENT, ACCENT_2)
GRADIENT_HOVER = _gradient(ACCENT_HOVER, "#9d74f8")
GRADIENT_PRESSED = _gradient(ACCENT_PRESSED, "#7c3aed")

# 라이트/다크 어디서나 자연스러운 반투명 회색 (배경 위에 겹쳐 그림). 푸른 기가 도는 슬레이트 회색
SOFT = "rgba(148, 163, 184, 0.12)"
SOFT_HOVER = "rgba(148, 163, 184, 0.20)"
SOFT_PRESSED = "rgba(148, 163, 184, 0.28)"
LINE = "rgba(148, 163, 184, 0.22)"
INDICATOR = "#7b8296"  # 체크박스·라디오 테두리

R_CONTROL = 9  # 버튼·입력칸
R_CARD = 14  # 카드·목록 틀

# 앱 고유 팔레트 (palette(...)로 스타일에서 참조). 역할 이름은 QPalette.ColorRole
PALETTES = {
    "dark": {
        "Window": "#0d0f15",
        "WindowText": "#e7e9f1",
        "Base": "#161923",
        "AlternateBase": "#1f2331",
        "Text": "#e7e9f1",
        "Button": "#1f2331",
        "ButtonText": "#e7e9f1",
        "PlaceholderText": "#8b91a5",
        "Link": "#a5b4fc",
        "Highlight": ACCENT,
        "HighlightedText": "#ffffff",
        "ToolTipBase": "#1f2331",
        "ToolTipText": "#e7e9f1",
        "Mid": "#2a2f40",
        "Light": "#2a2f40",
        "Midlight": "#232838",
        "Dark": "#0a0c11",
        "Shadow": "#000000",
        "BrightText": "#ffffff",
    },
    "light": {
        "Window": "#f4f5fa",
        "WindowText": "#161925",
        "Base": "#ffffff",
        "AlternateBase": "#eef0f7",
        "Text": "#161925",
        "Button": "#ffffff",
        "ButtonText": "#161925",
        "PlaceholderText": "#6a7086",
        "Link": "#4f46e5",
        "Highlight": ACCENT,
        "HighlightedText": "#ffffff",
        "ToolTipBase": "#ffffff",
        "ToolTipText": "#161925",
        "Mid": "#d7dae6",
        "Light": "#ffffff",
        "Midlight": "#eef0f7",
        "Dark": "#b9bdcc",
        "Shadow": "#8a8fa3",
        "BrightText": "#000000",
    },
}

# QSS의 url()은 슬래시 경로를 씀. exe 배포본에서도 focus_app/assets가 함께 들어감
_ASSETS = (Path(__file__).resolve().parent.parent / "assets").as_posix()

_TEMPLATE = f"""
QWidget {{ font-size: 8.5pt; }}

/* ---------------------------------------------------------------- 글자 */
QLabel#appTitle {{ font-size: 14pt; font-weight: 600; }}
QLabel#sectionTitle {{ font-size: 9.5pt; font-weight: 600; }}
QLabel#modeTitle {{ font-size: 13pt; font-weight: 600; }}
QLabel#muted {{ color: palette(placeholder-text); }}
QLabel#hint {{ color: palette(placeholder-text); font-size: 8pt; }}
QLabel#warnText {{ color: {WARN}; font-size: 8pt; }}
QLabel#timer {{ font-size: 47pt; font-weight: 300; }}
QLabel#runningMode {{ font-size: 15pt; font-weight: 600; color: {ACCENT}; }}
QLabel#modeRowTitle {{ font-size: 9.5pt; font-weight: 600; background: transparent; }}
QLabel#endIcon {{ font-size: 30pt; }}
QLabel#unlockCode {{
    font-family: Consolas, monospace;
    font-size: 14pt;
    background: {SOFT};
    border: 1px solid {LINE};
    padding: 14px;
    border-radius: 12px;
    letter-spacing: 1px;
}}
QLineEdit#unlockInput {{ font-family: Consolas, monospace; font-size: 14pt; }}
QLabel#unlockExample {{ font-family: Consolas, monospace; color: palette(placeholder-text); }}

/* ---------------------------------------------------------------- 카드·띠 */
QFrame#card {{
    background: palette(base);
    border: 1px solid {LINE};
    border-radius: {R_CARD}px;
}}
QFrame#banner {{
    background: {tint(WARN, 0.12)};
    border: 1px solid {WARN};
    border-radius: 10px;
}}
QFrame#card[leftPanel="true"] {{ min-width: 191px; max-width: 191px; }}
QFrame#notice {{
    background: {tint(SUCCESS, 0.12)};
    border: 1px solid {tint(SUCCESS, 0.7)};
    border-radius: 10px;
}}

/* ---------------------------------------------------------------- 버튼 */
QPushButton {{
    background: {SOFT};
    border: 1px solid {LINE};
    border-radius: {R_CONTROL}px;
    padding: 6px 14px;
    min-height: 16px;
}}
QPushButton:hover {{ background: {SOFT_HOVER}; }}
QPushButton:pressed {{ background: {SOFT_PRESSED}; }}
QPushButton:disabled {{
    color: palette(placeholder-text);
    background: rgba(148, 163, 184, 0.06);
    border-color: rgba(148, 163, 184, 0.14);
}}
/* 대화상자의 기본 동작(저장·추가·확인 등)은 초록으로 채움 */
QPushButton:default {{
    background: {GRADIENT};
    border-color: transparent;
    color: white;
    font-weight: 600;
}}
QPushButton:default:hover {{ background: {GRADIENT_HOVER}; }}
QPushButton:default:pressed {{ background: {GRADIENT_PRESSED}; }}
QPushButton:default:disabled {{
    background: {tint(ACCENT, 0.30)};
    border-color: transparent;
    color: rgba(255, 255, 255, 0.65);
}}

QPushButton#primary {{
    background: {GRADIENT};
    color: white;
    border: none;
    font-size: 10.5pt;
    font-weight: 600;
    padding: 10px 26px;
    border-radius: 16px;
}}
QPushButton#primary:hover {{ background: {GRADIENT_HOVER}; }}
QPushButton#primary:pressed {{ background: {GRADIENT_PRESSED}; }}
QPushButton#primary:disabled {{ background: palette(mid); color: palette(placeholder-text); }}

QPushButton#secondary {{
    border: 1px solid {ACCENT};
    color: {ACCENT};
    background: transparent;
    font-weight: 600;
    padding: 6px 14px;
    border-radius: 12px;
}}
QPushButton#secondary:hover {{ background: {tint(ACCENT, 0.14)}; }}
QPushButton#secondary:pressed {{ background: {tint(ACCENT, 0.24)}; }}
QPushButton#secondary:disabled {{ border-color: {LINE}; color: palette(placeholder-text); }}

QPushButton#chip {{
    padding: 5px 12px;
    border: 1px solid {LINE};
    border-radius: 11px;
    background: transparent;
}}
QPushButton#chip:hover {{ background: {SOFT}; }}
QPushButton#chip:checked {{
    background: {GRADIENT};
    border-color: transparent;
    color: white;
    font-weight: 600;
}}

QPushButton#iconButton {{
    border: none;
    background: transparent;
    padding: 3px 7px;
    border-radius: 12px;
    color: palette(placeholder-text);
    font-size: 9.5pt;
}}
QPushButton#iconButton:hover {{ color: {DANGER}; background: {tint(DANGER, 0.12)}; }}

QPushButton#linkButton {{
    border: none;
    background: transparent;
    color: palette(link);
    padding: 4px 9px;
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
    padding: 9px 21px;
    border-radius: 14px;
    font-weight: 600;
}}
QPushButton#danger:hover {{ background: {tint(DANGER, 0.12)}; }}

/* ---------------------------------------------------------------- 입력칸 */
QLineEdit {{
    background: palette(base);
    border: 1px solid {LINE};
    border-radius: {R_CONTROL}px;
    padding: 6px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}

QComboBox {{
    background: palette(base);
    border: 1px solid {LINE};
    border-radius: {R_CONTROL}px;
    padding: 5px 10px;
    min-height: 16px;
}}
QComboBox:focus, QComboBox:on {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 23px; }}
QComboBox::down-arrow {{ image: url({_ASSETS}/arrow_down.png); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{ selection-background-color: {tint(ACCENT, 0.25)}; selection-color: palette(text); }}

QSpinBox {{
    background: palette(base);
    border: 1px solid {LINE};
    border-radius: {R_CONTROL}px;
    padding: 5px 26px 5px 10px;
    min-height: 16px;
    selection-background-color: {ACCENT};
}}
QSpinBox:focus {{ border: 1px solid {ACCENT}; }}
QSpinBox:disabled {{ color: palette(placeholder-text); }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border;
    width: 23px;
    border: none;
    background: transparent;
}}
QSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: {R_CONTROL}px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: {R_CONTROL}px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {SOFT_HOVER}; }}
QSpinBox::up-arrow {{ image: url({_ASSETS}/arrow_up.png); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url({_ASSETS}/arrow_down.png); width: 10px; height: 10px; }}

/* ---------------------------------------------------------------- 체크박스·라디오 (강조색 통일) */
QCheckBox, QRadioButton {{ spacing: 7px; }}
QCheckBox::indicator, QListWidget#pickList::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {INDICATOR};
    border-radius: 5px;
    background: transparent;
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked, QListWidget#pickList::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: url({_ASSETS}/check.png);
}}
QCheckBox::indicator:checked:disabled, QListWidget#pickList::indicator:checked:disabled {{
    background: {tint(ACCENT, 0.45)};
    border-color: transparent;
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {INDICATOR};
    border-radius: 9px;
    background: transparent;
}}
QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
/* 강조색 원 + 가운데 흰 점 = 선택됨 (두꺼운 테두리로 그리면 가운데가 네모로 보여 원형 그라데이션으로) */
QRadioButton::indicator:checked {{
    border: 1px solid {ACCENT};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                                stop:0 white, stop:0.36 white, stop:0.42 {ACCENT}, stop:1 {ACCENT});
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
    border-radius: 10px;
}}
QListWidget#modeList::item:hover {{ background: palette(alternate-base); }}
QListWidget#modeList::item:selected {{
    background: {tint(ACCENT, 0.18)};
    border-left: 3px solid {ACCENT};
}}

QListWidget#pickList {{
    qproperty-iconSize: 21px 21px;
    border: 1px solid {LINE};
    border-radius: {R_CARD}px;
    background: palette(base);
    outline: none;
    padding: 5px;
}}
QListWidget#pickList::item {{ border-radius: {R_CONTROL}px; padding: 2px 3px; }}
QListWidget#pickList::item:hover {{ background: palette(alternate-base); }}

QListWidget#appList {{
    qproperty-iconSize: 17px 17px;
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget#appList::item {{ border-radius: {R_CONTROL}px; }}
QListWidget#appList::item:hover {{ background: palette(alternate-base); }}

/* 진행 화면의 '지금 쓸 수 있는 앱·사이트': 한눈에 보이게 크게 */
QListWidget#runList {{
    qproperty-iconSize: 24px 24px;
    background: transparent;
    border: none;
    outline: none;
    font-size: 10pt;
}}
QListWidget#runList::item {{ border-radius: {R_CONTROL}px; padding: 7px 10px; }}
QListWidget#runList::item:hover {{ background: palette(alternate-base); }}

/* 시간 버튼 편집 등 일반 목록 */
QListWidget {{
    border: 1px solid {LINE};
    border-radius: {R_CONTROL}px;
    background: palette(base);
    padding: 3px;
    outline: none;
}}
QListWidget::item {{ border-radius: 7px; padding: 5px 7px; }}
/* 줄마다 위젯을 넣는 목록(허용 앱·사이트 등): 위젯이 자기 여백을 가지므로 칸 여백을 빼야 글자가 잘리지 않음 */
QListWidget[rowWidgets="true"]::item {{ padding: 0; }}
QListWidget::item:selected {{ background: {tint(ACCENT, 0.22)}; color: palette(text); }}

QTextBrowser {{
    border: 1px solid {LINE};
    border-radius: {R_CONTROL}px;
    background: palette(base);
    padding: 5px;
}}

/* ---------------------------------------------------------------- 스크롤바 (얇고 둥글게) */
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 3px 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px 3px; }}
QScrollBar::handle:vertical {{ background: rgba(148, 163, 184, 0.35); border-radius: 3px; min-height: 26px; }}
QScrollBar::handle:horizontal {{ background: rgba(148, 163, 184, 0.35); border-radius: 3px; min-width: 26px; }}
QScrollBar::handle:hover {{ background: rgba(148, 163, 184, 0.60); }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------------------------------------------------------------- 진행 막대 */
QProgressBar {{
    border: none;
    background: {SOFT_HOVER};
    border-radius: 3px;
    max-height: 7px;
}}
QProgressBar::chunk {{ background: {_gradient(ACCENT, ACCENT_2).replace("y2:1", "y2:0")}; border-radius: 3px; }}

/* ---------------------------------------------------------------- 트레이 메뉴·말풍선 */
QMenu {{
    background: palette(base);
    border: 1px solid {LINE};
    border-radius: 10px;
    padding: 5px;
}}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {tint(ACCENT, 0.22)}; color: palette(text); }}
QMenu::item:disabled {{ color: palette(placeholder-text); }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}
QToolTip {{
    background: palette(tool-tip-base);
    color: palette(tool-tip-text);
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 4px 7px;
}}
"""

def scheme() -> str:
    """지금 Windows가 다크 모드면 "dark", 아니면 "light"."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    hints = QGuiApplication.styleHints()
    return "light" if hints.colorScheme() == Qt.ColorScheme.Light else "dark"


def build_palette(name: str):
    from PySide6.QtGui import QColor, QPalette

    pal = QPalette()
    for role, color in PALETTES[name].items():
        pal.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    muted = QColor(PALETTES[name]["PlaceholderText"])
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, muted)
    return pal


def apply_palette(app) -> None:
    """앱 고유 색을 입힙니다 (Fusion 스타일 + 다크/라이트 팔레트). Windows 모드를 바꾸면 따라 바뀜."""
    from PySide6.QtGui import QGuiApplication

    app.setStyle("Fusion")  # Windows 11 기본 스타일은 앱 팔레트를 일부 무시해 색이 섞임

    def update(*_args) -> None:
        app.setPalette(build_palette(scheme()))
        app.setStyleSheet(app.styleSheet())  # palette(...)를 쓰는 스타일을 새 색으로 다시 계산

    update()
    QGuiApplication.styleHints().colorSchemeChanged.connect(update)


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
