; Inno Setup script para Kodea (Windows).
; Empaqueta la build onedir de PyInstaller (dist\kodea) en un instalador con
; menú de instalación, accesos directos y desinstalador.
;
; La versión se pasa desde CI:  iscc /DAppVersion=1.2.3 installer\kodea.iss
; Compila a:  installer\Output\Kodea-Setup-<version>.exe

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Kodea"
#define AppPublisher "Kodea"
#define AppExeName "kodea.exe"

[Setup]
AppId={{B6F0E2A1-9C7D-4E3B-8A21-0F5C2D1E7A40}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Kodea-Setup-{#AppVersion}
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; toda la carpeta onedir generada por PyInstaller
Source: "..\dist\kodea\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
