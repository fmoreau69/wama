"""
Signal qualité « BENCHMARK TIERS CONFRONTÉ » — 2e étage de l'échelle des signaux.

    a priori (model_quality.py)  <  benchmark tiers confronté (ICI)  <  mesure interne

POURQUOI (décision Fabien 2026-08-19). L'indice a priori est structurel (paramètres, contexte,
quantification) : il s'est trompé deux fois de suite sur le catalogue réel — « MoE = ses totaux »
classait qwen3.6:35b devant qwen3.8 ; la révision √(totaux×actifs) corrige heavy mais sur-pénalise
la sparsité extrême (AA mesure qwen3.6:35b-A3B à 43, DEVANT Gemma4 31B à 39). Une mesure TIERCE
et indépendante tranche mieux qu'un a priori raffiné à l'infini.

DEUX SOURCES, CONFRONTÉES (l'une ne suffit pas — d'où « confronté ») :
  • Artificial Analysis — Intelligence Index composite, MESURÉ par eux (pas auto-déclaré).
    Data API publique, clé gratuite (1 000 req/j) : `ARTIFICIAL_ANALYSIS_API_KEY` dans `.env`.
    C'est LA valeur de `benchmark_index` (une seule échelle — jamais de mélange).
  • Arena (ex-LMArena) — Elo des votes humains. Pas d'API publique : miroir JSON quotidien
    MIT `oolong-tea-2026/arena-ai-leaderboards`. Stocké EN META (échelle différente), sert à
    la confrontation : une inversion d'ordre AA↔Elo sur nos appariés est SIGNALÉE, pas arbitrée.

GARDE-FOUS (hérités de la couche manifestes / du catalogue) :
  • Null plutôt que plausible : un modèle non apparié reste à NULL — jamais de score deviné.
  • Appariement CONSERVATEUR : famille+version (`ollama_registry.decomposer`) ET taille en
    milliards exactes des deux côtés ; l'ambiguïté (variantes Reasoning…) retient la mieux
    notée et TRACE le choix en meta (`aa_variantes`).
  • Champ SÉPARÉ de `quality_index` : `sync_models` (découverte) n'écrit jamais ici — la
    tension « valeur posée écrasée par le beat » (18/08) est structurellement impossible.
  • AA mesure des endpoints fp8/fp16 ; nos GGUF sont souvent Q4 → le score est une BORNE
    HAUTE, tracé `quant_locale` en meta.
"""
from __future__ import annotations

import logging
import os
import re

from .ollama_registry import decomposer, _milliards

logger = logging.getLogger(__name__)

AA_URL = 'https://artificialanalysis.ai/api/v2/data/llms/models'
ARENA_RAW = ('https://raw.githubusercontent.com/oolong-tea-2026/'
             'arena-ai-leaderboards/main/data/latest.json')
AA_KEY_ENV = 'ARTIFICIAL_ANALYSIS_API_KEY'


class SourceIndisponible(Exception):
    """Réseau/clé/format absents — la source est SKIPPÉE, jamais un score partiel inventé."""


# ── Normalisation d'identité (les deux côtés parlent des noms différents) ────────────────

def _identite(texte: str):
    """
    'qwen3.6:35b' / 'qwen3-6-35b-a3b' / 'Qwen3.6 35B A3B' / 'Gemma 4 31B'
        → ('qwen', (3, 6), 35.0) · ('gemma', (4,), 31.0) · … ou None.

    Famille+version par `decomposer` (la brique du « successeur de famille »), étendue aux
    deux formes que l'aplatissement des noms tiers produit : version COLLÉE ('gemma4'),
    version en SEGMENTS ('gemma-4', 'qwen3-6') ; taille = premier jeton `<n>b`
    (via `_milliards`). Sans taille ou sans version : None — on n'apparie pas ce qu'on ne
    sait pas nommer (les modèles API frontière sans taille sortent naturellement ici).
    """
    plat = re.sub(r'[\s_]+', '-', (texte or '').strip().lower())
    segments = [s for s in re.split(r'[:/-]', plat) if s]
    fam = ver = taille = None
    i = 0
    while i < len(segments):
        seg = segments[i]
        if fam is None:
            d = decomposer(seg)
            if d:
                fam, ver = d
            elif (re.fullmatch(r'[a-z]+', seg) and i + 1 < len(segments)
                  and re.fullmatch(r'\d+(?:\.\d+)*', segments[i + 1])):
                fam = seg
                i += 1
                ver = tuple(int(x) for x in segments[i].split('.'))
            if fam is not None:
                # fragments de version dispersés par l'aplatissement : 'qwen3-6' → (3,)+(6,)
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
    if not fam or not ver or taille is None:
        return None
    return fam, ver, taille


def _http_json(url: str, headers: dict | None = None, timeout: int = 30):
    import requests
    r = requests.get(url, headers=headers or {}, timeout=timeout)  # trust_env : proxy UGE honoré
    r.raise_for_status()
    return r.json()


# ── Sources ──────────────────────────────────────────────────────────────────────────────

def charger_aa():
    """Entrées AA : [{'nom', 'slug', 'index', 'identite'}]. SourceIndisponible si clé/réseau."""
    cle = os.environ.get(AA_KEY_ENV, '').strip()
    if not cle:
        raise SourceIndisponible(
            f"clé absente ({AA_KEY_ENV} dans .env — gratuite : artificialanalysis.ai/data-api)")
    try:
        data = _http_json(AA_URL, headers={'x-api-key': cle})
    except Exception as e:
        raise SourceIndisponible(f"Artificial Analysis injoignable : {e}")
    out = []
    for m in (data.get('data') or []):
        idx = (m.get('evaluations') or {}).get('artificial_analysis_intelligence_index')
        ident = _identite(m.get('slug') or m.get('name') or '')
        if idx is None or ident is None:
            continue        # null plutôt que plausible : sans score ou sans identité, on passe
        out.append({'nom': m.get('name', ''), 'slug': m.get('slug', ''),
                    'index': float(idx), 'identite': ident})
    if not out:
        raise SourceIndisponible("réponse AA vide ou illisible (format changé ?)")
    return out


