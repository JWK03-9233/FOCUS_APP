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
    assert Settings().edit_code_length == 16  # 편집용 기본 길이
    assert Settings.from_dict({"edit_code_length": 5}).edit_code_length == 16
    assert Settings.from_dict({"edit_code_length": 64}).edit_code_length == 64
    assert Settings.from_dict({"edit_code_length": 1000}).edit_code_length == 256


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


def test_add_profile_inherits_from_base():
    s = Settings()
    src = s.get_profile("업무용")
    src.restrict_sites = True
    src.add_site("notion.so")
    p = s.add_profile("코딩", base="업무용")
    assert p.normalized_apps() == src.normalized_apps()
    assert p.normalized_sites() == ["notion.so"] and p.restrict_sites and p.block_everything
    p.add_app("obsidian.exe")
    p.remove_app("code.exe")
    p.remove_site("notion.so")
    assert "code.exe" in src.normalized_apps() and "obsidian.exe" not in src.normalized_apps()  # 원본은 그대로
    assert src.normalized_sites() == ["notion.so"]
    assert not s.add_profile("쉬기", base="자유 시간").block_everything
    assert s.add_profile("빈 모드").allowed_apps == []
    with pytest.raises(ValueError):
        s.add_profile("없는 데서", base="없는 모드")


# ---------------------------------------------------------------- Ban 모드 (고른 앱만 막기)
KEEP_ID = "eilembjdkfgodjkcjnpgpaenohkicgjd"


def test_ban_profile_blocks_only_listed_apps():
    p = Profile("ban", allowed_apps=["KakaoTalk.exe", f"chrome.exe|{KEEP_ID}"], ban_apps=True)
    assert p.bans()
    assert not p.allows("kakaotalk.exe") and not p.allows_window("KAKAOTALK.EXE")
    assert p.allows("code.exe") and p.allows_window("code.exe")
    # 웹 앱을 막아도 브라우저 자체는 그대로 쓸 수 있음
    assert p.allows_window("chrome.exe", "Chrome.Default")
    assert not p.allows_window("chrome.exe", f"Chrome._crx_{KEEP_ID}")
    assert p.allows_window("msedge.exe", f"Edge._crx_{KEEP_ID}")  # 다른 브라우저의 같은 ID는 다른 앱


def test_ban_profile_never_limits_sites():
    p = Profile("ban", ban_apps=True, restrict_sites=True, allowed_sites=["notion.so"])
    assert not p.limits_sites() and not p.browses_sites()
    assert p.allows_window("chrome.exe")


def test_ban_flag_ignored_when_not_blocking():
    p = Profile("free", allowed_apps=["kakaotalk.exe"], block_everything=False, ban_apps=True)
    assert not p.bans() and p.allows("kakaotalk.exe")


def test_ban_mode_saved_and_inherited(tmp_path):
    s = Settings()
    s.add_profile("밴")
    s.get_profile("밴").ban_apps = True
    s.get_profile("밴").add_app("kakaotalk.exe")
    path = tmp_path / "settings.json"
    s.save(path)
    loaded = Settings.load(path)
    assert loaded.get_profile("밴").bans()
    assert not loaded.get_profile("공부용").bans()
    copy = loaded.add_profile("밴2", base="밴")
    assert copy.bans() and copy.normalized_apps() == ["kakaotalk.exe"]
