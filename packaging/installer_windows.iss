; ==============================================================================
; Script: packaging/installer_windows.iss
; Instalador Inno Setup para VmPOS v4.1.0 (Windows 10 / 11)
; ==============================================================================

#define MyAppName "VmPOS"
#define MyAppVersion "4.1.0"
#define MyAppPublisher "VmPOS Software"
#define MyAppURL "https://github.com/Eduardo30111/venta_pos_VM"
#define MyAppExeName "VmPOS.exe"

[Setup]
AppId={{E5847B12-9214-4A3C-9A82-C73B2599B87F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=VmPOS_Setup_v4.1.0
SetupIconFile=..\assets\Salome.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "firewall"; Description: "Permitir comunicación del Servidor POS a través del Firewall de Windows (Puerto 8000)"; GroupDescription: "Configuración de Red:"; Flags: checkedonce

[InstallDelete]
; Limpiar por completo el runtime anterior para evitar archivos .pyc o librerías antiguas en caché
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\{#MyAppExeName}"

[Files]
; Copiar todo el contenido de la carpeta compilada por PyInstaller
Source: "..\dist\VmPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Regla de Firewall opcional para el puerto 8000
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""VmPOS Servidor"" dir=in action=allow protocol=TCP localport=8000"; Tasks: firewall; Flags: runhidden
; Ejecutar la aplicación al finalizar si el usuario lo desea
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM VmPOS.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
