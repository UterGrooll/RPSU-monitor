; Inno Setup — установщик RPSU Monitor
; Программа ставится в Program Files (только чтение), данные (config.json + логи)
; пишутся в %PROGRAMDATA%\RPSU Monitor. Папку для SCADA-CSV задают в самой программе.
; Сборка: сначала PyInstaller (см. build.bat), затем  iscc installer\RPSU-monitor.iss

#define AppName "RPSU Monitor"
#define AppVersion "0.3"
#define AppPublisher "UterGrooll"
#define AppExe "RPSU.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppId={{6CDAD667-804D-40CE-AF78-E9A0940D69A8}}
DefaultDirName={autopf}\RPSU Monitor
DefaultGroupName=RPSU Monitor
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=Output
OutputBaseFilename=RPSU-Monitor-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
WizardStyle=modern

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
; onefile-сборка PyInstaller (один RPSU.exe в dist\)
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
; Если соберёшь onedir (pyinstaller без --onefile), замени строку выше на:
; Source: "..\dist\RPSU\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; Папка данных — общая, с правом записи всем пользователям
Name: "{commonappdata}\RPSU Monitor"; Permissions: users-modify

[Icons]
Name: "{group}\RPSU Monitor"; Filename: "{app}\{#AppExe}"
Name: "{group}\Удалить RPSU Monitor"; Filename: "{uninstallexe}"
Name: "{commondesktop}\RPSU Monitor"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
; Автозапуск настраивается в самой программе (Параметры → «Автозапуск с Windows»).

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Запустить RPSU Monitor"; Flags: nowait postinstall skipifsilent
