#ifndef AppVersion
#define AppVersion "0.1.0"
#endif
[Setup]
AppId={{4639BA85-4BEF-4202-98AE-26FD5E60EAB2}
AppName=Aletheia
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Aletheia
DefaultGroupName=Aletheia
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Aletheia-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\Aletheia.exe
[Tasks]
Name: "autostart"; Description: "Start Aletheia when I sign in"; Flags: checkedonce
[Files]
Source: "..\..\dist\Aletheia\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Aletheia"; Filename: "{app}\Aletheia.exe"
Name: "{group}\Uninstall Aletheia"; Filename: "{uninstallexe}"
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Aletheia"; ValueData: """{app}\Aletheia.exe"""; Tasks: autostart; Flags: uninsdeletevalue
[Run]
Filename: "{app}\Aletheia.exe"; Parameters: "--install-native-host"; Flags: runhidden waituntilterminated; Tasks: autostart
Filename: "{app}\Aletheia.exe"; Parameters: "--install-native-host --no-autostart"; Flags: runhidden waituntilterminated; Tasks: not autostart
Filename: "{app}\Aletheia.exe"; Description: "Start Aletheia"; Flags: nowait postinstall skipifsilent
[UninstallRun]
Filename: "{app}\Aletheia.exe"; Parameters: "--uninstall"; Flags: runhidden waituntilterminated
