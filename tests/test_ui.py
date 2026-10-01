"""오프스크린 Qt로 해제 대화상자의 붙여넣기 차단을 검증합니다."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, Qt  # noqa: E402
from PySide6.QtGui import QClipboard  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from focus_app.ui.unlock_dialog import NoPasteLineEdit, UnlockDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_ctrl_v_is_blocked(qapp):
    edit = NoPasteLineEdit()
    QApplication.clipboard().setText("PASTED", QClipboard.Mode.Clipboard)
    QTest.keyClick(edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert edit.text() == ""
    edit.paste()  # 프로그램적 붙여넣기도 insertFromMimeData에서 막힘
    assert edit.text() == ""


def test_bulk_insert_reverted_but_typing_works(qapp):
    edit = NoPasteLineEdit()
    QTest.keyClicks(edit, "abc")
    assert edit.text() == "abc"
    edit.insert("XYZW")  # 한 번에 여러 글자 -> 되돌림
    assert edit.text() == "abc"
    mime = QMimeData()
    mime.setText("DROP")
    edit.insertFromMimeData(mime)
    assert edit.text() == "abc"


def test_dialog_accepts_correct_code_and_rotates_on_wrong(qapp):
    dlg = UnlockDialog(length=12, purpose="테스트")
    first = dlg.challenge.code
    QTest.keyClicks(dlg.input, "wrong")
    dlg._check()
    assert dlg.result() != QDialog.DialogCode.Accepted
    assert dlg.challenge.code != first
    assert "틀렸습니다" in dlg.status.text()
    QTest.keyClicks(dlg.input, dlg.challenge.code)
    dlg._check()
    assert dlg.result() == QDialog.DialogCode.Accepted


def test_code_label_not_selectable(qapp):
    dlg = UnlockDialog(length=12)
    assert dlg.code_label.textInteractionFlags() == Qt.TextInteractionFlag.NoTextInteraction
