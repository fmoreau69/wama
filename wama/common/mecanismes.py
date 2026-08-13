"""
Registre DÉCLARATIF des mécanismes transversaux de WAMA.

POURQUOI ICI ET PAS DANS UN `.md`. WAMA génère déjà son UI depuis les métadonnées des éléments
plutôt que de l'écrire à la main ; la documentation obéit à la même règle. Le registre est donc
la SOURCE, et `WAMA_MECANISMES.md` n'en est que le rendu — régénéré par `doc_facts`, donc
incapable de dériver. L'inverse (une table tenue à la main dans un `.md`) est précisément ce qui
a produit `docs/PRECISION_MODE.md`, qui annonçait un seuil de 65 quand le code disait 50.

CE QU'ON DÉCLARE, ET CE QU'ON NE DÉCLARE PAS
  • ici : l'IDENTITÉ d'un mécanisme — à quoi il sert, où il habite, quel document porte son
    intention. Une ligne, stable, qui ne redit rien de ce que le document explique.
  • ailleurs : le POURQUOI, les décisions, les pièges. Ils restent dans le `.md` de référence.
    Recopier ici l'intention d'un mécanisme recréerait la redondance qu'on combat.

CE QUE LE CONTRÔLE SAIT DIRE (cf. `doc_facts --check`, fait `mecanismes`) :
  1. un mécanisme dont le DOMICILE a disparu — la carte pointe dans le vide ;
  2. un module de `common/services/` ou `common/utils/` **non déclaré** — « tu as oublié
     de le tracer », qui est la question posée par Fabien le 2026-08-13 ;
  3. un mécanisme **sans consommateur** — brique morte. C'est exactement l'état où sont restés
     `model_coverage.couvrir_classes` (0 consommateur pendant 8 jours, alors qu'il avait été
     extrait pour ça) et `qc.py` (0 aujourd'hui). Ces deux-là ont été trouvés à la main ;
     ce contrôle les aurait signalés seul.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Mecanisme:
    """Un mécanisme transversal : ce qu'il fait, où il vit, qui porte son intention."""

    cle: str
    nom: str
    #: Une ligne. Ce que le mécanisme FAIT, pas comment.
    role: str
    #: Chemin du module qui en est le domicile UNIQUE (relatif à BASE_DIR).
    domicile: str
    #: Document de référence portant l'intention. '' si elle n'est écrite nulle part — et
    #: c'est alors un trou que la carte doit rendre visible, pas masquer.
    doc: str = ''
    #: Modules supplémentaires qui font partie du mécanisme (le domicile reste le point d'entrée).
    annexes: tuple = field(default_factory=tuple)
    #: Symbole à compter quand le domicile est un module PARTAGÉ. Sans lui, un mécanisme logé
    #: dans `common/models.py` hérite du compte de tous les importateurs du module — 138 pour
    #: `ScopedVisibility` alors qu'ils importent surtout `Library` ou `BatchMixin` (mesuré le
    #: 2026-08-13). Le chiffre devenait décoratif ; renseigner le symbole le rend vrai.
    symbole: str = ''


