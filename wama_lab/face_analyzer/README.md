# face_analyzer

WAMA Lab Application.

## Purpose
Describe here the scientific purpose of this application.

## Structure
```
face_analyzer/
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
cd wama_lab\face_analyzer
venv_win\Scripts\activate
pip install -r requirements/windows.txt
```

### Linux
```bash
cd wama_lab/face_analyzer
source venv_linux/bin/activate
pip install -r requirements/linux.txt
```

## Run
```bash
python app.py --input <input> --output <output>
```
