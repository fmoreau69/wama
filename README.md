# WAMA: Web App for Media Automation

## What is WAMA?

WAMA, <i>"Web App for Media Automation"</i>, is a web application developed by Fabien Moreau at Lescot (Gustave Eiffel University laboratory) and based on deep learning, offering AI tools applied to media. These tools will be added as developments progress. The first tool offered is an automatic object blurring tool for images/videos, which can be used in particular to anonymize videos by blurring faces and license plates. 

<ins>Planned developments include</ins>: <br />
WAMA Anonymizer: Automatic blurring of objects in photos/videos <br />
WAMA Enhancer: Improvement of the resolution and quality of photos/videos <br />
WAMA Imager: automatic image generation based on prompt text <br />
WAMA Synthesizer: Automatic voice synthesis from text files <br />
WAMA Transcriber: Automatic transcription of audio files into text <br />

## Running Locally

```bash
git clone https://github.com/fmoreau69/web-app-for-media-automation.git
```

```bash
pip install ./mod_wsgi-4.9.2-cp311-cp311-win_amd64.whl
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
python manage.py init_wama
```

```bash
python manage.py runserver
```
