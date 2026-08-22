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
    #     avec la taxonomie de types (`common/data/data_types.py`) et `FUNCTION_CATALOG`.
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
                       'wama/common/nightly_scenarios.py')),
    Mecanisme('system_monitor', 'Moniteur système',
              "Mesure unifiée CPU/RAM/GPU/disque (WSL + hôte Windows) — barre de ressources, model manager",
              'wama/common/services/system_monitor.py', '',
              annexes=('wama/common/static/common/js/system-stats.js',)),

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

    )),

    *_domaine('Contenu & prompts', (
    Mecanisme('prompt_pipeline', 'Pipeline de prompts',
              "Traduction/enrichissement centralisés, déclarés par PROMPT_TARGETS",
              'wama/common/utils/prompt_enrichment.py', 'WAMA_IA_TRANSVERSE.md',
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
    Mecanisme('console', 'Console utilisateur',
              "Lignes de journal structurées par utilisateur et par app, via Redis",
              'wama/common/utils/console_utils.py', '',
              annexes=('wama/common/static/common/js/console.js',)),
    Mecanisme('notifications', 'Notifications de tâche',
              "notify_job() — fin de traitement, succès comme échec",
              'wama/common/utils/notifications.py', 'PROFILES_PERMISSIONS.md'),

    )),

    Mecanisme('app_sandbox', "Bac à sable d'apps (jumelles exécutables)",
              "Jumelle <app>_NN coexistante pour comparaison Playwright + diff dé-suffixé "
              "(route §10.3 marche S) — registre sandbox_apps.json injecté au boot "
              "(INSTALLED_APPS/urls/gating/catalogue), create/drop symétriques",
              'wama/common/sandbox.py', 'WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/management/commands/app_sandbox.py',)),
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
    Mecanisme('temporal_referential', 'Référentiel temporel (WAMA Data)',
              "Aligne des flux à cadences INCOMMENSURABLES et répond aux questions temporelles : "
              "quel échantillon à t, quels segments le contiennent, quel événement suit, et la vue "
              "DÉCIMÉE (min/max par tranche) sans laquelle aucun tracé n'est viable. N'interpole "
              "jamais : la valeur rendue est toujours un échantillon existant",
              'wama/common/data/temporal.py', 'WAMA_DATA_WORLD.md §2-§3'),
    Mecanisme('data_import', 'Importer universel (WAMA Data)',
              "REGISTRE de capacités de lecture — aucun format privilégié : ajouter un format = "
              "déposer un lecteur, jamais éditer le moteur. Porte aussi l'HORODATAGE par flux "
              "(dont le ré-horodatage par fréquence théorique, qui n'interpole rien et ne "
              "s'applique que sur demande)",
              'wama/common/data/sources/__init__.py', 'WAMA_DATA_WORLD.md §6.6',
              annexes=('wama/common/data/sources/trip.py',
                       'wama/common/data/sources/tabular.py')),
    Mecanisme('data_types', 'Taxonomie des types de donnée',
              "Vocabulaire commun des sources et des fonctions : sous-typage + compatibilité de "
              "ports. `segments` y est LE type « portion de temps bornée » (situation, état, section)",
              'wama/common/data/data_types.py', 'WAMA_DATA_FUNCTION_CARDS.md §3',
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
              'reference_ldap_supann_orgunit',
              # `annexes` : la remontée d'attributs au PROFIL est l'autre moitié — elle marchait
              # déjà (signaux au login) ; c'est l'ARBRE qui manquait, d'où le domicile ici.
              annexes=('wama/accounts/ldap.py',)),
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
}


def par_cle() -> dict:
    return {m.cle: m for m in MECANISMES}
