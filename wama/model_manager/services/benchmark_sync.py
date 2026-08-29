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

AA_BASE = 'https://artificialanalysis.ai/api/v2'
AA_KEY_ENV = 'ARTIFICIAL_ANALYSIS_API_KEY'
ARENA_DATASET = 'lmarena-ai/leaderboard-dataset'

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
}


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
    """
    prefixe = []
    j = i - 1
    while j >= 0 and re.fullmatch(r'[a-z]{2,}', segments[j]):
        prefixe.insert(0, segments[j])
        j -= 1
    return ''.join(prefixe) + mot


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


def _compatibles(a, b, taille_requise=False):
    """
    Identités appariables : même famille+version ; tailles égales si les DEUX existent.

    `taille_requise` (catégorie LLM) : la taille doit exister DES DEUX CÔTÉS — 1er dry-run
    19/08 : sans elle, `qwen3.5:4b` prenait l'Elo de `qwen3.5-max-preview` et
    `qwen3.8:27b` celui de `qwen3.8-max` (variantes API frontière SANS taille publiée,
    qui ne sont jamais nos poids locaux). Les modalités média gardent la taille optionnelle
    (les modèles image/vidéo n'en publient pas).
    """
    if a is None or b is None or a[0] != b[0] or a[1] != b[1]:
        return False
    if taille_requise and (a[2] is None or b[2] is None):
        return False
    return a[2] is None or b[2] is None or a[2] == b[2]


def _apparier(ident_local, entrees, taille_requise=False):
    """Candidats compatibles, les tailles EXACTES d'abord (jamais un score moyen)."""
    c = [e for e in entrees if _compatibles(ident_local, e['identite'], taille_requise)]
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


# ── Catégorie d'un modèle du catalogue ───────────────────────────────────────────────────

def _categorie_locale(m):
    """Catégorie de benchmark d'une ligne AIModel, depuis sa TÂCHE déclarée (sinon LLM Ollama)."""
    caps = m.capabilities or {}
    tache = (caps.get('task') or '').strip().lower()
    if tache in TACHE_VERS_CATEGORIE:
        return TACHE_VERS_CATEGORIE[tache]
    if m.model_key.startswith(('ollama:', 'proposed:ollama:')):
        # Un modèle d'EMBEDDING n'est pas un LLM de chat : quand les capacités existent
        # (découverte passée), `completion` fait foi — 1er dry-run 19/08 : bge-m3 prenait
        # un Intelligence Index. Lignes `proposed:` sans caps : tolérées (leurs faux
        # appariements meurent par la taille requise en catégorie llm).
        if caps and not caps.get('completion'):
            return None
        return 'llm'
    return None


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


# ── Synchronisation ──────────────────────────────────────────────────────────────────────

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
    for nom, chargeur in (('aa', charger_aa), ('arena', charger_arena)):
        try:
            sources[nom], motifs_cat[nom] = chargeur()
        except SourceIndisponible as e:
            indispo[nom] = str(e)
    if not sources:
        raise SourceIndisponible(' ; '.join(f'{k}: {v}' for k, v in indispo.items()))

    rapport = {'sources': {k: {c: len(v) for c, v in cats.items()} for k, cats in sources.items()},
               'motifs': motifs_cat, 'indisponibles': indispo,
               'apparies': [], 'non_apparies': [], 'sans_categorie': 0, 'inversions': []}

    qs = AIModel.objects.filter(Q(is_downloaded=True) | Q(is_proposed=True)) \
        if inclure_proposes else AIModel.objects.filter(is_downloaded=True)
    par_echelle = {}    # échelle → [(model, valeur, elo)] pour la confrontation

    for m in qs:
        cat = _categorie_locale(m)
        if cat is None:
            rapport['sans_categorie'] += 1
            continue
        alias = ALIAS.get(m.model_key)
        cands_aa, cands_ar = [], []
        if alias:       # confirmation humaine : égalité de slug, aucune heuristique
            cands_aa = _apparier_alias(alias, sources.get('aa', {}).get(cat, []))
            cands_ar = _apparier_alias(alias, sources.get('arena', {}).get(cat, []))
        else:
            idents = _local_identities(m)
            stricte = (cat == 'llm')  # cf. _compatibles : jamais une variante frontière sans taille
            for ident in idents:
                cands_aa = _apparier(ident, sources.get('aa', {}).get(cat, []), stricte)
                cands_ar = _apparier(ident, sources.get('arena', {}).get(cat, []), stricte)
                if cands_aa or cands_ar:
                    break
        if not cands_aa and not cands_ar:
            if idents:      # identifiable mais absent des leaderboards : tracé, pas un échec
                rapport['non_apparies'].append(f'{m.model_key} [{cat}]')
            continue

        meta = {'synced_at': timezone.now().isoformat(), 'categorie': cat,
                **({'alias_declare': alias} if alias else {}),
                'attribution': 'Artificial Analysis (Data API) / Arena leaderboard-dataset CC-BY-4.0',
                'quant_locale': 'score tiers = borne haute (mesuré fp8/16, local souvent Q4)'}
        valeur = echelle = None
        if cands_aa:
            # La variante qui CORRESPOND, pas la mieux notée (cf. `_choose_variant`).
            retenu = _choose_variant(m.name or m.model_key, cands_aa,
                                       lambda e: e['valeur'])
            valeur, echelle = retenu['valeur'], retenu['echelle']
            meta.update({'source': 'artificial-analysis', 'aa_nom': retenu['nom'],
                         'aa_slug': retenu['slug'],
                         'aa_variantes': [(e['nom'], e['valeur']) for e in cands_aa]})
            if retenu.get('sous_indices'):
                meta['sous_indices'] = retenu['sous_indices']
        arena_elo = None
        if cands_ar:
            best = _choose_variant(m.name or m.model_key, cands_ar, lambda e: e['elo'])
            arena_elo = best['elo']
            meta.update({'arena_nom': best['nom'], 'arena_elo': best['elo'],
                         'arena_votes': best['votes']})
            if valeur is None:      # AA absent : l'Elo Arena PORTE l'index, échelle nommée
                valeur, echelle = best['elo'], f'arena_elo_{CATEGORIES[cat]["arena"]}'
                meta['source'] = 'arena'
        meta['echelle'] = echelle
        rapport['apparies'].append((m.model_key, cat, valeur, echelle, arena_elo))
        par_echelle.setdefault((cat, 'confront'), []).append(
            (m, valeur, arena_elo, meta.get('source')))
        if not dry_run:
            m.benchmark_index = valeur
            m.benchmark_meta = meta
            m.save(update_fields=['benchmark_index', 'benchmark_meta'])

    # Confrontation par catégorie : inversions d'ordre AA↔Elo parmi les doubles appariés.
    # Dédoublonnée par PAIRE DE NOMS TIERS (une ligne `proposed:` et sa jumelle téléchargée
    # portent le même appariement — le 1er dry-run imprimait chaque inversion jusqu'à 4×).
    vues = set()
    for (cat, _), lot in par_echelle.items():
        # Seuls les modèles dont l'index vient d'AA participent (un index-repli Arena
        # comparerait deux échelles — la confrontation exige deux mesures INDÉPENDANTES).
        doubles = [(m, v, e) for m, v, e, src in lot
                   if v is not None and e is not None and src != 'arena']
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
