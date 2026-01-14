#!/usr/bin/env python
"""
WAMA Lab App Creator

Creates a new isolated lab application with:
- Dedicated folder
- Dedicated virtual environments (Windows / Linux)
- requirements/base.txt + windows.txt + linux.txt
- app.py template
- README.md
"""

import sys
import subprocess
from pathlib import Path


# ============================================================================
# Paths
# ============================================================================

ROOT_DIR = Path(__file__).resolve().parent.parent
LAB_DIR = ROOT_DIR / "wama_lab"


# ============================================================================
# Utils
# ============================================================================

def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def create_venv(path: Path) -> None:
    if path.exists():
        print(f"   ⚠️  venv déjà existant : {path.name}")
        return

    print(f"   🧪 Création venv : {path.name}")
    run([sys.executable, "-m", "venv", str(path)])


def write_file(path: Path, content: str) -> None:
    if path.exists():
        print(f"   ⚠️  {path.relative_to(LAB_DIR)} existe déjà, ignoré")
        return
    path.write_text(content, encoding="utf-8")


# ============================================================================
# Templates
# ============================================================================

APP_TEMPLATE = '''"""
{name} - WAMA Lab Application

Standalone scientific application.
Executed via subprocess from WAMA core.
"""

import argparse


def main():
    parser = argparse.ArgumentParser(description="{name} - WAMA Lab App")
    parser.add_argument("--input", help="Input file (video/image)", required=False)
    parser.add_argument("--output", help="Output folder", required=False)

    args = parser.parse_args()

    print("🚀 {name} launched")
    print(f"Input  : {{args.input}}")
    print(f"Output : {{args.output}}")


if __name__ == "__main__":
    main()
'''

README_TEMPLATE = '''# {name}

WAMA Lab Application.

## Purpose
Describe here the scientific purpose of this application.

## Structure
```
{name}/
├── app.py
├── requirements/
│   ├── base.txt
│   ├── windows.txt
│   └── linux.txt
├── venv_win/
└── venv_linux/
```

## Virtual environments
This application uses **isolated virtual environments**:

- `venv_win/` → Windows
- `venv_linux/` → Linux

## Install dependencies

### Windows
```bash
venv_win\\Scripts\\activate
pip install -r requirements/windows.txt
```

### Linux
```bash
source venv_linux/bin/activate
pip install -r requirements/linux.txt
```

## Run
```bash
python app.py --input <input> --output <output>
```
'''

BASE_REQUIREMENTS = """# Shared dependencies
"""

WINDOWS_REQUIREMENTS = """-r base.txt
# Windows-specific dependencies
"""

LINUX_REQUIREMENTS = """-r base.txt
# Linux-specific dependencies
"""


# ============================================================================
# Main
# ============================================================================

def main():
    if len(sys.argv) != 2:
        print("Usage: python create_lab_app.py <app_name>")
        sys.exit(1)

    app_name = sys.argv[1]
    app_dir = LAB_DIR / app_name

    print(f"\n🚀 Creating WAMA Lab app: {app_name}\n")

    # App directory
    app_dir.mkdir(parents=True, exist_ok=True)

    # Virtual environments
    create_venv(app_dir / "venv_win")
    create_venv(app_dir / "venv_linux")

    # Requirements
    req_dir = app_dir / "requirements"
    req_dir.mkdir(exist_ok=True)

    write_file(req_dir / "base.txt", BASE_REQUIREMENTS)
    write_file(req_dir / "windows.txt", WINDOWS_REQUIREMENTS)
    write_file(req_dir / "linux.txt", LINUX_REQUIREMENTS)

    # App & docs
    write_file(app_dir / "app.py", APP_TEMPLATE.format(name=app_name))
    write_file(app_dir / "README.md", README_TEMPLATE.format(name=app_name))

    print("\n✅ Lab app ready!")
    print(f"📁 Location: {app_dir.relative_to(ROOT_DIR)}")


if __name__ == "__main__":
    main()
