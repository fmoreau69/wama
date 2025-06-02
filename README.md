# WAMA: Web App for Media Automation

## Running Locally

```bash
git clone https://github.com/fmoreau69/web-app-for-media-automation.git
```

```bash
pip install ./python_ldap-3.4.4-cp311-cp311-win_amd64.whl
```

```bash
pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

```bash
pip install -r requirements.txt
```

```bash
python manage.py migrate
```

```bash
python manage.py runserver
```
