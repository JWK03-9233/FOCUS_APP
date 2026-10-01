; FocusApp 설치 프로그램 (Inno Setup 6)
;
; 보통은 scripts\release.py가 버전과 출력 폴더를 넘겨 컴파일합니다:
;   ISCC.exe /DMyAppVersion=0.4.0 /DMyOutputDir=..\installer_output installer\FocusApp.iss
;
; 앱 안의 업데이트는 이 설치 파일을 다음처럼 조용히 실행합니다:
;   FocusApp_Setup_<버전>.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="<현재 설치 폴더>" /RESTARTAPP=1
; /RESTARTAPP=1이면 설치가 끝난 뒤 FocusApp을 다시 실행합니다.
;
; 설정·세션은 %APPDATA%\FocusApp에 있으므로 업데이트·제거해도 지워지지 않습니다.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "..\installer_output"
#endif

#define MyAppName "FocusApp"
#define MyAppExeName "FocusApp.exe"
#define MyAppPublisher "JWK03-9233"
#define MyAppURL "https://github.com/JWK03-9233/FOCUS_APP"

[Setup]
; AppId는 절대 바꾸지 마세요. 바꾸면 업데이트가 아니라 별도 앱으로 설치됩니다.
AppId={{6F1C2B7A-4E2D-4C57-9B0E-8F3A5D1C9E42}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppVersion}
; 관리자 권한 없이 사용자 폴더에 설치 (앱 안 업데이트가 권한 요청 없이 되도록)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
OutputDir={#MyOutputDir}
OutputBaseFilename=FocusApp_Setup_{#MyAppVersion}
SetupIconFile=..\focus_app\assets\focus_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 실행 중인 FocusApp을 닫고 설치 (Restart Manager)
CloseApplications=force
RestartApplications=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Windows를 시작할 때 FocusApp 자동 실행"; GroupDescription: "시작 옵션:"; Flags: unchecked
; 관리자 확인(UAC) 1번. 관리자 권한 앱 차단 · 강제로 끄면 다시 띄우기 · 엄격 모드에 필요
Name: "helper"; Description: "관리자 권한 도우미 설치 (강제 종료 방지 · 관리자 권한 앱 차단, 관리자 확인 1번)"; GroupDescription: "집중 보호:"

[Files]
; 이전 버전에서 사라진 파일이 남지 않도록 _internal은 통째로 교체
Source: "..\dist\FocusApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
; 일반 설치: 마지막 화면의 "FocusApp 실행" 체크박스
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
; 앱 안 업데이트(조용한 설치): /RESTARTAPP=1이면 끝난 뒤 다시 실행
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: ShouldRestartApp

[Code]
function ShouldRestartApp: Boolean;
begin
  Result := ExpandConstant('{param:RESTARTAPP|0}') = '1';
end;

{ 설치할 때 '관리자 권한 도우미 설치'를 골랐으면 UAC를 거쳐 도우미 작업을 등록.
  앱 안 업데이트(조용한 설치)에서는 확인 창이 뜨지 않게 건너뜀 (작업은 같은 경로를 가리키므로 그대로 둬도 됨).
  취소하거나 실패해도 설치는 계속되고, 나중에 앱의 ⚙ 설정에서 설치할 수 있음. }
procedure RegisterHelper;
var
  ResultCode: Integer;
begin
  if not ShellExec('runas', ExpandConstant('{app}\{#MyAppExeName}'), '--register-helper', '', SW_HIDE,
                   ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
    MsgBox('관리자 권한 도우미를 설치하지 못했습니다. 나중에 FocusApp의 ⚙ 설정에서 설치할 수 있습니다.',
           mbInformation, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('helper') and not WizardSilent then
    RegisterHelper;
end;

{ 관리자 권한 도우미 작업(앱 설정이나 설치할 때 등록)이 있으면 제거할 때 함께 지움. 관리자 확인(UAC)이 한 번 뜹니다.
  도우미가 등록하는 본 앱 다시 띄우기 작업(FocusApp\Main)도 같이 지움. }
function HelperTaskExists: Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\schtasks.exe'), '/Query /TN "FocusApp\Helper"', '', SW_HIDE,
                 ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if (CurUninstallStep = usUninstall) and HelperTaskExists then
    ShellExec('runas', ExpandConstant('{cmd}'),
              '/c schtasks /Delete /TN "FocusApp\Main" /F & schtasks /Delete /TN "FocusApp\Helper" /F', '',
              SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;
