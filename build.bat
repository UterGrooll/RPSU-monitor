@echo off
REM Сборка RPSU Monitor: PyInstaller -> exe, затем Inno Setup -> установщик.
REM Требуется: pip install -r requirements.txt pyinstaller ; Inno Setup (iscc в PATH).
setlocal

echo [1/2] PyInstaller: сборка RPSU.exe...
python -m PyInstaller --onefile --noconsole --name RPSU ^
    --hidden-import pystray --hidden-import PIL ^
    RPSU.py
if errorlevel 1 goto :err

echo.
echo [2/2] Inno Setup: сборка установщика...
set "ISCC="
where iscc >nul 2>nul && set "ISCC=iscc"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    echo Inno Setup не найден. Установи его: https://jrsoftware.org/isdl.php
    echo Затем открой installer\RPSU-monitor.iss в Inno Setup и нажми F9.
    echo exe уже собран: dist\RPSU.exe
    goto :eof
)
"%ISCC%" installer\RPSU-monitor.iss
if errorlevel 1 goto :err

echo.
echo Готово. Установщик: installer\Output\RPSU-Monitor-0.2-setup.exe
goto :eof

:err
echo.
echo Сборка прервалась с ошибкой.
exit /b 1
