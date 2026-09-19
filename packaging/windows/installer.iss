#ifndef AppVersion
#define AppVersion "0.1.0"
#endif
[Setup]
AppId={{4639BA85-4BEF-4202-98AE-26FD5E60EAB2}
AppName=Privacy Guardian
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\PrivacyGuardian
DefaultGroupName=Privacy Guardian
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=PrivacyGuardian-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\PrivacyGuardian.exe
[Tasks]
Name: "autostart"; Description: "Start Privacy Guardian when I sign in"; Flags: checkedonce
[Files]
Source: "..\..\dist\PrivacyGuardian\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Privacy Guardian"; Filename: "{app}\PrivacyGuardian.exe"
Name: "{group}\Uninstall Privacy Guardian"; Filename: "{uninstallexe}"
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "PrivacyGuardian"; ValueData: """{app}\PrivacyGuardian.exe"""; Tasks: autostart; Flags: uninsdeletevalue
[Run]
Filename: "{app}\PrivacyGuardian.exe"; Parameters: "--install-native-host"; Flags: runhidden waituntilterminated; Tasks: autostart
Filename: "{app}\PrivacyGuardian.exe"; Parameters: "--install-native-host --no-autostart"; Flags: runhidden waituntilterminated; Tasks: not autostart
Filename: "{app}\PrivacyGuardian.exe"; Description: "Start Privacy Guardian"; Flags: nowait postinstall skipifsilent
[UninstallRun]
Filename: "{app}\PrivacyGuardian.exe"; Parameters: "--uninstall"; Flags: runhidden waituntilterminated