#: ⚠ ORDRE : par domaine, puis alphabétique. La carte est triée à la génération de toute façon.
MECANISMES = (
    # ── Ressources & exécution ────────────────────────────────────────────────────────────
    Mecanisme('resource_governor', 'Gouverneur de ressources',
              "Arbitre GPU/CPU/RAM entre process : réservation, résidence, priorités",
              'wama/common/services/resource_governor.py', 'PROJECT_STATUS.md §0'),
    Mecanisme('task_skeleton', 'Squelette de tâche',
              "Enchaînement commun des tâches Celery d'item : gardes, progress, statuts, ETA",
              'wama/common/utils/task_skeleton.py', 'WAMA_APP_GENERATION_ROUTE.md'),
    Mecanisme('process_control', 'Gardes de process',
              "Anti-boucle-de-crash (redélivrance) et réconciliation des tâches orphelines",
              'wama/common/utils/process_control.py', 'PROJECT_STATUS.md §0'),
    Mecanisme('eta', 'ETA auto-apprenante',
              "Estimation de durée par a-priori puis moyenne mobile, bucketisée par matériel",
              'wama/model_manager/services/eta_estimator.py', 'PROJECT_STATUS.md §10'),
    Mecanisme('nightly_tests', 'Tests nocturnes',
              "Registre déclaratif de scénarios + runner sérialisé VRAM-aware (wired/ui/consistency/…)",
              'wama/common/services/nightly_tests.py', 'PROJECT_STATUS.md §Tests fonctionnels nocturnes',
              annexes=('wama/common/services/ui_smoke.py',)),
    Mecanisme('system_monitor', 'Moniteur système',
              "Mesure unifiée CPU/RAM/GPU/disque (WSL + hôte Windows) — barre de ressources, model manager",
              'wama/common/services/system_monitor.py', ''),

    # ── Modèles ───────────────────────────────────────────────────────────────────────────
    Mecanisme('model_selector', 'Sélection de modèle',
              "Choisit UN modèle : capacités, entrées, priorités, budget VRAM, qualité",
              'wama/model_manager/services/model_selector.py', 'INPUT_MODEL_MATCHING.md'),
    Mecanisme('model_coverage', 'Couverture multi-modèles',
              "Choisit un ENSEMBLE de modèles couvrant des classes (couverture ou spécialisation)",
              'wama/common/services/model_coverage.py', ''),
    Mecanisme('model_quality', 'Indice de qualité a priori',
              "Ordonne les modèles autrement que par la taille (paramètres, contexte, quantif.)",
              'wama/model_manager/services/model_quality.py', ''),
    Mecanisme('bench', 'Banc de comparaison',
              "Mesures comparables par TÂCHE sur un échantillon (latence, sorties, saturation)",
              'wama/model_manager/services/bench.py', ''),
    Mecanisme('provenance', 'Provenance de modèle',
              "Identité chez l'éditeur (licence, auteur, plateforme), posée VIA le manifeste",
              'wama/model_manager/services/provenance.py', '',
              annexes=('wama/model_manager/services/weights_metadata.py',)),
    Mecanisme('prospection', 'Prospection de modèles',
              "Veille déterministe HuggingFace/Ollama + évaluation multi-agents (dry-run)",
              'wama/model_manager/services/prospector.py',
              'wama/model_manager/PROSPECTION_PIPELINE.md'),
    Mecanisme('hf_cache', 'Cache HF scopé',
              "Bascule TEMPORAIRE du cache HuggingFace par backend — anti-fuite d'artefacts inter-apps",
              'wama/common/utils/hf_cache.py', ''),

    # ── Qualité & auto-amélioration ───────────────────────────────────────────────────────
    Mecanisme('run_outcome', "Signaux d'exécution",
              "Journal append-only des FAITS observés sur un résultat (produit/corrigé/relancé…)",
              'wama/common/services/run_outcome.py', 'ROADMAP.md §16.7'),
    Mecanisme('qc', 'Contrôle qualité de sortie',
              "Note une sortie par un validateur LLM INDÉPENDANT ; signal relatif, escalade humaine",
              'wama/common/utils/qc.py', 'ROADMAP.md §16.5'),
    Mecanisme('divergence', 'Divergence inter-systèmes',
              "Désaccord entre deux sorties du même travail — signal objectif, sans avis de modèle",
              'wama/common/services/divergence.py',
              'wama/transcriber/TRANSCRIBER_CORRECTION.md §8.3'),

    # ── Contenu & prompts ─────────────────────────────────────────────────────────────────
    Mecanisme('prompt_pipeline', 'Pipeline de prompts',
              "Traduction/enrichissement centralisés, déclarés par PROMPT_TARGETS",
              'wama/common/utils/prompt_enrichment.py', 'PROMPT_PIPELINE.md',
              annexes=('wama/common/utils/app_metadata.py',
                       'wama/common/utils/prompt_pipeline.py',
                       'wama/common/utils/prompt_skills.py',
                       'wama/common/utils/reference_comprehension.py')),
    Mecanisme('llm', 'Accès LLM',
              "Route unique vers les LLM (tiers déclaratifs, sélection catalogue, Ollama local)",
              'wama/common/utils/llm_utils.py', ''),
    Mecanisme('source_ingest', 'Ingest de source',
              "Télécharge une source distante vers le FileField, déclaré par WAMA_INGEST",
              'wama/common/utils/source_ingest.py', 'WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/utils/url_ingest.py',)),
    Mecanisme('document_export', 'Export document',
              "Génère PDF (fpdf2) / DOCX (python-docx) depuis les résultats d'app",
              'wama/common/utils/document_export.py', ''),

    # ── Manifestes & registres ────────────────────────────────────────────────────────────
    Mecanisme('manifests', 'Manifestes',
              "Extraction/validation/projection des 7 kinds vers les registres",
              'wama/common/manifests/ingest.py', 'WAMA_MANIFEST_ARCHITECTURE.md',
              annexes=('wama/common/services/library_index.py',)),
    Mecanisme('output_formats', 'Formats de sortie',
              "Source commune des formats+qualités de fichier par domaine (réutilise le vocabulaire converter)",
              'wama/common/utils/output_formats.py', ''),
    Mecanisme('license_audit', 'Audit des licences',
              "Vue dérivée : licences+auteurs des 4 registres, traversée par app",
              'wama/common/services/license_audit.py', ''),
    Mecanisme('conformity', 'Grille de conformité',
              "Mesure les 8 facettes F1–F8 des apps par analyse du code réel",
              'wama/common/services/conformity_checker.py', 'WAMA_APP_CONVENTIONS.md'),

    # ── File d'attente & lots ─────────────────────────────────────────────────────────────
    # Déclarés parce que CLAUDE.md les nomme explicitement « ce qui existe déjà dans common/ —
    # à utiliser, ne pas recréer » : ne pas les tracer ici laisserait la carte en dessous des
    # instructions du dépôt.
    Mecanisme('queue_duplication', 'Duplication et suppression sûres',
              "duplicate_instance() et safe_delete_file() — fichiers partagés entre items",
              'wama/common/utils/queue_duplication.py', 'WAMA_APP_CONVENTIONS.md'),
    Mecanisme('batch', 'Import par lot',
              "Parsing des fichiers batch (txt/csv/pdf/docx) et cycle de vie du lot",
              'wama/common/utils/batch_parsers.py', 'BATCH_FORMAT.md',
              annexes=('wama/common/utils/batch_common.py',
                       'wama/common/utils/batch_sync.py',
                       'wama/common/utils/batch_utils.py')),
    Mecanisme('queue_view', 'Tri/filtrage de la file',
              "Tri + filtrage communs de la file unifiée, préférence persistée et PARTAGÉE entre apps",
              'wama/common/utils/queue_view.py', 'CARD_DESIGN.md'),
    Mecanisme('queue_manipulation', 'Manipulation directe de la file',
              "Endpoints génériques : sortir une card d'un batch, réordonner, déplacer, consolider",
              'wama/common/utils/queue_manipulation.py', 'CARD_DESIGN.md §3bis'),
    Mecanisme('console', 'Console utilisateur',
              "Lignes de journal structurées par utilisateur et par app, via Redis",
              'wama/common/utils/console_utils.py', ''),
    Mecanisme('notifications', 'Notifications de tâche',
              "notify_job() — fin de traitement, succès comme échec",
              'wama/common/utils/notifications.py', 'PROFILES_PERMISSIONS.md'),

    # ── UI déclarative ────────────────────────────────────────────────────────────────────
    Mecanisme('param_schema', 'Schéma de paramètres',
              "Source unique des réglages d'app : volet droit et modale sont RENDUS depuis lui",
              'wama/common/utils/param_schema.py', 'WAMA_APP_GENERATION_ROUTE.md'),
    Mecanisme('model_capabilities', 'Vocabulaire des capacités',
              "Canonicalise capabilities (tâche, modalités, entrées) — source du filtrage UI",
              'wama/common/utils/model_capabilities.py', 'INPUT_MODEL_MATCHING.md'),
    Mecanisme('detail_registry', 'Inspecteur — champs de détail',
              "Schéma canonique des infos d'item affichées au volet droit",
              'wama/common/utils/detail_registry.py', 'INSPECTOR_DETAIL_FIELDS.md'),
    Mecanisme('preview', 'Preview unifiée',
              "Registre d'adaptateurs par modèle : la preview des cards vient du commun, pas des apps",
              'wama/common/utils/preview_registry.py', '',
              annexes=('wama/common/utils/preview_utils.py',)),
    Mecanisme('card_chips', 'Chips méta des cards',
              "Chips de l'état concis GÉNÉRÉS du schéma params (chip=True) — jamais écrits par app",
              'wama/common/utils/card_chips.py', 'CARD_DESIGN.md §10.3'),
    Mecanisme('app_modes', 'Domaines → modes',
              "Schéma déclaratif des onglets-domaine et modes par app — scope la file",
              'wama/common/utils/app_modes.py', 'MODES_QUEUE_UX.md'),

    # ── Données & infrastructure ──────────────────────────────────────────────────────────
    Mecanisme('ffmpeg', 'Accès ffmpeg',
              "Résolution centralisée du binaire et des conversions (échappatoire FFMPEG_BINARY)",
              'wama/common/utils/ffmpeg_utils.py', ''),
    Mecanisme('mirror_sync', 'Sauvegarde & tirage',
              "Moteur unique de miroir (modèles, base, médias, secrets) et restauration",
              'wama/common/services/mirror_sync.py', '',
              annexes=('wama/common/services/config_backup.py',
                       'wama/common/services/media_backup.py')),
    Mecanisme('retention', 'Rétention des médias',
              "Purge automatique des sorties au-delà de la durée choisie par l'utilisateur (FileField découverts)",
              'wama/common/services/retention.py', 'PROFILES_PERMISSIONS.md'),
    Mecanisme('audio_decode', 'Décodage audio robuste',
              "Décode l'audio là où torchcodec/torchaudio sont cassés (WSL) : soundfile + repli ffmpeg",
              'wama/common/utils/audio_decode.py', ''),
    Mecanisme('media_probe', 'Sonde média',
              "Durée/codec/dimensions/pages d'un média pour les propriétés de card (via ffmpeg_utils)",
              'wama/common/utils/media_probe.py', ''),
    Mecanisme('video_utils', 'Utilitaires vidéo',
              "Extraction audio des vidéos + téléchargement YouTube/yt-dlp",
              'wama/common/utils/video_utils.py', ''),
    Mecanisme('media_paths', 'Chemins média',
              "Emplacements canoniques des entrées/sorties par app et par utilisateur",
              'wama/common/utils/media_paths.py', ''),
    Mecanisme('scoped_visibility', 'Visibilité et portée',
              "Privé / unité / public : filtrage des lectures, mutations inchangées",
              'wama/common/models.py', 'PROFILES_PERMISSIONS.md',
              symbole='ScopedVisibility'),
    Mecanisme('scoping', 'Accès scopé aux objets',
              "Deux chemins NOMMÉS pour lire un objet partageable depuis une vue (possédé / visible)",
              'wama/common/utils/scoping.py', 'PROFILES_PERMISSIONS.md'),
    Mecanisme('user_settings', 'Réglages utilisateur par app',
              "Persistance cache user_{id}_{app}_{clé} avec défauts déclarés par l'app",
              'wama/common/utils/user_settings.py', ''),
)


