; Offline CPU installer. Binaries and weights remain outside the source repository.
#define ProjectRoot AddBackslash(SourcePath) + ".."
#define Payload ProjectRoot + "\temp\offline-payload"
#include "..\temp\offline-payload\payload-sizes.iss"
[Setup]
AppId={{9C6427AA-AC70-4C59-84B1-679AE5688C47}
AppName=AI Test Generator
AppVersion=1.0.1
VersionInfoVersion=1.0.1.0
AppPublisher=AI Test Generator
DefaultDirName={code:DefaultAppDir}
DisableWelcomePage=no
DisableProgramGroupPage=yes
UsePreviousAppDir=no
UsePreviousLanguage=no
UsePreviousTasks=no
UsePreviousGroup=no
UsePreviousSetupType=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CreateUninstallRegKey=no
Uninstallable=yes
UninstallDisplayName=AI Test Generator
UninstallDisplayIcon={app}\AI Test Generator.exe
CloseApplications=no
RestartApplications=no
Compression=lzma2/fast
LZMADictionarySize=16384
LZMANumBlockThreads=1
SolidCompression=yes
WizardStyle=modern
LicenseFile={#ProjectRoot}\LICENSE
OutputDir={#ProjectRoot}\release
OutputBaseFilename=AI-Test-Generator-Setup
AllowNoIcons=yes

[Languages]
Name: russian; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: desktopicon; Description: "Создать ярлык на рабочем столе"; Flags: unchecked

[Files]
Source: "{#Payload}\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Payload}\runtime\*"; DestDir: "{code:RuntimeDir}"; Flags: onlyifdoesntexist recursesubdirs createallsubdirs uninsneveruninstall; Check: NeedRuntime
Source: "{#Payload}\models\*"; DestDir: "{code:ModelsDir}"; Flags: onlyifdoesntexist recursesubdirs createallsubdirs uninsneveruninstall nocompression; Check: NeedModels

[Icons]
Name: "{autodesktop}\AI Test Generator"; Filename: "{app}\AI Test Generator.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\AI Test Generator.exe"; Description: "Запустить AI Test Generator"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\installation.ini"

[Code]
const
  AppBytes = {#AppBytes};
  RuntimeBytes = {#RuntimeBytes};
  ModelBytes = {#ModelBytes};
var
  StoragePage: TInputDirWizardPage;
  FullSpaceLabel: TNewStaticText;
  ExpectedBlobs, ExpectedRuntimeFiles: TStringList;
  IncludeRuntime, IncludeModels: Boolean;
  LastDefaultRuntime, LastDefaultModels: String;

function DefaultAppDir(Param: String): String;
begin
  Result := ExtractFileDrive(ExpandConstant('{srcexe}')) + '\AI Test Generator';
end;

function RuntimeDir(Param: String): String;
begin Result := RemoveBackslashUnlessRoot(Trim(StoragePage.Values[0])); end;
function ModelsDir(Param: String): String;
begin Result := RemoveBackslashUnlessRoot(Trim(StoragePage.Values[1])); end;
function NeedRuntime: Boolean;
begin Result := IncludeRuntime; end;
function NeedModels: Boolean;
begin Result := IncludeModels; end;

function RequiredNewBytes: Int64;
begin
  Result:=AppBytes;
  if IncludeRuntime then Result:=Result+RuntimeBytes;
  if IncludeModels then Result:=Result+ModelBytes;
end;

function SizeInMB(Bytes: Int64): String;
begin Result:=IntToStr((Bytes+1048575) div 1048576)+' МБ';end;

function LocalDirectory(Value: String): Boolean;
begin
  Result := (Length(Value) > 3);
  if Result then Result := (Value[2] = ':') and (Value[3] = '\') and DirExists(Copy(Value,1,3));
end;

function RuntimeComplete(Folder: String): Boolean;
var I: Integer;
begin
  Result:=False;
  for I:=0 to ExpectedRuntimeFiles.Count-1 do
    if not FileExists(AddBackslash(Folder)+ExpectedRuntimeFiles[I]) then Exit;
  Result:=True;
end;

function HexDigest(Value: String): Boolean;
var I: Integer;
begin
  Result := Length(Value)=64;
  if not Result then Exit;
  for I:=1 to Length(Value) do
    if Pos(Lowercase(Value[I]),'0123456789abcdef')=0 then begin Result:=False;Exit;end;
end;

function LoadSmallFile(Path: String; var Data: AnsiString): Boolean;
var Info: TFindRec; Small: Boolean;
begin
  Result:=False;
  if not FindFirst(Path,Info) then Exit;
  Small:=(Info.SizeHigh=0) and (Info.SizeLow<131072);
  FindClose(Info);
  if Small then Result:=LoadStringFromFile(Path,Data);
end;

function IsManifest(Value: String): Boolean;
begin
  StringChangeEx(Value,' ','',True);
  StringChangeEx(Value,#9,'',True);
  StringChangeEx(Value,#10,'',True);
  StringChangeEx(Value,#13,'',True);
  Result:=(Pos('"schemaVersion":',Value)>0) and (Pos('"layers":[',Value)>0);
end;

function CheckManifest(Path, Store: String; Seen: TStringList; Depth: Integer): Boolean;
var Data: AnsiString; Content, Digest, Blob: String; Position: Integer;
begin
  Result:=False;
  if (Depth>4) or (Seen.Count>32) or not LoadSmallFile(Path,Data) then Exit;
  Content:=String(Data);
  if not IsManifest(Content) then Exit;
  Position:=Pos('sha256:',Content);
  if Position=0 then Exit;
  while Position>0 do begin
    Digest:=Copy(Content,Position+7,64);
    if not HexDigest(Digest) then Exit;
    Blob:=AddBackslash(Store)+'blobs\sha256-'+Digest;
    if not FileExists(Blob) then Exit;
    if Seen.IndexOf(Digest)<0 then begin
      Seen.Add(Digest);
      try
        if Lowercase(GetSHA256OfFile(Blob))<>Lowercase(Digest) then Exit;
      except Exit; end;
      if Seen.Count>32 then Exit;
      if LoadSmallFile(Blob,Data) then
        if IsManifest(String(Data)) then
          if not CheckManifest(Blob,Store,Seen,Depth+1) then Exit;
    end;
    Delete(Content,1,Position+70);
    Position:=Pos('sha256:',Content);
  end;
  Result:=True;
end;

function ExistingModelComplete(Store: String): Boolean;
var Seen: TStringList;
begin
  Seen:=TStringList.Create;
  try Result:=CheckManifest(AddBackslash(Store)+'manifests\registry.ollama.ai\library\qwen2.5\1.5b',Store,Seen,0);
  finally Seen.Free;end;
end;

function RunningWithoutModel: Boolean;
var Request: Variant; Body: String;
begin
  Result:=False;
  try
    Request:=CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Request.SetTimeouts(500,500,500,1000);
    Request.Open('GET','http://127.0.0.1:11434/api/tags',False);
    Request.Send;
    if Request.Status=200 then begin
      Body:=Request.ResponseText;
      Result:=Pos('"qwen2.5:1.5b"',Body)=0;
    end;
  except end;
end;

procedure SetStorageDefaults;
var RuntimePath, ModelPath, Existing, Parameter: String;
begin
  RuntimePath:=AddBackslash(WizardDirValue)+'Ollama';
  Existing:=GetEnv('LOCALAPPDATA');
  if Existing<>'' then begin
    Existing:=AddBackslash(Existing)+'Programs\Ollama';
    if RuntimeComplete(Existing) then RuntimePath:=Existing;
  end;
  Parameter:=ExpandConstant('{param:OLLAMADIR|}');
  if Parameter<>'' then RuntimePath:=Parameter;
  ModelPath:=AddBackslash(WizardDirValue)+'models';
  Parameter:=ExpandConstant('{param:MODELSDIR|}');
  if Parameter<>'' then ModelPath:=Parameter
  else begin
    Existing:=GetEnv('OLLAMA_MODELS');
    if (Existing<>'') and ExistingModelComplete(Existing) then ModelPath:=Existing
    else begin
      Existing:=GetEnv('USERPROFILE');
      if Existing<>'' then begin
        Existing:=AddBackslash(Existing)+'.ollama\models';
        if ExistingModelComplete(Existing) then ModelPath:=Existing;
      end;
    end;
  end;
  if (StoragePage.Values[0]='') or (StoragePage.Values[0]=LastDefaultRuntime) then StoragePage.Values[0]:=RuntimePath;
  if (StoragePage.Values[1]='') or (StoragePage.Values[1]=LastDefaultModels) then StoragePage.Values[1]:=ModelPath;
  LastDefaultRuntime:=RuntimePath;LastDefaultModels:=ModelPath;
end;

procedure InitializeWizard;
begin
  IncludeRuntime:=True;IncludeModels:=True;
  WizardForm.DiskSpaceLabel.Visible:=False;
  FullSpaceLabel:=TNewStaticText.Create(WizardForm);
  FullSpaceLabel.Parent:=WizardForm.SelectDirPage;
  FullSpaceLabel.SetBounds(WizardForm.DiskSpaceLabel.Left,WizardForm.DiskSpaceLabel.Top-ScaleY(32),
    WizardForm.DiskSpaceLabel.Width,WizardForm.DiskSpaceLabel.Height+ScaleY(32));
  FullSpaceLabel.AutoSize:=False;
  FullSpaceLabel.WordWrap:=True;
  FullSpaceLabel.Caption:='Полный новый комплект: около '+SizeInMB(AppBytes+RuntimeBytes+ModelBytes)+
    ' (программа, Ollama и модель).'+#13#10+'Если Ollama или модель уже есть, потребуется меньше места.';
  StoragePage:=CreateInputDirPage(wpSelectDir,'Ollama и модель','Выберите папки для локальной нейросети.',
    'Интернет для установки не нужен. Существующие файлы не перезаписываются. Переменные Windows и PATH не изменяются. При удалении приложения Ollama и модель сохранятся.',False,'');
  StoragePage.Add('Папка Ollama:');StoragePage.Add('Папка модели Qwen2.5 1.5B:');
  ExpectedBlobs:=TStringList.Create;
  ExpectedRuntimeFiles:=TStringList.Create;
  #include "..\temp\offline-payload\runtime-checks.iss"
  #include "..\temp\offline-payload\model-checks.iss"
end;

function ValidateStorage: String;
var I: Integer; Target, Digest: String;
begin
  Result:='';
  if not LocalDirectory(WizardDirValue) then begin Result:='Выберите отдельную папку приложения на локальном диске.';Exit;end;
  if FileExists(AddBackslash(WizardDirValue)+'main.py') and DirExists(AddBackslash(WizardDirValue)+'ai_test_generator') then begin Result:='Нельзя устанавливать приложение поверх исходного проекта. Выберите другую папку.';Exit;end;
  if not LocalDirectory(RuntimeDir('')) or not LocalDirectory(ModelsDir('')) then begin Result:='Выберите отдельные папки на доступном локальном диске.';Exit;end;
  if (CompareText(RuntimeDir(''),ModelsDir(''))=0) or (CompareText(RuntimeDir(''),WizardDirValue)=0) or (CompareText(ModelsDir(''),WizardDirValue)=0) then begin Result:='Приложению, Ollama и модели нужны разные папки.';Exit;end;
  IncludeRuntime:=not FileExists(AddBackslash(RuntimeDir(''))+'ollama.exe');
  if not IncludeRuntime and not RuntimeComplete(RuntimeDir('')) then begin Result:='Не удалось подтвердить полноту выбранной Ollama: отсутствуют комплектные CPU-библиотеки или другие файлы. Существующие файлы не изменены. Выберите другую папку для комплектной Ollama.';Exit;end;
  IncludeModels:=not ExistingModelComplete(ModelsDir(''));
  if IncludeModels and FileExists(AddBackslash(ModelsDir(''))+'manifests\registry.ollama.ai\library\qwen2.5\1.5b') then begin Result:='В выбранной папке найдена неполная или повреждённая модель. Она не будет перезаписана. Выберите новую папку либо исправьте существующее хранилище.';Exit;end;
  if IncludeModels then
    for I:=0 to ExpectedBlobs.Count-1 do begin
      Target:=AddBackslash(ModelsDir(''))+'blobs\'+ExpectedBlobs[I];
      if FileExists(Target) then begin
        Digest:=Copy(ExpectedBlobs[I],8,64);
        if Lowercase(GetSHA256OfFile(Target))<>Lowercase(Digest) then begin Result:='Обнаружен повреждённый файл модели. Выберите другую папку; существующие файлы не изменялись.';Exit;end;
      end;
    end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  SetStorageDefaults;
  Result:=ValidateStorage;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var Error: String;
begin
  Result:=True;
  if WizardSilent then Exit;
  if CurPageID=wpSelectDir then SetStorageDefaults;
  if CurPageID=StoragePage.ID then begin
    Error:=ValidateStorage;
    if Error<>'' then begin MsgBox(Error,mbError,MB_OK);Result:=False;Exit;end;
    if RunningWithoutModel then
      if MsgBox('Уже работающая Ollama не видит qwen2.5:1.5b. После установки закройте Ollama через значок в области уведомлений и откройте приложение. Чужой сервер автоматически не останавливается. Продолжить?',mbConfirmation,MB_YESNO)<>IDYES then Result:=False;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID=StoragePage.ID then SetStorageDefaults;
  if CurPageID=wpReady then begin
    WizardForm.ReadyMemo.Lines.Add('');
    WizardForm.ReadyMemo.Lines.Add('Новые файлы: около '+SizeInMB(RequiredNewBytes)+'. Место требуется на дисках выбранных папок.');
    WizardForm.ReadyMemo.Lines.Add('Ollama: '+RuntimeDir(''));
    if IncludeRuntime then WizardForm.ReadyMemo.Lines.Add('Будет размещён комплектный движок CPU.')
    else WizardForm.ReadyMemo.Lines.Add('Будет использована существующая Ollama.');
    WizardForm.ReadyMemo.Lines.Add('Модель: '+ModelsDir(''));
    if IncludeModels then WizardForm.ReadyMemo.Lines.Add('Будет размещена комплектная qwen2.5:1.5b.')
    else WizardForm.ReadyMemo.Lines.Add('Будет использована существующая модель; повторная копия не нужна.');
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Config: String;
begin
  if CurStep=ssPostInstall then begin
    Config:='[paths]'+#13#10+'ollama='+AddBackslash(RuntimeDir(''))+'ollama.exe'+#13#10+'models='+ModelsDir('')+#13#10;
    if not SaveStringToFile(ExpandConstant('{app}\installation.ini'),UTF8Encode(Config),False) then RaiseException('Не удалось сохранить выбранные пути установки.');
  end;
end;
