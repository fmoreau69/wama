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

RÈGLE DES ÉCHELLES (héritée de `_rank_key`, étendue) : Intelligence Index (~0-70) et Elo
(~1000-1500) sont INCOMMENSURABLES — `benchmark_meta['echelle']` nomme l'échelle de chaque
valeur, et le tri ne compare que des lots à échelle UNIQUE. On ne normalise jamais (une
normalisation inventerait une équivalence que personne n'a mesurée).

GARDE-FOUS :
  • Null plutôt que plausible : non apparié → NULL. Appariement CONSERVATEUR (famille+version
    par `ollama_registry.decompose`, taille exigée égale quand les DEUX côtés la déclarent).
  • `ALIAS` déclaratif : quand un humain confirme une équivalence que l'identité stricte ne
    voit pas (ex. un nom commercial ≠ tag), il la DÉCLARE ici — jamais de fuzzy silencieux.
  • Champ SÉPARÉ de `quality_index` : `sync_models` (découverte) n'écrit jamais ici.
  • AA/Arena mesurent des endpoints fp8/fp16 ; nos GGUF sont souvent Q4 → borne haute, tracée.
  • Catégorie par modèle DÉCLARÉE (TACHE_VERS_CATEGORIE) : on n'apparie jamais un modèle
    d'une modalité aux entrées d'une autre (un « qwen » TTS ne prendra pas l'index du LLM).
"""
from __future__ import annotations

import logging
import os
import re

from .ollama_registry import decompose, _milliards

logger = logging.getLogger(__name__)

#: Adresses et clé déclarées au registre COMMUN des sources externes (2026-09-01). `SOURCES`
#: plus bas reste le registre des BANCS — il dit comment LIRE une valeur (priorité, échelle,
#: méta) ; il ne dit plus où joindre la plateforme. Deux registres, deux questions.
from wama.common.external_sources import ARENA_DATASET, get as _source  # noqa: F401
from wama.common.external_sources import base_url as _base_url

AA_BASE = _base_url('artificial_analysis')
AA_KEY_ENV = _source('artificial_analysis').api_key_env

#: Catégorie → (endpoint AA, extracteur de score AA, échelle AA, sous-ensemble Arena).
#: DÉCLARATIF : ajouter une modalité = une ligne. Un endpoint AA absent/403 (tier) ou un
#: parquet manquant SKIPPE la (source, catégorie) avec motif — jamais un rouge global.
CATEGORIES = {
    'llm': {
        'aa': 'data/llms/models', 'aa_champ': 'artificial_analysis_intelligence_index',
        'aa_echelle': 'aa_intelligence_index', 'arena': 'text',
    },
    'text-to-image': {
        'aa': 'data/media/text-to-image', 'aa_champ': 'elo',
        'aa_echelle': 'aa_elo_text_to_image', 'arena': 'text_to_image',
    },
    'image-editing': {
        'aa': 'data/media/image-editing', 'aa_champ': 'elo',
        'aa_echelle': 'aa_elo_image_editing', 'arena': 'image_edit',
    },
    'text-to-speech': {
        'aa': 'data/media/text-to-speech', 'aa_champ': 'elo',
        'aa_echelle': 'aa_elo_text_to_speech', 'arena': None,
    },
    'text-to-video': {
        'aa': 'data/media/text-to-video', 'aa_champ': 'elo',
        'aa_echelle': 'aa_elo_text_to_video', 'arena': 'text_to_video',
    },
    'image-to-video': {
        'aa': 'data/media/image-to-video', 'aa_champ': 'elo',
        'aa_echelle': 'aa_elo_image_to_video', 'arena': 'image_to_video',
    },
}

#: Tâche canonique du catalogue (`capabilities.task` / `ModelTask`) → catégorie de benchmark.
#: Indexé sur la TÂCHE, jamais sur l'app (règle des bancs). Tâche absente → 'llm' si le
#: modèle est un LLM Ollama, sinon PAS de catégorie (donc pas d'appariement).
TACHE_VERS_CATEGORIE = {
    'text-generation': 'llm',
    'text-to-image': 'text-to-image',
    'image-to-image': 'image-editing',
    'image-editing': 'image-editing',
    'text-to-speech': 'text-to-speech',
    'text-to-video': 'text-to-video',
    'image-to-video': 'image-to-video',
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
}


#: Mots qui nomment un TIRAGE d'un modèle, pas le modèle — écartés de la famille (cf.
#: `_avec_prefixe`). Liste volontairement COURTE : chaque entrée doit être un mot qui ne
#: distingue jamais deux modèles différents. `lite`, `mini` ou `turbo` n'y sont PAS — ceux-là
#: désignent bien des modèles distincts (« DeepSeek Coder V2 Lite » ≠ « DeepSeek-Coder-V2 »).
MOTS_DE_CONDITIONNEMENT = {'base', 'instruct', 'chat', 'it'}


class SourceIndisponible(Exception):
    """Réseau/clé/format absents — la source est SKIPPÉE, jamais un score partiel inventé."""


# ── Identité (les sources parlent des noms différents) ───────────────────────────────────

def _avec_prefixe(mot: str, segments: list, i: int) -> str:
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
    prefixe = []
    j = i - 1
    while j >= 0 and re.fullmatch(r'[a-z]{2,}', segments[j]):
        prefixe.insert(0, segments[j])
        j -= 1
    mots = [x for x in prefixe + [mot] if x not in MOTS_DE_CONDITIONNEMENT]
    return ''.join(mots or [mot])


def _words(texte: str) -> set:
    """
    Jetons PUREMENT alphabétiques (≥ 2 lettres) d'un nom — les mots qui QUALIFIENT la variante.

    Volontairement générique plutôt qu'une liste fermée de qualificatifs : une liste figée
    aurait raté « coder » (mesuré le 2026-08-19 — voir `_choose_variant`) et aurait dérivé
    à chaque nouvelle série. Les jetons alphanumériques (`qwen3`, `30b`, `a3b`, `2507`) sont
    écartés : ils portent famille/taille/date, déjà traitées par l'identité.
    """
    return {j for j in re.split(r'[^a-z]+', (texte or '').lower()) if len(j) >= 2}


def _choose_variant(nom_local: str, candidats: list, cle):
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
    chaîne ; (4) en dernier recours la valeur la PLUS BASSE — conservateur, cohérent avec la
    règle « null plutôt que plausible » du module.
    """
    from difflib import SequenceMatcher
    if len(candidats) == 1:
        return candidats[0]
    plat = re.sub(r'[^a-z0-9]+', ' ', (nom_local or '').lower())
    mots_local = _words(nom_local)

    def rang(e):
        nom = re.sub(r'[^a-z0-9]+', ' ', (e.get('nom') or '').lower())
        mots = _words(e.get('nom'))
        return (len(mots_local & mots), -len(mots - mots_local),
                SequenceMatcher(None, plat, nom).ratio(), -float(cle(e) or 0))

    return max(candidats, key=rang)


def _identity(texte: str):
    """
    'qwen3.6:35b' / 'qwen3-6-35b-a3b' / 'Qwen3.6 35B A3B' / 'Gemma 4 31B' / 'veo-3.1'
        → ('qwen', (3,6), 35.0) · ('gemma', (4,), 31.0) · ('veo', (3,1), None) · … ou None.

    Famille+version par `decompose` (brique du « successeur de famille »), étendue aux formes
    éclatées ('gemma-4', 'qwen3-6') ; taille = premier jeton `<n>b` (via `_milliards`),
    OPTIONNELLE (les modèles média n'en publient pas). Sans famille+version : None.
    """
    plat = re.sub(r'[\s_]+', '-', (texte or '').strip().lower())
    segments = [s for s in re.split(r'[:/-]', plat) if s]
    fam = ver = taille = None
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
                fam = _avec_prefixe(seg, segments, i)
                i += 1
                ver = tuple(int(x) for x in segments[i].split('.'))
            elif (re.fullmatch(r'v\d+(?:\.\d+)*', seg) and i > 0
                  and re.fullmatch(r'[a-z]{2,}', segments[i - 1])):
                # 'stable-diffusion-v1-5' : 'v1' = marqueur de VERSION du mot précédent.
                fam = _avec_prefixe(segments[i - 1], segments, i - 1)
                ver = tuple(int(x) for x in seg[1:].split('.'))
            if fam is not None:
                while i + 1 < len(segments) and segments[i + 1].isdigit():
                    i += 1
                    ver = ver + (int(segments[i]),)
                i += 1
                continue
        if taille is None:
            t = _milliards(seg)
            if t is not None:
                taille = t
        i += 1
    if not fam or not ver:
        return None
    return fam, ver, taille


def _compatibles(a, b, taille_requise=False, nom_local='', nom_tiers=''):
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
    if taille_requise:
        if (a[2] is None) != (b[2] is None):
            return False
        if a[2] is None:
            # `latest` n'est pas un qualificatif de modèle, c'est un pointeur de tag Ollama.
            if _words(nom_tiers) - _words(nom_local) - {'latest'}:
                return False
    return a[2] is None or b[2] is None or a[2] == b[2]


def _apparier(ident_local, entrees, taille_requise=False, nom_local=''):
    """Candidats compatibles, les tailles EXACTES d'abord (jamais un score moyen)."""
    c = [e for e in entrees
         if _compatibles(ident_local, e['identite'], taille_requise,
                         nom_local, e.get('nom') or '')]
    exacts = [e for e in c if ident_local and e['identite'][2] == ident_local[2]]
    return exacts or c


def _apparier_alias(cible: str, entrees):
    """Entrées dont le slug OU le nom vaut EXACTEMENT `cible` (comparaison normalisée)."""
    def norme(s):
        return re.sub(r'[\s_]+', '-', (s or '').strip().lower())
    c = norme(cible)
    return [e for e in entrees if norme(e.get('slug')) == c or norme(e.get('nom')) == c]


# ── Sources ──────────────────────────────────────────────────────────────────────────────

def _http_json(url: str, headers: dict | None = None, timeout: int = 45):
    import requests
    r = requests.get(url, headers=headers or {}, timeout=timeout)  # trust_env : proxy UGE
    r.raise_for_status()
    return r.json()


def charger_aa():
    """{'categorie': [{'nom','slug','valeur','echelle','identite'}]} ; motifs par catégorie."""
    cle = os.environ.get(AA_KEY_ENV, '').strip()
    if not cle:
        raise SourceIndisponible(
            f"clé absente ({AA_KEY_ENV} dans .env — gratuite : artificialanalysis.ai/data-api)")
    par_cat, motifs = {}, {}
    for cat, spec in CATEGORIES.items():
        try:
            data = _http_json(f"{AA_BASE}/{spec['aa']}", headers={'x-api-key': cle})
        except Exception as e:
            motifs[cat] = f'endpoint AA indisponible : {e}'
            continue
        out = []
        for m in (data.get('data') or []):
            ev = m.get('evaluations') or {}
            v = ev.get(spec['aa_champ'], m.get(spec['aa_champ']))
            ident = _identity(m.get('slug') or m.get('name') or '')
            if v is None or ident is None:
                continue    # null plutôt que plausible
            # Sous-indices PAR DOMAINE : « le meilleur » dépend de ce qu'on demande
            # (qwen3.8 = 52,0 en général, 68,1 en coding). Même requête, coût nul ;
            # consommés par `select_model(benchmark_domaine='coding')`.
            sous = {cle[len('artificial_analysis_'):-len('_index')]: val
                    for cle, val in ev.items()
                    if cle.startswith('artificial_analysis_') and cle.endswith('_index')
                    and cle != f"artificial_analysis_{spec['aa_champ'].split('_')[-1]}"
                    and val is not None}
            sous.pop('intelligence', None)      # déjà porté par `benchmark_index`
            out.append({'nom': m.get('name', ''), 'slug': m.get('slug', ''),
                        'valeur': float(v), 'echelle': spec['aa_echelle'], 'identite': ident,
                        'sous_indices': sous})
        if out:
            par_cat[cat] = out
        else:
            motifs[cat] = 'réponse vide ou sans entrée identifiable'
    if not par_cat:
        raise SourceIndisponible('AA : ' + ' ; '.join(f'{c}: {m}' for c, m in motifs.items()))
    return par_cat, motifs


def charger_arena():
    """
    {'categorie': [{'nom','elo','votes','identite'}]} depuis le dataset HF officiel
    (CC-BY-4.0). Parquet `latest` par modalité, lignes `category == 'overall'` du dernier
    `leaderboard_publish_date`. Un sous-ensemble manquant est un motif, pas un échec global.
    """
    try:
        from huggingface_hub import hf_hub_download
        import pandas as pd
    except ImportError as e:
        raise SourceIndisponible(f'outillage absent ({e})')
    par_cat, motifs = {}, {}
    for cat, spec in CATEGORIES.items():
        subset = spec.get('arena')
        if not subset:
            continue
        try:
            p = hf_hub_download(ARENA_DATASET, f'{subset}/latest-00000-of-00001.parquet',
                                repo_type='dataset')
            df = pd.read_parquet(p)
        except Exception as e:
            motifs[cat] = f'parquet {subset} indisponible : {e}'
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
            out.append({'nom': str(r['model_name']), 'elo': float(r['rating']),
                        'votes': int(r['vote_count']) if r.get('vote_count') else None,
                        'identite': ident})
        if out:
            par_cat[cat] = out
        else:
            motifs[cat] = f'{subset} : aucune entrée identifiable'
    if not par_cat:
        raise SourceIndisponible('Arena : ' + ' ; '.join(f'{c}: {m}' for c, m in motifs.items()))
    return par_cat, motifs


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
    lot = list(pool)
    if not lot:
        return False
    echelles = {(getattr(m, 'benchmark_meta', None) or {}).get('echelle') for m in lot}
    return (len(echelles) == 1 and None not in echelles
            and all(getattr(m, 'benchmark_index', None) is not None for m in lot))


# ── Catégorie d'un modèle du catalogue ───────────────────────────────────────────────────

def _categories_locales(m):
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

    caps = m.capabilities or {}
    # `canonical_task` traduit le vocabulaire d'une plateforme vers le nôtre : une tâche
    # écrite en HF (`automatic-speech-recognition`) ne trouvait AUCUNE catégorie et
    # retombait en silence sur le repli LLM ou sur rien (leçon du 31/08).
    brutes = caps.get('tasks') or ([caps['task']] if caps.get('task') else [])
    out = []
    for t in brutes:
        cat = TACHE_VERS_CATEGORIE.get(canonical_task((t or '').strip().lower()))
        if cat and cat not in out:
            out.append(cat)
    if out:
        return out
    if m.model_key.startswith(('ollama:', 'proposed:ollama:')):
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
        if m.model_type not in (ModelType.LLM, ModelType.VLM):
            return []
        return ['llm']
    return []


def _local_identities(m):
    """Identités candidates d'une ligne AIModel : tag/nom/hf_id/platform_ref (hors ALIAS,
    traité à part par égalité de slug — cf. `_apparier_alias`)."""
    bruts = [m.model_key.split(':', 1)[1] if ':' in m.model_key else m.model_key,
             m.name or '', (m.hf_id or '').rsplit('/', 1)[-1],
             (m.platform_ref or '').rpartition(':')[2].rsplit('/', 1)[-1]]
    vus, out = set(), []
    for b in bruts:
        i = _identity(b)
        if i and i not in vus:
            vus.add(i)
            out.append(i)
    # tag sans taille ('latest') : demander le tag réel à Ollama (métadonnée locale) —
    # PAS seulement quand out est vide : `qwen3.8:latest` donnait (qwen,(3,8),None), qui
    # matcherait `qwen3.8-max` (frontière) au lieu du vrai 27b (1er dry-run 19/08).
    if m.model_key.startswith('ollama:') and not any(i[2] is not None for i in out):
        i = _identity(_tag_reel(m.model_key.split(':', 1)[1]) or '')
        if i and i not in out:
            out.insert(0, i)
    return out


def _tag_reel(nom: str):
    """':latest' → tag réel via /api/show `details.parent_model` (métadonnée locale Ollama)."""
    try:
        import requests
        from wama.common.utils.ollama_host import ollama_base, ollama_kwargs
        r = requests.post(f'{ollama_base()}/api/show', json={'model': nom},
                          **ollama_kwargs(timeout=10))
        r.raise_for_status()
        return (r.json().get('details') or {}).get('parent_model') or ''
    except Exception:
        return ''


# ── Registre des sources ─────────────────────────────────────────────────────────────────

def _meta_aa(retenu, candidats):
    d = {'aa_nom': retenu['nom'], 'aa_slug': retenu['slug'],
         'aa_variantes': [(e['nom'], e['valeur']) for e in candidats]}
    if retenu.get('sous_indices'):
        d['sous_indices'] = retenu['sous_indices']
    return d


def _meta_arena(retenu, candidats):
    return {'arena_nom': retenu['nom'], 'arena_elo': retenu['elo'],
            'arena_votes': retenu['votes']}


#: LES SOURCES, DÉCLARÉES. Ajouter une plateforme = une entrée ici, plus un chargeur qui rend
#: `{catégorie: [entrées]}`. Avant le 2026-09-01 il fallait toucher CINQ endroits : les deux
#: chargeurs nommés, le couple codé en dur de `synchroniser`, la priorité « AA d'abord, Arena
#: en repli » écrite dans le corps de `_banc_pour_categorie`, les clés de meta préfixées par
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
SOURCES = (
    {'cle': 'aa', 'label': 'Artificial Analysis', 'priorite': 1,
     'nom_source': 'artificial-analysis', 'chargeur': lambda: charger_aa(),
     'valeur': lambda e: e.get('valeur'),
     'echelle': lambda e, cat: e.get('echelle'),
     'meta': _meta_aa},
    {'cle': 'arena', 'label': 'Arena (leaderboard-dataset, CC-BY-4.0)', 'priorite': 2,
     'nom_source': 'arena', 'chargeur': lambda: charger_arena(),
     'valeur': lambda e: e.get('elo'),
     'echelle': lambda e, cat: f'arena_elo_{CATEGORIES[cat]["arena"]}',
     'meta': _meta_arena},
)

#: Ordre de consultation — figé une fois, pas retrié à chaque modèle.
SOURCES_PAR_PRIORITE = tuple(sorted(SOURCES, key=lambda s: s['priorite']))


# ── Synchronisation ──────────────────────────────────────────────────────────────────────

def rang_centile(valeur, population, cle):
    """
    Position de `valeur` dans la population de SON banc, en centiles (0-100), ou None.

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
    valeurs = [v for v in (cle(e) for e in population) if v is not None]
    if valeur is None or not valeurs:
        return None
    return round(100.0 * sum(1 for v in valeurs if v < valeur) / len(valeurs), 1)


def _banc_pour_categorie(m, cat, alias, sources):
    """
    Mesure d'UNE catégorie pour un modèle → `(banc, idents)`, `banc` à None si non apparié.

    Extrait tel quel du corps de `synchroniser` le 2026-09-01 pour qu'il puisse être appelé
    UNE FOIS PAR MÉTIER (cf. `_categories_locales`) : la logique d'appariement, elle, est
    inchangée. `idents` remonte pour que l'appelant distingue « absent des leaderboards » de
    « identité illisible ».
    """
    nom_local = m.name or m.model_key
    idents = []
    cands = {}
    if alias:       # confirmation humaine : égalité de slug, aucune heuristique
        cands = {s['cle']: _apparier_alias(alias, sources.get(s['cle'], {}).get(cat, []))
                 for s in SOURCES_PAR_PRIORITE}
    else:
        idents = _local_identities(m)
        stricte = (cat == 'llm')  # cf. _compatibles : jamais une variante frontière sans taille
        for ident in idents:
            cands = {s['cle']: _apparier(ident, sources.get(s['cle'], {}).get(cat, []),
                                         stricte, nom_local)
                     for s in SOURCES_PAR_PRIORITE}
            if any(cands.values()):
                break
    if not any(cands.values()):
        return None, idents

    banc = {'categorie': cat}
    valeur = echelle = None
    porteuse = None
    for s in SOURCES_PAR_PRIORITE:
        candidats = cands.get(s['cle']) or []
        if not candidats:
            continue
        # La variante qui CORRESPOND, pas la mieux notée (cf. `_choose_variant`).
        retenu = _choose_variant(nom_local, candidats, s['valeur'])
        banc.update(s['meta'](retenu, candidats))
        if valeur is None:      # la PREMIÈRE source appariée porte l'index ; les autres non
            valeur, echelle = s['valeur'](retenu), s['echelle'](retenu, cat)
            banc['source'] = s['nom_source']
            porteuse = s
    banc['valeur'], banc['echelle'] = valeur, echelle
    # Rang dans la population du banc QUI PORTE la valeur — jamais dans un autre : un centile
    # se lit sur une seule population, sinon il redevient la comparaison inter-échelles qu'il
    # est censé remplacer.
    population = sources.get(porteuse['cle'], {}).get(cat, []) if porteuse else []
    banc['rang_centile'] = rang_centile(valeur, population, porteuse['valeur']) if porteuse else None
    banc['population'] = len(population)
    return banc, idents


def synchroniser(dry_run: bool = False, inclure_proposes: bool = True):
    """
    Apparie le catalogue (téléchargés + candidats de prospection `proposed:`) aux deux
    sources, par CATÉGORIE. Écrit `benchmark_index` (AA prioritaire, sinon Elo Arena —
    échelle TOUJOURS nommée en meta) + `benchmark_meta`. SourceIndisponible si AUCUNE source.
    """
    from django.db.models import Q
    from django.utils import timezone
    from wama.model_manager.models import AIModel

    sources, indispo, motifs_cat = {}, {}, {}
    for s in SOURCES_PAR_PRIORITE:
        try:
            sources[s['cle']], motifs_cat[s['cle']] = s['chargeur']()
        except SourceIndisponible as e:
            indispo[s['cle']] = str(e)
    if not sources:
        raise SourceIndisponible(' ; '.join(f'{k}: {v}' for k, v in indispo.items()))

    # Les quatre issues sont EXHAUSTIVES et disjointes : leur somme vaut le nombre de lignes
    # examinées. Ce n'était pas le cas avant le 2026-09-01 — `sans_identite` n'existait pas et
    # ses lignes ne tombaient dans aucun compteur (mesuré : 15 modèles, dont kokoro, bark,
    # chatterbox et cogvideox, invisibles au rapport comme à l'UI). Un modèle qui disparaît du
    # compte se lit « il n'y en a pas » alors qu'il dit « je n'ai pas su le nommer ».
    rapport = {'sources': {k: {c: len(v) for c, v in cats.items()} for k, cats in sources.items()},
               'motifs': motifs_cat, 'indisponibles': indispo,
               'apparies': [], 'non_apparies': [], 'sans_identite': [],
               'sans_categorie': 0, 'inversions': []}

    qs = AIModel.objects.filter(Q(is_downloaded=True) | Q(is_proposed=True)) \
        if inclure_proposes else AIModel.objects.filter(is_downloaded=True)
    par_echelle = {}    # échelle → [(model, valeur, elo)] pour la confrontation

    for m in qs:
        cats = _categories_locales(m)
        if not cats:
            rapport['sans_categorie'] += 1
            continue
        alias = ALIAS.get(m.model_key)
        bancs, idents = [], []
        for cat in cats:
            banc, ids = _banc_pour_categorie(m, cat, alias, sources)
            idents = idents or ids
            if banc:
                bancs.append(banc)
        if not bancs:
            if alias or idents:
                # Identifiable mais absent des leaderboards : tracé, pas un échec. Un ALIAS qui
                # ne trouve rien se range ICI et jamais dans `sans_identite` : c'est une
                # confirmation humaine démentie par la source (entrée retirée, slug changé),
                # donc un DÉFAUT à voir, pas une identité manquante.
                rapport['non_apparies'].append(f'{m.model_key} [{cats[0]}]')
            else:
                # Aucune identité famille+version lisible : la question du banc ne s'est même
                # pas posée. Distinct d'un « sans banc » — le remède n'est pas un ALIAS mais
                # une identité (nom, `hf_id` ou `platform_ref` exploitable).
                rapport['sans_identite'].append(f'{m.model_key} [{cats[0]}]')
            continue

        # Le banc PORTEUR est le premier apparié, donc celui du métier principal quand il l'est.
        # Si le métier principal n'a pas de banc et qu'un secondaire en a un, c'est ce dernier
        # qui porte l'index : `categorie` et `echelle` le nomment, donc rien n'est masqué —
        # une valeur mesurée et nommée vaut mieux qu'un NULL.
        porteur = bancs[0]
        meta = {'synced_at': timezone.now().isoformat(),
                **({'alias_declare': alias} if alias else {}),
                # Attribution DÉRIVÉE du registre : une source ajoutée s'y cite d'elle-même,
                # au lieu d'être oubliée dans une chaîne figée (l'Arena est sous CC-BY-4.0,
                # l'attribution est une OBLIGATION de licence, pas une politesse).
                'attribution': ' / '.join(s['label'] for s in SOURCES_PAR_PRIORITE),
                'quant_locale': 'score tiers = borne haute (mesuré fp8/16, local souvent Q4)'}
        # Clés À PLAT du banc porteur : la forme d'avant le 2026-09-01, à l'identique. Les
        # consommateurs (`to_dict`, cards, `_rank_key`) ne voient aucune différence.
        meta.update({k: v for k, v in porteur.items() if k != 'valeur'})
        # AJOUT : un banc par métier, chacun avec SON échelle nommée. Toujours présent, même
        # à un seul élément — un consommateur lit `bancs` sans avoir à tester sa présence.
        meta['bancs'] = bancs
        rapport['apparies'].append((m.model_key, porteur['categorie'], porteur['valeur'],
                                    porteur['echelle'], porteur.get('arena_elo')))
        for b in bancs:
            par_echelle.setdefault((b['categorie'], 'confront'), []).append(
                (m, b['valeur'], b.get('arena_elo'), b.get('source')))
        if not dry_run:
            m.benchmark_index = porteur['valeur']
            m.benchmark_meta = meta
            m.save(update_fields=['benchmark_index', 'benchmark_meta'])

    # Confrontation par catégorie : inversions d'ordre AA↔Elo parmi les doubles appariés.
    # Dédoublonnée par PAIRE DE NOMS TIERS (une ligne `proposed:` et sa jumelle téléchargée
    # portent le même appariement — le 1er dry-run imprimait chaque inversion jusqu'à 4×).
    vues = set()
    for (cat, _), lot in par_echelle.items():
        # Seuls les modèles dont l'index vient de la source PRIORITAIRE participent : un index
        # porté par une source de repli comparerait deux échelles, alors que la confrontation
        # exige deux mesures INDÉPENDANTES du même modèle. Lu depuis le registre plutôt
        # qu'écrit « != 'arena' », qui supposait qu'il n'existe jamais que deux sources.
        _primaire = SOURCES_PAR_PRIORITE[0]['nom_source']
        doubles = [(m, v, e) for m, v, e, src in lot
                   if v is not None and e is not None and src == _primaire]
        for i in range(len(doubles)):
            for j in range(i + 1, len(doubles)):
                (m1, a1, e1), (m2, a2, e2) = doubles[i], doubles[j]
                if (a1 - a2) * (e1 - e2) < 0:
                    paire = (cat,) + tuple(sorted((m1.name, m2.name)))
                    if paire not in vues:
                        vues.add(paire)
                        rapport['inversions'].append(
                            f"[{cat}] {m1.name} vs {m2.name} : AA {a1}/{a2} mais Elo {e1}/{e2}")
    return rapport
