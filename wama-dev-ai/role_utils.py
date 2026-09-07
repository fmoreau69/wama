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
    """Adresse d'Ollama — DÉLÈGUE à la brique commune (2026-09-07).

    Ce fichier en portait une copie. Elle n'était pas « une variante » : la brique commune
    `common/utils/ollama_host.py` a justement été EXTRAITE de `run_librarian.py` le
    2026-08-02 comme « seule implémentation correcte du repo » — et sa source ne l'a jamais
    adoptée. *Une brique qu'on extrait sans que son origine l'adopte laisse deux vérités
    derrière elle.*

    Les deux résolvaient la même adresse aujourd'hui (mesuré : `http://172.21.96.1:11434`
    des deux côtés), mais la copie était en retard sur TROIS points, tous latents :
      • elle lisait `os.environ` BRUT au lieu du registre `external_sources` — le jour où
        l'adresse est posée par réglage Django et non par l'environnement, elle vise encore
        la boucle locale, avec le symptôme trompeur que la brique commune documente
        (« Ollama ne répond pas » alors qu'il tourne) ;
      • son `subprocess` n'avait AUCUN timeout — un `ip route` qui pend gèle le rôle ;
      • passerelle introuvable = retour silencieux sur la boucle locale, sans avertissement.

    Import PARESSEUX : `role_utils` reste importable sans Django, et Django n'est exigé qu'à
    l'appel — les 5 rôles font tous `django.setup()` avant d'importer ce module (vérifié).
    Pas de repli « si Django manque » : ce serait exactement le second chemin qu'on retire.
    """
    from wama.common.utils.ollama_host import ollama_base
    return ollama_base()


def fetch(url, user_agent='wama-dev-ai'):
    """GET texte via le proxy d'environnement (GitHub/HF passent par le proxy UGE)."""
    req = urllib.request.Request(url, headers={'User-Agent': user_agent})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'replace')


def call_ollama(model, system, user_msg, num_ctx=16384, keep_alive=None,
                temperature=0.1, timeout=600):
    """Appel Ollama one-shot. `keep_alive='0'` décharge le modèle SITÔT la réponse rendue
    (au lieu des ~5 min de résidence par défaut) — c'est la parade du mode dépannage GPU,
    à passer depuis `resource_governor.pipeline_keep_alive()`. None = défaut Ollama.

    ⚠ `temperature` et `timeout` sont PARAMÈTRES depuis le 2026-09-07, et les défauts ici
    sont EXACTEMENT ceux d'avant (0.1 / 600 s) : les quatre rôles qui appellent sans les
    citer sont donc inchangés au bit près. Ils existent parce que `run_codegen` portait un
    DOUBLON de cette fonction avec trois valeurs différentes (0.2 / 32768 / 900 s) —
    remplacer sans les offrir aurait TRONQUÉ sa matière (jusqu'à 60 000 caractères servis,
    illisibles à num_ctx=16384) et raccourci son délai. *Avant de supprimer un doublon, on
    compare ; s'il diverge, on FUSIONNE — sinon la déduplication perd une capacité.*
    """
    payload = {
        'model': model,
        'messages': [{'role': 'system', 'content': system},
                     {'role': 'user', 'content': user_msg}],
        'stream': False,
        'options': {'temperature': temperature, 'num_ctx': num_ctx},
    }
    if keep_alive is not None:
        payload['keep_alive'] = keep_alive
    req = urllib.request.Request(
        f'{ollama_host()}/api/chat', data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    with _OPENER_DIRECT.open(req, timeout=timeout) as r:
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
