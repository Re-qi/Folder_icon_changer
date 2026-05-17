[Setup]
AppName=Folder Icon Changer
AppVersion=1.0.0
DefaultDirName={autopf}\FolderIconChanger
DefaultGroupName=Folder Icon Changer
UninstallDisplayIcon={app}\bin\folder_icon_changer.exe
OutputDir=..\Output
OutputBaseFilename=FolderIconChanger_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\ico\folder11.ico

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务"

[Files]
Source: "..\dist\app\bin\folder_icon_changer.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "..\dist\app\bin\icon_creator.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "..\dist\app\bin\icon_downloader.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "..\dist\app\ico\*"; DestDir: "{app}\ico"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Folder Icon Changer"; Filename: "{app}\bin\folder_icon_changer.exe"; IconFilename: "{app}\bin\..\ico\folder11.ico"
Name: "{autodesktop}\Folder Icon Changer"; Filename: "{app}\bin\folder_icon_changer.exe"; Tasks: desktopicon; IconFilename: "{app}\bin\..\ico\folder11.ico"