#: Modules de `common/` ASSUMÉS utilitaires locaux — PAS des mécanismes transversaux, et pas des
#: oublis non plus : chaque entrée porte sa raison, datée du triage. Le fait `mecanismes` les
#: retire du backlog « non rattachés » ; ce qui y reste est donc VRAIMENT à trancher. Un module
#: assumé qui gagne des consommateurs multi-apps doit repasser en `Mecanisme` (ou en annexe).
ASSUMES_LOCAUX = {
    'wama/common/utils/disk_utils.py': "plomberie disque (1 consommateur common)",
    'wama/common/utils/format_policy.py': "politique de formats de POIDS de modèle — chaîne modèles",
    'wama/common/utils/html_render.py': "rendu HTML→PDF, consommé par le converter seul",
    'wama/common/utils/http_proxy.py': "plomberie proxy UGE (common + model_manager)",
    'wama/common/utils/lang_routing.py': "routage de langue — sera absorbé par le Translator (ROADMAP §10)",
    'wama/common/utils/log_rotation.py': "décalage des journaux au démarrage (politique : on décale, on ne vide pas)",
    'wama/common/utils/mime_utils.py': "détection MIME — helper fin (filemanager/studio)",
    'wama/common/utils/model_locations.py': "chemins de modèles — plomberie model_manager",
    'wama/common/utils/ollama_host.py': "résolution OLLAMA_HOST (hôte Windows depuis WSL2) — plomberie infra",
    'wama/common/utils/onnx_utils.py': "inspection de poids ONNX — plomberie chaîne modèles",
    'wama/common/utils/safetensors_utils.py': "inspection de poids safetensors — plomberie chaîne modèles",
    'wama/common/utils/translator.py': "brique deep-translator — sera absorbée par le Translator (ROADMAP §10)",
    'wama/common/utils/voice_options.py': "pendant VOIX d'output_formats (avatarizer) — promouvoir si adoption s'élargit",
    'wama/common/utils/waveform.py': "rendu de forme d'onde — fusion des 2 renderers encore pendante (REPRISE)",
}


def par_cle() -> dict:
    return {m.cle: m for m in MECANISMES}
