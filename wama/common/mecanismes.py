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
  2. un module de `common/services/`, `common/utils/`, `common/backends/`,
     `model_manager/services/` ou `studio/services/` **non déclaré** — « tu as oublié de le
     tracer », la question posée par Fabien le 2026-08-13 (balayage étendu aux 3 derniers
     dossiers le même jour ; `common/backends/` en dernier, après que Fabien ait demandé où
     vivait le suivi des modèles : le dossier hors balayage ne produisait AUCUN signal, donc
     `BaseModelBackend` — qui alimente tout le suivi — était invisible sans que rien ne l'indique) ;
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
    #: Domaine de rendu de la carte (sous-table). Posé par `_domaine()` — jamais entrée par entrée.
    domaine: str = ''
    # ⚠ CE REGISTRE NE DÉCRIT PAS LES PLUGINS DE VISUALISATION — arbitrage Fabien du
    # 2026-08-19, après une tentative (la mienne) d'ajouter ici un champ `resolu_par` :
    # c'était mélanger deux niveaux qui ne doivent pas cohabiter, et le champ a été RETIRÉ.
    #
    #   • un MÉCANISME est adressé par le DÉVELOPPEUR, au moment d'écrire le code : il
    #     s'importe, il s'appelle par son nom, et sa mesure est l'ADOPTION (grille de
    #     conformité). Une brique très visuelle en reste un (`card_gear`, `media_picker`).
    #   • un PLUGIN de visualisation est chargé par l'UTILISATEUR, À CHAUD, pendant une
    #     session d'analyse (« je veux aussi le cardiaque »). Sa mesure n'est pas l'adoption
    #     mais la COMPATIBILITÉ (types de données acceptés) et la SYNCHRONISATION sur un axe
    #     partagé avec les autres plugins chargés — une propriété de SESSION, pas de code.
    #     Sa finalité première est le monde DATA (modèle BIND) ; son registre vivra donc là,
    #     avec la taxonomie de types (`common/catalog/data_types.py`) et `FUNCTION_CATALOG`.
    #
    # Un plugin pourra RÉUTILISER des mécanismes ; il n'en est pas une espèce.


def _domaine(nom: str, mecanismes: tuple) -> tuple:
    """Pose le domaine sur un groupe d'entrées : le nom du domaine ne s'écrit qu'UNE fois."""
    from dataclasses import replace
    return tuple(replace(m, domaine=nom) for m in mecanismes)


#: ⚠ ORDRE : par domaine (= ordre des sous-tables de la carte) ; alphabétique à la génération.
MECANISMES = (
    *_domaine('Ressources & exécution', (
    Mecanisme('resource_governor', 'Gouverneur de ressources',
              "Arbitre GPU/CPU/RAM entre process : réservation, résidence, priorités",
              'wama/common/services/resource_governor.py', 'PROJECT_STATUS.md §0'),
    Mecanisme('backend_contract', 'Contrat de backend',
              "Cycle de vie commun des porteurs de modèle — ALIMENTATION du gouverneur "
              "(enveloppe load/unload/process à toute profondeur d'héritage) et CAPACITÉS "
              "déclarées par le moteur (supports_*), lues par le catalogue",
              'wama/common/backends/base.py', 'WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/backends/manager.py',),
              # ⚠ `symbole` OBLIGATOIRE ici, et pour une raison différente de `scoped_visibility` :
              # le domicile n'est pas un module partagé, c'est son NOM DE FEUILLE qui est banal.
              # Le repli « import relatif » du compteur (`from …base import`) capturait alors
              # TOUS les `from .base import` du dépôt — 100 consommateurs annoncés au premier
              # rendu, mesuré le 2026-08-13, pour ~25 réels. Même piège pour l'annexe
              # `manager.py`. Règle : domicile au nom générique (base/manager/models/utils) ⇒
              # renseigner le symbole, sinon le chiffre est décoratif.
              symbole='BaseModelBackend'),
    Mecanisme('task_skeleton', 'Squelette de tâche',
              "Enchaînement commun des tâches Celery d'item : gardes, progress, statuts, ETA",
              'wama/common/utils/task_skeleton.py', 'WAMA_APP_GENERATION_ROUTE.md'),
    Mecanisme('task_progress', 'Progression de tâche longue',
              "Avancement d'une tâche Celery HORS file d'items publié dans le cache "
              "(F5-proof) + garde « déjà en cours » vérifiée auprès de Celery ; "
              "pendant navigateur = WamaApp.Poller",
              'wama/common/utils/task_progress.py',
              'wama/model_manager/PROSPECTION_PIPELINE.md'),
    Mecanisme('process_control', 'Gardes de process',
              "Anti-boucle-de-crash (redélivrance) et réconciliation des tâches orphelines",
              'wama/common/utils/process_control.py', 'PROJECT_STATUS.md §0'),
    Mecanisme('memory_manager', 'Mémoire GPU',
              "Garantit la VRAM avant un chargement, la reprend sur les autres modèles, "
              "et réessaie après libération sur erreur CUDA",
              'wama/model_manager/services/memory_manager.py', 'PROJECT_STATUS.md §0',
              annexes=('wama/model_manager/services/memory_monitor.py',
                       'wama/model_manager/services/memory_cleaner.py',
                       'wama/model_manager/services/memory_diagnostics.py')),
    Mecanisme('eta', 'ETA auto-apprenante',
              "Estimation de durée par a-priori puis moyenne mobile, bucketisée par matériel",
              'wama/model_manager/services/eta_estimator.py', 'PROJECT_STATUS.md §10'),
    Mecanisme('nightly_tests', 'Tests nocturnes',
              "Registre déclaratif de scénarios + runner sérialisé VRAM-aware (wired/ui/consistency/…)",
              'wama/common/services/nightly_tests.py', 'PROJECT_STATUS.md §Tests fonctionnels nocturnes',
              annexes=('wama/common/services/ui_smoke.py',
                       'wama/common/services/rights_matrix.py',
                       'wama/common/nightly_scenarios.py')),
    Mecanisme('system_monitor', 'Moniteur système',
              "Mesure unifiée CPU/RAM/GPU/disque (WSL + hôte Windows) — barre de ressources, model manager",
              'wama/common/services/system_monitor.py', '',
              annexes=('wama/common/static/common/js/system-stats.js',)),
    Mecanisme('tts_service_client', 'Client du service TTS',
              "L'appel POST /tts UNIQUE vers le microservice TTS (payload contractuel, 503 "
              "« loading » → TTSServiceLoadingError, WAV temporaire ou bytes) ; les POLITIQUES "
              "(retry Celery, chunking, replis) restent aux appelants — extrait 2026-08-28 : "
              "4 exemplaires vivaient dans le dépôt, un seul détectait le 503",
              'wama/common/tts/service_client.py', 'MODES_QUEUE_UX.md §2bis'),

    )),

    *_domaine('Modèles', (
    Mecanisme('model_selector', 'Sélection de modèle',
              "Choisit UN modèle : capacités, entrées, priorités, budget VRAM, qualité",
              'wama/model_manager/services/model_selector.py', 'INPUT_MODEL_MATCHING.md'),
    Mecanisme('model_coverage', 'Couverture multi-modèles',
              "Choisit un ENSEMBLE de modèles couvrant des classes (couverture ou spécialisation)",
              'wama/common/services/model_coverage.py', ''),
    Mecanisme('model_quality', 'Indice de qualité a priori',
              "Ordonne les modèles autrement que par la taille (params EFFECTIFS √(totaux×actifs), contexte, quantif.)",
              'wama/model_manager/services/model_quality.py', ''),
    Mecanisme('benchmark_sync', 'Benchmark tiers confronté',
              "Étage 2 qualité (a priori < benchmark < mesure) : AA + Elo Arena appariés au catalogue, prospection incluse",
              'wama/model_manager/services/benchmark_sync.py', 'PROJECT_STATUS.md §REPRISE 2026-08-18',
              annexes=('wama/model_manager/management/commands/sync_benchmarks.py',)),
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
              'wama/model_manager/PROSPECTION_PIPELINE.md',
              annexes=('wama/model_manager/services/prospect_agents.py',
                       'wama/model_manager/services/prospect_ollama.py',
                       'wama/model_manager/services/ollama_registry.py',
                       'wama/model_manager/services/update_checker.py')),
    Mecanisme('model_registry_discovery', 'Découverte de modèles',
              "Découverte unifiée des modèles (apps + sources externes), synchronisée vers le catalogue AIModel",
              'wama/model_manager/services/model_registry.py', '',
              annexes=('wama/model_manager/services/model_sync.py',
                       'wama/model_manager/services/file_watcher.py')),
    Mecanisme('model_installer', 'Installation de modèles',
              "Pipeline accept→download→register : télécharge au bon endroit puis enregistre au catalogue",
              'wama/model_manager/services/model_installer.py', ''),
    Mecanisme('vision_probe', 'Sonde vision',
              "Décrit une image via un modèle multimodal Ollama local (bench, smoke UI, fichiers de référence)",
              'wama/model_manager/services/vision_probe.py', ''),
    Mecanisme('hf_cache', 'Cache HF scopé',
              "Bascule TEMPORAIRE du cache HuggingFace par backend — anti-fuite d'artefacts inter-apps",
              'wama/common/utils/hf_cache.py', ''),

    )),

    *_domaine('Qualité & auto-amélioration', (
    Mecanisme('run_outcome', "Signaux d'exécution",
              "Journal append-only des FAITS observés sur un résultat (produit/corrigé/relancé…)",
              'wama/common/services/run_outcome.py', 'ROADMAP.md §16.7'),
    # `symbole` OBLIGATOIRE ici : un middleware n'est jamais IMPORTÉ, il est nommé par une chaîne
    # pointée dans `settings.MIDDLEWARE`. Sans lui, le scanner (qui compte les imports) le classe
    # « sans consommateur » alors qu'il est actif sur CHAQUE requête — un faux positif qui ferait
    # croire à une brique morte.
    Mecanisme('run_outcome_capture', "Captation générique des gestes",
              "Middleware : telecharge/supprime/relance lus de resolver_match — zéro ligne par app",
              'wama/common/middleware.py', 'WAMA_MEMORY.md §7bis',
              symbole='RunOutcomeCaptureMiddleware'),
    Mecanisme('memory', 'Mémoire & RAG',
              "Souvenirs + fragments sur pgvector, scope hérité de ScopedVisibility ; 5 opérations",
              'wama/common/memory/store.py', 'WAMA_MEMORY.md',
              # ANNEXES et non mécanismes séparés : `embed` (vecteurs), `index` (découpe RAG) et
              # `dev_ai` (reprise de memory.json) n'ont de sens QUE par le magasin — les déclarer
              # à part gonflerait la carte de trois entrées qu'on ne consulte jamais seules.
              # Le domicile reste `store.py`, point d'entrée des 5 opérations.
              annexes=('wama/common/memory/embed.py',
                       'wama/common/memory/index.py',
                       'wama/common/memory/dev_ai.py')),
    Mecanisme('memory_project', 'Projection des faits en souvenirs',
              "RunOutcome → MemoryItem par OBJET (mécanique, sans modèle, idempotente)",
              'wama/common/memory/project.py', 'WAMA_MEMORY.md §7'),
    Mecanisme('filter_bar', 'Barre de filtrage',
              "Recherche + facettes EN DIRECT ; options dérivées du DOM (client) ou déclarées (server)",
              'wama/common/static/common/js/wama-filter-bar.js', 'CARD_DESIGN.md',
              annexes=('wama/common/templates/common/_filter_bar.html',)),
    Mecanisme('journal', "Journal transversal de l'utilisateur",
              "Tout ce qu'il a lancé, toutes apps — DÉRIVÉ de detail_registry, aucune ligne par app",
              'wama/common/services/journal.py', 'WAMA_MEMORY.md §9bis'),
    Mecanisme('rag_geste', "Ajout au RAG (geste explicite)",
              "Bouton dans l'INSPECTEUR + page « Mon RAG » ; texte pris au schéma canonique, "
              "aucune ligne par app. Pas de balayage : l'entrée au RAG est un geste, par décision",
              'wama/common/static/common/js/wama-inspector.js', 'WAMA_MEMORY.md §7ter',
              # Le domicile est le JS : c'est LUI qui rend le geste universel (inspecteur global).
              # Les vues sont l'annexe serveur — la seule porte d'écriture offerte à l'UI.
              annexes=('wama/common/templates/common/rag.html',)),
    Mecanisme('qc', 'Contrôle qualité de sortie',
              "Note une sortie par un validateur LLM INDÉPENDANT ; signal relatif, escalade humaine",
              'wama/common/utils/qc.py', 'ROADMAP.md §16.5'),
    Mecanisme('divergence', 'Divergence inter-systèmes',
              "Désaccord entre deux sorties du même travail — signal objectif, sans avis de modèle",
              'wama/common/services/divergence.py',
              'wama/transcriber/TRANSCRIBER_CORRECTION.md §8.3'),
    # Rattaché le 2026-08-27, en même temps que son extension aux skills : la brique existait
    # depuis longtemps sans figurer sur la carte — donc invisible à qui cherche « qu'est-ce qui
    # contrôle la doc ? ». C'est précisément le trou que ce mécanisme sert à fermer ailleurs.
    Mecanisme('docs_integrity', 'Intégrité doc → code',
              "Vérifie que chaque chemin, ligne et renvoi .md cité par la doc ET par les skills "
              "existe encore ; gate nocturne sur les CIBLES distinctes, pas sur les références",
              'wama/common/management/commands/check_docs.py', 'CLAUDE.md §Fichiers de référence',
              annexes=('wama/common/tests_check_docs.py',),
              symbole='check_docs'),      # nommée par une CHAÎNE, jamais importée — cf. plus bas
    Mecanisme('templates_integrity', 'Intégrité des gabarits',
              "Attrape la famille de fautes qui a récidivé SEPT fois : le commentaire `{# … #}` "
              "MULTI-LIGNE, que le lexer de Django (pas de re.DOTALL) rend en TEXTE littéral — "
              "et le nom de balise avaleuse écrit dans un commentaire. Un scan de 5 s contre des "
              "diagnostics qui ont coûté des sessions",
              'wama/common/management/commands/check_templates.py', 'CLAUDE.md',
              annexes=('wama/common/tests_check_templates.py',),
              symbole='check_templates'),
    # Ces deux-là TOURNENT CHAQUE NUIT (`nightly_scenarios.py:137,145`) et étaient pourtant hors
    # carte — le pire cas : pas une brique morte, une garde active que personne ne trouve en
    # cherchant « qu'est-ce qui contrôle la sécurité ? ». Rattachées le 2026-08-27.
    Mecanisme('dep_vulns', 'Vulnérabilités des dépendances',
              "CVE des paquets INSTALLÉS du venv courant via l'API OSV.dev (pas les requirements, "
              "qui sont des bornes basses). Contrat-cliquet : la dette connue vit dans une "
              "baseline versionnée par venv, toute vulnérabilité nouvelle est rouge",
              'wama/common/management/commands/check_dep_vulns.py', 'ROADMAP.md §16.10',
              symbole='check_dep_vulns'),
    Mecanisme('secret_leaks', 'Fuites de secrets',
              "gitleaks sur l'historique git COMPLET + vérifie que le hook pre-commit est en "
              "place et non dérivé : un hook mort est une garde silencieusement absente, donc "
              "rouge et pas warning",
              'wama/common/management/commands/check_secret_leaks.py', 'ROADMAP.md §16.10',
              symbole='check_secret_leaks'),

    )),

    *_domaine('Contenu & prompts', (
    Mecanisme('prompt_pipeline', 'Pipeline de prompts',
              "Traduction/enrichissement centralisés, déclarés par PROMPT_TARGETS",
              'wama/common/utils/prompt_enrichment.py', 'WAMA_LLM.md',
              annexes=('wama/common/utils/app_metadata.py',
                       'wama/common/utils/prompt_pipeline.py',
                       'wama/common/utils/prompt_skills.py',
                       'wama/common/utils/reference_comprehension.py',
                       'wama/common/static/common/js/wama-prompt-chips.js',
                       'wama/common/static/common/js/wama-prompt-enrich.js')),
    Mecanisme('llm', 'Accès LLM',
              "Route unique vers les LLM (tiers déclaratifs, sélection catalogue, Ollama local)",
              'wama/common/utils/llm_utils.py', ''),
    Mecanisme('assistant_skills', "Skills de rôle de l'assistant",
              "Posture et domaine de l'assistant (science, design, dev) + rappel du "
              "contexte de laboratoire, déclarés par domaine — distinct de l'enrichissement",
              'wama/common/utils/assistant_skills.py', 'ROADMAP.md §19.7'),
    Mecanisme('claude_code', "Claude Code sur abonnement",
              "Délègue une tâche de développement au CLI Claude Code en headless — "
              "lecture seule par défaut, environnement construit sans la clé API",
              'wama/common/services/claude_code.py', 'ROADMAP.md §19.3'),
    Mecanisme('gateway_identity', "Appariement d'identité de canal",
              "Relie une identité Matrix/Discord à un compte WAMA par code prouvé hors "
              "canal — la garde que tout adaptateur appelle avant d'agir",
              'wama/gateway/services.py', 'ROADMAP.md §19',
              annexes=('wama/gateway/models.py',)),
    Mecanisme('assistant_engine', "Moteur de l'assistant IA",
              "Boucle agentique multi-surface (prompts, outils tool_api, local/cloud) — "
              "la vue web et /api/v1/assistant/chat/ en sont des clients",
              'wama/common/services/assistant_engine.py', '',
              symbole='run_assistant_turn'),
    Mecanisme('source_ingest', 'Ingest de source',
              "Télécharge une source distante vers le FileField, déclaré par WAMA_INGEST",
              'wama/common/utils/source_ingest.py', 'WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/utils/url_ingest.py',)),
    # Garde de SORTIE, distincte de l'ingest : l'ingest sait CHERCHER, celle-ci dit OÙ il a le
    # droit d'aller. Séparées parce que tout nouvel appelant réseau doit la traverser, même
    # s'il n'a rien à voir avec WAMA_INGEST.
    Mecanisme('url_guard', 'Garde des URL sortantes',
              "Valide toute cible de téléchargement pilotée par une saisie : schéma, "
              "identifiants, et adresses privées/bouclage/lien-local — anti-SSRF",
              'wama/common/utils/url_guard.py', 'PROFILES_PERMISSIONS.md'),
    Mecanisme('document_export', 'Export document',
              "Génère PDF (fpdf2) / DOCX (python-docx) depuis les résultats d'app",
              'wama/common/utils/document_export.py', ''),

    )),

    *_domaine('Manifestes & registres', (
    Mecanisme('manifests', 'Manifestes',
              "Extraction/validation/projection des 7 kinds vers les registres",
              'wama/common/manifests/ingest.py', 'WAMA_MANIFEST_ARCHITECTURE.md',
              annexes=('wama/common/services/library_index.py',)),
    Mecanisme('output_formats', 'Formats de sortie',
              "Source commune des formats+qualités de fichier par domaine (réutilise le vocabulaire converter)",
              'wama/common/utils/output_formats.py', ''),
    Mecanisme('license_audit', 'Audit des licences',
              "Vue dérivée : licences+auteurs des 4 registres, traversée par app. "
              "Ne voit PAS le code vendorisé (`static/vendors/`, codeformer) — inventorié à "
              "la main dans LICENSING.md §3",
              'wama/common/services/license_audit.py', 'LICENSING.md'),
    Mecanisme('mecanismes_scan', 'Adoption des mécanismes',
              "Qui consomme quoi (imports + briques front), niveau APP vs infrastructure, et "
              "jonction registre↔grille : mécanisme adopté par des apps que rien ne vérifie",
              'wama/common/services/mecanismes_scan.py', 'WAMA_MECANISMES.md'),
    Mecanisme('conformity', 'Grille de conformité',
              "Mesure les 8 facettes F1–F8 des apps par analyse du code réel",
              'wama/common/services/conformity_checker.py', 'WAMA_APP_CONVENTIONS.md'),
    # ⚠ Déclaré ICI et non entre deux groupes : hors d'un `_domaine()` une entrée perd son
    # domaine, donc n'apparaît dans AUCUNE sous-table de la carte — invisible, pas fausse.
    # C'était son état jusqu'au 2026-08-22 (seul cas sur 88, trouvé par `tests_catalogues`).
    Mecanisme('app_sandbox', "Bac à sable d'apps (jumelles exécutables)",
              "Jumelle <app>_NN coexistante pour comparaison Playwright + diff dé-suffixé "
              "(route §10.3 marche S) — registre sandbox_apps.json injecté au boot "
              "(INSTALLED_APPS/urls/gating/catalogue), create/drop symétriques",
              'wama/common/sandbox.py', 'WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/management/commands/app_sandbox.py',)),

    )),

    *_domaine("File d'attente & lots", (
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
                       'wama/common/utils/batch_utils.py',
                       'wama/common/static/common/js/batch-import.js')),
    Mecanisme('queue_view', 'Tri/filtrage de la file',
              "Tri + filtrage communs de la file unifiée, préférence persistée et PARTAGÉE entre apps",
              'wama/common/utils/queue_view.py', 'CARD_DESIGN.md'),
    Mecanisme('queue_manipulation', 'Manipulation directe de la file',
              "Endpoints génériques : sortir une card d'un batch, réordonner, déplacer, consolider",
              'wama/common/utils/queue_manipulation.py', 'CARD_DESIGN.md §3bis'),
    Mecanisme('queue_front', "File d'attente (front)",
              "Comportements communs des files : collapse de batch persisté, focus card, data-wama-*",
              'wama/common/static/common/js/wama-queue.js', 'CARD_DESIGN.md',
              annexes=('wama/common/static/common/js/queue-actions.js',
                       'wama/common/templates/common/_queue_toolbar.html',
                       'wama/common/templates/common/_queue_actions.html',
                       'wama/common/templates/common/_batch_card.html')),
    Mecanisme('queue_entry', "Entrée de file (card seule OU lot)",
              "Décide, pour une entrée de file, si elle s'affiche en card unique ou en card MÈRE "
              "avec ses filles repliables — et rend l'un ou l'autre. Le bloc vivait recopié À "
              "L'IDENTIQUE dans 9 gabarits ; il n'a pu être centralisé (2026-08-25) qu'une fois "
              "deux verrous levés : `is_unitary` adopté (la décision se lit sur le modèle) et "
              "`elem` (les 9 cards filles reçoivent leur élément sous le MÊME nom — avant, 8 "
              "graphies). Signature à 3 paramètres : `card_template`, plus `collapse_prefix` et "
              "`batch_key` pour la seule app à deux files sur une page (enhancer audio). ⚠ Tout "
              "le reste TRAVERSE PAR LE CONTEXTE — les ~9 paramètres de `_batch_card.html` sont "
              "fournis par l'app et passent au travers, sinon la signature atteindrait la "
              "quinzaine. Apparence uniformisée sur le TRANSCRIBER (référence), conforme à "
              "`CARD_DESIGN §11.2` (famille de lot = cyan #0dcaf0) : les 3 couleurs et 2 "
              "habillages qui coexistaient étaient des séquelles d'implémentations successives",
              'wama/common/templates/common/_queue_entry.html', 'CARD_DESIGN.md §11.2',
              annexes=('wama/common/utils/batch_common.py',
                       'wama/common/models.py')),
    Mecanisme('output_naming', 'Nom du fichier de sortie',
              "Une règle unique pour les 8 apps à liaison PRÉCOCE, en deux familles : entrée "
              "FICHIER → `<stem>_<process>_<modèle>[_<i>]<ext>` (l'utilisateur retrouve SON nom, "
              "augmenté de ce qu'on lui a fait et avec quoi) ; entrée PROMPT → "
              "`<process><id>_<modèle>[_<i>]<ext>` (l'identifiant de card remplace le nom absent "
              "et garantit l'unicité dans un `output/` PLAT). Le suffixe `_<i>` n'apparaît QUE "
              "si la card produit plusieurs fichiers — cas réel : `imager.num_images` va de 1 à "
              "4. ⚠ Le mot de process est DÉCLARÉ (`APP_CATALOG['output_tag']`), plus écrit en "
              "dur dans chaque tâche (`blurred`, `enhanced`, `gen`… étaient invisibles à tout "
              "relevé et impossibles à changer sans toucher chaque app). ⚠ `output/` reste PLAT : "
              "c'est le NOM qui porte l'unicité, pas un sous-dossier par card — ce dernier est "
              "précisément ce qui a été démonté le 2026-08-25 (`job_<id>/`, 1,7 Go)",
              'wama/common/utils/output_naming.py', 'MEDIA_STORAGE_TIERING.md',
              annexes=('wama/anonymizer/core/anonymize.py',)),
    Mecanisme('media_integrity', 'Intégrité des médias',
              "Audit MESURÉ de `media/` en 4 états : RÉFÉRENCÉ (une ligne de base pointe "
              "dessus), orphelin, RÉSIDU DE TEST, et RÉFÉRENCÉ MAIS ABSENT — ce dernier étant "
              "celui que personne ne voyait : au 2026-08-25, **33 lignes de base pointent vers "
              "des fichiers inexistants**, et un téléchargement ou un aperçu y échoue sans rien "
              "dire. Signale aussi les fichiers ÉGARÉS hors des emplacements légitimes. "
              "⚠⚠ La méthode exige DEUX signaux indépendants, jamais le nom seul : « orphelin » "
              "seul désignait 3447 fichiers sur 3779 (les sorties de workers ne passent pas par "
              "un FileField), et le nom seul aurait emporté le dépôt manuel d'une utilisatrice. "
              "⚠ Un kind de manifeste `media` a été ÉCARTÉ : `manifests/` est versionné alors "
              "que `media/` porte des données personnelles, et un export serait périmé au "
              "moindre dépôt — un contrôle toujours rouge ne protège plus rien",
              'wama/common/management/commands/check_media_integrity.py',
              # `symbole` OBLIGATOIRE pour une management command, MÊME RAISON que le middleware
              # plus haut : elle n'est jamais IMPORTÉE, elle est nommée par une CHAÎNE
              # (`call_command('check_media_integrity')`, ligne de commande, cron). Le scanner
              # compte les imports, donc il l'annonçait « sans consommateur » — faux positif
              # corrigé le 2026-08-27, en même temps que celui de `docs_integrity`.
              'MEDIA_STORAGE_TIERING.md', symbole='check_media_integrity'),
    Mecanisme('work_dir', 'Dossier de travail jetable',
              "Les fichiers INTERMÉDIAIRES d'un traitement ne vivent pas dans `media/`. Mesuré le "
              "2026-08-25 : `media/avatarizer/` pesait 1,69 Go pour 2101 fichiers dont 99,6 % de "
              "PNG — les frames de CodeFormer, écrites dans le dossier de sortie du job et jamais "
              "nettoyées ; `job_11` portait 1715,7 Mo pour une vidéo de 0,70 Mo. `media/` ne "
              "contient que `<app>/<user>/input|output/` et `users/` (MEDIA_STORAGE_TIERING.md) : "
              "un fichier de travail y est sauvegardé par le miroir, compté par le tiering et "
              "servi par Apache pour rien. Le `with` rend le nettoyage STRUCTUREL au lieu d'être "
              "une convention qu'on oublie. ADOPTÉ par 5 sites (avatarizer/codeformer, "
              "describer/views, enhancer/views, reader/glm_ocr, describer/video_describer) ; "
              "reste `enhancer/tasks.py:534`, déjà nettoyé sur les deux chemins, dont le portage "
              "est une restructuration d'une fonction GPU de 200 lignes. ⚠⚠ L'audit AUTOMATIQUE "
              "des `mkdtemp` a mal classé 2 sites sur 6 — `glm_ocr` déléguait par contrat "
              "DOCUMENTÉ, `enhancer/tasks` nettoyait déjà — mais la lecture site par site a "
              "trouvé l'inverse, des fuites qu'aucun motif ne voyait : un `rmdir` conditionné à "
              "« si le dossier est vide » qui ne se déclenchait donc jamais, un nettoyage placé "
              "APRÈS l'appel qui sautait sur exception, et un `except ImportError` qui empêchait "
              "un repli d'exister. Un relevé par motif oriente ; il ne conclut pas. "
              "Porte aussi `purge_job_dir` : la suppression d'une card doit emporter le dossier du "
              "job — 13 dossiers `job_*` orphelins relevés contre 4 rattachés",
              'wama/common/utils/work_dir.py', 'MEDIA_STORAGE_TIERING.md',
              annexes=('wama/avatarizer/backends/codeformer_backend.py',
                       'wama/avatarizer/views.py')),
    Mecanisme('console', 'Console utilisateur',
              "Lignes de journal structurées par utilisateur et par app. ⚠ Annoncé « via Redis », "
              "mais le chemin Redis exige `django_redis` — ABSENT des deux venvs et des "
              "`requirements` (vérifié 2026-08-22) : la console tourne DEPUIS TOUJOURS sur son "
              "repli cache, qui fonctionne mais n'est pas atomique (lire/insérer/réécrire, donc "
              "des lignes perdues quand gunicorn et les workers Celery poussent en même temps). "
              "Le correctif n'est PAS d'ajouter la dépendance : le client `redis` brut est déjà "
              "installé et la brique d'accès existe (`resource_governor._redis`, via "
              "`CELERY_BROKER_URL`)",
              'wama/common/utils/console_utils.py', '',
              annexes=('wama/common/static/common/js/console.js',)),
    Mecanisme('notifications', 'Notifications de tâche',
              "notify_job() — fin de traitement, succès comme échec",
              'wama/common/utils/notifications.py', 'PROFILES_PERMISSIONS.md'),

    )),

    *_domaine('UI générée', (
    # Les briques FRONT d'un mécanisme (js/partials) sont ses ANNEXES : même identité, le
    # comptage voit alors aussi les gabarits qui les référencent (balise <script>, include).
    Mecanisme('param_schema', 'Schéma de paramètres',
              "Source unique des réglages d'app : volet droit et modale sont RENDUS depuis lui",
              'wama/common/utils/param_schema.py', 'WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/static/common/js/wama-params.js',
                       'wama/common/templates/common/_settings_modal_footer.html')),
    Mecanisme('model_capabilities', 'Vocabulaire des capacités',
              "Canonicalise capabilities (tâche, modalités, entrées) — source du filtrage UI",
              'wama/common/utils/model_capabilities.py', 'INPUT_MODEL_MATCHING.md',
              annexes=('wama/common/static/common/js/wama-model-caps.js',
                       'wama/common/static/common/js/wama-input-match.js',
                       # Côté SERVEUR de wama-input-match (meta catalogue + labels INPUT_TYPES),
                       # extrait de composer/imager le 2026-08-17 (adoption ×7).
                       'wama/common/utils/input_match.py',
                       'wama/common/static/common/js/wama-model-help.js')),
    Mecanisme('detail_registry', 'Inspecteur — champs de détail',
              "Schéma canonique des infos d'item affichées au volet droit",
              'wama/common/utils/detail_registry.py', 'INSPECTOR_DETAIL_FIELDS.md',
              annexes=('wama/common/static/common/js/wama-inspector.js',
                       'wama/common/static/common/js/wama-inspector-autofill.js',
                       'wama/common/templates/common/_inspector_actions.html',
                       'wama/common/templates/common/_inspector_banner.html')),
    Mecanisme('preview', 'Preview unifiée',
              "Registre d'adaptateurs par modèle : la preview des cards vient du commun, pas des apps",
              'wama/common/utils/preview_registry.py', '',
              annexes=('wama/common/utils/preview_utils.py',
                       'wama/common/static/common/js/media-preview.js')),
    Mecanisme('card_gear', 'data-* du gear ⚙ des cards',
              "data-* du bouton ⚙ DÉRIVÉS du schéma (contrat cardSettings de l'inspecteur : "
              "le volet reflète la card sélectionnée) — remplace les attributs écrits à la main "
              "par app ; booléens 'true'/'false', tous les params item émis (anti-résidus)",
              'wama/common/utils/card_gear.py', ''),
    Mecanisme('card_chips', 'Chips méta des cards',
              "Chips de l'état concis GÉNÉRÉS du schéma params (chip=True) — jamais écrits par app",
              'wama/common/utils/card_chips.py', 'CARD_DESIGN.md §10.3',
              annexes=('wama/common/templates/common/_card_chips.html',)),
    Mecanisme('app_modes', 'Domaines → modes',
              "Schéma déclaratif des onglets-domaine et modes par app — scope la file",
              'wama/common/utils/app_modes.py', 'MODES_QUEUE_UX.md',
              annexes=('wama/common/static/common/js/wama-modes.js',)),
    Mecanisme('app_base_js', 'Socle JS des apps',
              "Plomberie commune file/cards : csrfFetch, urls, Poller de progression, états vides",
              'wama/common/static/common/js/wama-app-base.js', 'WAMA_APP_GENERATION_ROUTE.md'),
    # ── Briques d'INTERFACE communes (⚠ PAS des plugins — voir « rendu résolu » ci-dessus) ──
    # Déclarées le 2026-08-19 : elles vivaient dans `common/` sans être au registre — invisibles
    # de la carte, donc de la jonction avec la grille (le balayage ne regardait pas
    # `common/static/`). Elles sont toutes APPELÉES PAR LEUR NOM par leur hôte : ce sont donc
    # des mécanismes ordinaires, pas des rendus enfichables. `audio_player` est le seul
    # CANDIDAT au statut de rendu — il le deviendra le jour où l'aiguillage par mime de
    # `renderInlinePreview` sera un registre et non une cascade de `if`.
    Mecanisme('audio_player', 'Lecteur audio (onde + transport)',
              "Widget autonome : onde canvas (pics serveur ou décodés), play/pause, exclusivité "
              "inter-lecteurs et inter-onglets ; monté par la preview dans le volet ET les cards",
              'wama/common/static/common/js/wama-audio-player.js', ''),
    Mecanisme('shuttle', 'Shuttle J/K/L',
              "État de vitesse/direction de lecture (paliers éditeur) + binding clavier ; l'app "
              "fournit apply(speed) — la commande est commune, l'application au lecteur reste locale",
              'wama/common/static/common/js/wama-shuttle.js', ''),
    Mecanisme('media_picker', 'Sélecteur de médiathèque',
              "Modale commune de choix d'un asset de la médiathèque (filtrée par type), rendue "
              "à l'appelant sous forme de File + méta",
              'wama/common/static/common/js/media-picker.js', ''),
    Mecanisme('fm_notify', 'Signalement au gestionnaire de fichiers',
              "Noms d'événements centralisés (media:uploaded/processed/deleted) — l'arborescence "
              "du filemanager se rafraîchit sans que chaque app invente son event",
              'wama/common/static/common/js/wama-fm-notify.js', ''),
    Mecanisme('card_system', 'Card v3',
              "Dimensionnement déclaratif des pistes de card — dépend de l'app, des actions, des libellés",
              'wama/common/static/common/js/wama-card-v3.js', 'CARD_DESIGN.md §11',
              annexes=('wama/common/templates/common/_card_state.html',)),
    Mecanisme('new_item_card', 'Card « Nouvel élément »',
              "Card d'entrée dépliable commune (dropzones, URL, médiathèque, batch) — auto-init",
              'wama/common/static/common/js/wama-new-item-card.js', 'MODES_QUEUE_UX.md',
              annexes=('wama/common/templates/common/_new_item_card.html',)),
    # La card d'entrée porte les MODALITÉS ; celle-ci porte le GESTE d'envoi. Elles se
    # complètent : `new_item_card` déplie/replie, `batch_import` traite les fichiers de LOT,
    # `WamaApp.initUrlImport` le champ URL — et personne ne prenait le fichier ORDINAIRE.
    # Chaque app réécrivait sa boucle `handleFiles` (converter.js, reader.js…), donc une app
    # GÉNÉRÉE n'en avait aucune et ne pouvait créer aucune card, sans erreur console.
    Mecanisme('import_front', "Voie d'import (front)",
              "Envoi d'un fichier vers l'endpoint upload de l'app depuis toutes les sources "
              "(dépôt, clic, médiathèque), délégation du LOT à batch_import, consolidation et "
              "rafraîchissement — agnostique du monde (ni MIME ni extension)",
              'wama/common/static/common/js/wama-import.js', 'WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/templates/common/_app_scripts.html',)),
    Mecanisme('cycle_button', 'Bouton de cycle',
              "Bouton commun ▶/⏹/↻ toujours vert — l'icône porte l'action, l'état vit sur la card",
              'wama/common/static/common/js/wama-cycle-button.js', '',
              annexes=('wama/common/templates/common/_cycle_button.html',)),
    Mecanisme('progress_ui', 'Progression & ETA (front)',
              "Moteur ETA par débit observé + barres aux 3 niveaux : card, batch, globale",
              'wama/common/static/common/js/wama-eta.js', 'PROJECT_STATUS.md §10',
              annexes=('wama/common/static/common/js/wama-global-progress.js',
                       'wama/common/templates/common/_global_progress.html',
                       'wama/common/templates/common/_card_progress.html',
                       'wama/common/templates/common/_processing_time.html')),
    Mecanisme('folder_import', 'Import de dossier récursif',
              "Traversée récursive d'un drop/webkitdirectory — brique F2 montée globale (base.html)",
              'wama/common/static/common/js/wama-folder-import.js', 'WAMA_APP_GENERATION_ROUTE.md'),

    )),

    *_domaine('Données & infrastructure', (
    Mecanisme('units_display', "Unités d'affichage",
              "Moteur UNIQUE de conversion d'unités pour la PRÉSENTATION (pint) : la donnée "
              "reste dans SON unité (`WamaVariables.unit`, `ParamSpec.unit`), la préférence "
              "utilisateur (métrique/impérial) ne convertit qu'à l'écran — résolution par "
              "DIMENSION, une unité inconnue reste affichable — et un export qui convertit "
              "doit le DIRE. Un trou de donnée traverse en trou (None), jamais en valeur",
              'wama/common/utils/units.py', 'WAMA_DATA_WORLD.md §10 D27'),
    Mecanisme('temporal_referential', 'Référentiel temporel (WAMA Data)',
              "Aligne des flux à cadences INCOMMENSURABLES et répond aux questions temporelles : "
              "quel échantillon à t, quels segments le contiennent, quel événement suit, et la vue "
              "DÉCIMÉE (min/max par tranche) sans laquelle aucun tracé n'est viable. N'interpole "
              "jamais : la valeur rendue est toujours un échantillon existant",
              'wama_data/core/temporal.py', 'WAMA_DATA_WORLD.md §2-§3'),
    Mecanisme('data_import', 'Importer universel (WAMA Data)',
              "REGISTRE de capacités de lecture — aucun format privilégié : ajouter un format = "
              "déposer un lecteur, jamais éditer le moteur. Porte aussi l'HORODATAGE par flux "
              "(dont le ré-horodatage par fréquence théorique, qui n'interpole rien et ne "
              "s'applique que sur demande). ⚠ La MÉCANIQUE SQLite (ouverture en lecture seule, "
              "décodage UTF-8→cp1252 du texte des bases MATLAB, valeurs triées, les trois niveaux "
              "d'agrégation) est un socle partagé — un lecteur de base concret n'écrit plus que "
              "`can_read`, `probe` et `read`, c'est-à-dire sa seule connaissance du schéma",
              'wama_data/sources/__init__.py', 'WAMA_DATA_WORLD.md §6.6, §9terdecies',
              annexes=('wama_data/sources/_sqlite.py',
                       'wama_data/sources/trip.py',
                       'wama_data/sources/wdat.py',
                       'wama_data/sources/rtmaps.py',
                       'wama_data/sources/tabular.py')),
    Mecanisme('data_frames_bridge', 'Pont référentiel ↔ cadres typés (WAMA Data)',
              "SEULE frontière entre les deux vocabulaires du monde Data : le référentiel "
              "(paresseux, indexé, sans pandas) et le `TypedFrame` que mangent toutes les "
              "fonctions du catalogue. Sans lui le référentiel n'avait AUCUN consommateur — non "
              "parce qu'on ne s'en servait pas, mais parce qu'on ne POUVAIT pas. Traite quatre "
              "pièges mesurés : le temps de SESSION (± offset) vs le temps local du flux, la "
              "colonne temporelle brute PÉRIMÉE après ré-horodatage, le contrat `rows` réel mais "
              "non déclaré, et la PROVENANCE — ce qui revient d'un calcul ne peut pas se déclarer "
              "acquis (`is_base=False` sans échappatoire)",
              'wama_data/frames.py', 'WAMA_DATA_WORLD.md §9quater.7'),
    Mecanisme('data_vue', "View-model d'exploration (WAMA Data)",
              "Une VUE déclare ce qu'on regarde — flux, fenêtre, résolution, colonnes dérivées — "
              "et rien de plus : sérialisable en JSON, donc rejouable et diffable, et on persiste "
              "ELLE plutôt que les valeurs (une colonne matérialisée se périme sans le dire). "
              "Rend EXÉCUTABLE la règle « une nouvelle table SSI la clé temporelle change » en la "
              "DÉRIVANT de la `FunctionCategory` : ajouter une fonction au catalogue la range du "
              "bon côté sans toucher le view-model. La séparation tables/annexes rend la règle "
              "visible à l'écran au lieu d'avoir à l'expliquer",
              'wama_data/view.py', 'WAMA_DATA_WORLD.md §9quater.4, §9quater.7'),
    Mecanisme('data_noms', 'Noms dérivés (WAMA Data)',
              "DOMICILE UNIQUE de la règle « le nom se DÉRIVE des paramètres, il ne se saisit "
              "pas » : deux productions de mêmes réglages portent le même nom, deux réglages "
              "différents ne peuvent pas le partager. Elle était appliquée par QUATRE règles dans "
              "TROIS lieux — dont une f-string écrite en dur — avant l'audit du 23/08. Les anciens "
              "emplacements réexportent ; un test vérifie l'IDENTITÉ des fonctions, donc une "
              "redéfinition locale même à l'identique échoue. Sans dépendance, par nécessité : "
              "c'est ce qui permet à `conditions.py` de l'importer sans cycle",
              'wama_data/core/naming.py', 'WAMA_DATA_WORLD.md §9ter.6 B7, §9sexies.4'),
    Mecanisme('data_containers', 'Écrivain de conteneur (WAMA Data)',
              "UN MOTEUR, N SCHÉMAS — le pendant exact du registre de lecteurs, et le premier "
              "code du monde Data qui ÉCRIVE du SQLite (0 `INSERT` dans tout le monde avant lui). "
              "Le moteur tient la transaction, les tranches, l'indexation temporelle et la "
              "conversion des valeurs ; un schéma ne décide que des NOMS et du CATALOGUE — c'est "
              "ce qui garantit que `.wdat` (natif, D3) et `.trip` (compatibilité BIND) se "
              "comportent pareil là où ils le doivent. Écrit d'abord un `.partiel` puis renomme : "
              "un conteneur à moitié rempli s'ouvrirait normalement en mentant sur son contenu. "
              "⚠ CE QUE LE SCHÉMA CIBLE NE SAIT PAS PORTER EST COMPTÉ, pas tu (`Rapport.pertes`) "
              "— une conversion qui appauvrit en silence fait croire à un aller-retour fidèle. "
              "La compatibilité est attestée par CONTRE-ÉPREUVE : ce que WAMA écrit, le lecteur "
              "`.trip` — écrit contre le format de l'autre, sans rien savoir de l'écrivain — le "
              "relit",
              'wama_data/containers/__init__.py', 'WAMA_DATA_WORLD.md §9quater.2, §9duodecies',
              annexes=('wama_data/containers/wdat.py',
                       'wama_data/containers/trip.py')),
    Mecanisme('catalog_refresh', 'Actualisation des catalogues',
              "REGISTRE des registres : une page catalogue déclare la CLÉ de son registre et "
              "hérite du bouton, de l'endpoint, de la permission et du compte-rendu. La NATURE "
              "déclarée (scan / mesure / re-déclaration / DÉRIVÉ) décide du rendu — un dérivé "
              "affiche « toujours à jour » au lieu d'un bouton qui ne ferait rien — ET le LIEU "
              "d'exécution : état partagé → tâche Celery non bloquante, registre en mémoire → "
              "sur place, avec propagation aux autres workers gunicorn",
              'wama/common/registries.py', '',
              annexes=('wama/common/registries_builtin.py',
                       'wama/common/static/common/js/wama-catalog-refresh.js',
                       'wama/common/templatetags/wama_catalog.py')),
    Mecanisme('data_types', 'Taxonomie des types de donnée',
              "Vocabulaire commun des sources et des fonctions : sous-typage + compatibilité de "
              "ports. `segments` y est LE type « portion de temps bornée » (situation, état, section)",
              'wama/common/catalog/data_types.py', 'WAMA_DATA_FUNCTION_CARDS.md §3',
              symbole='DataType'),
    Mecanisme('ffmpeg', 'Accès ffmpeg',
              "Résolution centralisée du binaire et des conversions (échappatoire FFMPEG_BINARY)",
              'wama/common/utils/ffmpeg_utils.py', ''),
    Mecanisme('mirror_sync', 'Sauvegarde & tirage',
              "Moteur unique de miroir (modèles, base, médias, secrets) et restauration",
              'wama/common/services/mirror_sync.py', '',
              annexes=('wama/common/services/config_backup.py',
                       'wama/common/services/media_backup.py',
                       'wama/model_manager/services/remote_backup.py')),
    Mecanisme('retention', 'Rétention des médias',
              "Purge automatique des sorties au-delà de la durée choisie par l'utilisateur (FileField découverts)",
              'wama/common/services/retention.py', 'PROFILES_PERMISSIONS.md'),
    Mecanisme('audio_decode', 'Décodage audio robuste',
              "Décode l'audio là où torchcodec/torchaudio sont cassés (WSL) : soundfile + repli ffmpeg. "
              "Annexe torchaudio_compat = l'autre forme du même problème : shims soundfile posés DANS "
              "torchaudio pour les libs tierces qui l'appellent en interne (Coqui, DeepFilterNet)",
              'wama/common/utils/audio_decode.py', '',
              annexes=('wama/common/utils/torchaudio_compat.py',)),
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
    Mecanisme('org_sync', "Arbre organisationnel depuis l'annuaire",
              "ou=structures (SUPANN) → OrgUnit + parents ; peuple ce dont dépend le partage "
              "par unité (RAG labo, médiathèque). Lecture seule côté LDAP, idempotente",
              'wama/accounts/management/commands/sync_org_units.py',
              # ⚠ Pointait sur un souvenir d'agent (`reference_ldap_supann_orgunit`) : un
              # pointeur que personne lisant le dépôt ne peut suivre. Le document du domaine
              # est celui-là — `scoped_visibility`, l'autre moitié du mécanisme, l'y désigne déjà.
              'PROFILES_PERMISSIONS.md',
              # `annexes` : la remontée d'attributs au PROFIL est l'autre moitié — elle marchait
              # déjà (signaux au login) ; c'est l'ARBRE qui manquait, d'où le domicile ici.
              annexes=('wama/accounts/ldap.py',)),
    # Rattaché le 2026-08-27 : c'est le POINT UNIQUE DE DÉCISION de l'accès aux apps (tier ×
    # rôles), et il n'était sur aucune carte. Son absence s'est payée — la fermeture du compte de
    # service `anonymous` avait été faite à la main sur la base vivante, donc défaite par toute
    # réinstallation, faute d'un endroit où l'invariant soit déclaré.
    Mecanisme('app_access', "Accès aux éléments (apps aujourd'hui)",
              "Décide seul qui voit quel élément, sur DEUX axes qui se cumulent : le TIER du compte "
              "(anonymous < utilisateur < developpeur < admin, tranche en premier) et les RÔLES "
              "métier (groupes `role:*`, intersection avec la politique de l'app). Le compte de "
              "service `anonymous` y est FERMÉ par code, pas par état de base. Signature GÉNÉRALE "
              "depuis S2 — accessible(user, kind, element_id) : chaque FAMILLE d'élément déclare "
              "dans KIND_DECISION qui décide pour elle, un kind inconnu LÈVE, et une décision "
              "unique ne garde que ce que ses POINTS D'APPLICATION lisent réellement (§8.9)",
              'wama/accounts/permissions.py', 'PROFILES_PERMISSIONS.md',
              annexes=('wama/accounts/tests.py', 'wama/accounts/tests_access_points.py'),
              symbole='accessible'),
    # Ajouté le 2026-08-27 avec le jalon S1 (PROFILES_PERMISSIONS §8). Il est le VOISIN de
    # `app_access` et son exact complément — d'où sa place ici, collé à lui : `app_access` répond
    # « ai-je le DROIT ? », celui-ci « est-ce que je VEUX m'en servir ? ». Les confondre est le
    # défaut que ce mécanisme existe pour empêcher : une préférence ne décide JAMAIS d'un accès,
    # et aucune décision d'accès ne lit sa table.
    Mecanisme('abonnement', "Abonnement aux éléments de catalogue",
              "PRÉFÉRENCE d'affichage, appliquée APRÈS le droit et seulement à l'affichage : elle "
              "ne peut que RESTREINDRE ce à quoi l'utilisateur a déjà accès. Seules les EXCEPTIONS "
              "sont stockées (se réabonner efface la ligne) ; une nature d'élément s'ajoute par "
              "une entrée dans KINDS, et la page de catalogue hérite du mécanisme par deux "
              "attributs (`data-abo`, `data-abo-toggle`). Son PÉRIMÈTRE est celui du DROIT, pas "
              "d'APP_CATALOG : les surfaces transversales et Lab (extra_links) se masquent par la "
              "même clé `gate` que celle dont accessible() décide (§8.8.1)",
              'wama/common/services/subscriptions.py', 'PROFILES_PERMISSIONS.md',
              annexes=('wama/common/static/common/js/wama-abonnement.js',
                       'wama/common/tests_subscriptions.py')),
    Mecanisme('scoping', 'Accès scopé aux objets',
              "Deux chemins NOMMÉS pour lire un objet partageable depuis une vue (possédé / visible)",
              'wama/common/utils/scoping.py', 'PROFILES_PERMISSIONS.md'),
    Mecanisme('user_settings', 'Réglages utilisateur par app',
              "Persistance cache user_{id}_{app}_{clé} avec défauts déclarés par l'app",
              'wama/common/utils/user_settings.py', ''),
    Mecanisme('feature_flags', 'Bascules de fonctionnalités',
              "Registre de Feature par app + surcharges JSON de l'objet porteur — comparer AVEC/SANS",
              'wama/common/utils/feature_flags.py', ''),

    )),

    *_domaine("Studio & surface d'outils (API)", (
    Mecanisme('generic_runner', 'Runner générique du studio',
              "Exécute une app par son CONTRAT (triade tool_api normalisée) — zéro logique par app",
              'wama/studio/services/generic_runner.py', 'STUDIO_VISION.md',
              annexes=('wama/studio/services/launch.py',
                       'wama/studio/services/runners.py')),
    Mecanisme('tool_api', "Surface d'outils",
              "Registre central TOOL_REGISTRY : triades add/start/status par app, gating F7 via execute_tool, descriptions dérivées des schémas",
              'wama/tool_api.py', 'WAMA_APP_GENERATION_ROUTE.md'),
    Mecanisme('api_v1', 'API REST v1',
              "Passerelle générique (token+session) sur TOOL_REGISTRY : lister/exécuter, gating F7 à l'annonce ET à l'exécution",
              'wama/api/v1/views.py', '',
              annexes=('wama/api/v1/urls.py',),
              symbole='api_v1'),
    )),
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
    'wama/model_manager/services/format_converter.py': "conversion de formats de poids — plomberie chaîne modèles (avec format_policy)",
    # Triage du 2026-08-13 (les 3 dernières entrées du backlog) — aucun n'était mort, mes
    # « 0 apps » ne comptaient pas wama_lab :
    'wama/common/utils/intervals.py': "algèbre d'intervalles — cam_analyzer (coverage) seul consommateur",
    'wama/common/utils/video_compat.py': "compat lecteur navigateur (ensure_h264) — cam_analyzer seul ; promouvoir si adoption",
    'wama/common/utils/whisper_utils.py': "adaptateur describer → backend Whisper du transcriber (UNIFIÉ 13/08 : plus de double chemin de chargement) ; consommé par le describer seul",
    # 2026-08-27 : la page du registre `skills`. Le service ne porte AUCUN mécanisme propre — il
    # dérive `prompt_skills/*.md` × PROMPT_TARGETS × DOMAINES pour un seul gabarit. Les mécanismes
    # qu'il donne à VOIR sont déjà déclarés (`prompt_pipeline`, `assistant_skills`, `registres`).
    'wama/common/services/skills_catalog.py': "dérivation d'affichage du catalogue de skills — consommée par la vue `skills_catalog` seule",
}


def par_cle() -> dict:
    return {m.cle: m for m in MECANISMES}
