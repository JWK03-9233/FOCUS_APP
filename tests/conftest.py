import os

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """모든 테스트가 실제 AppData 대신 임시 폴더를 쓰도록 합니다."""
    monkeypatch.setenv("FOCUSAPP_DATA_DIR", str(tmp_path / "data"))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    yield tmp_path
