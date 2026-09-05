"""external_sources — registre DÉCLARATIF des sources externes joignables par WAMA.

Ajouter une plateforme = **une entrée ici**. Avant le 2026-09-01, chaque source vivait dans le
fichier qui la consommait ; personne ne pouvait répondre à « à quoi WAMA se connecte-t-il ? »
autrement qu'en fouillant le dépôt. Idée de Fabien (01/09), les trois étapes livrées le jour même
(déclaration commune, migration des consommateurs, registre catalogué + page).

⚠ CE QUI SE DÉCLARE ICI : l'identité, l'adresse de base, le réglage qui la surcharge, la
variable portant la clé d'API, la PORTÉE (service local ou Internet — donc le traitement du
proxy), l'attribution quand une licence l'oblige.

⚠ CE QUI NE SE DÉCLARE PAS : le CLIENT. Chaque plateforme a sa forme — Artificial Analysis rend
du JSON authentifié, l'Arena un parquet HuggingFace, Ollama du HTML scrapé. Un « chargeur
générique paramétré depuis l'écran » serait à la fois fragile et une surface de requête
arbitraire côté serveur. Le parseur reste chez le consommateur ; seule son ADRESSE vient d'ici.
C'est la ligne écrite dans `benchmark_sync.SOURCES` (registre SŒUR, cf. plus bas) — elle vaut ici.

L'étape 3 (le registre catalogué `sources_externes`, nature `mesure`) vit en bas de ce module :
`probe_all()` SONDE chaque source — clé posée ? service joignable ? — et écrit son rapport dans
`logs/external_sources_report.json`. La valeur de la page est dans la sonde : un inventaire pur
n'aurait aucun bouton, la doctrine des registres le refuse.

── Ce que la mesure du 2026-09-01 a trouvé, et qui motive la brique ────────────────────────

Le handoff annonçait « 9 sources dans 7 fichiers ». Le relevé exhaustif en donne **une
vingtaine**, et surtout le défaut n'était pas seulement la dispersion, c'était la DUPLICATION :

  • `http://127.0.0.1:11434` écrit **10 fois**, dont 8 sous la forme
    `getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434')` — or `settings.py` pose
    TOUJOURS cet attribut : ces 8 replis sont MORTS. Un repli qui ne se déclenche jamais est
    une fausse sécurité, et le jour où il se déclencherait il divergerait du réglage.
  • `_LJ_BASE` (échantillons ljspeech) recopié **3 fois** à l'identique.
  • `TTS_SERVICE_URL` et `WAMA_UI_SMOKE_BASE` : défaut redéclaré chez chaque appelant.

── PÉRIMÈTRE : les sources configurées par le SERVEUR ───────────────────────────────────────

Ce registre couvre les sources dont la configuration appartient à l'installation (variable
d'environnement, réglage Django). Il NE couvre PAS les connecteurs de `media_library`
(wikimedia, pixabay, pexels, openverse, jamendo, freesound) : leur clé est une donnée **par
utilisateur, stockée en base** (`MediaProvider` + `MediaProviderConfig`), avec sa propre UI de
saisie et son propre contrat de provider (`media_library/providers/base.py`).

⚠ Les y rapatrier aurait été **uniformiser ce qui n'est pas pareil** — une perte d'information
déguisée en centralisation. Une clé de serveur et une clé d'utilisateur ne se sondent pas, ne
se posent pas et ne se révoquent pas de la même façon.

── Registres VOISINS, volontairement distincts ──────────────────────────────────────────────

  • `benchmark_sync.SOURCES` déclare comment LIRE un banc (priorité, échelle, méta). Il parle
    de mesure, pas de connectivité — il devient CONSOMMATEUR d'ici pour ses adresses.
  • `http_proxy` reste la plomberie du proxy ; `proxies_for()` ci-dessous ne fait que choisir
    entre ses deux gestes d'après la portée déclarée, au lieu de laisser chaque appelant deviner.
  • `ollama_host.ollama_base()` reste le résolveur SPÉCIALISÉ d'Ollama : il porte en plus la
    réécriture WSL2 → passerelle Windows, que rien de générique ne saurait faire.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

#: Portées. `LOCAL` = service tournant sur la machine (ou l'hôte) : le proxy doit être
#: NEUTRALISÉ, sans quoi il répond sa page d'erreur HTML à la place du service (incident
#: mesuré le 2026-08-31 sur le TTS : 90 s de repli en-process et de la VRAM prise côté web,
#: alors que le service répondait parfaitement). `OUTBOUND` = Internet, à travers le proxy UGE.
LOCAL = 'local'
OUTBOUND = 'outbound'

#: TYPES de source — ce à quoi elle SERT. Jusqu'au 2026-09-02 cette famille n'existait que
#: dans les commentaires de séparation de `SOURCES` (« Services locaux », « Bancs de
#: performance »…) : la page ne pouvait donc filtrer que par PORTÉE (locale/sortante), un axe
#: technique qui ne dit rien de l'usage. Une famille lisible uniquement dans le code est une
#: facette perdue pour l'écran. Clé = valeur de `data-f-type` ; libellé = option du select.
KINDS = {
    'service':   'Service local',
    'catalogue': 'Catalogue de modèles',
    'banc':      'Banc de performance',
    'poids':     'Outillage et poids',
    'audit':     'Audit de sécurité',
    'recherche': 'Recherche web',
}


@dataclass(frozen=True)
class ExternalSource:
    """Une source externe : ce qu'elle est et comment on l'adresse — jamais comment on la lit."""

    key: str
    #: Nom lisible — sert aux écrans et aux attributions.
    label: str
    #: Adresse de base par DÉFAUT. Surchargée par `setting` puis `env` (cf. `base_url`).
    base: str
    #: Une ligne : à quoi elle sert dans WAMA.
    usage: str
    #: Clé de `KINDS` — la famille d'USAGE (facette « Type » de la page).
    kind: str = 'poids'
    #: `LOCAL` ou `OUTBOUND` — décide du traitement du proxy, jamais laissé à l'appelant.
    scope: str = OUTBOUND
    #: Réglage Django qui surcharge `base` (prioritaire sur `env`).
    setting: str = ''
    #: Variable d'environnement qui surcharge `base` quand aucun réglage Django ne la porte.
    env: str = ''
    #: Variable d'environnement portant la clé d'API. '' = source anonyme.
    api_key_env: str = ''
    #: Attribution EXIGÉE par la licence de la source. Une obligation, pas une politesse.
    attribution: str = ''
    #: Document portant l'intention, quand elle est écrite quelque part.
    doc: str = ''


#: ⚠ ORDRE : par famille, pour la lecture. Aucun code ne dépend de l'ordre.
SOURCES: tuple[ExternalSource, ...] = (
    # ── Services LOCAUX ─────────────────────────────────────────────────────────────────
    ExternalSource(
        'ollama', 'Ollama (hôte)', 'http://127.0.0.1:11434',
        "Moteur LLM local — assistant, describer, reader, prospection de modèles",
        kind='service', scope=LOCAL, setting='OLLAMA_HOST', env='OLLAMA_HOST',
        doc='INFRA_WSL_VS_WINDOWS.md'),
    ExternalSource(
        'tts_service', 'Service TTS WAMA', 'http://localhost:8001',
        "Vocalisation hors du process web (évite de charger un modèle dans gunicorn)",
        kind='service', scope=LOCAL, setting='TTS_SERVICE_URL', env='TTS_SERVICE_URL'),
    ExternalSource(
        'wama_self', 'WAMA (cette instance)', 'http://127.0.0.1:8000',
        "WAMA s'interroge lui-même : smoke navigateur, matrice de droits",
        kind='service', scope=LOCAL, env='WAMA_UI_SMOKE_BASE'),

    # ── Catalogues de modèles ───────────────────────────────────────────────────────────
    ExternalSource(
        'ollama_site', 'ollama.com', 'https://ollama.com',
        "Pages publiques du catalogue Ollama — prospection (HTML scrapé)", kind='catalogue'),
    ExternalSource(
        'ollama_registry', "Registre d'images Ollama", 'https://registry.ollama.ai',
        "Manifestes et digests des tags Ollama — désambiguïse une variante par son ARTEFACT",
        kind='catalogue'),
    # `api_key_env` posé le 2026-09-02 : le jeton vivait dans un fichier que personne ne
    # localisait ; `settings.py` le promeut en `HF_TOKEN`, la page peut donc le DIRE.
    ExternalSource(
        'huggingface', 'HuggingFace Hub', 'https://huggingface.co',
        "Poids, datasets et fiches de modèles — source principale du parc ; jeton = dépôts "
        "gated + quota d'API relevé", kind='catalogue', api_key_env='HF_TOKEN'),
    ExternalSource(
        'roboflow', 'Roboflow Universe', 'https://universe.roboflow.com',
        "Fiches de modèles de vision (référence de plateforme, pas de téléchargement)",
        kind='catalogue'),

    # ── Bancs de performance (cf. `benchmark_sync`) ──────────────────────────────────────
    ExternalSource(
        'artificial_analysis', 'Artificial Analysis', 'https://artificialanalysis.ai/api/v2',
        "Indices de performance tiers par modalité — API JSON authentifiée",
        kind='banc', api_key_env='ARTIFICIAL_ANALYSIS_API_KEY',
        attribution='Artificial Analysis',
        doc='wama/model_manager/PROSPECTION_PIPELINE.md'),
    ExternalSource(
        'arena', 'LMArena (leaderboard-dataset)', 'https://huggingface.co',
        "Scores Elo par préférence humaine — parquet publié sur le Hub",
        kind='banc', attribution='Arena (leaderboard-dataset, CC-BY-4.0)',
        doc='wama/model_manager/PROSPECTION_PIPELINE.md'),
    # 2026-09-02 : 3ᵉ banc, le premier hors génération — la TRANSCRIPTION (WER, plus bas =
    # mieux). Choisi parce que ses résultats sont des CSV publics sur le Hub, avec un fichier
    # PAR LANGUE (dont le français — le seul banc tiers qui mesure ce que le transcriber fait
    # ici). ⚠ La licence des CSV de résultats n'est pas énoncée par le dépôt (les corpus
    # sous-jacents vont de CC0 à CC-BY-NC-ND) : on cite la source, on ne redistribue rien.
    ExternalSource(
        'open_asr', 'Open ASR Leaderboard (Hugging Face)', 'https://huggingface.co',
        "WER par modèle de transcription (anglais + français) — CSV publiés sur le Hub",
        kind='banc', attribution='Open ASR Leaderboard (Hugging Face, hf-audio)',
        doc='wama/model_manager/PROSPECTION_PIPELINE.md'),

    # 2026-09-02 : 4ᵉ banc — les EMBEDDINGS (le RAG tourne sur bge-m3 sans aucune mesure
    # tierce). Résultats bruts du dépôt `embeddings-benchmark/results` (CC0-1.0) : un JSON par
    # modèle et par tâche, lu sur raw.githubusercontent.com ; l'INDEX des dossiers passe par
    # l'API GitHub (`github_api`, déjà déclarée) parce que `paths.json` du dépôt est périmé
    # (333 modèles sur 685 le 02/09, sans Qwen3-Embedding). Pas de clé : quota anonyme.
    ExternalSource(
        'mteb', 'MTEB — résultats bruts (embeddings-benchmark)', 'https://raw.githubusercontent.com',
        "nDCG@10 par tâche de recherche (jeu FRANÇAIS déclaré) — JSON CC0 lus sur GitHub",
        kind='banc', attribution='MTEB results (embeddings-benchmark/results, CC0-1.0)',
        doc='wama/model_manager/PROSPECTION_PIPELINE.md'),

    # ── Outillage et poids ──────────────────────────────────────────────────────────────
    ExternalSource(
        'github', 'GitHub', 'https://github.com',
        "Poids et échantillons publiés en releases (ultralytics, coqui, "
        "serengil/deepface_models…) — TOUT poids qui n'est pas sur HuggingFace passe par ici",
        kind='poids'),
    ExternalSource(
        'github_api', 'API GitHub', 'https://api.github.com',
        "Liste des releases — résolution de la version d'un poids", kind='poids'),
    ExternalSource(
        'pytorch_download', 'download.pytorch.org', 'https://download.pytorch.org',
        "Roues PyTorch/CUDA — installation de dépendances de modèles", kind='poids'),
    ExternalSource(
        'osv', 'OSV (Open Source Vulnerabilities)', 'https://api.osv.dev/v1',
        "Audit de vulnérabilités des dépendances (contrôle nocturne)",
        kind='audit', doc='PROJECT_STATUS.md'),
    ExternalSource(
        'duckduckgo', 'DuckDuckGo (HTML)', 'https://html.duckduckgo.com/html/',
        "Recherche web de l'assistant — point d'entrée sans clé", kind='recherche'),
)

#: Le dataset Arena, nommé une fois (ce n'est pas une URL : un identifiant de dataset du Hub).
ARENA_DATASET = 'lmarena-ai/leaderboard-dataset'

#: Les datasets de RÉSULTATS de l'Open ASR Leaderboard, nommés une fois — même nature que
#: `ARENA_DATASET`. Le Space lit ces CSV par `snapshot_download` (vérifié dans son `init.py`
#: le 2026-09-02) ; les noms de fichier sont ceux qu'il consomme. Clé = jeu (celle que
#: `benchmark_sync.CATEGORIES` cite), valeur = (dépôt, fichier).
OPEN_ASR_DATASETS = {
    'english_short': ('hf-audio/open-asr-leaderboard-results', 'english_short_latest.csv'),
    'multilingual_fr': ('hf-audio/multilingual_evals', 'multilingual_fr.csv'),
}

#: Le dépôt GitHub des résultats MTEB, nommé une fois (identifiant `owner/repo`, pas une URL).
MTEB_RESULTS_REPO = 'embeddings-benchmark/results'


def by_key() -> dict[str, ExternalSource]:
    return {s.key: s for s in SOURCES}


_BY_KEY = by_key()


def get(key: str) -> ExternalSource:
    """La source déclarée. `KeyError` explicite : une clé inconnue est un défaut de code."""
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(
            f"source externe inconnue : {key!r}. Déclarées : {', '.join(sorted(_BY_KEY))}"
        ) from None


def base_url(key: str) -> str:
    """Adresse EFFECTIVE : réglage Django, puis variable d'environnement, puis défaut déclaré.

    Sans barre finale — les appelants concatènent leur chemin.

    ⚠ Le défaut déclaré ne vit QU'ICI. C'est tout l'objet de la brique : un `getattr(settings,
    'OLLAMA_HOST', 'http://127.0.0.1:11434')` recopié chez huit appelants promet un repli qui
    ne se déclenche jamais, et qui divergerait le jour où il se déclencherait.
    """
    src = get(key)
    val = ''
    if src.setting:
        try:
            from django.conf import settings
            val = getattr(settings, src.setting, '') or ''
        except Exception:
            val = ''
    if not val and src.env:
        val = os.environ.get(src.env, '') or ''
    return (val or src.base).rstrip('/')


def proxies_for(key: str):
    """`proxies` à passer à `requests`, choisis d'après la PORTÉE déclarée.

    L'appelant n'a plus à savoir si sa source est locale : c'est une propriété de la source.
    Neutralise le proxy pour un service local, l'emprunte pour une source Internet.
    """
    from wama.common.utils.http_proxy import local_proxies, outbound_proxies
    return local_proxies() if get(key).scope == LOCAL else outbound_proxies()


def api_key(key: str) -> str:
    """Clé d'API lue dans l'environnement, ou '' — jamais une exception : une source sans clé
    se SKIPPE avec un motif, elle ne fait pas tomber l'appelant."""
    src = get(key)
    return os.environ.get(src.api_key_env, '') if src.api_key_env else ''


def is_configured(key: str) -> bool:
    """La source est-elle utilisable en l'état ? (clé posée si elle en exige une)

    ⚠ Ne dit RIEN de sa joignabilité — sonder appartient à l'étape 3 (page en nature `mesure`).
    Une source anonyme est toujours « configurée » ; cela ne veut pas dire qu'elle répond.
    """
    src = get(key)
    return bool(api_key(key)) if src.api_key_env else True


def attributions() -> tuple[str, ...]:
    """Attributions exigées par les licences des sources qui en portent une.

    DÉRIVÉE du registre, jamais écrite en dur : une source ajoutée se cite d'elle-même. L'Arena
    est sous CC-BY-4.0 — l'attribution est une obligation, pas une politesse, et une chaîne
    figée quelque part est une chaîne qu'on oubliera de mettre à jour.
    """
    return tuple(s.attribution for s in SOURCES if s.attribution)


# ── La SONDE (étape 3) — ce que le bouton « Actualiser » de la page mesure ──────────────────

#: Court à dessein : la sonde répond « joignable ? », pas « performant ? ». Un service local qui
#: met 5 s à répondre est déjà une information — la latence est relevée à part.
PROBE_TIMEOUT_S = 5.0


def _probe_url(key: str) -> str:
    """Adresse EFFECTIVEMENT sondée. Pour Ollama, le résolveur spécialisé : sonder `127.0.0.1`
    depuis WSL2 dirait « injoignable » d'un service qui tourne — le mensonge exact que la
    réécriture vers la passerelle Windows existe pour empêcher."""
    if key == 'ollama':
        from wama.common.utils.ollama_host import ollama_base
        return ollama_base()
    return base_url(key)


def probe(key: str, timeout: float = PROBE_TIMEOUT_S) -> dict:
    """Sonde UNE source : clé posée ? adresse joignable ? en combien de temps ?

    « Joignable » = le serveur a RÉPONDU en HTTP, quel que soit le statut : un 403 (tier d'API),
    un 404 (pas de page à la racine) ou un 405 prouvent autant la joignabilité qu'un 200 — seul
    un échec de connexion ou un délai expiré dit le contraire. Exiger `200` ferait accuser de
    panne des sources en parfaite santé dont la racine n'est simplement pas une page.

    ⚠ La sonde ne suit PAS les redirections et ne lit PAS le corps (`stream=True`, fermé
    aussitôt) : elle prouve la connectivité, elle ne télécharge rien.
    """
    import time as _time

    import requests

    out = {'key': key, 'url': _probe_url(key), 'configured': is_configured(key),
           'reachable': None, 'status': None, 'latency_ms': None, 'error': ''}
    t0 = _time.monotonic()
    try:
        r = requests.get(out['url'], timeout=timeout, proxies=proxies_for(key),
                         stream=True, allow_redirects=False)
        out['reachable'] = True
        out['status'] = r.status_code
        r.close()
    except requests.RequestException as e:
        out['reachable'] = False
        out['error'] = f"{type(e).__name__}: {str(e)[:160]}"
    out['latency_ms'] = round((_time.monotonic() - t0) * 1000)
    return out


def report_path():
    from django.conf import settings
    from pathlib import Path
    return Path(settings.BASE_DIR) / 'logs' / 'external_sources_report.json'


def probe_all(write: bool = False) -> dict:
    """Sonde TOUTES les sources déclarées, et écrit le rapport si demandé.

    Tourne en Celery (nature `mesure` du registre `sources_externes`) : une quinzaine de
    requêtes réseau, même courtes, n'ont rien à faire dans un worker web.
    """
    import datetime
    import json

    results = [probe(s.key) for s in SOURCES]
    counts = {
        'total': len(results),
        'reachable': sum(1 for r in results if r['reachable']),
        'unreachable': sum(1 for r in results if r['reachable'] is False),
        'unconfigured': sum(1 for r in results if not r['configured']),
    }
    rapport = {'generated_at': datetime.datetime.now().isoformat(timespec='seconds'),
               'counts': counts, 'results': results}
    if write:
        p = report_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding='utf-8')
    return rapport


def last_report() -> dict | None:
    """Le dernier rapport ÉCRIT, ou None — la page l'affiche sans jamais sonder elle-même."""
    import json
    try:
        return json.loads(report_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
