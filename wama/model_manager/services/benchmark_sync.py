"""
Signal qualité « BENCHMARK TIERS CONFRONTÉ » — 2e étage de l'échelle des signaux.

    a priori (model_quality.py)  <  benchmark tiers confronté (ICI)  <  mesure interne

POURQUOI (décisions Fabien 2026-08-19). L'indice a priori est structurel : il s'est trompé deux
fois sur le catalogue réel (MoE crédité de ses totaux, puis √ sur-pénalisant la sparsité extrême
— AA mesure qwen3.6:35b-A3B à 43, DEVANT Gemma4 31B à 39). Une mesure TIERCE indépendante
tranche mieux qu'un a priori raffiné. UNIVERSEL (pas seulement LLM/Ollama) : mêmes sources pour
l'image, la vidéo, la voix… et pour les candidats de PROSPECTION (lignes `proposed:` incluses —
le critère s'ajoute à la confiance LLM et à la simplicité d'installation AVANT installation).

DEUX SOURCES GRATUITES, CONFRONTÉES :
  • Artificial Analysis — Data API publique, clé gratuite 1 000 req/j
    (`ARTIFICIAL_ANALYSIS_API_KEY` dans `.env`). LLM : Intelligence Index composite MESURÉ ;
    média : Elo d'arène AA par modalité. PRIORITAIRE quand apparié.
  • Arena (ex-LMArena) — dataset HF officiel `lmarena-ai/leaderboard-dataset`
    (**CC-BY-4.0** : gratuit, attribution tracée en meta), parquet `latest` par modalité.
    Valeur retenue quand AA manque ; sinon CONFRONTATION (inversion d'ordre = signalée).
    Depuis le 2026-09-02, ses sous-ensembles `vision` (VLM) et `document` sont lus aussi :
    ils étaient téléchargeables par le MÊME chargeur et personne ne les demandait.

UNE TROISIÈME, HORS GÉNÉRATION (2026-09-02) :
  • Open ASR Leaderboard (Hugging Face, `hf-audio`) — CSV de résultats publiés sur le Hub,
    un fichier par langue. WER moyen : **plus bas = mieux** (`sens='bas'` dans la
    déclaration de source — cf. `SOURCES`). Le français est le banc PRINCIPAL du transcriber
    (c'est ce qu'il transcrit ici), l'anglais le secondaire. Aucun autre banc tiers lisible
    par machine ne couvre l'ASR (relevé du 02/09 : AA n'expose pas cette modalité en API).

RÈGLE DES ÉCHELLES (héritée de `_rank_key`, étendue) : Intelligence Index (~0-70) et Elo
(~1000-1500) sont INCOMMENSURABLES — `benchmark_meta['echelle']` nomme l'échelle de chaque
valeur, et le tri ne compare que des lots à échelle UNIQUE. On ne normalise jamais (une
normalisation inventerait une équivalence que personne n'a mesurée). Une échelle porte
aussi son SENS (`benchmark_meta['direction']`, 'haut' par défaut, 'bas' pour un taux d'erreur) :
ordonner un lot de WER par valeur décroissante mettrait le pire en tête — `orderable_value`
est le seul point où un consommateur doit lire une valeur pour TRIER.

GARDE-FOUS :
  • Null plutôt que plausible : non apparié → NULL. Appariement CONSERVATEUR (famille+version
    par `ollama_registry.decompose`, taille exigée égale quand les DEUX côtés la déclarent).
  • `ALIAS` déclaratif : quand un humain confirme une équivalence que l'identité stricte ne
    voit pas (ex. un nom commercial ≠ tag), il la DÉCLARE ici — jamais de fuzzy silencieux.
  • Champ SÉPARÉ de `quality_index` : `sync_models` (découverte) n'écrit jamais ici.
  • AA/Arena mesurent des endpoints fp8/fp16 ; nos GGUF sont souvent Q4 → borne haute, tracée.
  • Catégorie par modèle DÉCLARÉE (TASK_TO_BENCH_CATEGORY) : on n'apparie jamais un modèle
    d'une modalité aux entrées d'une autre (un « qwen » TTS ne prendra pas l'index du LLM).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from .ollama_registry import decompose, _milliards

logger = logging.getLogger(__name__)

#: Adresses et clé déclarées au registre COMMUN des sources externes (2026-09-01). `SOURCES`
#: plus bas reste le registre des BANCS — il dit comment LIRE une valeur (priorité, échelle,
#: méta) ; il ne dit plus où joindre la plateforme. Deux registres, deux questions.
from wama.common.external_sources import (ARENA_DATASET, MTEB_RESULTS_REPO,  # noqa: F401
                                          OPEN_ASR_DATASETS, base_url as _base_url_of,
                                          get as _source, proxies_for as _proxies_for)
from wama.common.external_sources import base_url as _base_url

AA_BASE = _base_url('artificial_analysis')
AA_KEY_ENV = _source('artificial_analysis').api_key_env

#: Catégorie → (endpoint AA, extracteur de score AA, échelle AA, sous-ensemble Arena, jeu
#: Open ASR). DÉCLARATIF : ajouter une modalité = une ligne ; une source qui ne couvre pas
#: la catégorie n'y déclare rien (clé absente ou None) et son chargeur la SAUTE. Un endpoint
#: AA absent/403 (tier) ou un parquet manquant SKIPPE la (source, catégorie) avec motif —
#: jamais un rouge global.
CATEGORIES = {
    # `strict_size` : la taille (milliards de paramètres) est EXIGÉE symétrique — cf.
    # `_compatible`. Vrai pour les bancs de la famille LLM, où les entrées tierces publient
    # leur taille : sans elle, une identité locale SANS taille (dérivée du nom) apparie la
    # première variante venue. Mesuré le 02/09 à la première lecture de l'arène `vision` :
    # `gemma4:12b` prenait l'Elo de `gemma-4-31b`. Faux pour les modalités média (les
    # modèles image/vidéo ne publient pas de taille) et l'ASR (`whisper-large-v3` non plus).
    'llm': {
        'aa': 'data/llms/models', 'aa_field': 'artificial_analysis_intelligence_index',
        'aa_scale': 'aa_intelligence_index', 'arena': 'text', 'strict_size': True,
    },
    'text-to-image': {
        'aa': 'data/media/text-to-image', 'aa_field': 'elo',
        'aa_scale': 'aa_elo_text_to_image', 'arena': 'text_to_image',
    },
    'image-editing': {
        'aa': 'data/media/image-editing', 'aa_field': 'elo',
        'aa_scale': 'aa_elo_image_editing', 'arena': 'image_edit',
    },
    'text-to-speech': {
        'aa': 'data/media/text-to-speech', 'aa_field': 'elo',
        'aa_scale': 'aa_elo_text_to_speech', 'arena': None,
    },
    'text-to-video': {
        'aa': 'data/media/text-to-video', 'aa_field': 'elo',
        'aa_scale': 'aa_elo_text_to_video', 'arena': 'text_to_video',
    },
    'image-to-video': {
        'aa': 'data/media/image-to-video', 'aa_field': 'elo',
        'aa_scale': 'aa_elo_image_to_video', 'arena': 'image_to_video',
    },
    # ── 2026-09-02 : les sous-ensembles Arena que le chargeur savait déjà lire ──────────
    # `vision` = arène multimodale (image + prompt) : le banc des VLM — et des LLM à
    # capacité `vision` (gemma4, qwen3.8 : Arena y classe `qwen3.8-27b`, `gemma-4-31b`).
    # AA n'a pas d'endpoint équivalent (son leaderboard LLM absorbe MiniCPM-V).
    'vision': {'arena': 'vision', 'strict_size': True},
    # `document` = arène de lecture de documents. Le seul banc tiers lisible par machine
    # qui touche à l'OCR ; ses entrées sont des LLM frontière — nos moteurs OCR (docTR,
    # olmOCR…) n'y figurent pas AUJOURD'HUI. La catégorie est déclarée pour que la ligne
    # sorte de « hors catégorie » et dise « sans banc » : c'est une information, pas un
    # score. Null plutôt que plausible.
    'document': {'arena': 'document', 'strict_size': True},
    # ── 2026-09-02 : la transcription, première catégorie HORS génération ───────────────
    # Deux bancs pour un métier : le FRANÇAIS d'abord (macro-moyenne des WER FLEURS / MCV /
    # MLS du fichier par langue — c'est ce que le transcriber fait ici), l'anglais ensuite
    # (colonne `avg` du leaderboard principal, population plus large). Un modèle mesuré sur
    # les deux porte les deux bancs (`bancs`), l'index vient du principal apparié.
    'speech-to-text-fr': {'open_asr': 'multilingual_fr', 'open_asr_value': None},
    'speech-to-text': {'open_asr': 'english_short', 'open_asr_value': 'avg'},
    # ── 2026-09-02 : les EMBEDDINGS — MTEB, résultats bruts ─────────────────────────────
    # Le jeu est DÉCLARÉ ici, et c'est le point : sans le paquet `mteb` (lourd, non
    # installé) on ne reproduit pas la moyenne officielle « MTEB(Multilingual) » ; on
    # déclare donc un jeu NOMMÉ, celui qui répond à la question du labo — retrouver du
    # FRANÇAIS (le RAG indexe des entretiens en français). ⚠ Première version (5 tâches du
    # sous-ensemble « MTEB français » : Alloprof/BSARD/Syntec/Mintaka/XPQA) RÉFUTÉE PAR LA
    # MESURE le 02/09 : nos modèles ne les ont pas (bge-m3 2/5, Qwen3-Embedding et nomic v2
    # 0/5 — seuls les contributeurs anciens les ont exécutées). Le jeu retenu = les tâches
    # MULTILINGUES que nos modèles partagent et qui portent un SOUS-ENSEMBLE français :
    # (tâche, split, hf_subset). Un modèle sans les quatre n'est pas noté, jamais moyenné
    # sur moins. Échelle `mteb_fr_retrieval` (moyenne des main_score ×100 — nDCG@10 pour
    # la recherche, MAP pour le reranking : une moyenne DÉCLARÉE, pas la leur).
    'embedding': {'mteb': (('BelebeleRetrieval', 'test', 'fra_Latn-fra_Latn'),
                           ('MIRACLRetrievalHardNegatives', 'dev', 'fr'),
                           ('StatcanDialogueDatasetRetrieval', 'test', 'french'),
                           ('AlloprofReranking', 'test', 'default'))},
}

#: Tâche canonique du catalogue (`capabilities.task` / `ModelTask`) → catégorie(s) de
#: benchmark. Indexé sur la TÂCHE, jamais sur l'app (règle des bancs). Tâche absente → 'llm'
#: si le modèle est un LLM Ollama, sinon PAS de catégorie (donc pas d'appariement).
#: Une valeur peut être un TUPLE quand une même tâche a plusieurs bancs (transcription :
#: français puis anglais) — l'ordre est celui des métiers, le premier apparié porte l'index.
TASK_TO_BENCH_CATEGORY = {
    'text-generation': 'llm',
    'text-to-image': 'text-to-image',
    'image-to-image': 'image-editing',
    'image-editing': 'image-editing',
    'text-to-speech': 'text-to-speech',
    'text-to-video': 'text-to-video',
    'image-to-video': 'image-to-video',
    'captioning': 'vision',
    'ocr': 'document',
    'transcription': ('speech-to-text-fr', 'speech-to-text'),
    'feature-extraction': 'embedding',
}

#: Équivalences CONFIRMÉES À LA MAIN : model_key local → slug/nom EXACT chez le tiers.
#: Appariement par ÉGALITÉ de slug (pas par identité) : une confirmation humaine désigne UNE
#: entrée, jamais une famille — `gemma4:e4b` rapproché par identité aurait capté le score du
#: « Gemma 4 31B » (29,7), la taille `e4b` n'étant pas un nombre de milliards analysable.
#: Chaque ligne se justifie : qui l'a confirmée, sur quoi.
ALIAS: dict[str, str] = {
    # Fabien 2026-08-19 : même modèle, AA nomme la variante de raisonnement à part
    # (« Gemma 4 E4B (Reasoning) » 12,2 vs « (Non-reasoning) » 8,7) ; notre tag Ollama
    # déclare `thinking` → variante Reasoning.
    'ollama:gemma4:e4b': 'gemma-4-e4b',
    'proposed:ollama:gemma4:e4b': 'gemma-4-e4b',
    # 2026-09-01 : `deepseek-coder-v2:latest` est le 16B — donc le **Lite**, pas le 236B.
    # Ce n'est pas une supposition, c'est le registre Ollama qui le dit : le manifeste de
    # `latest` et celui de `16b` portent le MÊME digest
    # (63fb193b3a9b4322a18e8c6b250ca2e70a5ff531e962dbf95ba089b2566f2fa5, 8,29 Go), quand
    # `236b` en a un autre (123,78 Go). Même artefact, donc même modèle.
    # Sans cette ligne, l'appariement va sur « DeepSeek-Coder-V2 » (4,7 = le 236B) : la règle
    # des qualificatifs écarte « DeepSeek Coder V2 Lite Instruct » parce que « lite » est
    # étranger à NOTRE nom — et elle a raison de le faire, c'est notre nom qui est muet.
    # Aucune règle ne peut deviner qu'un tag sans qualificatif désigne la petite variante :
    # c'est exactement ce que ce dictionnaire existe pour porter.
    'ollama:deepseek-coder-v2:latest': 'deepseek-coder-v2-lite',
    'proposed:ollama:deepseek-coder-v2:latest': 'deepseek-coder-v2-lite',
    # 2026-09-02 : le tag Ollama `bge-m3` EST `BAAI/bge-m3` (la bibliothèque Ollama le
    # cite comme origine). `_identity` rejette « m3 » (famille d'une lettre — garde du
    # 19/08 contre les parasites), donc sans alias le modèle du RAG n'aurait jamais de banc.
    'ollama:bge-m3:latest': 'BAAI/bge-m3',
}


#: Mots qui nomment un TIRAGE d'un modèle, pas le modèle — écartés de la famille (cf.
#: `_with_prefix`). Liste volontairement COURTE : chaque entrée doit être un mot qui ne
#: distingue jamais deux modèles différents. `lite`, `mini` ou `turbo` n'y sont PAS — ceux-là
#: désignent bien des modèles distincts (« DeepSeek Coder V2 Lite » ≠ « DeepSeek-Coder-V2 »).
CONDITIONING_WORDS = {'base', 'instruct', 'chat', 'it'}

#: Marqueurs d'ADD-ON non autonome dans un identifiant : jamais un banc (cf. `_local_categories`).
ADD_ONS = ('lora', 'adapter', 'controlnet')


class SourceUnavailable(Exception):
    """Réseau/clé/format absents — la source est SKIPPÉE, jamais un score partiel inventé."""


# ── Identité (les sources parlent des noms différents) ───────────────────────────────────

def _with_prefix(word: str, segments: list, i: int) -> str:
    """
    Famille COMPLÈTE quand elle est détectée sous forme éclatée : le mot porteur PRÉCÉDÉ des
    segments alphabétiques qui l'introduisent, concaténés SANS séparateur.

    ⚠ CORRIGE UN FAUX APPARIEMENT MESURÉ (2026-08-19) : `qwen-image-2` et `GPT Image 2 (high)`
    donnaient tous deux la famille « image » — un MOT COMMUN, pas une identité — et se sont
    appariés (l'imager local a hérité de l'indice 1369 de GPT Image 2). En rendant
    « qwenimage » ≠ « gptimage », l'appariement disparaît au lieu d'être faux.

    Concaténation SANS tiret pour que les graphies des deux sources convergent :
    `hunyuan-image-2.1` (local) et `HunyuanImage 2.1` (AA) donnent tous deux « hunyuanimage »
    — cet appariement-là, correct, devait être PRÉSERVÉ.

    ⚠ Les mots de CONDITIONNEMENT sont écartés (2026-09-01) : `stable-diffusion-xl-base-1.0`
    (notre `hf_id`) donnait « stablediffusionxlbase » là où AA dit « stablediffusionxl » —
    un seul mot d'écart faisait rater un appariement juste. `base`, `instruct`, `chat` ne
    nomment pas un MODÈLE, ils nomment un tirage de ce modèle ; la famille ne doit pas en
    dépendre. Écarté seulement s'il RESTE un mot : « base » seul reste « base ».
    """
    prefix = []
    j = i - 1
    while j >= 0 and re.fullmatch(r'[a-z]{2,}', segments[j]):
        prefix.insert(0, segments[j])
        j -= 1
    words = [x for x in prefix + [word] if x not in CONDITIONING_WORDS]
    return ''.join(words or [word])


def _words(text: str) -> set:
    """
    Jetons PUREMENT alphabétiques (≥ 2 lettres) d'un nom — les mots qui QUALIFIENT la variante.

    Volontairement générique plutôt qu'une liste fermée de qualificatifs : une liste figée
    aurait raté « coder » (mesuré le 2026-08-19 — voir `_choose_variant`) et aurait dérivé
    à chaque nouvelle série. Les jetons alphanumériques (`qwen3`, `30b`, `a3b`, `2507`) sont
    écartés : ils portent famille/taille/date, déjà traitées par l'identité.
    """
    return {j for j in re.split(r'[^a-z]+', (text or '').lower()) if len(j) >= 2}


def _choose_variant(local_name: str, candidates: list, key, direction: str = 'higher'):
    """
    LA variante qui correspond au modèle local parmi des candidats déjà compatibles.

    ⚠ CORRIGE DEUX ERREURS MESURÉES LE 2026-08-19, toutes deux dues à `max(valeur)` :
      • `flux-1-dev` recevait l'indice de **FLUX.1 Kontext [max]** (1141) alors que
        **FLUX.1 [dev]** (1041) était dans la même liste — prendre le meilleur score d'une
        famille flatte systématiquement nos poids locaux, qui sont la variante ouverte
        (dev/schnell), jamais la variante frontière ;
      • `qwen3-coder:30b` recevait 14,6 (« Qwen3 30B A3B 2507 Reasoning ») parmi **9**
        candidats compatibles — l'identité famille+version+taille ne distingue pas Coder,
        VL et Omni — alors que « Qwen3 Coder 30B A3B Instruct » (13,6) est LE bon.

    Départage : (1) mots COMMUNS avec le nom local (« coder » ↔ « Coder ») ; (2) à égalité,
    moins de mots ÉTRANGERS (« Omni », « Kontext » absents du nom local) ; (3) similarité de
    chaîne ; (4) en dernier recours la valeur la PIRE — conservateur, cohérent avec la
    règle « null plutôt que plausible » du module. « Pire » dépend du SENS de l'échelle :
    la plus basse pour un score, la plus HAUTE pour un taux d'erreur (`sens='bas'`).
    """
    from difflib import SequenceMatcher
    if len(candidates) == 1:
        return candidates[0]
    flat = re.sub(r'[^a-z0-9]+', ' ', (local_name or '').lower())
    local_words = _words(local_name)
    sign = 1.0 if direction == 'lower' else -1.0

    def rank(e):
        name = re.sub(r'[^a-z0-9]+', ' ', (e.get('name') or '').lower())
        words = _words(e.get('name'))
        return (len(local_words & words), -len(words - local_words),
                SequenceMatcher(None, flat, name).ratio(), sign * float(key(e) or 0))

    return max(candidates, key=rank)


def _identity(text: str):
    """
    'qwen3.6:35b' / 'qwen3-6-35b-a3b' / 'Qwen3.6 35B A3B' / 'Gemma 4 31B' / 'veo-3.1'
        → ('qwen', (3,6), 35.0) · ('gemma', (4,), 31.0) · ('veo', (3,1), None) · … ou None.

    Famille+version par `decompose` (brique du « successeur de famille »), étendue aux formes
    éclatées ('gemma-4', 'qwen3-6') ; taille = premier jeton `<n>b` (via `_milliards`),
    OPTIONNELLE (les modèles média n'en publient pas). Sans famille+version : None.
    """
    flat = re.sub(r'[\s_]+', '-', (text or '').strip().lower())
    # « FLUX.1-schnell » / « FLUX.2-dev » : la version suit la famille après un POINT. Ni
    # `decompose('flux.1')` ni la forme éclatée ne la lisaient → aucune identité pour toute
    # la famille FLUX sous son nom HF (mesuré le 02/09 : 5 candidats « sans identité »
    # alors que `flux-1-dev`, écrit avec un tiret, s'appariait). Le point entre une LETTRE
    # et un CHIFFRE devient un tiret ; `qwen3.6` ou `v1.5` (chiffre.chiffre) sont intacts.
    flat = re.sub(r'(?<=[a-z])\.(?=\d)', '-', flat)
    segments = [s for s in re.split(r'[:/-]', flat) if s]
    fam = ver = size = None
    i = 0
    while i < len(segments):
        seg = segments[i]
        if fam is None:
            d = decompose(seg)
            # ⚠ Familles PARASITES (1er dry-run 19/08) : 'm3' → ('m',(3,)), 'v2' → ('v',(2,))
            # appariaient bge-m3 et deepseek-coder-v2 à n'importe quoi. Une famille d'une
            # lettre n'est pas une identité → rejetée.
            if d and len(d[0]) >= 2:
                fam, ver = d
            elif (re.fullmatch(r'[a-z]{2,}', seg) and i + 1 < len(segments)
                  and re.fullmatch(r'\d+(?:\.\d+)*', segments[i + 1])):
                fam = _with_prefix(seg, segments, i)
                i += 1
                ver = tuple(int(x) for x in segments[i].split('.'))
            elif (re.fullmatch(r'v\d+(?:\.\d+)*', seg) and i > 0
                  and re.fullmatch(r'[a-z]{2,}', segments[i - 1])):
                # 'stable-diffusion-v1-5' : 'v1' = marqueur de VERSION du mot précédent.
                fam = _with_prefix(segments[i - 1], segments, i - 1)
                ver = tuple(int(x) for x in seg[1:].split('.'))
            if fam is not None:
                while i + 1 < len(segments) and segments[i + 1].isdigit():
                    i += 1
                    ver = ver + (int(segments[i]),)
                i += 1
                continue
        if size is None:
            t = _milliards(seg)
            if t is not None:
                size = t
        i += 1
    if not fam or not ver:
        return None
    return fam, ver, size


def _compatible(a, b, size_required=False, local_name='', third_party_name=''):
    """
    Identités appariables : même famille+version ; tailles égales si les DEUX existent.

    `taille_requise` (catégorie LLM) — trois cas, et c'est la SYMÉTRIE qui tranche :

    • tailles ASYMÉTRIQUES (l'un la publie, l'autre non) → refus. C'est le cas d'origine
      (1er dry-run 19/08) : `qwen3.5:4b` prenait l'Elo de `qwen3.5-max-preview` et
      `qwen3.8:27b` celui de `qwen3.8-max` — des variantes API frontière sans taille
      publiée, qui ne sont jamais nos poids locaux.
    • tailles ABSENTES DES DEUX CÔTÉS → ce sont les QUALIFICATIFS qui décident. L'ancienne
      règle refusait en bloc et tuait des appariements EXACTS (« Mistral Medium 3.5 »,
      « Nemotron 3.5 Lightning », « DeepSeek-Coder-V2 » portent LITTÉRALEMENT notre nom).
      Mais l'accepter en bloc est pire — mesuré le 2026-09-01 : `qwen3-embedding:latest`
      captait alors l'indice de « Qwen3 Max ». *Une garde binaire sur une question qui ne
      l'est pas se trompe dans les deux sens.* `_identity` jette les qualificatifs
      (famille+version+taille seulement) ; c'est pourtant « embedding » vs « max » qui
      distingue ces deux modèles. On exige donc qu'aucun mot ÉTRANGER ne vienne du tiers.
    • tailles présentes des deux côtés → elles doivent être égales (inchangé).

    Les modalités média gardent la taille optionnelle (les modèles image/vidéo n'en publient
    pas) : `taille_requise` est faux pour elles, rien de ce qui précède ne s'y applique.
    """
    if a is None or b is None or a[0] != b[0] or a[1] != b[1]:
        return False
    if size_required:
        if (a[2] is None) != (b[2] is None):
            return False
        if a[2] is None:
            # `latest` n'est pas un qualificatif de modèle, c'est un pointeur de tag Ollama.
            if _words(third_party_name) - _words(local_name) - {'latest'}:
                return False
    return a[2] is None or b[2] is None or a[2] == b[2]


def _match(local_ident, entries, size_required=False, local_name=''):
    """Candidats compatibles, les tailles EXACTES d'abord (jamais un score moyen)."""
    c = [e for e in entries
         if _compatible(local_ident, e['identity'], size_required,
                         local_name, e.get('name') or '')]
    exact = [e for e in c if local_ident and e['identity'][2] == local_ident[2]]
    return exact or c


def _match_alias(target: str, entries):
    """Entrées dont le slug OU le nom vaut EXACTEMENT `cible` (comparaison normalisée)."""
    def normalize(s):
        return re.sub(r'[\s_]+', '-', (s or '').strip().lower())
    c = normalize(target)
    return [e for e in entries if normalize(e.get('slug')) == c or normalize(e.get('name')) == c]


# ── Sources ──────────────────────────────────────────────────────────────────────────────

def _http_json(url: str, headers: dict | None = None, timeout: int = 45):
    import requests
    r = requests.get(url, headers=headers or {}, timeout=timeout)  # trust_env : proxy UGE
    r.raise_for_status()
    return r.json()


def load_aa():
    """{'categorie': [{'nom','slug','valeur','echelle','identite'}]} ; motifs par catégorie."""
    key = os.environ.get(AA_KEY_ENV, '').strip()
    if not key:
        raise SourceUnavailable(
            f"clé absente ({AA_KEY_ENV} dans .env — gratuite : artificialanalysis.ai/data-api)")
    by_category, reasons = {}, {}
    for cat, spec in CATEGORIES.items():
        if not spec.get('aa'):
            continue        # AA ne couvre pas cette catégorie : ni requête, ni motif
        try:
            data = _http_json(f"{AA_BASE}/{spec['aa']}", headers={'x-api-key': key})
        except Exception as e:
            reasons[cat] = f'endpoint AA indisponible : {e}'
            continue
        out = []
        for m in (data.get('data') or []):
            ev = m.get('evaluations') or {}
            v = ev.get(spec['aa_field'], m.get(spec['aa_field']))
            ident = _identity(m.get('slug') or m.get('name') or '')
            if v is None or ident is None:
                continue    # null plutôt que plausible
            # Sous-indices PAR DOMAINE : « le meilleur » dépend de ce qu'on demande
            # (qwen3.8 = 52,0 en général, 68,1 en coding). Même requête, coût nul ;
            # consommés par `select_model(benchmark_family='coding')`.
            sub_scores = {key[len('artificial_analysis_'):-len('_index')]: val
                    for key, val in ev.items()
                    if key.startswith('artificial_analysis_') and key.endswith('_index')
                    and key != f"artificial_analysis_{spec['aa_field'].split('_')[-1]}"
                    and val is not None}
            sub_scores.pop('intelligence', None)      # déjà porté par `benchmark_index`
            out.append({'name': m.get('name', ''), 'slug': m.get('slug', ''),
                        'value': float(v), 'scale': spec['aa_scale'], 'identity': ident,
                        'family_scores': sub_scores})
        if out:
            by_category[cat] = out
        else:
            reasons[cat] = 'réponse vide ou sans entrée identifiable'
    if not by_category:
        raise SourceUnavailable('AA : ' + ' ; '.join(f'{c}: {m}' for c, m in reasons.items()))
    return by_category, reasons


def load_arena():
    """
    {'categorie': [{'nom','elo','votes','identite'}]} depuis le dataset HF officiel
    (CC-BY-4.0). Parquet `latest` par modalité, lignes `category == 'overall'` du dernier
    `leaderboard_publish_date`. Un sous-ensemble manquant est un motif, pas un échec global.
    """
    try:
        from huggingface_hub import hf_hub_download
        import pandas as pd
    except ImportError as e:
        raise SourceUnavailable(f'outillage absent ({e})')
    by_category, reasons = {}, {}
    for cat, spec in CATEGORIES.items():
        subset = spec.get('arena')
        if not subset:
            continue
        try:
            p = hf_hub_download(ARENA_DATASET, f'{subset}/latest-00000-of-00001.parquet',
                                repo_type='dataset')
            df = pd.read_parquet(p)
        except Exception as e:
            reasons[cat] = f'parquet {subset} indisponible : {e}'
            continue
        if 'category' in df.columns:
            df = df[df['category'] == 'overall']
        if 'leaderboard_publish_date' in df.columns and len(df):
            df = df[df['leaderboard_publish_date'] == df['leaderboard_publish_date'].max()]
        out = []
        for _, r in df.iterrows():
            ident = _identity(str(r.get('model_name') or ''))
            if ident is None or r.get('rating') is None:
                continue
            out.append({'name': str(r['model_name']), 'elo': float(r['rating']),
                        'votes': int(r['vote_count']) if r.get('vote_count') else None,
                        'identity': ident})
        if out:
            by_category[cat] = out
        else:
            reasons[cat] = f'{subset} : aucune entrée identifiable'
    if not by_category:
        raise SourceUnavailable('Arena : ' + ' ; '.join(f'{c}: {m}' for c, m in reasons.items()))
    return by_category, reasons


def load_open_asr():
    """
    {'categorie': [{'nom','slug','wer','identite','rtfx','licence','taille_b','jeux'}]}
    depuis les CSV de résultats de l'Open ASR Leaderboard (Hub, `OPEN_ASR_DATASETS`).

    Forme RÉELLE des fichiers (sondée le 2026-09-02, pas supposée) :
      • `english_short_latest.csv` : `model`, `avg` (WER moyen), `RTFx`, `License`,
        `Size (B)`, puis un couple `<jeu> WER` / `<jeu> RTFx` par corpus ;
      • `multilingual_fr.csv` : `model`, `RTFx`, `FLEURS WER`, `MCV WER`, `MLS WER` — PAS de
        moyenne publiée : on la calcule (macro-moyenne des colonnes `* WER` présentes) et on
        garde chaque jeu en meta pour que la valeur reste RETRAÇABLE.
    `open_asr_valeur` (CATEGORIES) nomme la colonne de valeur ; None = moyenne calculée.

    Identité : le dernier segment de `org/modele` (comme le `slug` AA). `Qwen3-ASR-1.7B-hf`
    → ('qwen', (3,), 1.7) — le suffixe `-hf` est un mot ÉTRANGER que `_choose_variant`
    pénalise, pas une identité différente. `parakeet-tdt-0.6b-v2` n'a pas d'identité lisible
    (version après la taille) : sauté, comme toute entrée sans identité — null plutôt que
    plausible.
    """
    try:
        from huggingface_hub import hf_hub_download
        import pandas as pd
    except ImportError as e:
        raise SourceUnavailable(f'outillage absent ({e})')
    by_category, reasons = {}, {}
    for cat, spec in CATEGORIES.items():
        dataset = spec.get('open_asr')
        if not dataset:
            continue
        repo, file = OPEN_ASR_DATASETS[dataset]
        try:
            df = pd.read_csv(hf_hub_download(repo, file, repo_type='dataset'))
        except Exception as e:
            reasons[cat] = f'CSV {dataset} indisponible : {e}'
            continue
        model_col = 'model' if 'model' in df.columns else 'model_id'
        value_col = spec.get('open_asr_value')
        wer_cols = [c for c in df.columns if c.endswith(' WER')]
        out = []
        for _, r in df.iterrows():
            name = str(r.get(model_col) or '').strip()
            if value_col:
                v = r.get(value_col)
            else:
                vals = [float(r[c]) for c in wer_cols if pd.notna(r.get(c))]
                v = sum(vals) / len(vals) if vals else None
            ident = _identity(name.rsplit('/', 1)[-1])
            if name == '' or v is None or pd.isna(v) or ident is None:
                continue
            datasets = {c[:-len(' WER')]: float(r[c]) for c in wer_cols if pd.notna(r.get(c))}
            size = r.get('Size (B)')
            rtfx = r.get('RTFx')
            out.append({'name': name, 'slug': name, 'wer': round(float(v), 3), 'identity': ident,
                        'rtfx': float(rtfx) if pd.notna(rtfx) and float(rtfx) > 0 else None,
                        'license': str(r['License']) if 'License' in df.columns and pd.notna(r.get('License')) else '',
                        'size_b': float(size) if pd.notna(size) else None,
                        'datasets': datasets})
        if out:
            by_category[cat] = out
        else:
            reasons[cat] = f'{dataset} : aucune entrée identifiable'
    if not by_category:
        raise SourceUnavailable('Open ASR : ' + ' ; '.join(f'{c}: {m}' for c, m in reasons.items()))
    return by_category, reasons


def _mteb_markers():
    """Fragments de nom des modèles d'EMBEDDING du catalogue (installés ou proposés) — ce
    pour quoi on paie un appel d'API GitHub quand `paths.json` ne les connaît pas."""
    from ..models import AIModel
    out = set()
    for m in AIModel.objects.filter(model_type='embedding'):
        for raw_name in (m.hf_id or '', m.name or '', m.model_key.rsplit(':', 1)[0].rsplit(':', 1)[-1]):
            fragment = raw_name.rsplit('/', 1)[-1].split(':')[0].strip().lower()
            if len(fragment) >= 5:
                out.add(fragment)
    return out


def _mteb_index(markers=()):
    """
    {'<owner>__<model>': '<révision>'} — l'INDEX des résultats.

    Deux couches, parce que `paths.json` du dépôt est PÉRIMÉ (333 modèles sur 685 le
    02/09, sans Qwen3-Embedding) et que l'API GitHub anonyme est bornée à 60 appels/h :
      1. `paths.json` (un fichier brut) donne la révision de 333 modèles — la POPULATION ;
      2. l'API (arbre du dossier `results/`, 1 appel) liste les 685 dossiers ; seuls ceux
         qui manquent à `paths.json` ET portent un marqueur de NOTRE catalogue valent un
         appel de plus (leur révision) — une dizaine, jamais 352.
    Un modèle que ni l'une ni l'autre ne nomme n'est pas noté : null plutôt que plausible.
    """
    import requests
    tasks = {t[0] for t in CATEGORIES['embedding']['mteb']}
    raw = _base_url_of('mteb')
    r = requests.get(f'{raw}/{MTEB_RESULTS_REPO}/main/paths.json',
                     proxies=_proxies_for('mteb'), timeout=90)
    r.raise_for_status()
    # ⚠ Un modèle peut avoir PLUSIEURS dossiers de révision, et une tâche donnée vit dans
    # l'un d'eux seulement (mesuré : `AlloprofRetrieval` de bge-m3 n'est PAS sous la révision
    # de son premier chemin → 404). L'index garde donc le CHEMIN EXACT par (modèle, tâche).
    index = {}
    for folder, paths in r.json().items():
        for p in paths or ():
            seg = p.split('/')
            if len(seg) >= 4 and seg[0] == 'results' and seg[-1].endswith('.json'):
                t = seg[-1][:-5]
                if t in tasks:
                    index.setdefault(folder, {})[t] = p
    marker_set = {str(x).lower() for x in markers if x}
    if not marker_set:
        return index
    api = _base_url_of('github_api')
    proxies = _proxies_for('github_api')
    headers = {'Accept': 'application/vnd.github+json'}
    tok = os.environ.get('GITHUB_TOKEN', '').strip()
    if tok:
        headers['Authorization'] = f'Bearer {tok}'

    def tree(sha_or_ref):
        rr = requests.get(f'{api}/repos/{MTEB_RESULTS_REPO}/git/trees/{sha_or_ref}',
                          headers=headers, proxies=proxies, timeout=60)
        rr.raise_for_status()
        return rr.json().get('tree', [])

    try:
        root = {e['path']: e['sha'] for e in tree('main')}
        folders = {e['path']: e['sha'] for e in tree(root['results']) if e['type'] == 'tree'}
        for folder, sha in folders.items():
            if folder in index or not any(f in folder.lower() for f in marker_set):
                continue
            # Arbre RÉCURSIF du dossier du modèle (1 appel) : toutes ses révisions, tous
            # ses fichiers — on ne garde que les tâches du jeu, chemin exact.
            for e in tree(f'{sha}?recursive=1'):
                if e['type'] != 'blob' or not e['path'].endswith('.json'):
                    continue
                t = e['path'].rsplit('/', 1)[-1][:-5]
                if t in tasks:
                    index.setdefault(folder, {})[t] = f"results/{folder}/{e['path']}"
    except Exception as e:
        # L'API (quota, réseau) ne fait pas tomber la population de `paths.json`.
        logger.warning("[mteb] index API GitHub incomplet : %s", e)
    return index


def _mteb_cache_path():
    from django.conf import settings
    p = Path(settings.BASE_DIR) / 'logs' / 'benchmarks' / 'mteb_scores.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_mteb():
    """
    {'embedding': [{'nom','slug','score','identite','taches','revision'}]} depuis le dépôt
    des résultats MTEB — jeu de tâches DÉCLARÉ dans `CATEGORIES['embedding']['mteb']`.

    Un score = moyenne des `main_score` (nDCG@10, 0-1) des tâches du jeu, ×100. Un modèle
    qui n'a pas TOUTES les tâches est ignoré — jamais une moyenne sur moins. Les scores
    sont IMMUABLES par (modèle, révision, tâche) : cache disque `logs/benchmarks/`, donc la
    première passe coûte ~5 fichiers × population (143 le 02/09), les suivantes zéro.

    Identité : `owner__model` → dernier segment (`Qwen3-Embedding-0.6B` → (qwen,(3,),0.6)).
    `bge-m3` n'en a pas (famille d'une lettre) → `ALIAS` par égalité de slug `BAAI/bge-m3`.
    """
    import json
    import requests

    spec = CATEGORIES['embedding']
    dataset = tuple(spec['mteb'])                   # (tâche, split, hf_subset)
    try:
        index = _mteb_index(_mteb_markers())
    except Exception as e:
        raise SourceUnavailable(f'MTEB : index indisponible ({type(e).__name__}: {e})')

    cache_p = _mteb_cache_path()
    try:
        cache = json.loads(cache_p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        cache = {}
    raw = _base_url_of('mteb')
    proxies = _proxies_for('mteb')

    def read_score(key, wanted_split, wanted_subset):
        """main_score du sous-ensemble voulu, None si ABSENT (404 / subset manquant —
        cacheable), ou lève si l'échec est PASSAGER (réseau, 5xx, JSON tronqué) — jamais
        mis en cache : un `None` de proxy se lisait « absent » et le restait (mesuré :
        SyntecRetrieval → 200 à la relecture)."""
        url = f'{raw}/{MTEB_RESULTS_REPO}/main/{key}'
        last_error = None
        for _ in range(2):
            try:
                r = requests.get(url, proxies=proxies, timeout=60)
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                # json stdlib : simplejson (via requests) refuse les `NaN` que mteb écrit.
                sc = (json.loads(r.text).get('scores') or {})
                split = sc.get(wanted_split) or []
                for s in split:
                    if str(s.get('hf_subset', 'default')) == wanted_subset:
                        return float(s['main_score'])
                return None
            except Exception as e:      # passager : on retente une fois, puis on lève
                last_error = e
        raise last_error

    out, reasons = [], {}
    missing = transient_count = 0
    for folder, paths in sorted(index.items()):
        if any(t not in paths for t, _, _ in dataset):
            missing += 1
            continue
        scores, rev, transient = {}, '', False
        for t, split, subset in dataset:
            key = f'{paths[t]}#{split}#{subset}'    # chemin exact = clé de cache immuable
            rev = paths[t].split('/')[2] if paths[t].count('/') >= 3 else rev
            if key in cache:
                v = cache[key]
            else:
                try:
                    v = read_score(paths[t], split, subset)
                except Exception:
                    transient = True
                    break
                cache[key] = v
            if v is None:
                break
            scores[t] = v
        if transient:
            transient_count += 1
            continue
        if len(scores) < len(dataset):
            missing += 1
            continue
        name = folder.replace('__', '/', 1)
        ident = _identity(name.rsplit('/', 1)[-1])
        out.append({'name': name, 'slug': name, 'identity': ident, 'revision': rev,
                    'score': round(100.0 * sum(scores.values()) / len(scores), 2),
                    'tasks': {t: round(100.0 * v, 2) for t, v in scores.items()}})
    try:
        cache_p.write_text(json.dumps(cache, indent=0, sort_keys=True), encoding='utf-8')
    except OSError:
        pass
    if transient_count:
        reasons['embedding'] = f'{transient_count} modèle(s) non lus cette passe (réseau) — relancer'
    if not out:
        raise SourceUnavailable('MTEB : ' + (reasons.get('embedding') or 'aucun modèle avec le jeu complet'))
    return {'embedding': out}, reasons


# ── Comparabilité (règle des échelles) ───────────────────────────────────────────────────

def benchmarks_comparable(pool) -> bool:
    """
    Vrai si les `benchmark_index` du lot peuvent être ORDONNÉS entre eux.

    Deux conditions, indissociables : tout le lot est mesuré, ET une seule `echelle`. Un
    Intelligence Index (~0-70) et un Elo (~1000-1500) ne se classent pas ensemble, et deux
    Elo non plus s'ils viennent de bancs différents — on ne normalise JAMAIS.

    ⚠ POURQUOI CETTE FONCTION EXISTE (2026-09-01, question de Fabien sur les échelles). Le
    test vivait en double : `model_selector._rank_key` l'appliquait en entier, `best_installed`
    n'en gardait que la MOITIÉ (tout le lot mesuré, échelle jamais regardée) tout en annonçant
    « MÊME RÈGLE D'ÉTAGE QUE LA SÉLECTION » dans son commentaire. Le lot `diffusion` porte
    pourtant DÉJÀ deux échelles (`aa_elo_text_to_image` 1077 pour hunyuan, `arena_elo_text_to_image`
    1125,76 pour qwen-image-2) : le classement ne s'est pas trompé jusqu'ici seulement parce
    qu'un modèle non mesuré faisait basculer tout le lot sur le repli `quality_index`.
    *Un piège masqué par une couverture incomplète se déclenche quand la couverture s'améliore*
    — c'est-à-dire exactement là où mène ce chantier. Un seul domicile, donc.
    """
    batch = list(pool)
    if not batch:
        return False
    scales = {(getattr(m, 'benchmark_meta', None) or {}).get('scale') for m in batch}
    return (len(scales) == 1 and None not in scales
            and all(getattr(m, 'benchmark_index', None) is not None for m in batch))


# ── Catégorie d'un modèle du catalogue ───────────────────────────────────────────────────

def _local_categories(m):
    """
    Catégories de banc d'une ligne AIModel, la PRINCIPALE d'abord. Liste vide = hors banc.

    Plusieurs, parce qu'un modèle peut exercer plusieurs MÉTIERS : `ltx-video` fait T2V *et*
    I2V (son libellé le dit, et AA le classe dans les deux leaderboards), un modèle « omni »
    en fera davantage. Rendre une seule catégorie faisait tomber les autres EN SILENCE.

    Les métiers secondaires se DÉCLARENT dans `capabilities['tasks']` — jamais devinés depuis
    le libellé : c'est la trappe qui a donné l'identité `('max', (768,))` à la LoRA logo, lue
    dans « max 768 px ». Tant que rien ne déclare `tasks`, cette fonction rend exactement une
    catégorie et le comportement est celui d'avant (mesuré : les 10 appariés sont inchangés).

    ⚠ Les capacités d'ENTRÉE ne sont pas des métiers : `ModelAbility.VISION` (« lecture
    d'images ») ne met pas un VLM dans le banc texte→image. Les 6 leaderboards sont tous en
    GÉNÉRATION — d'où la dérivation par la tâche seule.
    """
    from ..models import ModelType, canonical_task

    # Un ADD-ON (LoRA, adaptateur, ControlNet) n'est pas un modèle : aucun leaderboard ne
    # le mesure, et son nom porte celui du modèle de base — `FLUX.1-dev-LoRA-Logo-Design`
    # prenait l'Elo de FLUX.1 dès que la forme « FLUX.1 » est devenue lisible (02/09).
    # Hors catégorie, par nature — la même famille que `_NOISE_MARKERS` de la prospection.
    # ⚠ Lu sur les IDENTIFIANTS (clé, `hf_id`), jamais sur `name` : le libellé descriptif de
    # SD 1.5 et de SDXL cite « LoRA » et les deux sortaient du banc (mesuré à la 1ʳᵉ passe).
    identifiers = ' '.join((m.model_key or '', getattr(m, 'hf_id', '') or '')).lower()
    if any(marker in identifiers for marker in ADD_ONS):
        return []

    caps = m.capabilities or {}
    # `canonical_task` traduit le vocabulaire d'une plateforme vers le nôtre : une tâche
    # écrite en HF (`automatic-speech-recognition`) ne trouvait AUCUNE catégorie et
    # retombait en silence sur le repli LLM ou sur rien (leçon du 31/08).
    raw_tasks = caps.get('tasks') or ([caps['task']] if caps.get('task') else [])
    out = []
    for t in raw_tasks:
        cats = TASK_TO_BENCH_CATEGORY.get(canonical_task((t or '').strip().lower()))
        for cat in (cats if isinstance(cats, tuple) else (cats,)):
            if cat and cat not in out:
                out.append(cat)
    ollama = m.model_key.startswith(('ollama:', 'proposed:ollama:'))
    if out:
        # Un LLM Ollama à capacité `vision` (découverte : gemma4, qwen3.8) exerce AUSSI le
        # métier de l'arène `vision`, en SECONDAIRE de sa tâche déclarée. Ce n'est pas la
        # trappe « capacité d'entrée ≠ métier » du docstring (celle-là vise un VLM poussé
        # vers texte→IMAGE) : ici le banc mesure exactement la lecture d'images annoncée.
        # Mesuré le 02/09 : les 4 LLM installés portent `task` ET `vision`, donc cette
        # branche — la règle écrite d'abord dans le repli plus bas ne les touchait jamais.
        if ollama and caps.get('vision') and 'llm' in out and 'vision' not in out:
            out.append('vision')
        return out
    if ollama:
        # Un modèle d'EMBEDDING n'est pas un LLM de chat : quand les capacités existent
        # (découverte passée), `completion` fait foi — 1er dry-run 19/08 : bge-m3 prenait
        # un Intelligence Index. Les lignes `proposed:` n'ont PAS de caps (la découverte
        # n'est pas passée) — mais elles ont un `model_type`, posé par la prospection
        # (`prospect_ollama` écrit `'embedding'`), et c'est LUI qui fait foi : 5 embeddings
        # proposés tombaient en catégorie llm et polluaient « sans banc » / « sans identité »
        # (mesuré le 02/09, promesse du 01/09 tenue ici). Les `vlm` RESTENT éligibles : AA
        # classe MiniCPM-V dans son leaderboard LLM.
        if caps and not caps.get('completion'):
            return []
        if m.model_type == ModelType.VLM:
            # Un VLM a pour banc PRINCIPAL l'arène `vision` (image + prompt) ; le banc
            # texte reste un métier secondaire (AA y classe MiniCPM-V).
            return ['vision', 'llm']
        if m.model_type == ModelType.EMBEDDING:
            # Proposé sans capacités : la prospection a posé le type, MTEB est son banc.
            return ['embedding']
        if m.model_type != ModelType.LLM:
            return []
        # Même règle `vision` que ci-dessus, pour un LLM sans tâche déclarée.
        return ['llm', 'vision'] if caps.get('vision') else ['llm']
    return []


def orderable_value(m):
    """
    La valeur d'un `benchmark_index` telle qu'on peut la TRIER (plus grand = meilleur), ou
    None. Seul point de lecture pour un tri : un WER (`sens='bas'`) trié décroissant mettrait
    le pire modèle en tête. Les consommateurs (`_rank_key`, `best_installed`) passent par ici
    au lieu de lire `benchmark_index` — un nombre dont ils ne connaissent pas le sens.
    """
    v = getattr(m, 'benchmark_index', None)
    if v is None:
        return None
    direction = (getattr(m, 'benchmark_meta', None) or {}).get('direction', 'higher')
    return -v if direction == 'lower' else v


def _local_identities(m):
    """Identités candidates d'une ligne AIModel : tag/nom/hf_id/platform_ref (hors ALIAS,
    traité à part par égalité de slug — cf. `_match_alias`)."""
    raw_names = [m.model_key.split(':', 1)[1] if ':' in m.model_key else m.model_key,
             m.name or '', (m.hf_id or '').rsplit('/', 1)[-1],
             (m.platform_ref or '').rpartition(':')[2].rsplit('/', 1)[-1]]
    seen, out = set(), []
    for b in raw_names:
        i = _identity(b)
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    # tag sans taille ('latest') : demander le tag réel à Ollama (métadonnée locale) —
    # PAS seulement quand out est vide : `qwen3.8:latest` donnait (qwen,(3,8),None), qui
    # matcherait `qwen3.8-max` (frontière) au lieu du vrai 27b (1er dry-run 19/08).
    if m.model_key.startswith('ollama:') and not any(i[2] is not None for i in out):
        i = _identity(_real_tag(m.model_key.split(':', 1)[1]) or '')
        if i and i not in out:
            out.insert(0, i)
    return out


def _real_tag(name: str):
    """':latest' → tag réel via /api/show `details.parent_model` (métadonnée locale Ollama)."""
    try:
        import requests
        from wama.common.utils.ollama_host import ollama_base, ollama_kwargs
        r = requests.post(f'{ollama_base()}/api/show', json={'model': name},
                          **ollama_kwargs(timeout=10))
        r.raise_for_status()
        return (r.json().get('details') or {}).get('parent_model') or ''
    except Exception:
        return ''


# ── Registre des sources ─────────────────────────────────────────────────────────────────

def _meta_aa(chosen, candidates):
    d = {'aa_name': chosen['name'], 'aa_slug': chosen['slug'],
         'aa_variants': [(e['name'], e['value']) for e in candidates]}
    if chosen.get('family_scores'):
        d['family_scores'] = chosen['family_scores']
    return d


def _meta_arena(chosen, candidates):
    return {'arena_name': chosen['name'], 'arena_elo': chosen['elo'],
            'arena_votes': chosen['votes']}


def _meta_mteb(chosen, candidates):
    return {'mteb_name': chosen['name'], 'mteb_score': chosen['score'],
            'mteb_tasks': chosen.get('tasks') or {}, 'mteb_revision': chosen.get('revision', '')}


def _meta_open_asr(chosen, candidates):
    d = {'open_asr_name': chosen['name'], 'open_asr_wer': chosen['wer'],
         'open_asr_datasets': chosen.get('datasets') or {}}
    for k in ('rtfx', 'license', 'size_b'):
        if chosen.get(k) not in (None, ''):
            d[f'open_asr_{k}'] = chosen[k]
    return d


#: LES SOURCES, DÉCLARÉES. Ajouter une plateforme = une entrée ici, plus un chargeur qui rend
#: `{catégorie: [entrées]}`. Avant le 2026-09-01 il fallait toucher CINQ endroits : les deux
#: chargeurs nommés, le couple codé en dur de `synchronize`, la priorité « AA d'abord, Arena
#: en repli » écrite dans le corps de `_benchmark_for_category`, les clés de meta préfixées par
#: source, et une confrontation qui supposait EXACTEMENT deux sources. Une table de modalités
#: déclarative (`CATEGORIES`) au-dessus d'un jeu de sources câblé : c'était déclaratif sur
#: l'axe qui bouge le moins.
#:
#: ⚠ Ce qui se DÉCLARE ici : l'identité, la priorité, comment lire une valeur, comment nommer
#: l'échelle, quelles clés de meta écrire. Ce qui ne se déclare PAS : le chargeur — chaque
#: plateforme a sa forme (AA rend du JSON authentifié, Arena un parquet HuggingFace, Ollama
#: du HTML). Un « chargeur générique paramétré » serait à la fois fragile et une surface de
#: requête arbitraire côté serveur.
#:
#: `priorite` : le plus BAS porte `benchmark_index` quand il apparie ; les suivants n'ajoutent
#: que leur meta. Les valeurs ne se mélangent jamais — échelles incommensurables.
#: `sens` (défaut 'haut') : 'bas' quand une valeur plus PETITE est meilleure (taux d'erreur).
#: Écrit dans le banc (`benchmark_meta['direction']`) et lu par `percentile_rank`, `_choose_variant`
#: et `orderable_value` — nulle part ailleurs un consommateur n'a à connaître le sens.
SOURCES = (
    {'key': 'aa', 'label': 'Artificial Analysis', 'priority': 1,
     'source_name': 'artificial-analysis', 'loader': lambda: load_aa(),
     'value': lambda e: e.get('value'),
     'scale': lambda e, cat: e.get('scale'),
     'meta': _meta_aa},
    {'key': 'arena', 'label': 'Arena (leaderboard-dataset, CC-BY-4.0)', 'priority': 2,
     'source_name': 'arena', 'loader': lambda: load_arena(),
     'value': lambda e: e.get('elo'),
     'scale': lambda e, cat: f'arena_elo_{CATEGORIES[cat]["arena"]}',
     'meta': _meta_arena},
    {'key': 'open_asr', 'label': 'Open ASR Leaderboard (Hugging Face, hf-audio)', 'priority': 3,
     'source_name': 'open-asr', 'loader': lambda: load_open_asr(),
     'value': lambda e: e.get('wer'), 'direction': 'lower',
     'scale': lambda e, cat: f'open_asr_wer_{CATEGORIES[cat]["open_asr"]}',
     'meta': _meta_open_asr},
    {'key': 'mteb', 'label': 'MTEB results (embeddings-benchmark/results, CC0-1.0)', 'priority': 4,
     'source_name': 'mteb', 'loader': lambda: load_mteb(),
     'value': lambda e: e.get('score'),
     'scale': lambda e, cat: 'mteb_fr_retrieval',
     'meta': _meta_mteb},
)

#: Ordre de consultation — figé une fois, pas retrié à chaque modèle.
SOURCES_BY_PRIORITY = tuple(sorted(SOURCES, key=lambda s: s['priority']))


# ── Synchronisation ──────────────────────────────────────────────────────────────────────

def percentile_rank(value, population, key, direction: str = 'higher'):
    """
    Position de `valeur` dans la population de SON banc, en centiles (0-100), ou None.
    `sens='bas'` (taux d'erreur) : le centile compte les valeurs PLUS GRANDES — 90ᵉ centile
    reste « meilleur que 90 % du banc », quelle que soit l'échelle.

    POURQUOI (demande de Fabien, 2026-09-01 : « ramener toute valeur entre 0 et 100 pour
    pouvoir comparer »). Le besoin est réel — sans lui, deux modèles mesurés par des bancs
    différents ne se classent pas. Mais un min-max vers 0-100 serait la pire réponse :
      • il n'est pas REPRODUCTIBLE — les bornes viennent de la population du leaderboard,
        donc l'arrivée d'un modèle au sommet ferait baisser le score d'un modèle qui n'a
        pas bougé. Une valeur de qualité qui change sans que le modèle change n'en est pas une ;
      • il FABRIQUERAIT l'équivalence que ce module refuse depuis toujours : un Intelligence
        Index est une moyenne de taux de réussite, un Elo une probabilité de préférence
        humaine. Les ramener au même intervalle les rend comparables à l'œil sans qu'aucune
        expérience ne les relie.
    Un rang, lui, n'invente rien : il énonce la position de chacun parmi SES pairs, ce qui
    est mesuré. Il s'AJOUTE — `benchmark_index` et son `echelle` restent la donnée ;
    le centile est une lecture.

    ⚠ Deux réserves, à dire partout où il s'affiche :
      • il est ORDINAL — 90ᵉ et 80ᵉ centile ne veulent pas dire « 10 % meilleur » ;
      • il dépend de la POPULATION du banc, qui contient des modèles fermés que nous ne
        pouvons pas faire tourner : être médian chez AA n'est pas être médian chez soi.
    """
    values = [v for v in (key(e) for e in population) if v is not None]
    if value is None or not values:
        return None
    beaten = (sum(1 for v in values if v > value) if direction == 'lower'
              else sum(1 for v in values if v < value))
    return round(100.0 * beaten / len(values), 1)


def _benchmark_for_category(m, cat, alias, sources):
    """
    Mesure d'UNE catégorie pour un modèle → `(banc, idents)`, `banc` à None si non apparié.

    Extrait tel quel du corps de `synchronize` le 2026-09-01 pour qu'il puisse être appelé
    UNE FOIS PAR MÉTIER (cf. `_local_categories`) : la logique d'appariement, elle, est
    inchangée. `idents` remonte pour que l'appelant distingue « absent des leaderboards » de
    « identité illisible ».
    """
    local_name = m.name or m.model_key
    idents = []
    cands = {}
    if alias:       # confirmation humaine : égalité de slug, aucune heuristique
        cands = {s['key']: _match_alias(alias, sources.get(s['key'], {}).get(cat, []))
                 for s in SOURCES_BY_PRIORITY}
    else:
        idents = _local_identities(m)
        # cf. `_compatible` : jamais une variante frontière sans taille. DÉCLARÉ par la
        # catégorie (`strict_size`), plus écrit `cat == 'llm'` : l'arène `vision` est
        # peuplée des mêmes LLM et exige la même règle (faux appariement mesuré le 02/09).
        strict = bool(CATEGORIES.get(cat, {}).get('strict_size'))
        for ident in idents:
            cands = {s['key']: _match(ident, sources.get(s['key'], {}).get(cat, []),
                                         strict, local_name)
                     for s in SOURCES_BY_PRIORITY}
            if any(cands.values()):
                break
    if not any(cands.values()):
        return None, idents

    benchmark = {'category': cat}
    value = scale = None
    carrier = None
    for s in SOURCES_BY_PRIORITY:
        candidates = cands.get(s['key']) or []
        if not candidates:
            continue
        # La variante qui CORRESPOND, pas la mieux notée (cf. `_choose_variant`).
        chosen = _choose_variant(local_name, candidates, s['value'], s.get('direction', 'higher'))
        benchmark.update(s['meta'](chosen, candidates))
        if value is None:      # la PREMIÈRE source appariée porte l'index ; les autres non
            value, scale = s['value'](chosen), s['scale'](chosen, cat)
            benchmark['source'] = s['source_name']
            carrier = s
    benchmark['value'], benchmark['scale'] = value, scale
    # Le SENS de l'échelle voyage avec la valeur : sans lui, un consommateur trierait un WER
    # comme un Elo. Toujours écrit, même 'haut' — un lecteur ne teste pas sa présence.
    benchmark['direction'] = carrier.get('direction', 'higher') if carrier else 'higher'
    # Rang dans la population du banc QUI PORTE la valeur — jamais dans un autre : un centile
    # se lit sur une seule population, sinon il redevient la comparaison inter-échelles qu'il
    # est censé remplacer.
    population = sources.get(carrier['key'], {}).get(cat, []) if carrier else []
    benchmark['percentile_rank'] = (percentile_rank(value, population, carrier['value'], benchmark['direction'])
                            if carrier else None)
    benchmark['population'] = len(population)
    return benchmark, idents


def synchronize(dry_run: bool = False, include_proposed: bool = True):
    """
    Apparie le catalogue (téléchargés + candidats de prospection `proposed:`) aux deux
    sources, par CATÉGORIE. Écrit `benchmark_index` (AA prioritaire, sinon Elo Arena —
    échelle TOUJOURS nommée en meta) + `benchmark_meta`. SourceUnavailable si AUCUNE source.
    """
    from django.db.models import Q
    from django.utils import timezone
    from wama.model_manager.models import AIModel

    sources, unavailable, reasons_by_category = {}, {}, {}
    for s in SOURCES_BY_PRIORITY:
        try:
            sources[s['key']], reasons_by_category[s['key']] = s['loader']()
        except SourceUnavailable as e:
            unavailable[s['key']] = str(e)
    if not sources:
        raise SourceUnavailable(' ; '.join(f'{k}: {v}' for k, v in unavailable.items()))

    # Les quatre issues sont EXHAUSTIVES et disjointes : leur somme vaut le nombre de lignes
    # examinées. Ce n'était pas le cas avant le 2026-09-01 — `without_identity` n'existait pas et
    # ses lignes ne tombaient dans aucun compteur (mesuré : 15 modèles, dont kokoro, bark,
    # chatterbox et cogvideox, invisibles au rapport comme à l'UI). Un modèle qui disparaît du
    # compte se lit « il n'y en a pas » alors qu'il dit « je n'ai pas su le nommer ».
    report = {'sources': {k: {c: len(v) for c, v in cats.items()} for k, cats in sources.items()},
               'reasons': reasons_by_category, 'unavailable': unavailable,
               'matched': [], 'unmatched': [], 'without_identity': [],
               'without_category': 0, 'inversions': []}

    # ⚠ UN MODÈLE CLOUD N'EST PAS TÉLÉCHARGÉ, et il est utilisable quand même (2026-09-19).
    # `is_downloaded=True` voulait dire « utilisable ici » — vrai tant que tout était local.
    # Depuis que le cloud est une source de découverte du registre, les 22 lignes servies par
    # une clé d'API (Albert, Anthropic, abonnement) ont `is_downloaded=False` : elles n'étaient
    # donc NI appariées, NI comptées dans `without_category` — invisibles du rapport, alors
    # que ce sont les modèles les mieux couverts par les leaderboards publics (gpt-oss-120b,
    # deepseek, mistral, gemma, claude). Mesuré avant correction : 0/22 avec un banc.
    # C'est le défaut que le commentaire ci-dessus dénonce, d'un cran plus haut : une ligne
    # exclue du QUERYSET ne disparaît pas d'un compteur, elle disparaît de la question.
    servi_sans_poids = Q(execution='cloud', is_available=True)
    qs = AIModel.objects.filter(Q(is_downloaded=True) | servi_sans_poids | Q(is_proposed=True)) \
        if include_proposed else AIModel.objects.filter(Q(is_downloaded=True) | servi_sans_poids)
    by_scale = {}    # échelle → [(model, valeur, elo)] pour la confrontation

    for m in qs:
        cats = _local_categories(m)
        if not cats:
            report['without_category'] += 1
            continue
        alias = ALIAS.get(m.model_key)
        benchmarks, idents = [], []
        for cat in cats:
            benchmark, ids = _benchmark_for_category(m, cat, alias, sources)
            idents = idents or ids
            if benchmark:
                benchmarks.append(benchmark)
        if not benchmarks:
            if alias or idents:
                # Identifiable mais absent des leaderboards : tracé, pas un échec. Un ALIAS qui
                # ne trouve rien se range ICI et jamais dans `without_identity` : c'est une
                # confirmation humaine démentie par la source (entrée retirée, slug changé),
                # donc un DÉFAUT à voir, pas une identité manquante.
                report['unmatched'].append(f'{m.model_key} [{cats[0]}]')
            else:
                # Aucune identité famille+version lisible : la question du banc ne s'est même
                # pas posée. Distinct d'un « sans banc » — le remède n'est pas un ALIAS mais
                # une identité (nom, `hf_id` ou `platform_ref` exploitable).
                report['without_identity'].append(f'{m.model_key} [{cats[0]}]')
            continue

        # Le banc PORTEUR est le premier apparié, donc celui du métier principal quand il l'est.
        # Si le métier principal n'a pas de banc et qu'un secondaire en a un, c'est ce dernier
        # qui porte l'index : `categorie` et `echelle` le nomment, donc rien n'est masqué —
        # une valeur mesurée et nommée vaut mieux qu'un NULL.
        carrier = benchmarks[0]
        meta = {'synced_at': timezone.now().isoformat(),
                **({'declared_alias': alias} if alias else {}),
                # Attribution DÉRIVÉE du registre : une source ajoutée s'y cite d'elle-même,
                # au lieu d'être oubliée dans une chaîne figée (l'Arena est sous CC-BY-4.0,
                # l'attribution est une OBLIGATION de licence, pas une politesse).
                'attribution': ' / '.join(s['label'] for s in SOURCES_BY_PRIORITY),
                'local_quant': 'score tiers = borne haute (mesuré fp8/16, local souvent Q4)'}
        # Clés À PLAT du banc porteur : la forme d'avant le 2026-09-01, à l'identique. Les
        # consommateurs (`to_dict`, cards, `_rank_key`) ne voient aucune différence.
        meta.update({k: v for k, v in carrier.items() if k != 'value'})
        # AJOUT : un banc par métier, chacun avec SON échelle nommée. Toujours présent, même
        # à un seul élément — un consommateur lit `bancs` sans avoir à tester sa présence.
        meta['benchmarks'] = benchmarks
        report['matched'].append((m.model_key, carrier['category'], carrier['value'],
                                    carrier['scale'], carrier.get('arena_elo')))
        for b in benchmarks:
            by_scale.setdefault((b['category'], 'confront'), []).append(
                (m, b['value'], b.get('arena_elo'), b.get('source')))
        if not dry_run:
            m.benchmark_index = carrier['value']
            m.benchmark_meta = meta
            m.save(update_fields=['benchmark_index', 'benchmark_meta'])

    # Confrontation par catégorie : inversions d'ordre AA↔Elo parmi les doubles appariés.
    # Dédoublonnée par PAIRE DE NOMS TIERS (une ligne `proposed:` et sa jumelle téléchargée
    # portent le même appariement — le 1er dry-run imprimait chaque inversion jusqu'à 4×).
    seen = set()
    for (cat, _), batch in by_scale.items():
        # Seuls les modèles dont l'index vient de la source PRIORITAIRE participent : un index
        # porté par une source de repli comparerait deux échelles, alors que la confrontation
        # exige deux mesures INDÉPENDANTES du même modèle. Lu depuis le registre plutôt
        # qu'écrit « != 'arena' », qui supposait qu'il n'existe jamais que deux sources.
        _primary = SOURCES_BY_PRIORITY[0]['source_name']
        pairs = [(m, v, e) for m, v, e, src in batch
                   if v is not None and e is not None and src == _primary]
        for i in range(len(pairs)):
            for j in range(i + 1, len(pairs)):
                (m1, a1, e1), (m2, a2, e2) = pairs[i], pairs[j]
                if (a1 - a2) * (e1 - e2) < 0:
                    pair = (cat,) + tuple(sorted((m1.name, m2.name)))
                    if pair not in seen:
                        seen.add(pair)
                        report['inversions'].append(
                            f"[{cat}] {m1.name} vs {m2.name} : AA {a1}/{a2} mais Elo {e1}/{e2}")
    return report
