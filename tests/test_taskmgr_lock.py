"""엄격 모드의 작업 관리자 끄기/되돌리기 (레지스트리는 가짜로 바꿔 검증)."""

import pytest

from focus_app import taskmgr_lock


@pytest.fixture
def reg(monkeypatch):
    store = {}

    def write(value):
        store["value"] = value

    monkeypatch.setattr(taskmgr_lock, "_read_value", lambda: store.get("value"))
    monkeypatch.setattr(taskmgr_lock, "_write_value", write)
    monkeypatch.setattr(taskmgr_lock, "_delete_value", lambda: store.pop("value", None))
    return store


def test_engage_then_release_removes_value(tmp_path, reg):
    assert taskmgr_lock.engage(tmp_path)
    assert reg["value"] == 1 and taskmgr_lock.engaged(tmp_path)
    assert taskmgr_lock.engage(tmp_path)  # 두 번 켜도 원래 값을 덮어쓰지 않음
    assert taskmgr_lock.release(tmp_path)
    assert "value" not in reg and not taskmgr_lock.engaged(tmp_path)


def test_release_restores_previous_value(tmp_path, reg):
    reg["value"] = 0
    taskmgr_lock.engage(tmp_path)
    assert reg["value"] == 1
    taskmgr_lock.release(tmp_path)
    assert reg["value"] == 0


def test_keeps_policy_that_was_already_set(tmp_path, reg):
    reg["value"] = 1  # 관리자가 원래 꺼 둔 경우
    taskmgr_lock.engage(tmp_path)
    taskmgr_lock.release(tmp_path)
    assert reg["value"] == 1


def test_release_without_engage_does_nothing(tmp_path, reg):
    reg["value"] = 0
    assert taskmgr_lock.release(tmp_path)
    assert reg["value"] == 0


def test_failed_engage_leaves_nothing_behind(tmp_path, reg, monkeypatch):
    def denied(value):
        raise PermissionError("접근 거부")

    monkeypatch.setattr(taskmgr_lock, "_write_value", denied)
    assert not taskmgr_lock.engage(tmp_path)
    assert not taskmgr_lock.engaged(tmp_path)
    assert "value" not in reg


def test_failed_release_keeps_marker_for_retry(tmp_path, reg, monkeypatch):
    taskmgr_lock.engage(tmp_path)

    def denied():
        raise PermissionError("접근 거부")

    monkeypatch.setattr(taskmgr_lock, "_delete_value", denied)
    assert not taskmgr_lock.release(tmp_path)
    assert taskmgr_lock.engaged(tmp_path)  # 다음에 다시 되돌릴 수 있게 남겨 둠
