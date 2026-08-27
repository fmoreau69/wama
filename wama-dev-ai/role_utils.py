"""
Briques COMMUNES des pilotes de rôle (librarian, scout, integrator) — extraites de
run_librarian.py le 2026-08-27 au moment d'écrire les deux rôles frères (zéro duplication,
même règle que wama/common/ côté produit).

Tout est BORNÉ (leçons wama-dev-ai) : un appel Ollama one-shot, sorties dans outputs/ avec
PENDING_HUMAN_VALIDATION, jamais d'auto-application.
"""
import json
import re
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = Path(__file__).resolve().parent / 'outputs'
PROMPTS = Path(__file__).resolve().parent / 'prompts'

# Ollama (gateway) SANS proxy — le proxy UGE avalerait 172.x ; le web AVEC proxy (défaut env).
_OPENER_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ollama_host():
    """Sous WSL2, 127.0.0.1 n'atteint PAS l'Ollama de l'hôte Windows : gateway obligatoire."""
    from config import OLLAMA_HOST  # wama-dev-ai/config.py
    host = OLLAMA_HOST
    if '127.0.0.1' in host or 'localhost' in host:
        try:
            if 'microsoft' in Path('/proc/version').read_text().lower():
                import subprocess
                gw = subprocess.run(['sh', '-c', "ip route | awk '/default/ {print $3; exit}'"],
                                    capture_output=True, text=True).stdout.strip()
                if gw:
                    host = re.sub(r'127\.0\.0\.1|localhost', gw, host)
        except OSError:
            pass
    return host


def fetch(url, user_agent='wama-dev-ai'):
    """GET texte via le proxy d'environnement (GitHub/HF passent par le proxy UGE)."""
    req = urllib.request.Request(url, headers={'User-Agent': user_agent})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'replace')


def call_ollama(model, system, user_msg, num_ctx=16384):
    payload = {
        'model': model,
        'messages': [{'role': 'system', 'content': system},
                     {'role': 'user', 'content': user_msg}],
        'stream': False,
        'options': {'temperature': 0.1, 'num_ctx': num_ctx},
    }
    req = urllib.request.Request(
        f'{ollama_host()}/api/chat', data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    with _OPENER_DIRECT.open(req, timeout=600) as r:
        return json.loads(r.read())['message']['content']


def extract_json(text):
    """Premier objet JSON équilibré du texte (les modèles emballent parfois en ```json)."""
    text = re.sub(r'^```(?:json)?|```$', '', text.strip(), flags=re.M)
    start = text.find('{')
    if start < 0:
        raise ValueError('aucun JSON dans la réponse')
    depth = 0
    for i, c in enumerate(text[start:], start):
        depth += (c == '{') - (c == '}')
        if depth == 0:
            return json.loads(text[start:i + 1])
    raise ValueError('JSON non équilibré')


def write_output(role, slug, payload):
    """Rapport horodaté dans outputs/ — TOUJOURS PENDING_HUMAN_VALIDATION."""
    from datetime import datetime
    OUTPUTS.mkdir(exist_ok=True)
    horodatage = datetime.now().strftime('%Y-%m-%d_%H-%M')
    sortie = OUTPUTS / f"{role}_{slug.replace('/', '_')}_{horodatage}.json"
    sortie.write_text(json.dumps({'status': 'PENDING_HUMAN_VALIDATION', 'role': role,
                                  **payload}, ensure_ascii=False, indent=2), encoding='utf-8')
    return sortie