def charger_arena():
    """Entrées Arena (leaderboard texte) : [{'nom', 'elo', 'votes', 'identite'}]."""
    try:
        latest = _http_json(ARENA_RAW)
        # `latest.json` est un pointeur OU un snapshot complet selon les versions du miroir.
        if 'models' not in latest:
            date = latest.get('date') or latest.get('latest') or ''
            latest = _http_json(ARENA_RAW.replace('latest.json', f'{date}/text.json'))
        modeles = latest.get('models') or []
    except Exception as e:
        raise SourceIndisponible(f"miroir Arena injoignable : {e}")
    out = []
    for m in modeles:
        ident = _identite(m.get('model') or '')
        if m.get('score') is None or ident is None:
            continue
        out.append({'nom': m.get('model', ''), 'elo': int(m['score']),
                    'votes': m.get('votes'), 'identite': ident})
    if not out:
        # Constaté au 1er run (19/08) : le miroir ne publie que le TOP-20 frontière (modèles
        # API sans jeton de taille) — aucun de nos open-weights locaux n'y figure. Skipper
        # avec le motif EXACT ; la source complète, si le besoin se confirme, est le dataset
        # HF officiel `lmarena-ai/leaderboard-dataset` (consigné, non branché).
        raise SourceIndisponible(
            f"couverture insuffisante : {len(modeles)} entrées (top frontière), "
            "aucune à identité appariable — source complète = dataset HF "
            "lmarena-ai/leaderboard-dataset (non branché)")
    return out


# ── Appariement + écriture ───────────────────────────────────────────────────────────────

def _apparier(ident_local, entrees):
    """Entrées de MÊME identité (famille+version+taille exactes). Liste, jamais un score moyen."""
    return [e for e in entrees if e['identite'] == ident_local]


def synchroniser(dry_run: bool = False):
    """
    Apparie chaque LLM Ollama téléchargé du catalogue aux deux sources et écrit
    `benchmark_index` (échelle AA uniquement) + `benchmark_meta` (traçabilité + Elo).
    Retourne un rapport dict ; lève SourceIndisponible si AUCUNE source n'est joignable.
    """
    from django.utils import timezone
    from wama.model_manager.models import AIModel

    sources, indispo = {}, {}
    for nom, chargeur in (('aa', charger_aa), ('arena', charger_arena)):
        try:
            sources[nom] = chargeur()
        except SourceIndisponible as e:
            indispo[nom] = str(e)
    if not sources:
        raise SourceIndisponible(' ; '.join(f'{k}: {v}' for k, v in indispo.items()))

    rapport = {'sources': {k: len(v) for k, v in sources.items()},
               'indisponibles': indispo, 'apparies': [], 'non_apparies': [], 'inversions': []}
    apparies = []   # (model, index_aa, elo) pour la confrontation

    for m in AIModel.objects.filter(model_key__startswith='ollama:', is_downloaded=True):
        nom_local = m.model_key.split(':', 1)[1]
        ident = _identite(nom_local)
        if ident is None:       # tag sans taille ('latest') : demander sa vraie taille à Ollama
            ident = _identite(_tag_reel(nom_local) or '')
        if ident is None:
            rapport['non_apparies'].append(f'{nom_local} (identité indéterminable)')
            continue

        cands_aa = _apparier(ident, sources.get('aa', []))
        cands_ar = _apparier(ident, sources.get('arena', []))
        if not cands_aa and not cands_ar:
            rapport['non_apparies'].append(nom_local)
            continue

        meta = {'synced_at': timezone.now().isoformat(), 'identite': list(ident),
                'quant_locale': 'gguf (score tiers = borne haute, mesuré fp8/16)'}
        index_aa = None
        if cands_aa:
            retenu = max(cands_aa, key=lambda e: e['index'])   # variante la mieux notée, tracée
            index_aa = retenu['index']
            meta.update({'source': 'artificial-analysis', 'aa_nom': retenu['nom'],
                         'aa_slug': retenu['slug'],
                         'aa_variantes': [(e['nom'], e['index']) for e in cands_aa]})
        if cands_ar:
            best = max(cands_ar, key=lambda e: e['elo'])
            meta.update({'arena_nom': best['nom'], 'arena_elo': best['elo'],
                         'arena_votes': best['votes']})
        rapport['apparies'].append((nom_local, index_aa, meta.get('arena_elo')))
        apparies.append((m, index_aa, meta.get('arena_elo')))
        if not dry_run:
            m.benchmark_index = index_aa      # échelle AA seule ; Arena reste en meta
            m.benchmark_meta = meta
            m.save(update_fields=['benchmark_index', 'benchmark_meta'])

    # Confrontation : inversions d'ordre AA↔Elo parmi les appariés aux DEUX sources.
    doubles = [(m, a, e) for m, a, e in apparies if a is not None and e is not None]
    for i in range(len(doubles)):
        for j in range(i + 1, len(doubles)):
            (m1, a1, e1), (m2, a2, e2) = doubles[i], doubles[j]
            if (a1 - a2) * (e1 - e2) < 0:
                rapport['inversions'].append(
                    f"{m1.name} vs {m2.name} : AA {a1}/{a2} mais Elo {e1}/{e2}")
    return rapport


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
