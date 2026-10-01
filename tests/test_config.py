import pytest

from focus_app.config import Profile, Settings, normalize_exe


def test_normalize_exe_strips_path_and_case():
    assert normalize_exe(r"C:\Program Files\Google\Chrome\chrome.EXE") == "chrome.exe"
    assert normalize_exe("/usr/bin/Code.exe") == "code.exe"
    assert normalize_exe('  "notepad.exe" ') == "notepad.exe"
    assert normalize_exe("") == ""


def test_profile_allows_and_dedupes():
    p = Profile("t", allowed_apps=["Chrome.exe", "chrome.exe", "code.exe"])
    assert p.normalized_apps() == ["chrome.exe", "code.exe"]
    assert p.allows("CHROME.EXE")
    assert not p.allows("discord.exe")
    assert p.add_app("discord.exe")
    assert not p.add_app("Discord.exe")
    p.remove_app("CHROME.exe")
    assert p.normalized_apps() == ["code.exe", "discord.exe"]


def test_free_profile_allows_everything():
    p = Profile("free", block_everything=False)
    assert p.allows("anything.exe")


def test_settings_roundtrip(tmp_path):
    s = Settings()
    s.add_profile("새 프로필").add_app("foo.exe")
    s.active_profile = "새 프로필"
    s.poll_interval_ms = 250
    path = tmp_path / "settings.json"
    s.save(path)
    loaded = Settings.load(path)
    assert loaded.active_profile == "새 프로필"
    assert loaded.get_profile("새 프로필").allowed_apps == ["foo.exe"]
    assert loaded.poll_interval_ms == 250
    assert loaded.profile_names() == s.profile_names()


def test_settings_load_tolerates_garbage(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    s = Settings.load(path)
    assert s.profile_names() == ["공부용", "업무용", "자유 시간"]

    path.write_text('{"profiles": [], "active_profile": "없음", "poll_interval_ms": 5, "unlock_code_length": 1000}', encoding="utf-8")
    s = Settings.load(path)
    assert s.active_profile == "공부용"
    assert s.poll_interval_ms == 100
    assert s.unlock_code_length == 256  # 최대 길이
    assert Settings.from_dict({"unlock_code_length": 10}).unlock_code_length == 32  # 최소 길이


def test_profile_management_rules():
    s = Settings()
    with pytest.raises(ValueError):
        s.add_profile("공부용")
    with pytest.raises(ValueError):
        s.add_profile("   ")
    s.rename_profile("공부용", "스터디")
    assert s.active_profile == "스터디"
    with pytest.raises(ValueError):
        s.rename_profile("스터디", "업무용")
    s.remove_profile("스터디")
    assert s.active_profile == "업무용"
    s.remove_profile("업무용")
    with pytest.raises(ValueError):
        s.remove_profile("자유 시간")
