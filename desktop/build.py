"""Сборка desktop-клиента в один .exe (PyInstaller). Запуск из папки desktop: python build.py

Результат: dist/CompetitionMonitor.exe. Это клиент: сервер (python run.py) запускается отдельно.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "CompetitionMonitor",
        "--distpath", str(HERE / "dist"),
        "--workpath", str(HERE / "build"),
        "--specpath", str(HERE / "build"),
        str(HERE / "main.py"),
    ]
    print("Сборка:", " ".join(command))
    result = subprocess.run(command, cwd=HERE)
    if result.returncode == 0:
        print(f"Готово: {HERE / 'dist' / 'CompetitionMonitor.exe'}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
