@echo off
chcp 65001>nul
set "CJ_HOME=D:\CangjieN\cangjie"
set "PATH=%CJ_HOME%\runtime\lib\windows_x86_64_cjnative;%CJ_HOME%\bin;%PATH%"
cd /d "%~dp0"
echo === compile: cjc main.cj -o main.exe ===
cjc main.cj -o main.exe
echo === run: main.exe ===
main.exe
echo.
pause
