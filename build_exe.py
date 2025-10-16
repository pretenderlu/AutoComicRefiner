"""Helper script to package AutoComicRefiner as a standalone executable via PyInstaller."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from run import CONFIG_FILENAME


def _find_pyinstaller() -> Path | None:
    """Return the path to the PyInstaller executable if it is installed."""
    exe_name = "pyinstaller.exe" if os.name == "nt" else "pyinstaller"
    pyinstaller_path = shutil.which(exe_name)
    if pyinstaller_path:
        return Path(pyinstaller_path)
    return None


def build_executable(*, one_file: bool, icon: str | None) -> None:
    """Invoke PyInstaller with sensible defaults for this project."""
    project_root = Path(__file__).resolve().parent

    if _find_pyinstaller() is None:
        raise SystemExit(
            "未检测到 PyInstaller。请先运行 `pip install pyinstaller` 后再重新执行此脚本。"
        )

    config_path = project_root / CONFIG_FILENAME
    add_data_arg: list[str] = []
    if config_path.exists():
        add_data_arg = ["--add-data", f"{config_path}{os.pathsep}."]

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        "AutoComicRefiner",
        "gui.py",
    ]

    if icon:
        icon_path = Path(icon)
        if not icon_path.is_file():
            raise SystemExit(f"指定的图标文件不存在: {icon}")
        cmd.extend(["--icon", str(icon_path)])

    cmd.append("--onefile" if one_file else "--onedir")
    cmd.extend(add_data_arg)

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")

    print("运行命令:", " ".join(cmd))
    subprocess.run(cmd, cwd=project_root, check=True, env=env)

    output_hint = "AutoComicRefiner.exe" if one_file else "AutoComicRefiner/"
    print(
        f"打包完成。可执行文件位于 {project_root / 'dist' / output_hint}.\n"
        "如需自定义输出位置或额外资源，请直接编辑 build_exe.py。"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="打包 AutoComicRefiner 为独立可执行文件")
    parser.add_argument(
        "--one-dir",
        action="store_true",
        help="使用 onedir 模式输出（默认使用单文件模式）",
    )
    parser.add_argument(
        "--icon",
        help="可选的 ico 图标文件路径",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_executable(one_file=not args.one_dir, icon=args.icon)


if __name__ == "__main__":
    main()
