from focus_app.session import FocusSession, format_duration


def test_timed_session_expires():
    s = FocusSession.start("study", 25, now=1000.0)
    assert s.remaining_seconds(now=1000.0) == 25 * 60
    assert not s.is_expired(now=1000.0 + 25 * 60 - 1)
    assert s.is_expired(now=1000.0 + 25 * 60)
    assert s.expiry_reason(now=1000.0 + 25 * 60) == "expired"
    assert s.elapsed_seconds(now=1060.0) == 60


def test_unlimited_session():
    s = FocusSession.start("study", None, now=0.0)
    assert s.remaining_seconds() is None
    assert not s.is_expired(now=10**9)
    assert s.expiry_reason(now=10**9) is None


def test_emergency_delay():
    s = FocusSession.start("study", 120, now=0.0)
    s.request_emergency(10, now=0.0)
    assert s.emergency_remaining_seconds(now=0.0) == 600
    assert not s.is_expired(now=599)
    assert s.expiry_reason(now=600) == "emergency"
    s.cancel_emergency()
    assert not s.is_expired(now=600)


def test_save_load_clear(tmp_path):
    path = tmp_path / "session.json"
    s = FocusSession.start("study", 30, now=50.0)
    s.request_emergency(5, now=50.0)
    s.save(path)
    loaded = FocusSession.load(path)
    assert loaded == s
    FocusSession.clear(path)
    assert FocusSession.load(path) is None
    FocusSession.clear(path)  # 없어도 오류 없음
    path.write_text("broken")
    assert FocusSession.load(path) is None


def test_format_duration():
    assert format_duration(None) == "제한 없음"
    assert format_duration(59) == "0분 59초"
    assert format_duration(3661) == "1시간 01분 01초"
