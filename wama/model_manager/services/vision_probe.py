"""
Sonde vision via Ollama — décrire une image avec un modèle multimodal local (gemma4:12b, e4b…).
Sert au bench (d) : comparer des modèles candidats sur de vraies images WAMA, en français.

API LOCALE officielle Ollama `/api/chat` (champ `images` base64), par l'appel commun
`llm_utils.ollama_chat` depuis le 2026-10-21. Aucun scraping.
"""
from __future__ import annotations

import base64
import os


def describe_image_ollama(image_path: str, model: str = '',
                          prompt: str | None = None, timeout: int = 180,
                          keep_alive: str | None = None, num_predict: int | None = None,
                          temperature: float | None = None):
    """Décrit une image via un modèle vision Ollama LOCAL. Retourne {'ok', 'description'|'error'}.

    Le seul client de vision de WAMA depuis le 2026-10-20 : le Describer y passe (images et
    images-clés de vidéo), au lieu de son propre appel. `num_predict` borne la longueur (le
    Describer : 1 024 jetons) ; None = le défaut d'Ollama. `temperature` : celle que la card a
    réglée ; None = celle du MODÈLE (son fichier de modèle, comme avant le portage).

    L'appel est celui de toute conversation (`llm_utils.ollama_chat`, 2026-10-21) : adresse,
    contournement du proxy et MESURE de l'empreinte à la carte (`ollama_host.measured_load`) y
    vivent — cette sonde tenait sa propre copie des trois.

    `model` vide → RÉSOLU par la route commune (`modele_par_tier('default',
    exige=['completion','vision'])`) — plus de nom en dur : l'ancien défaut `'gemma4:12b'`
    aurait désigné un modèle absent à son remplacement par la prospection (même leçon que
    les six noms figés éradiqués de llm_utils le 04/08 ; audit Fabien du 19/08). Le tier
    `default` (≤16 Go) porte l'intention « triage/description rapide », pas « le meilleur ».
    ICI est le seul point de résolution : les appelants passent un modèle explicite (bench)
    ou rien — jamais un littéral de repli.

    `keep_alive` : résidence VRAM après réponse (défaut Ollama : 5 min). Une valeur courte
    ('120s') laisse s'enchaîner un LOT d'images sans repayer le chargement des poids, puis
    libère ; '0' décharge tout de suite. Cf. [[llm_utils]], même réglage côté texte.
    """
    if not model:
        from wama.common.utils.llm_utils import modele_par_tier
        model = modele_par_tier('default', exige=['completion', 'vision'])
        if not model:
            return {'ok': False, 'error': "aucun modèle vision résoluble (catalogue et Ollama muets)"}
    if not os.path.exists(image_path):
        return {'ok': False, 'error': f"image introuvable : {image_path}"}
    try:
        with open(image_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
    except OSError as e:
        return {'ok': False, 'error': f"lecture image : {e}"}

    from wama.common.utils.llm_utils import ollama_chat
    prompt = prompt or "Décris cette image en français, de façon précise et concise."
    text, error = ollama_chat(
        [{'role': 'user', 'content': prompt, 'images': [b64]}], model=model,
        num_predict=int(num_predict) if num_predict is not None else None,
        timeout=timeout, keep_alive=keep_alive, temperature=temperature)
    if error:
        return {'ok': False, 'error': error}
    return {'ok': True, 'description': text}
