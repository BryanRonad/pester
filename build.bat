@echo off
echo Building pester.exe...
python assets\make_icon.py
pip install pyinstaller >nul 2>&1
pyinstaller --onefile --windowed --icon=assets\icon.ico --name pester --add-data "assets;assets" --add-data "pester.config.json;." src\pester.py
echo.
echo Build complete: dist\pester.exe
