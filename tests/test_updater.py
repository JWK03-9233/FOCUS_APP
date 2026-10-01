"""업데이트 핵심 로직 (버전 비교, 릴리스 해석, 다운로드 검증, 압축 해제, 설치 스크립트)."""

import hashlib
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from focus_app import updater
from focus_app.updater import ReleaseInfo, UpdateError, is_newer, parse_version, release_from_json


def test_parse_and_compare_versions():
    assert parse_version("v0.10.2") == (0, 10, 2)
    assert parse_version("1.2") == (1, 2)
    assert parse_version("1.2.0-beta") == (1, 2, 0)
    assert is_newer("0.10.0", "0.9.9")
    assert is_newer("v1.0", "0.9")
    assert not is_newer("1.0", "1.0.0")
    assert not is_newer("0.2.0", "0.3.0")


def test_release_from_json_picks_zip_asset_and_digest():
    data = {
        "tag_name": "v9.9.9",
        "body": "## 바뀐 점",
        "html_url": "https://example/rel",
        "assets": [
            {"name": "notes.txt", "url": "u1", "size": 1},
            {"name": "FocusApp-v9.9.9-win64.zip", "url": "u2", "size": 42, "digest": "sha256:ABCD"},
        ],
    }
    info = release_from_json(data)
    assert info.version == "9.9.9" and info.newer
    assert info.asset_url == "u2" and info.asset_size == 42 and info.sha256 == "abcd"
    assert release_from_json({"tag_name": "v1", "assets": []}).installable is False


def _zip_with(tmp_path: Path, files: dict) -> Path:
    path = tmp_path / "FocusApp-v1.0.0-win64.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


def _info_for(path: Path, sha: str = "", size: int = 0) -> ReleaseInfo:
    return ReleaseInfo("1.0.0", "v1.0.0", "", "", path.name, path.as_uri(), size, sha)


def test_download_verifies_checksum(tmp_path):
    src = _zip_with(tmp_path, {"FocusApp/FocusApp.exe": b"exe"})
    data = src.read_bytes()
    good = _info_for(src, hashlib.sha256(data).hexdigest(), len(data))
    seen = []
    out = updater.download(good, tmp_path / "dl", progress=lambda d, t: seen.append(d))
    assert out.read_bytes() == data and seen[-1] == len(data)

    with pytest.raises(UpdateError, match="손상"):
        updater.download(_info_for(src, "0" * 64, len(data)), tmp_path / "dl2")
    with pytest.raises(UpdateError, match="크기"):
        updater.download(_info_for(src, "", len(data) + 1), tmp_path / "dl3")
    with pytest.raises(UpdateError, match="취소"):
        updater.download(good, tmp_path / "dl4", cancelled=lambda: True)


def test_extract_finds_app_folder_and_blocks_path_traversal(tmp_path):
    ok = _zip_with(tmp_path, {"FocusApp/FocusApp.exe": b"x", "FocusApp/_internal/a.dll": b"y"})
    folder = updater.extract(ok, tmp_path / "out")
    assert folder.name == "FocusApp" and (folder / "_internal" / "a.dll").exists()

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../escape.txt", b"bad")
    with pytest.raises(UpdateError, match="잘못된 경로"):
        updater.extract(evil, tmp_path / "out2")

    no_exe = tmp_path / "noexe.zip"
    with zipfile.ZipFile(no_exe, "w") as zf:
        zf.writestr("readme.txt", b"")
    with pytest.raises(UpdateError, match="찾지 못했"):
        updater.extract(no_exe, tmp_path / "out3")


def test_install_script_quotes_paths():
    script = updater.build_install_script(
        123, Path(r"C:\tmp\new"), Path(r"C:\Users\it's me\FocusApp"), Path(r"C:\tmp"), Path(r"C:\log.txt")
    )
    assert "'C:\\Users\\it''s me\\FocusApp'" in script
    assert "Get-Process -Id 123" in script


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows PowerShell 전용")
def test_install_script_replaces_files_after_process_exits(tmp_path):
    """실제 PowerShell로: 앱 프로세스가 끝나길 기다린 뒤 파일을 덮어쓰고 exe를 다시 실행하는지."""
    target = tmp_path / "install"
    new = tmp_path / "work" / "new" / "FocusApp"
    (target / "_internal").mkdir(parents=True)
    (new / "_internal").mkdir(parents=True)
    harmless = Path(r"C:\Windows\System32\whoami.exe")  # 바로 끝나는 무해한 exe를 FocusApp.exe 대신 사용
    (target / "FocusApp.exe").write_bytes(harmless.read_bytes())
    (target / "_internal" / "lib.txt").write_text("old")
    (target / "user_note.txt").write_text("keep")
    (new / "FocusApp.exe").write_bytes(harmless.read_bytes())
    (new / "_internal" / "lib.txt").write_text("new")

    app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])  # '실행 중인 앱' 역할
    log = tmp_path / "update.log"
    script = updater.build_install_script(app.pid, new, target, tmp_path / "work", log)
    started = time.time()
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=60)
    app.wait()

    assert time.time() - started >= 1.5  # 프로세스가 끝날 때까지 기다렸음
    assert (target / "_internal" / "lib.txt").read_text() == "new"
    assert (target / "user_note.txt").read_text() == "keep"  # 설치 폴더의 다른 파일은 지우지 않음
    assert not (tmp_path / "work").exists()  # 작업 폴더 정리
    assert "files replaced" in log.read_text(encoding="utf-8-sig")
