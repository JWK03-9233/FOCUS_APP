"""
FocusApp 릴리스 자동화 스크립트
================================
릴리스 순서:

    preflight -> test -> bump -> build -> secrets scan -> zip -> installer
              -> publish (draft 생성 + 업로드 -> 체크섬 확인 -> 공개)
              -> verify (공개 다운로드 주소 확인)

앱 안의 업데이트는 GitHub Releases의 "최신 릴리스"를 읽습니다. 그래서 릴리스를 먼저
draft(비공개 초안)로 만들어 파일을 올리고, 올라간 파일의 체크섬을 확인한 뒤에야 공개합니다.
확인에 실패하면 draft로 남으므로 사용자에게는 보이지 않습니다.

이 스크립트는 로컬 git을 건드리지 않습니다. 버전 파일을 고치고 작업 폴더에서 빌드할 뿐이며,
커밋·push는 직접 하세요. 마지막 요약에 정확한 명령을 보여 줍니다.

릴리스 설명은 CHANGELOG.md의 해당 버전 절을 씁니다 (없으면 비워 둠).

사용법:
    python release.py                        # 상태 + 다음 버전 제안
    python release.py 0.4.0                  # 전체 파이프라인
    python release.py 0.4.0 --dry-run        # 무엇을 할지 보여 주기만 (아무것도 바꾸지 않음)
    python release.py 0.4.0 --skip-build     # 기존 dist/FocusApp 재사용
    python release.py 0.4.0 --publish-only   # 이미 만든 파일만 올리기 (bump/build 없음)

옵션:
    --dry-run        파일·GitHub를 건드리지 않고 각 단계를 출력만
    --yes / -y       확인 질문 건너뛰기
    --skip-tests     pytest 건너뛰기
    --skip-build     PyInstaller 건너뛰기 (dist/FocusApp 재사용)
    --publish-only   bump·build 없이 이미 만든 파일 올리기
    --no-publish     GitHub 릴리스 만들기·업로드 건너뛰기 (로컬 빌드만)
    --urgency U      optional | recommended | critical   (기본: optional)
                     recommended: 앱이 알림으로 알려 줌
                     critical:    앱이 실행되자마자 업데이트 창을 띄움

준비물:
    * `gh auth login` ('repo' 권한)  -> 릴리스 생성 + 파일 업로드
    * Inno Setup 6                   -> 설치 프로그램 빌드
    * pip install -r requirements-dev.txt  (pytest, pyinstaller)
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import webbrowser
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # 한글 출력이 깨지지 않게

# ---------------------------------------------------------------- 설정

ROOT = os.path.dirname(os.path.abspath(__file__))

VERSION_FILE = os.path.join("focus_app", "version.py")
PYPROJECT_FILE = "pyproject.toml"
CHANGELOG_FILE = "CHANGELOG.md"
SPEC_FILE = os.path.join("installer", "FocusApp.spec")
ISS_FILE = os.path.join("installer", "FocusApp.iss")
EXE_NAME = "FocusApp.exe"
DIST_DIR = "dist"
BUILD_NAME = "FocusApp"
INSTALLER_OUTPUT_DIR = "installer_output"

GITHUB_REPO = "JWK03-9233/FOCUS_APP"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases/new"
INSTALLER_NAME = "FocusApp_Setup_{version}.exe"
ZIP_NAME = "FocusApp-v{version}-win64.zip"
SUMS_NAME = "SHA256SUMS.txt"
DOWNLOAD_URL_TEMPLATE = "https://github.com/" + GITHUB_REPO + "/releases/download/v{version}/{name}"

# bump가 고치는 파일. 이 스크립트는 git을 쓰지 않으므로 마지막에 커밋할 목록으로 보여 줌
VERSIONED_FILES = [VERSION_FILE, PYPROJECT_FILE, CHANGELOG_FILE]

CHANGELOG_PLACEHOLDER = "- (바뀐 점을 적어 주세요)"

INNO_SETUP_PATHS = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
]

DRY_RUN = False


def say(msg=""):
    print(msg, flush=True)


def step(title):
    say("")
    say("=" * 62)
    say(f"  {title}")
    say("=" * 62)


def dry(msg):
    say(f"   [dry-run] {msg}")


def run(cmd, **kw):
    """--dry-run을 따르는 subprocess.run."""
    if DRY_RUN:
        dry("실행할 명령: " + " ".join(str(c) for c in cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return subprocess.run(cmd, **kw)


def rel(path):
    return os.path.relpath(path, ROOT)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- 도구 찾기

def find_inno_setup():
    for path in INNO_SETUP_PATHS:
        if os.path.exists(path):
            return path
    return shutil.which("iscc")


def find_gh():
    return shutil.which("gh")


def gh_authenticated():
    """(ok, 설명). 파일을 올리려면 gh에 'repo' 권한이 있어야 합니다."""
    gh = find_gh()
    if not gh:
        return False, "gh CLI가 없습니다 (https://cli.github.com)"
    try:
        r = subprocess.run([gh, "auth", "status"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
    except Exception as e:
        return False, f"gh auth status 실패: {e}"
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return False, "gh에 로그인되어 있지 않습니다 - 실행: gh auth login"
    if "'repo'" not in out and '"repo"' not in out and " repo" not in out:
        return False, "gh 토큰에 'repo' 권한이 없습니다 - 실행: gh auth refresh -s repo"
    return True, "'repo' 권한으로 로그인됨"


def gh_token():
    """빌드 결과물에 토큰이 섞여 들어가지 않았는지 검사할 때 쓰는 gh 토큰 값."""
    gh = find_gh()
    if not gh:
        return None
    try:
        r = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=20)
        return r.stdout.strip() or None
    except Exception:
        return None


# ---------------------------------------------------------------- 버전

def get_current_version():
    with open(os.path.join(ROOT, VERSION_FILE), "r", encoding="utf-8") as f:
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', f.read())
    return m.group(1) if m else None


def get_latest_github_version():
    """공개된 최신 릴리스 태그 (draft 제외)."""
    gh = find_gh()
    if gh:
        try:
            r = subprocess.run([gh, "release", "view", "--repo", GITHUB_REPO, "--json", "tagName"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=20)
            if r.returncode == 0:
                tag = json.loads(r.stdout).get("tagName", "")
                if tag:
                    return tag.lstrip("v")
        except Exception:
            pass
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "FocusApp-Release"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            tag = json.loads(resp.read().decode()).get("tag_name", "")
            return tag.lstrip("v") if tag else None
    except Exception:
        return None


def suggest_next_versions(version_str):
    try:
        major, minor, patch = (int(p) for p in version_str.split(".")[:3])
        return {"patch": f"{major}.{minor}.{patch + 1}", "minor": f"{major}.{minor + 1}.0"}
    except (ValueError, IndexError):
        return None


def version_tuple(v):
    try:
        return tuple(int(p) for p in v.split(".")[:3])
    except (ValueError, AttributeError):
        return (0, 0, 0)


def release_info(version):
    """(존재 여부, draft 여부)."""
    gh = find_gh()
    if not gh:
        return False, False
    r = subprocess.run([gh, "release", "view", f"v{version}", "--repo", GITHUB_REPO, "--json", "isDraft"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return False, False
    try:
        return True, bool(json.loads(r.stdout).get("isDraft"))
    except ValueError:
        return True, False


# ---------------------------------------------------------------- 변경 기록

def changelog_section(version):
    """CHANGELOG.md에서 해당 버전 절의 본문. 없으면 None."""
    path = os.path.join(ROOT, CHANGELOG_FILE)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"(?ms)^##\s*\[?v?" + re.escape(version) + r"\]?[^\n]*\n(.*?)(?=^##\s|\Z)", text)
    return m.group(1).strip() if m else None


def ensure_changelog_section(version):
    path = os.path.join(ROOT, CHANGELOG_FILE)
    body = open(path, encoding="utf-8").read() if os.path.exists(path) else "# 변경 기록\n"
    if changelog_section(version) is not None:
        return
    head, _, rest = body.partition("\n## ")
    entry = f"## [{version}] - {datetime.now():%Y-%m-%d}\n\n{CHANGELOG_PLACEHOLDER}\n"
    new = f"{head.rstrip()}\n\n{entry}" + (f"\n## {rest}" if rest else "")
    if DRY_RUN:
        dry(f"{CHANGELOG_FILE}에 [{version}] 절 추가")
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    say(f"OK  {CHANGELOG_FILE}에 [{version}] 절 추가 (내용을 채워 주세요)")


# ---------------------------------------------------------------- bump

def _rewrite(rel_path, pattern, replacement, label):
    path = os.path.join(ROOT, rel_path)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    new_content, n = re.subn(pattern, replacement, content, count=1, flags=re.M)
    if n == 0:
        say(f"!!  {rel_path}에서 버전을 찾지 못했습니다")
        return False
    if DRY_RUN:
        dry(f"{rel_path}: {label}")
        return True
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    say(f"OK  {rel_path}: {label}")
    return True


def bump(new_version):
    step("BUMP - 버전 파일")
    ok = _rewrite(VERSION_FILE, r'(__version__\s*=\s*")[^"]+(")', rf"\g<1>{new_version}\g<2>",
                  f"__version__ = {new_version}")
    ok &= _rewrite(PYPROJECT_FILE, r'^(version\s*=\s*")[^"]+(")', rf"\g<1>{new_version}\g<2>",
                   f"version = {new_version}")
    ensure_changelog_section(new_version)
    return ok


# ---------------------------------------------------------------- test / build

def run_tests():
    step("TEST - pytest")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, env=env)
    if DRY_RUN:
        return True
    if r.returncode != 0:
        say(f"\nXX  테스트 실패 (exit {r.returncode}) - 아무것도 바꾸지 않고 멈춥니다.")
        return False
    say("OK  테스트 통과")
    return True


def build_exe():
    step("BUILD - PyInstaller")
    r = run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", SPEC_FILE], cwd=ROOT)
    if DRY_RUN:
        return True
    if r.returncode != 0:
        say(f"\nXX  빌드 실패 (exit {r.returncode})")
        return False
    exe_path = os.path.join(ROOT, DIST_DIR, BUILD_NAME, EXE_NAME)
    if not os.path.exists(exe_path):
        say(f"\nXX  빌드는 성공했다는데 {exe_path}가 없습니다")
        return False
    say(f"\nOK  빌드 완료: {rel(exe_path)}")
    return True


def check_build_version(version):
    """빌드된 exe의 파일 버전이 bump한 버전과 같은지 (예전 빌드를 올리는 실수 방지)."""
    exe_path = os.path.join(ROOT, DIST_DIR, BUILD_NAME, EXE_NAME)
    if DRY_RUN or not os.path.exists(exe_path):
        return True
    ps = f"(Get-Item -LiteralPath '{exe_path}').VersionInfo.ProductVersion"
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    found = (r.stdout or "").strip()
    if found and found != version:
        say(f"XX  빌드된 exe 버전({found})이 릴리스 버전({version})과 다릅니다. --skip-build 없이 다시 빌드하세요.")
        return False
    say(f"OK  exe 버전 정보: {found or '(읽지 못함)'}")
    return True


# dist/FocusApp 안에 절대 들어가면 안 되는 파일 (zip과 설치 프로그램이 폴더를 통째로 담음)
FORBIDDEN_BUILD_FILES = {".github_token", ".env", "settings.json", "session.json", "focus_app.log"}
TOKEN_PATTERN = re.compile(rb"(ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,}|gho_[A-Za-z0-9]{36})")


def check_build_secrets():
    """빌드 폴더에 비밀 파일이나 GitHub 토큰 문자열이 있으면 릴리스를 멈춥니다. 깨끗하면 True."""
    step("SECRETS - 빌드 결과물 검사")
    source_dir = os.path.join(ROOT, DIST_DIR, BUILD_NAME)
    if DRY_RUN:
        dry(f"{rel(source_dir)}에서 {sorted(FORBIDDEN_BUILD_FILES)} 와 GitHub 토큰 검사")
        return True
    token = gh_token()
    token_bytes = token.encode() if token else None
    problems = []
    for dirpath, _dirs, files in os.walk(source_dir):
        for name in files:
            path = os.path.join(dirpath, name)
            if name in FORBIDDEN_BUILD_FILES or name.startswith(".env"):
                problems.append(f"들어가면 안 되는 파일: {rel(path)}")
                continue
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            if token_bytes and token_bytes in data:
                problems.append(f"내 GitHub 토큰이 들어 있음: {rel(path)}")
            elif TOKEN_PATTERN.search(data):
                problems.append(f"GitHub 토큰으로 보이는 문자열: {rel(path)}")
    if problems:
        for p in problems:
            say(f"XX  {p}")
        return False
    say("OK  비밀 파일이나 토큰 문자열 없음")
    return True


def create_zip(version):
    source_dir = os.path.join(ROOT, DIST_DIR, BUILD_NAME)
    zip_path = os.path.join(ROOT, DIST_DIR, ZIP_NAME.format(version=version))
    if DRY_RUN:
        dry(f"{rel(source_dir)} -> {rel(zip_path)}")
        return zip_path
    if not os.path.exists(source_dir):
        say(f"XX  빌드 폴더가 없습니다: {source_dir}")
        return None
    say("\nZIP 만드는 중...")
    try:
        base = zip_path[:-4]
        final_zip = shutil.make_archive(base, "zip", os.path.join(ROOT, DIST_DIR), BUILD_NAME)
        say(f"OK  ZIP: {rel(final_zip)}  ({os.path.getsize(final_zip) / 1048576:.1f} MB)")
        return final_zip
    except Exception as e:
        say(f"XX  ZIP 만들기 실패: {e}")
        return None


def build_installer(version):
    step("PACKAGE - Inno Setup")
    iscc = find_inno_setup()
    if not iscc:
        say("XX  Inno Setup을 찾지 못했습니다.")
        return None
    out_dir = os.path.join(ROOT, INSTALLER_OUTPUT_DIR)
    installer_path = os.path.join(out_dir, INSTALLER_NAME.format(version=version))
    cmd = [iscc, f"/DMyAppVersion={version}", f"/DMyOutputDir={out_dir}", ISS_FILE]
    if DRY_RUN:
        dry(" ".join(cmd))
        return installer_path
    os.makedirs(out_dir, exist_ok=True)
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        say(f"XX  설치 프로그램 빌드 실패 (exit {r.returncode})")
        say((r.stdout or "")[-2000:])
        say((r.stderr or "")[-2000:])
        return None
    if not os.path.exists(installer_path):
        say(f"XX  설치 프로그램이 예상 위치에 없습니다: {installer_path}")
        return None
    say(f"OK  설치 프로그램: {rel(installer_path)}  ({os.path.getsize(installer_path) / 1048576:.1f} MB)")
    return installer_path


def write_checksums(version, assets):
    path = os.path.join(ROOT, INSTALLER_OUTPUT_DIR, SUMS_NAME)
    if DRY_RUN:
        dry(f"{rel(path)}에 SHA-256 기록")
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii", newline="\n") as f:
        for a in assets:
            f.write(f"{sha256_of(a)}  {os.path.basename(a)}\n")
    say(f"OK  체크섬: {rel(path)}")
    return path


# ---------------------------------------------------------------- publish

def release_notes(version, urgency):
    notes = changelog_section(version) or ""
    if notes.strip() == CHANGELOG_PLACEHOLDER:
        notes = ""
    marker = f"<!-- focusapp-urgency: {urgency} -->"  # 앱이 읽는 업데이트 중요도 (화면에는 안 보임)
    return (notes + "\n\n" + marker).strip()


def publish_release(version, assets, urgency):
    """draft로 만들어 올린 뒤 체크섬을 확인하고 나서 공개합니다."""
    step("PUBLISH - GitHub Release")
    gh = find_gh()
    if not gh:
        say("XX  gh CLI가 없어 직접 올려야 합니다.")
        open_github_release(version)
        return False

    assets = [a for a in assets if a and (DRY_RUN or os.path.exists(a))]
    if not assets:
        say("XX  올릴 파일이 없습니다 - 중단합니다.")
        return False
    for a in assets:
        say(f"   - {os.path.basename(a)}")

    tag = f"v{version}"
    exists, is_draft = (False, False) if DRY_RUN else release_info(version)
    notes_path = os.path.join(tempfile.mkdtemp(prefix="focusapp-notes-"), "notes.md")
    if not DRY_RUN:
        with open(notes_path, "w", encoding="utf-8") as f:
            f.write(release_notes(version, urgency))

    # 1) draft 만들기 (또는 기존 draft에 덮어쓰기)
    if exists and not is_draft:
        say(f"..  v{version}은 이미 공개된 릴리스입니다 - 파일만 --clobber로 교체합니다")
        r = run([gh, "release", "upload", tag, *assets, "--repo", GITHUB_REPO, "--clobber"], cwd=ROOT)
    elif exists:
        say(f"..  v{version} draft가 이미 있습니다 - 파일을 --clobber로 다시 올립니다")
        r = run([gh, "release", "upload", tag, *assets, "--repo", GITHUB_REPO, "--clobber"], cwd=ROOT)
        if DRY_RUN or r.returncode == 0:
            r = run([gh, "release", "edit", tag, "--repo", GITHUB_REPO, "--notes-file", notes_path], cwd=ROOT)
    else:
        r = run([gh, "release", "create", tag, *assets, "--repo", GITHUB_REPO, "--draft",
                 "--title", f"FocusApp {tag}", "--notes-file", notes_path], cwd=ROOT)
    if not DRY_RUN and r.returncode != 0:
        say(f"XX  gh release 실패 (exit {r.returncode}) - 웹 페이지를 엽니다")
        open_github_release(version)
        return False

    # 2) 올라간 파일의 체크섬이 로컬과 같은지 확인
    if not verify_uploaded_assets(version, assets):
        say("XX  올라간 파일이 로컬과 다릅니다 - draft로 남겨 둡니다 (사용자에게 보이지 않음).")
        return False

    # 3) 공개 + 최신으로 지정 (이때부터 앱이 새 버전을 봄)
    if not exists or is_draft:
        r = run([gh, "release", "edit", tag, "--repo", GITHUB_REPO, "--draft=false", "--latest"], cwd=ROOT)
        if not DRY_RUN and r.returncode != 0:
            say("XX  릴리스 공개 실패 - draft로 남아 있습니다. GitHub에서 직접 공개하세요.")
            return False
    say(f"OK  공개됨: https://github.com/{GITHUB_REPO}/releases/tag/{tag}")
    return True


def verify_uploaded_assets(version, assets):
    if DRY_RUN:
        dry("올라간 파일의 sha256 digest를 로컬 파일과 비교")
        return True
    r = subprocess.run([find_gh(), "release", "view", f"v{version}", "--repo", GITHUB_REPO, "--json", "assets"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        say("XX  릴리스 정보를 읽지 못했습니다")
        return False
    remote = {a["name"]: (a.get("digest") or "", a.get("size")) for a in json.loads(r.stdout).get("assets", [])}
    ok = True
    for a in assets:
        name = os.path.basename(a)
        digest, size = remote.get(name, ("", None))
        local = sha256_of(a)
        if name not in remote:
            say(f"XX  올라가지 않음: {name}")
            ok = False
        elif digest and digest != f"sha256:{local}":
            say(f"XX  체크섬 불일치: {name}")
            ok = False
        elif size != os.path.getsize(a):
            say(f"XX  크기 불일치: {name}")
            ok = False
        else:
            say(f"OK  {name}  sha256:{local[:16]}…")
    return ok


def verify_download(version):
    """앱이 받을 설치 프로그램 주소가 실제로 열리는지 확인합니다."""
    url = DOWNLOAD_URL_TEMPLATE.format(version=version, name=INSTALLER_NAME.format(version=version))
    if DRY_RUN:
        dry(f"{url} 확인")
        return True
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "FocusApp-Release"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            ok = 200 <= resp.status < 400
    except Exception as e:
        say(f"XX  다운로드 주소에 접속하지 못했습니다: {e}")
        return False
    say(f"{'OK ' if ok else 'XX '} 다운로드 주소 확인: {url}")
    return ok


def open_github_release(version):
    url = f"{GITHUB_RELEASES_URL}?tag=v{version}&title=FocusApp%20v{version}"
    webbrowser.open(url)
    say(f"    v{version} 릴리스 페이지를 열었습니다 - 파일을 직접 올려 주세요.")


# ---------------------------------------------------------------- preflight

def preflight(version, opts):
    """긴 빌드를 시작하기 전에, 실패할 수 있는 것을 모두 미리 확인합니다."""
    step("PREFLIGHT")
    errors, warnings = [], []

    if not re.match(r"^\d+\.\d+\.\d+$", version):
        errors.append(f"버전 형식이 잘못됐습니다: '{version}' - 주.부.수 (예: 0.4.0)")

    current = get_current_version()
    say(f"   로컬 버전              : {current}")
    if current and version_tuple(version) < version_tuple(current) and not opts["publish_only"]:
        errors.append(f"새 버전 {version}이 로컬 버전 {current}보다 낮습니다")
    elif current == version and not opts["publish_only"]:
        warnings.append(f"로컬 버전이 이미 {version}입니다 (bump 없이 빌드)")

    latest = get_latest_github_version()
    if latest:
        say(f"   GitHub 최신 릴리스     : v{latest}")
        if version_tuple(version) <= version_tuple(latest) and not opts["publish_only"]:
            errors.append(f"v{version}은 이미 공개된 v{latest}보다 새 버전이 아닙니다")

    if not opts["publish_only"] and not opts["skip_build"]:
        try:
            import PyInstaller  # noqa: F401
        except ImportError:
            errors.append("PyInstaller가 없습니다 - pip install -r requirements-dev.txt")
        if not os.path.exists(os.path.join(ROOT, SPEC_FILE)):
            errors.append(f"{SPEC_FILE}가 없습니다")
    if not opts["publish_only"] and not opts["skip_tests"]:
        try:
            import pytest  # noqa: F401
        except ImportError:
            errors.append("pytest가 없습니다 - pip install -r requirements-dev.txt")

    iscc = find_inno_setup()
    say(f"   Inno Setup             : {iscc or '없음'}")
    if not iscc and not opts["publish_only"]:
        errors.append("Inno Setup 6이 없습니다 - 설치 프로그램 없이는 앱 업데이트가 동작하지 않습니다 "
                      "(winget install JRSoftware.InnoSetup)")

    notes = changelog_section(version)
    if notes is None or notes.strip() in ("", CHANGELOG_PLACEHOLDER):
        warnings.append(f"{CHANGELOG_FILE}에 [{version}] 변경 내용이 없습니다 - 릴리스 설명이 비게 됩니다")

    if not opts["no_publish"]:
        ok, detail = gh_authenticated()
        say(f"   gh CLI                 : {detail}")
        if not ok:
            errors.append(detail)
        else:
            exists, is_draft = release_info(version)
            if exists and not is_draft:
                warnings.append(f"v{version} 릴리스가 이미 공개되어 있습니다 - 파일이 교체됩니다")
            elif exists:
                warnings.append(f"v{version} draft가 이미 있습니다 - 이어서 올립니다")

    for w in warnings:
        say(f"   !!  {w}")
    for e in errors:
        say(f"   XX  {e}")

    if errors:
        say("\nPreflight 실패. 아무것도 바꾸지 않았습니다.")
        return False
    say("\nOK  Preflight 통과")
    return True


# ---------------------------------------------------------------- 요약

def summary(version, state):
    step("RELEASE SUMMARY")
    rows = [
        ("테스트", state.get("tested")),
        ("버전 bump", state.get("bumped")),
        ("빌드", state.get("built")),
        ("비밀 검사", state.get("secrets")),
        ("ZIP", state.get("zip")),
        ("설치 프로그램", state.get("installer")),
        ("GitHub 릴리스 (앱 업데이트)", state.get("published")),
        ("다운로드 확인", state.get("verified")),
    ]
    for label, value in rows:
        if value is None:
            mark, detail = "--", "건너뜀"
        elif value is False:
            mark, detail = "XX", "실패"
        else:
            mark, detail = "OK", "완료"
        say(f"  {mark}  {label:<28} {detail}")

    if state.get("bumped"):
        files = " ".join(f.replace(os.sep, "/") for f in VERSIONED_FILES if os.path.exists(os.path.join(ROOT, f)))
        say("\n  버전 파일을 고쳤지만 커밋하지 않았습니다. 커밋하려면:")
        say(f"    git add {files}")
        say(f'    git commit -m "Release v{version}"')
        say("    git push")

    if state.get("published") and state.get("verified"):
        say(f"\nv{version} 배포 완료. 확인: 이전 버전 FocusApp -> '업데이트 확인'")
    elif not DRY_RUN and state.get("published") is not None:
        say(f"\nv{version}이 완전히 배포되지 않았습니다. 이어서 하려면:")
        say(f"    python release.py {version} --publish-only")


# ---------------------------------------------------------------- 상태

def print_status():
    current = get_current_version()
    say(f"\n로컬 버전 (version.py):    {current}")
    github_ver = get_latest_github_version()
    if github_ver:
        say(f"GitHub 최신 릴리스:        {github_ver}")
        say("   일치" if current == github_ver else "   !! 로컬과 GitHub가 다릅니다")
        base = github_ver if version_tuple(github_ver) >= version_tuple(current or "0") else current
    else:
        say("GitHub 최신 릴리스:        (가져오지 못함)")
        base = current
    suggestions = suggest_next_versions(base) if base else None

    ok, detail = gh_authenticated()
    say(f"gh CLI:                    {detail}")
    say(f"Inno Setup:                {find_inno_setup() or '없음'}")

    say("\n" + "-" * 50)
    say("사용법: python release.py <버전> [옵션]")
    if suggestions:
        say("\n추천:")
        say(f"  Patch  python release.py {suggestions['patch']}")
        say(f"  Minor  python release.py {suggestions['minor']}")
    say("\n옵션: --dry-run  --yes  --skip-tests  --skip-build  --publish-only  --no-publish")
    say("      --urgency optional|recommended|critical")
    say("\n이 스크립트는 커밋·태그를 하지 않습니다 - 릴리스 뒤에 직접 하세요.")


# ---------------------------------------------------------------- main

def parse_args(argv):
    flags = {
        "dry_run": "--dry-run" in argv,
        "yes": "--yes" in argv or "-y" in argv,
        "skip_tests": "--skip-tests" in argv,
        "skip_build": "--skip-build" in argv,
        "publish_only": "--publish-only" in argv,
        "no_publish": "--no-publish" in argv,
        "urgency": "optional",
    }
    positional = []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--urgency" and i + 1 < len(argv):
            flags["urgency"] = argv[i + 1]
            i += 2
            continue
        if not a.startswith("-"):
            positional.append(a)
        i += 1
    return flags, positional


def main():
    global DRY_RUN

    flags, positional = parse_args(sys.argv)
    if not positional:
        print_status()
        return 0

    DRY_RUN = flags["dry_run"]
    new_version = positional[0]

    if flags["urgency"] not in ("optional", "recommended", "critical"):
        say(f"XX  --urgency 값이 잘못됐습니다: '{flags['urgency']}'")
        return 1

    if DRY_RUN:
        say("\n*** DRY RUN - 아무것도 쓰거나 올리지 않습니다. ***")

    if not preflight(new_version, flags):
        return 1

    step("PLAN")
    say(f"   {get_current_version()}  ->  {new_version}   (중요도: {flags['urgency']})")
    if not flags["publish_only"]:
        say("   버전 파일을 고치지만 커밋하지 않습니다 - 커밋은 직접 하세요.")

    if not flags["yes"] and not DRY_RUN:
        if input(f"\n{new_version} 릴리스를 진행할까요? (y/n): ").strip().lower() != "y":
            say("취소했습니다.")
            return 1

    state = {}

    # --- test (bump 전에: 실패하면 아무것도 바뀌지 않음) ---------------------
    if flags["publish_only"] or flags["skip_tests"]:
        state["tested"] = None
    else:
        state["tested"] = run_tests()
        if not state["tested"]:
            summary(new_version, state)
            return 1

    # --- bump -------------------------------------------------------------
    if not flags["publish_only"]:
        state["bumped"] = bump(new_version)

    # --- build ------------------------------------------------------------
    version = new_version
    zip_path = installer_path = None
    if flags["publish_only"]:
        zp = os.path.join(ROOT, DIST_DIR, ZIP_NAME.format(version=version))
        ip = os.path.join(ROOT, INSTALLER_OUTPUT_DIR, INSTALLER_NAME.format(version=version))
        zip_path = zp if os.path.exists(zp) else None
        installer_path = ip if os.path.exists(ip) else None
        state["zip"] = True if zip_path else None
        state["installer"] = True if installer_path else False
    else:
        if flags["skip_build"]:
            say("\n--  PyInstaller 건너뜀 (--skip-build)")
            built_ok = DRY_RUN or os.path.exists(os.path.join(ROOT, DIST_DIR, BUILD_NAME))
            if not built_ok:
                say(f"XX  {DIST_DIR}/{BUILD_NAME}에 기존 빌드가 없습니다.")
        else:
            built_ok = build_exe()
            state["built"] = built_ok

        built_ok = built_ok and check_build_version(version)
        if built_ok:
            state["secrets"] = check_build_secrets()
            built_ok = state["secrets"]

        if built_ok:
            zip_path = create_zip(version)
            state["zip"] = bool(zip_path)
            installer_path = build_installer(version)
            state["installer"] = bool(installer_path)
        else:
            say("\nXX  빌드를 쓸 수 없어 배포 전에 멈춥니다. 버전 파일은 이미 고쳐졌습니다.")
            summary(version, state)
            return 1

    if not installer_path:
        say("\nXX  설치 프로그램이 없습니다 - 앱이 업데이트할 수 없는 릴리스는 올리지 않습니다.")
        summary(version, state)
        return 1

    # --- publish (draft -> 검증 -> 공개) ------------------------------------
    if flags["no_publish"]:
        state["published"] = None
    else:
        assets = [installer_path, zip_path]
        assets.append(write_checksums(version, [a for a in assets if a]))
        state["published"] = publish_release(version, assets, flags["urgency"])
        if not state["published"]:
            summary(version, state)
            return 1
        state["verified"] = verify_download(version)

    summary(version, state)
    return 0 if state.get("verified") is not False else 1


if __name__ == "__main__":
    sys.exit(main())
