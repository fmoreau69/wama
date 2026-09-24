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
  2. un module d'un dossier BALAYÉ **non déclaré** — « tu as oublié de le tracer », la question
     posée par Fabien le 2026-08-13. ⚠ **La liste des dossiers n'est PAS recopiée ici** : elle vit
     dans `doc_facts.py` (`dossiers_balayes`), et la version qui était écrite à cette place avait
     déjà divergé — elle citait 5 dossiers quand le code en balayait 7, ignorant `common/memory/`
     et `common/static/common/js/` ajoutés depuis. *Une liste blanche recopiée à côté de la vraie
     ne se met jamais à jour deux fois.* Ce que ce point doit retenir, lui, est la LEÇON : un
     dossier hors balayage ne produit AUCUN signal — ni « non rattaché », ni rien — et elle s'est
     rejouée QUATRE fois (`common/backends/` 13/08, le front 19/08, `common/memory/` 21/08,
     `common/tts/` 28/08). D'où le geste : **ajouter le dossier au balayage dans le même commit
     que son premier fichier**, jamais après coup ;
  3. un mécanisme **sans consommateur** — brique morte. C'est exactement l'état où sont restés
     `model_coverage.couvrir_classes` (0 consommateur pendant 8 jours, alors qu'il avait été
     extrait pour ça) et `qc.py` (0 aujourd'hui). Ces deux-là ont été trouvés à la main ;
     ce contrôle les aurait signalés seul.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Mechanism:
    """Un mécanisme transversal : ce qu'il fait, où il vit, qui porte son intention."""

    key: str
    name: str
    #: Une ligne. Ce que le mécanisme FAIT, pas comment.
    role: str
    #: Chemin du module qui en est le domicile UNIQUE (relatif à BASE_DIR).
    home: str
    #: Document de référence portant l'intention. '' si elle n'est écrite nulle part — et
    #: c'est alors un trou que la carte doit rendre visible, pas masquer.
    doc: str = ''
    #: Modules supplémentaires qui font partie du mécanisme (le domicile reste le point d'entrée).
    annexes: tuple = field(default_factory=tuple)
    #: Symbole à compter quand le domicile est un module PARTAGÉ. Sans lui, un mécanisme logé
    #: dans `common/models.py` hérite du compte de tous les importateurs du module — 138 pour
    #: `ScopedVisibility` alors qu'ils importent surtout `Library` ou `BatchMixin` (mesuré le
    #: 2026-08-13). Le chiffre devenait décoratif ; renseigner le symbole le rend vrai.
    symbol: str = ''
    #: POURQUOI ce mécanisme n'a aucun consommateur qui l'IMPORTE — quand c'est voulu.
    #: ⚠ Ajouté le 2026-09-19 sur une remarque de Fabien : « ce sont des intentions, pas du code
    #: mort, et elles sont normalement consignées. Il ne faut pas les considérer comme mortes si
    #: elles ne le sont pas. » La carte listait quatre briques sous « brique morte ou pas encore
    #: adoptée » alors que TROIS natures s'y mélangeaient : un faux positif de mesure
    #: (`dev_tools`, importé sous une forme que le détecteur rate — corrigé à la source), des
    #: POINTS D'ENTRÉE dont le seul appelant est leur propre commande, déclarée en annexe donc
    #: exclue du comptage (`bench`, `mcp_server`), et une INTENTION consignée (`qc`, ROADMAP
    #: §16.5). Renseigner ce champ sort le mécanisme de la liste des morts et affiche sa raison.
    #: ⚠ Ce n'est PAS une trappe à silence : un mécanisme qui devrait être importé et ne l'est
    #: pas doit rester dans la liste — d'où une raison ÉCRITE, relue comme le reste du registre.
    standalone: str = ''
    #: Domaine de rendu de la carte (sous-table). Posé par `_domain()` — jamais entrée par entrée.
    domain: str = ''
    #: Clés des mécanismes sur lesquels celui-ci S'APPUIE — il les appelle pour faire son travail
    #: (l'inspecteur appelle le détail d'élément ; la modale générée, le schéma de paramètres).
    #: ⚠ DÉCISION Fabien du 2026-09-15 (option B) : un FICHIER appartient à UN seul mécanisme, comme
    #: domicile ou comme annexe ; la relation entre deux mécanismes se DÉCLARE ici, jamais en
    #: rangeant le domicile de l'un parmi les annexes de l'autre. Mesuré ce jour-là : 18 fichiers
    #: étaient portés par plusieurs mécanismes, dont `wama-inspector.js` à la fois domicile
    #: d'`inspector` et annexe de `detail_registry` — la relation existait, mais cachée dans un
    #: rangement de fichiers, et elle faisait compter les mêmes consommateurs deux fois.
    #: Même NIVEAU que le reste du registre (des mécanismes appelés par le développeur) : ce
    #: n'est pas le champ `resolu_par` retiré le 19/08, qui y mêlait les plugins chargés à chaud.
    depends_on: tuple = field(default_factory=tuple)
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


def _domain(name: str, mechanisms: tuple) -> tuple:
    """Pose le domaine sur un groupe d'entrées : le nom du domaine ne s'écrit qu'UNE fois."""
    from dataclasses import replace
    return tuple(replace(m, domain=name) for m in mechanisms)


#: ⚠ ORDRE : par domaine (= ordre des sous-tables de la carte) ; alphabétique à la génération.
MECHANISMS = (
    *_domain('Ressources & exécution', (
    Mechanism('resource_governor', 'Gouverneur de ressources',
              "Arbitre GPU/CPU/RAM entre process : réservation, résidence, priorités",
              'wama/common/services/resource_governor.py', 'docs/construction/suivi/PROJECT_STATUS.md §0'),
    Mechanism('backend_contract', 'Contrat de backend',
              "Cycle de vie commun des porteurs de modèle — ALIMENTATION du gouverneur "
              "(enveloppe load/unload/process à toute profondeur d'héritage) et CAPACITÉS "
              "déclarées par le moteur (supports_*), lues par le catalogue",
              'wama/common/backends/base.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/backends/manager.py',),
              # ⚠ `symbole` OBLIGATOIRE ici, et pour une raison différente de `scoped_visibility` :
              # le domicile n'est pas un module partagé, c'est son NOM DE FEUILLE qui est banal.
              # Le repli « import relatif » du compteur (`from …base import`) capturait alors
              # TOUS les `from .base import` du dépôt — 100 consommateurs annoncés au premier
              # rendu, mesuré le 2026-08-13, pour ~25 réels. Même piège pour l'annexe
              # `manager.py`. Règle : domicile au nom générique (base/manager/models/utils) ⇒
              # renseigner le symbole, sinon le chiffre est décoratif.
              symbol='BaseModelBackend'),
    Mechanism('task_skeleton', 'Squelette de tâche',
              "Enchaînement commun des tâches Celery d'item : gardes, progress, statuts, ETA",
              'wama/common/utils/task_skeleton.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md'),
    Mechanism('model_readiness', 'Annonce de téléchargement des poids',
              "Un modèle jamais utilisé télécharge ses poids À LA PREMIÈRE EXÉCUTION (37 appels "
              "`from_pretrained`/`snapshot_download` dans les backends) — et RIEN ne le disait : "
              "ni le squelette, ni les backends, ni la card. Mesuré le 2026-09-08, 4 modèles "
              "catalogués sont dans ce cas (mochi-1-preview, qwen-image-edit, flux2-klein-4b, "
              "musicgen-melody) : les lancer donnait une tâche figée, sans un mot, le temps de "
              "récupérer des dizaines de Go. *Une attente qu'on n'explique pas se lit comme une "
              "panne.* La brique ANNONCE et rien d'autre — elle ne télécharge pas (c'est le "
              "backend, au chargement), ne bloque pas, ne décide pas ; best-effort intégral. "
              "Adressée par la CLÉ DE CATALOGUE, la même qui résout le backend : l'annonce et "
              "l'exécution parlent du même modèle. Le squelette la déclare par `model_key` "
              "(OPTIONNEL, comme `vram_needed`). ⚠ Elle ne parle QUE si `is_downloaded=False`, et "
              "n'annonce la taille que si `disk_gb` la connaît : un avertissement permanent "
              "n'avertit plus de rien (celui de l'imager vidéo, en dur et à chaque lancement avec "
              "un volume inventé, a été retiré ce jour-là)",
              'wama/common/utils/model_readiness.py', 'docs/construction/suivi/PROJECT_STATUS.md',
              annexes=('wama/common/utils/task_skeleton.py',
                       'wama/common/tests_model_readiness.py')),
    Mechanism('file_cache', 'Cache par empreinte de fichier',
              "Garde une valeur calculée depuis un fichier (lecture AST, rendu markdown, compte "
              "de lignes) tant que son empreinte — date de modification, taille — n'a pas "
              "changé : un fichier modifié est relu, jamais servi périmé. Extrait le 2026-09-14 : "
              "le catalogue des docs portait le geste en dur, et l'inventaire des backends "
              "relisait 6 237 fois des fichiers pour UNE extraction de manifeste (48 résolutions "
              "d'un même vivier). ⚠ Ne convient qu'à ce qui ne dépend QUE du fichier",
              'wama/common/file_cache.py', '',
              annexes=('wama/common/tests_file_cache.py',)),
    Mechanism('task_progress', 'Progression de tâche longue',
              "Avancement d'une tâche Celery HORS file d'items publié dans le cache "
              "(F5-proof) + garde « déjà en cours » vérifiée auprès de Celery ; "
              "pendant navigateur = WamaApp.Poller",
              'wama/common/utils/task_progress.py',
              'wama/model_manager/PROSPECTION_PIPELINE.md'),
    Mechanism('process_control', 'Gardes de process',
              "Anti-boucle-de-crash (redélivrance) et réconciliation des tâches orphelines",
              'wama/common/utils/process_control.py', 'docs/construction/suivi/PROJECT_STATUS.md §0'),
    Mechanism('memory_manager', 'Mémoire GPU',
              "Garantit la VRAM avant un chargement, la reprend sur les autres modèles, "
              "et réessaie après libération sur erreur CUDA",
              'wama/model_manager/services/memory_manager.py', 'docs/construction/suivi/PROJECT_STATUS.md §0',
              annexes=('wama/model_manager/services/memory_monitor.py',
                       'wama/model_manager/services/memory_cleaner.py',
                       'wama/model_manager/services/memory_diagnostics.py')),
    Mechanism('eta', 'ETA auto-apprenante',
              "Estimation de durée par a-priori puis moyenne mobile, bucketisée par matériel",
              'wama/model_manager/services/eta_estimator.py', 'docs/construction/suivi/PROJECT_STATUS.md §10'),
    Mechanism('nightly_tests', 'Tests nocturnes',
              "Registre déclaratif de scénarios + runner sérialisé VRAM-aware "
              "(wired/ui/consistency/suite/model_loaded/output). Le stage `suite` (2026-09-19) fait "
              "entrer LA SUITE DJANGO dans la grille fonctionnelle : un scénario par app ayant des "
              "tests, DÉRIVÉ des apps installées ; verdict lu dans la SORTIE de `manage.py test` "
              "(jamais au code retour, qui sort en 0 sans rien lancer) et rouges NOMMÉS. "
              "DEUX comptes de test déclaratifs : le standard (rôles métier, SANS tier dev — c'est "
              "LUI que la matrice de droits mesure) et `get_test_dev_user` pour les surfaces "
              "dev-gated (jumelles de bac à sable), routé par `ui_smoke._test_session_key(app)` "
              "— sans lui les 11 scénarios d'une jumelle skippent (mesuré 2026-08-30)",
              'wama/common/services/nightly_tests.py', 'docs/construction/suivi/PROJECT_STATUS.md §Tests fonctionnels nocturnes',
              annexes=('wama/common/services/ui_smoke.py',
                       # Familles de scénarios sorties d'`ui_smoke.py` (5 300 lignes) : leurs
                       # registreurs sont appelés par `register_examples` (2026-09-13 / 09-14 /
                       # 09-18). ⚠ Une famille neuve se RATTACHE ici, jamais en `Mechanism` à
                       # elle : un fichier appartient à UN seul mécanisme (décision du 15/09),
                       # et un module de scénarios non rattaché ressort en « non rattaché » —
                       # c'est ainsi que `ui_smoke_states.py` a été repéré le jour même.
                       'wama/common/services/ui_smoke_matching.py',
                       'wama/common/services/ui_smoke_menus.py',
                       'wama/common/services/ui_smoke_states.py',
                       'wama/common/services/rights_matrix.py',
                       'wama/common/nightly_scenarios.py',
                       'wama/common/nightly_suite.py')),
    Mechanism('filemanager_importers', "Import « Envoyer vers » (registre + dérivation jumelles)",
              "Le registre `IMPORTERS` EST le dispatch ET la source du résolveur SERVEUR "
              "« Envoyer vers » (`common/services/send_to.py` — cards ET arbre de fichiers depuis "
              "le 2026-09-14, qui calculait avant ses destinations chez le client ; une seule "
              "liste — plus d'app offerte-puis-refusée) ; une JUMELLE de bac à sable n'y écrit "
              "jamais sa ligne : son importeur est DÉRIVÉ de sa source (`importer_for`, via "
              "`generated_from` + paramètre `app_label` — re-ciblé sur SES tables, jamais celles "
              "de la source), et la CONSOLIDATION en lots de l'import groupé suit la même voie "
              "(2026-08-30/31, constats Fabien : jumelle absente du menu, puis cards unitaires). "
              "⏳ avatarizer/composer sans importeur : leur fichier est une RÉFÉRENCE — attend le "
              "contrat d'import PAR RÔLE (CARD_DESIGN §11.8)",
              'wama/filemanager/views.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §S2bis',
              symbol='importer_for',
              annexes=('wama/filemanager/tests.py',)),
    Mechanism('system_monitor', 'Moniteur système',
              "Mesure unifiée CPU/RAM/GPU/disque (WSL + hôte Windows) — barre de ressources, model manager",
              'wama/common/services/system_monitor.py', '',
              annexes=('wama/common/static/common/js/system-stats.js',)),
    Mechanism('tts_service_client', 'Client du service TTS',
              "L'appel POST /tts UNIQUE vers le microservice TTS (payload contractuel, 503 "
              "« loading » → TTSServiceLoadingError, WAV temporaire ou bytes) ; les POLITIQUES "
              "(retry Celery, chunking, replis) restent aux appelants — extrait 2026-08-28 : "
              "4 exemplaires vivaient dans le dépôt, un seul détectait le 503",
              'wama/common/tts/service_client.py', 'docs/construction/ui/MODES_QUEUE_UX.md §2bis'),
    Mechanism('tts_vocabulary', 'Vocabulaire TTS partagé',
              "Le JEU DE CHOIX unique de la parole synthétique — moteurs, langues, presets de "
              "voix, cartes moteur↔langue — et sa résolution (voix pour une langue, langue "
              "d'une voix). Distinct du client de service : celui-ci TRANSPORTE, celui-là "
              "NOMME. Les deux apps TTS, `accounts` (langue de profil) et l'assistant y "
              "puisent les mêmes libellés",
              'wama/common/tts/constants.py', '',
              annexes=('wama/common/tts/voices.py',)),
    # ⚠ Pas de `symbole` : le repli « feuille » du compteur capturerait tout `from …constants
    # import` du dépôt — vérifié le 2026-08-28, il n'en existe AUCUN autre (`voices.py` est
    # une annexe, donc exclu). Le chiffre est donc honnête tel quel. À reconsidérer le jour où
    # un second `constants.py` apparaît : c'est exactement le piège documenté pour `base.py`.

    )),

    *_domain('Modèles', (
    Mechanism('model_selector', 'Sélection de modèle',
              "Choisit UN modèle : capacités, entrées, priorités, budget VRAM, qualité",
              'wama/model_manager/services/model_selector.py', 'docs/construction/ui/INPUT_MODEL_MATCHING.md'),
    Mechanism('auto_model', 'Auto-sélection (« auto » au select)',
              "Valeur « auto » d'un select de modèle : résolution AU LANCEMENT sur le "
              "domaine que le schéma déclare pour ses options (options_query), prévision "
              "affichée sous le select (options_auto) + curseur de QUALITÉ continu 0-100 "
              "(intent_param, poids dans le score de select_model)",
              'wama/common/utils/auto_model.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md'),
    Mechanism('model_coverage', 'Couverture multi-modèles',
              "Choisit un ENSEMBLE de modèles couvrant des classes (couverture ou spécialisation)",
              'wama/common/services/model_coverage.py', ''),
    Mechanism('model_quality', 'Indice de qualité a priori',
              "Ordonne les modèles autrement que par la taille (params EFFECTIFS √(totaux×actifs), contexte, quantif.)",
              'wama/model_manager/services/model_quality.py', ''),
    Mechanism('benchmark_sync', 'Benchmark tiers confronté',
              "Étage 2 qualité (a priori < benchmark < mesure) : AA + Elo Arena (texte, image, vidéo, VISION, document) + Open ASR (WER, sens 'bas') + MTEB (embeddings, jeu FRANÇAIS déclaré) appariés au catalogue, prospection incluse",
              'wama/model_manager/services/benchmark_sync.py', 'docs/construction/suivi/PROJECT_STATUS.md §REPRISE 2026-08-18',
              annexes=('wama/model_manager/management/commands/sync_benchmarks.py',)),
    Mechanism('internal_quality', 'Mesure interne des modèles',
              "Étage 3 qualité : ce que WAMA a MESURÉ elle-même contre une référence humaine "
              "(`ResultEvaluation`), agrégé par modèle — taux de CORPUS, échelle nommée "
              "`internal_<métrique>_<protocole>`, sens, rang parmi les modèles mesurés sur les "
              "MÊMES références, accumulation dite. RABATTUE À LA LECTURE (jamais écrite au "
              "catalogue) : elle n'entre dans aucun tri tant que Q3 n'est pas tranchée, et "
              "`sync_benchmarks`, qui remplace `benchmark_meta`, ne peut pas l'effacer",
              'wama/model_manager/services/internal_quality.py', 'docs/construction/ia/WAMA_QUALITE.md',
              annexes=('wama/model_manager/tests_internal_quality.py',),
              depends_on=('result_evaluation',)),
    Mechanism('bench', 'Banc de comparaison',
              "Mesures comparables par TÂCHE sur un échantillon (latence, sorties, saturation) ; "
              "`text-generation` mesure le DÉBIT d'un LLM Ollama (jetons/s, prefill, chargement) "
              "et nourrit la boucle d'ETA (`ModelRuntimeStat`, unité token) — des coûts, jamais "
              "une qualité",
              'wama/model_manager/services/bench.py', 'docs/construction/suivi/ROADMAP.md §16.2',
              annexes=('wama/model_manager/management/commands/bench.py',),
              standalone="POINT D'ENTRÉE : son seul appelant est sa propre commande "
                         "(`manage.py bench`), déclarée en annexe — un banc se LANCE, il ne "
                         "s'importe pas. 0 consommateur est donc le compte JUSTE"),
    Mechanism('provenance', 'Provenance de modèle',
              "Identité chez l'éditeur (licence, auteur, plateforme), posée VIA le manifeste",
              'wama/model_manager/services/provenance.py', '',
              annexes=('wama/model_manager/services/weights_metadata.py',)),
    Mechanism('prospection', 'Prospection de modèles',
              "Veille déterministe HuggingFace/Ollama + évaluation multi-agents (dry-run)",
              'wama/model_manager/services/prospector.py',
              'wama/model_manager/PROSPECTION_PIPELINE.md',
              annexes=('wama/model_manager/services/prospect_agents.py',
                       'wama/model_manager/services/prospect_ollama.py',
                       'wama/model_manager/services/ollama_registry.py',
                       'wama/model_manager/services/update_checker.py')),
    Mechanism('model_registry_discovery', 'Découverte de modèles',
              "Découverte unifiée des modèles (apps + sources externes), synchronisée vers le catalogue AIModel",
              'wama/model_manager/services/model_registry.py', '',
              annexes=('wama/model_manager/services/model_sync.py',
                       'wama/model_manager/services/file_watcher.py')),
    Mechanism('model_installer', 'Installation de modèles',
              "Pipeline accept→download→register : télécharge au bon endroit puis enregistre au catalogue",
              'wama/model_manager/services/model_installer.py', ''),
    Mechanism('vision_probe', 'Sonde vision',
              "Décrit une image via un modèle multimodal Ollama local (bench, smoke UI, fichiers de référence)",
              'wama/model_manager/services/vision_probe.py', ''),
    Mechanism('hf_cache', 'Cache HF scopé — dernier recours',
              "Bascule TEMPORAIRE du cache HuggingFace, restaurée en sortie : le levier D de "
              "`hf_weights`, réservé à une lib qui n'offre ni `cache_dir=`, ni chemin local, ni "
              "variable propre. ⚠ Restaure l'environnement, JAMAIS les fichiers. Aucun emploi "
              "aujourd'hui (`RECOURS_ASSUMES` vide, tenu par `tests_hf_cache_routing`)",
              'wama/common/utils/hf_cache.py', 'docs/construction/suivi/ROADMAP.md §5b'),

    )),

    *_domain('Qualité & auto-amélioration', (
    Mechanism('run_outcome', "Signaux d'exécution",
              "Journal append-only des FAITS observés sur un résultat (produit/corrigé/relancé…)",
              'wama/common/services/run_outcome.py', 'docs/construction/suivi/ROADMAP.md §16.7'),
    # `symbole` OBLIGATOIRE ici : un middleware n'est jamais IMPORTÉ, il est nommé par une chaîne
    # pointée dans `settings.MIDDLEWARE`. Sans lui, le scanner (qui compte les imports) le classe
    # « sans consommateur » alors qu'il est actif sur CHAQUE requête — un faux positif qui ferait
    # croire à une brique morte.
    Mechanism('run_outcome_capture', "Captation générique des gestes",
              "Middleware : telecharge/supprime/relance lus de resolver_match — zéro ligne par app",
              'wama/common/middleware.py', 'docs/construction/ia/WAMA_MEMORY.md §7bis',
              symbol='RunOutcomeCaptureMiddleware'),
    Mechanism('memory', 'Mémoire & RAG',
              "Souvenirs + fragments sur pgvector, scope hérité de ScopedVisibility ; 5 opérations",
              'wama/common/memory/store.py', 'docs/construction/ia/WAMA_MEMORY.md',
              # ANNEXES et non mécanismes séparés : `embed` (vecteurs), `index` (découpe RAG) et
              # `dev_ai` (reprise de memory.json) n'ont de sens QUE par le magasin — les déclarer
              # à part gonflerait la carte de trois entrées qu'on ne consulte jamais seules.
              # Le domicile reste `store.py`, point d'entrée des 5 opérations.
              annexes=('wama/common/memory/embed.py',
                       'wama/common/memory/index.py',
                       'wama/common/memory/dev_ai.py')),
    Mechanism('memory_project', 'Projection des faits en souvenirs',
              "RunOutcome → MemoryItem par OBJET (mécanique, sans modèle, idempotente)",
              'wama/common/memory/project.py', 'docs/construction/ia/WAMA_MEMORY.md §7'),
    Mechanism('library_export', 'Sortie d’app → médiathèque',
              "Range le RÉSULTAT d'un élément comme asset, lu au schéma canonique du détail : "
              "toute app qui déclare son adapter a le geste sans une ligne. Le RÔLE est FOURNI "
              "(un .mp3 peut être voix/musique/bruitage) ; une seule route pour les 10 apps. "
              "⚠ NE CONSTRUIT AUCUN CHEMIN — `upload_to` décide du domicile, donc le geste suit "
              "la refonte des dossiers utilisateur (chiffrement) au lieu de la figer. Les 2 "
              "copies manuelles (composer + sa jumelle) DÉLÈGUENT depuis le 2026-09-12, et un "
              "gardien AST refuse qu'une vue d'app recopie le geste. Surfaces : le menu « … » / "
              "clic droit des cards, le MÊME menu dans l'arbre de fichiers sur un fichier de "
              "SORTIE (2026-09-18), l'outil d'assistant. Le bouton dédié du composer et sa "
              "route d'app (seconde porte du même geste) sont RETIRÉS le 2026-09-18 (R64, "
              "R65) : le RÔLE se DÉCLARE au commun par l'app (`result_role` du détail "
              "canonique) et `admissible_roles` filtre — extension, puis rôle déclaré, pour "
              "les 10 apps ; non déclaré = l'utilisateur choisit. DEUX archétypes (§6.4), un "
              "geste : early-binding = le fichier déjà rendu, le choix est le rôle ; "
              "late-binding (transcriber, describer, reader) = le master texte est RENDU au "
              "format choisi par le builder du ⬇ (`register_export_builder`), asset "
              "`document`, coche et retrait par format (`export_choices`). ⚠ `synthesizer` "
              "n'était PAS une copie : son écriture d'asset est l'UPLOAD d'une voix, un autre "
              "geste.",
              'wama/media_library/services.py', 'docs/construction/ui/CARD_DESIGN.md §2bis',
              symbol='export_item_to_library'),
    Mechanism('filter_bar', 'Barre de filtrage',
              "Recherche + facettes EN DIRECT ; options dérivées du DOM (client) ou déclarées "
              "(server). Depuis le 2026-09-08 la recherche est un OUTIL du registre de barre "
              "(`toolbar_registry`), donc la même dans les registres et dans les 12 files. "
              "Masquage PAR CLASSE (`.wama-f-hors-filtre`) et non par `style.display` : une "
              "cible à `display` inline (l'entrée unitaire de file est en `display:contents`) "
              "ne survivait pas à la restauration. `data-cible-dans` BORNE la recherche — sans "
              "quoi deux files sur une même page se filtreraient l'une l'autre",
              'wama/common/static/common/js/wama-filter-bar.js', 'docs/construction/ui/CARD_DESIGN.md',
              annexes=('wama/common/templates/common/_filter_bar.html',),
              symbol='WamaFilterBar'),      # global de base.html : compté par son symbole
    Mechanism('card_menu', "Menu contextuel de card/lot + débordement « … »",
              "Clic droit = la liste COMPLÈTE des actions (+ celles de la SÉLECTION MULTIPLE) ; "
              "le « … » de la rangée = le DÉBORDEMENT SEUL, au-delà des 6 actions nominales "
              "(bouton édition compris — décision Fabien 2026-09-08). Modèle HYBRIDE : les "
              "actions EXISTANTES sont LUES sur le `.btn-group-actions` de la card (contrat de "
              "`cloneActions`, donc zéro ligne par app et clic PROXIFIÉ vers le vrai bouton), "
              "les TRANSVERSES sont déclarées et leurs URLs viennent de `queue_dnd_attrs` — une "
              "route absente n'émet pas son attribut, donc l'entrée n'apparaît pas. Sous-menus en "
              "CASCADE, au survol et au clic, le parent restant ouvert (2026-09-14) et DIFFÉRÉS "
              "(« Recherche… » puis rempli : il n'attend pas le réseau). Se ferme sur un geste de "
              "l'UTILISATEUR hors du menu, jamais sur un `scroll` (un focus programmatique le "
              "refermait en 7 ms). 2ᵉ surface : l'arbre de fichiers (`ouvrir()` depuis "
              "`filemanager.js`, 2026-09-14), qui obtient depuis le 2026-09-18 les gestes "
              "d'ÉLÉMENT (Partager…, Ajouter à la médiathèque…, Ajouter au RAG) sur un fichier "
              "de SORTIE par `entreesPourChemin` — le serveur remonte à l'élément "
              "(`send_to.item_for_output_path`), les entrées sont CELLES de la card "
              "(`entreesPourElement`, une seule liste), posées en ENTRÉE DIFFÉRÉE à la racine "
              "du menu (`{chargement, charger}` : « Recherche… » puis remplacement, le menu "
              "n'attend pas le réseau). ⚠ Le menu est posé sur `document.body` : une card "
              "vit dans un conteneur à `overflow` qui le rognerait. Le « … » suit les cards INSÉRÉES "
              "ou REMPLACÉES après le chargement (observation de la file, 2026-09-15)",
              'wama/common/static/common/js/wama-card-menu.js', 'docs/construction/ui/CARD_DESIGN.md',
              symbol='WamaCardMenu'),
    Mechanism('item_sharing', "Partage d'un élément ou d'un lot (1ʳᵉ interface)",
              "LE GESTE qui manquait au mécanisme de visibilité : `PROFILES_PERMISSIONS §7.5` "
              "disait « il n'existe AUCUNE interface de partage » (il fallait l'admin Django). "
              "Écrit `visibility` + son scope sur l'élément ET son lot — ou sur le lot ET ses "
              "éléments : les DEUX sens sont exigés, le filtre de lecture s'appliquant aux deux "
              "niveaux (un lot partagé aux éléments privés s'affiche VIDE chez le destinataire). "
              "Portées OFFRABLES dérivées de l'utilisateur (unités qui le couvrent, projets dont "
              "il est membre) : une portée sans cible réelle n'est pas proposée. Lecture seule "
              "par construction — l'écriture est le jalon S3 `AccessGrant`, et la modale le DIT",
              'wama/common/services/sharing.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md',
              annexes=('wama/common/static/common/js/wama-share.js',)),
    Mechanism('send_to', "Envoyer vers (chaînage progressif, hors studio)",
              "La SORTIE d'une card devient l'ENTRÉE d'une autre app, sans passer par le studio. "
              "RÉSOLVEUR en lecture seule : il rend les chemins de sortie (clé canonique "
              "`result_file`/`result_files` du schéma de détail), les apps ÉLIGIBLES et l'URL de "
              "l'endpoint. L'envoi lui-même passe par `filemanager:api_import` — celui qui sert "
              "déjà « Envoyer vers… » — donc aucun second dispatch et aucune garde de chemin "
              "recopiée. ⚠ Les destinations sont DÉRIVÉES de trois conditions (importeur, "
              "extension déclarée, accès) et jamais listées : c'est la leçon du Geste 14, où le "
              "menu offrait trois apps que le serveur refusait. Une app qui ne prendrait qu'une "
              "PARTIE des fichiers n'est pas offerte — un envoi partiel silencieux ferait croire "
              "le résultat entier transmis. Porte aussi l'INVERSE (2026-09-18) : "
              "`item_for_output_path` — de quel élément un chemin de `media/` est la SORTIE "
              "(candidats par requête, CONFIRMATION par l'adapter), route "
              "`api/element-pour-chemin/` — ce qui donne à l'arbre les gestes d'élément",
              'wama/common/services/send_to.py', 'docs/construction/architecture/WAMA_VERIFICATION.md',
              annexes=('wama/common/static/common/js/wama-send-to.js',)),
    Mechanism('input_provenance', "Provenance d'une entrée (source ⟷ copie de travail)",
              "D'OÙ vient le fichier qu'une card consomme. La frontière était déjà tracée par le "
              "code — la SOURCE de vérité (médiathèque, temp, montage, URL) reste où elle est, "
              "l'ENTRÉE d'une card est une copie de travail jetable — mais rien ne reliait les "
              "deux. Quatre gestes en dépendaient, tous demandés et tous impossibles : la DÉDUP "
              "par provenance (mesuré le 11/09 : chaîner describer → imager → enhancer par "
              "« Envoyer vers » produit TROIS copies des mêmes octets), le retour app → "
              "médiathèque sans re-copie, savoir qu'une source a BOUGÉ au lieu de le découvrir "
              "au lancement, et surtout l'INDEX INVERSE — « qui référence ce fichier ? », la "
              "question que le gestionnaire de fichiers doit poser AVANT de supprimer. C'est lui "
              "qui lève la seule objection restée debout contre le pointage : on ne bloque pas la "
              "suppression, on la rend INFORMÉE (la card survit, l'utilisateur sait que sa source "
              "a disparu). ⚠ PAS de `GenericForeignKey` malgré la lettre de la décision du 07/09 : "
              "`RunOutcome` avait déjà tranché l'inverse avec sa raison écrite, on suit SA "
              "convention (`app`+`object_type`+`object_id`, plus `field` — un élément peut avoir "
              "plusieurs entrées). ⚠ ÉCRITE PAR LES BRIQUES SEULES : `copy_into_app_input` "
              "enregistre quand on lui donne l'élément, `record_import` est sa moitié pour le "
              "motif « copier PUIS créer ». Aucune app n'écrit sa provenance. ⭐ CÂBLÉE le "
              "2026-09-22 (elle ne l'était qu'à UN site sur onze) : le répartiteur « Envoyer "
              "vers » enregistre pour tous les importeurs et leurs jumelles (`record_origin`, "
              "qui retrouve les cards par le chemin de leur copie), `ensure_local_input` pour "
              "une URL, les deux lots `-i` qui copient une ligne serveur ; nouveau `kind` `app` "
              "— « Envoyer vers » part aussi de l'entrée ou de la sortie d'une autre card",
              'wama/common/utils/provenance.py', 'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md',
              annexes=('wama/common/utils/file_references.py',
                       'wama/common/tests_file_references.py')),
    Mechanism('file_references', "Qui désigne ce fichier ? (déplacer, supprimer sans casser)",
              "L'index des cards qui DÉSIGNENT un chemin, et les deux gestes qui le tiennent à "
              "jour — `repoint` quand le fichier bouge, `detach` quand il disparaît. Décision de "
              "Fabien du 2026-09-22 (`MEDIA_STORAGE_TIERING §8.6` D20) : déplacer ou renommer met "
              "à jour le lien des cards SANS rien demander ; supprimer un fichier qu'une card "
              "utilise demande d'abord une confirmation qui dit COMBIEN de cards il touche, puis "
              "laisse les cards en place, détachées. Avant, le gestionnaire renommait, déplaçait "
              "et supprimait sans jamais regarder les cards : c'est ce geste qui fabrique les "
              "« référencés mais absents » comptés par `check_media_integrity`. ⚠ DEUX façons de "
              "désigner, une seule met la card en péril : par un `FileField` (elle perd son "
              "fichier) ou par sa PROVENANCE (elle a sa copie — information, jamais un blocage). "
              "⚠ `filemanager.UserFile` est exclu : c'est l'index du gestionnaire lui-même",
              'wama/common/utils/file_references.py',
              'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md',
              annexes=('wama/common/tests_file_references.py',)),
    Mechanism('toolbar_registry', "Barre d'outils générale (registre + profils)",
              "UN registre d'outils (l'UNION de toutes les barres) et des PROFILS par nature de "
              "surface : `file` (12 files d'app) et `registre` (15 catalogues). Une surface tire "
              "des outils, elle ne les énumère pas — ajouter un outil à toutes les files est UNE "
              "clé, plus jamais douze gabarits (demande Fabien 2026-09-08 : « de façon globale, "
              "pas par app »). Les deux barres historiques SURVIVENT en façades vers "
              "`_toolbar.html`, ce qui laisse les 27 pages appelantes inchangées ; les deux "
              "ENVELOPPES sont conservées telles quelles (les fondre aurait changé les deux "
              "apparences). Chaque outil est un partial sous `common/toolbar/`",
              'wama/common/toolbar.py', 'docs/construction/ui/CARD_DESIGN.md',
              annexes=('wama/common/templates/common/_toolbar.html',
                       'wama/common/templatetags/wama_toolbar.py')),
    Mechanism('journal', "Journal transversal de l'utilisateur",
              "Tout ce qu'il a lancé, toutes apps — DÉRIVÉ de detail_registry, aucune ligne par app",
              'wama/common/services/journal.py', 'docs/construction/ia/WAMA_MEMORY.md §9bis'),
    Mechanism('rag_gesture', "Ajout au RAG (geste explicite)",
              "Bouton dans l'INSPECTEUR + page « Mon RAG » ; texte pris au schéma canonique, "
              "aucune ligne par app. Pas de balayage : l'entrée au RAG est un geste, par décision",
              'wama/common/static/common/js/wama-inspector.js', 'docs/construction/ia/WAMA_MEMORY.md §7ter',
              # Le domicile est le JS : c'est LUI qui rend le geste universel (inspecteur global).
              # Les vues sont l'annexe serveur — la seule porte d'écriture offerte à l'UI.
              annexes=('wama/common/templates/common/rag.html',)),
    Mechanism('qc', 'Contrôle qualité de sortie',
              "Note une sortie par un validateur LLM INDÉPENDANT ; signal relatif, escalade humaine",
              'wama/common/utils/qc.py', 'docs/construction/suivi/ROADMAP.md §16.5',
              standalone="INTENTION CONSIGNÉE, pas une brique morte (ROADMAP §16.5) : le 3ᵉ "
                         "étage de l'échelle des signaux — la MESURE INTERNE — est vide, et ce "
                         "juge l'attend. Mesuré le 2026-09-19 : 0 consommateur, bench compris"),
    Mechanism('divergence', 'Divergence inter-systèmes',
              "Désaccord entre deux sorties du même travail — signal objectif, sans avis de modèle",
              'wama/common/services/divergence.py',
              'wama/transcriber/TRANSCRIBER_CORRECTION.md §8.3'),
    # 2026-09-23 : la mesure M3 (WAMA_QUALITE) — la première métrique à vérité terrain du dépôt.
    # Elle porte le découpage en mots que la divergence utilisait seule : UN découpage pour tous
    # les signaux de qualité, sinon deux signaux se contrediraient sur le même texte.
    Mechanism('text_metrics', 'Métriques à vérité terrain (WER / CER)',
              "Distance d'une sortie texte à sa RÉFÉRENCE (port `reference_result`) : "
              "substitutions, suppressions, insertions rapportées à la longueur de la référence. "
              "Ne normalise que la casse et la ponctuation — les hésitations restent des données "
              "(verbatim) ; une référence vide rend un taux INDÉFINI, jamais zéro",
              'wama/common/services/text_metrics.py', 'docs/construction/ia/WAMA_QUALITE.md',
              annexes=('wama/common/tests_text_metrics.py',)),
    Mechanism('word_anchoring', 'Ancrage d\'un texte sans temps sur des mots horodatés',
              "Étage A de l'alignement forcé, SANS modèle : un texte fait ailleurs (export Sonal, "
              "texte) retrouve l'heure de chacun de ses mots parmi ceux d'une sortie ASR de la même "
              "audio — plus longue sous-suite commune des mots (RapidFuzz `Indel`, jamais "
              "Levenshtein, qui substitue aux ex-aequo et décale la suite). Chaque mot dit la "
              "qualité de son temps : `exact`, `estimated` (dans la durée réelle des mots corrigés), "
              "`interpolated` (rien en face). Étage B (`refine_turns`) : un aligneur ACOUSTIQUE "
              "(contrat `ForcedAlignmentBackend`, choisi au catalogue par sa tâche `alignment` et sa "
              "langue) reprend les seuls mots estimés, par fenêtres que tiennent leurs voisins sûrs, "
              "coupées entre deux mots au-delà de sa capacité ; ils deviennent `aligned`. Le module "
              "ne charge aucun modèle : il reçoit le geste d'alignement",
              'wama/common/services/word_anchoring.py', 'wama/transcriber/TRANSCRIBER_CORRECTION.md §10.5',
              annexes=('wama/common/tests_word_anchoring.py',
                       'wama/common/backends/forced_alignment_base.py',
                       'wama/common/backends/wav2vec2_aligner_backend.py'),
              depends_on=('text_metrics',)),
    Mechanism('result_evaluation', 'Évaluation d\'un résultat contre sa référence',
              "Une app DÉCLARE son évaluation (`register_evaluation` : champ de la référence, "
              "lecture du résultat et de la référence, modèle, métriques) et la brique fait le "
              "reste : pose la référence sur un élément OU un lot (un seul fichier, partagé), "
              "mesure, conserve la mesure par élément (`ResultEvaluation` — modèle, échelle, "
              "sens, identité de la référence : ce que l'indice interne des modèles agrégera) et "
              "compare les modèles d'un lot (taux de CORPUS, et dit quand les références "
              "diffèrent). SANS référence, l'accord entre moteurs d'une même entrée (M1 deux à "
              "deux, médiane M6, jamais de « meilleur »). Va avec la capacité "
              "`has_reference_result` — un test refuse l'une sans l'autre",
              'wama/common/services/result_evaluation.py', 'docs/construction/ia/WAMA_QUALITE.md',
              annexes=('wama/common/tests_result_evaluation.py',
                       'wama/common/static/common/js/wama-evaluation.js',
                       'wama/common/templates/common/_batch_evaluation_line.html',
                       'wama/common/templates/common/_batch_agreement_line.html'),
              depends_on=('text_metrics', 'divergence')),
    # Rattaché le 2026-08-27, en même temps que son extension aux skills : la brique existait
    # depuis longtemps sans figurer sur la carte — donc invisible à qui cherche « qu'est-ce qui
    # contrôle la doc ? ». C'est précisément le trou que ce mécanisme sert à fermer ailleurs.
    Mechanism('docs_integrity', 'Intégrité doc → code',
              "Vérifie que chaque chemin, ligne et renvoi .md cité par la doc ET par les skills "
              "existe encore ; gate nocturne sur les CIBLES distinctes, pas sur les références",
              'wama/common/management/commands/check_docs.py', 'AGENTS.md §Fichiers de référence',
              annexes=('wama/common/tests_check_docs.py',),
              symbol='check_docs'),      # nommée par une CHAÎNE, jamais importée — cf. plus bas
    # 2026-09-11 : la liste des docs de référence vivait en double (table d'AGENTS.md +
    # `check_docs.DOCS`) ; le lecteur de doc en aurait fait une troisième. UNE déclaration.
    # 2026-09-19 (question de Fabien : « Encore des termes en français... Comment arrêter ça ? »).
    # La règle de langue existait depuis le 22/08, durcie le 14/09, et elle a dérivé quand même :
    # elle demandait de s'en SOUVENIR. Ce mécanisme la rend mesurable — et donc opposable.
    # Quatre briques livrées les 15-18/09 et restées HORS de la carte — relevé listé comme reste
    # depuis plusieurs sessions, fermé le 2026-09-19. Elles étaient invisibles à qui cherche
    # « qu'est-ce qui sert les modèles cloud ? » ou « où vit le chiffrement des clés ? », et c'est
    # exactement le trou que ce registre existe pour fermer (cf. l'entrée `docs_integrity`).
    Mechanism('cloud_models', 'Modèles DISTANTS au catalogue',
              "Un modèle servi par une clé d'API entre au catalogue comme les autres (ligne "
              "`<source>:<id>`, `execution='cloud'`, le modèle porte son moteur et le fournisseur "
              "s'en DÉRIVE) : découverte par la clé de CHAQUE utilisateur (`GET /models` à "
              "l'enregistrement), le catalogue porte l'UNION, et `retire_unlisted` MARQUE ce que la "
              "source ne liste plus au lieu de le supprimer — une clé qui ne voit plus un modèle ne "
              "prouve pas qu'il a disparu. Ces lignes n'entrent au tirage que par "
              "`select_model(cloud_keys=…)`",
              'wama/model_manager/services/cloud_models.py',
              'docs/construction/suivi/ROADMAP.md §8d',
              annexes=('wama/model_manager/tests_cloud_models.py',)),
    Mechanism('secret_crypto', "Chiffrement RÉVERSIBLE des secrets d'utilisateur",
              "Les clés d'API de fournisseurs cloud sont chiffrées en base, pas hachées : WAMA doit "
              "les RELIRE pour appeler le fournisseur à la place de l'utilisateur. Clé DÉRIVÉE de "
              "`SECRET_KEY` par HKDF avec une étiquette d'usage (décision Fabien : pas de clé de "
              "plus dans `.env`) — on ne chiffre pas avec la valeur qui signe les sessions. "
              "⚠ La rotation de `SECRET_KEY` est le piège : le déchiffrement essaie la courante "
              "puis les `SECRET_KEY_FALLBACKS`, dont `rotate_secrets` ne garde que TROIS",
              'wama/common/utils/secret_crypto.py',
              'docs/construction/suivi/ROADMAP.md §8d',
              annexes=('wama/accounts/tests_api_keys.py',)),
    Mechanism('mcp_server', 'Serveur MCP (adaptateur mince sur tool_api)',
              "Un seul contrat d'outils pour TOUS les cerveaux (Ollama, Claude Code, Albert, un "
              "IDE) : `tools/list` = le registre filtré par `tool_accessible`, `tools/call` = "
              "`execute_tool` — LA porte unique. Adaptateur MINCE : aucun protocole maison, "
              "`tool_descriptions()` dérive déjà nom/description/schéma. DEUX surfaces, DEUX "
              "process : `wama` (prod) et `wama-dev`, jamais chargés ensemble",
              'wama/common/services/mcp_server.py',
              'docs/construction/suivi/ROADMAP.md §8d',
              annexes=('wama/common/management/commands/run_mcp_server.py',
                       'wama/common/tests_mcp_server.py')),
              # Déclaré « autonome » (point d'entrée de process, importé par personne) jusqu'au
              # 2026-09-22 : depuis, `mcp_client` lui emprunte le chemin d'endpoint (`MCP_PATH`)
              # — un consommateur, donc plus autonome (garde `tests_catalogues`).
    Mechanism('dev_tools', 'Outils de DÉVELOPPEMENT (surface MCP « wama-dev »)',
              "Rôles wama-dev-ai (librarian, model, scout, integrator, codegen) et bac à sable "
              "d'apps, exposés à un client MCP. ⚠ JAMAIS chargé dans le process de PRODUCTION "
              "(ROADMAP §16 : défense en profondeur > scope de jeton) — ni dans `TOOL_REGISTRY` ni "
              "importé par `tool_api` ; seul `run_mcp_server --surface dev` l'importe, et "
              "`tests_mcp_dev_tools` le garde. Les rôles écrivent une PROPOSITION dans "
              "`wama-dev-ai/outputs/` et n'appliquent rien",
              'wama/common/services/dev_tools.py',
              'docs/construction/suivi/ROADMAP.md §8d',
              annexes=('wama/common/tests_mcp_dev_tools.py',)),
    Mechanism('development_models', 'Modèles de NIVEAU DÉVELOPPEMENT (bridage « qualité max »)',
              "UN domicile pour « quel modèle a le droit de travailler sur le code » : plancher "
              "sur le score coding du banc tiers (≥ 40) + déclaration explicite pour le seul "
              "distant non mesuré (albert:gpt-oss-120b), curseur imposé à 100 (réflexion), "
              "distants SOUVERAINS admis dès « cloud si saturé », et REFUS lisible plutôt qu'un "
              "petit modèle en repli. Lu par l'assistant (domaine dev, bascule en cours de tour "
              "dès qu'une compétence dev ou un outil dev_* est appelé, domaine collant au fil) et "
              "par les rôles wama-dev-ai (`role_utils.resolve_model`) — décision Fabien 22/09 "
              "après un tour réel où qwen3.5:4b inventait des jumelles",
              'wama/common/services/development_models.py',
              'docs/construction/ia/WAMA_LLM.md',
              annexes=('wama/common/tests_development_models.py',)),
    Mechanism('mcp_client', "L'assistant, CLIENT MCP de la surface de développement",
              "Le moteur de l'assistant RELAIE les outils `dev_*` (rôles wama-dev-ai, bac à "
              "sable) à la surface « wama-dev » par le protocole — process séparé, §16 tenu : "
              "rien n'est importé, la porte (droits à chaque appel, arguments admis) reste celle "
              "du serveur. Annoncés aux seuls développeurs/admins ; serveur absent = aucun outil, "
              "l'assistant répond quand même. Étape 5 de §8d, moitié dev (2026-09-22)",
              'wama/common/services/mcp_client.py',
              'docs/construction/suivi/ROADMAP.md §8d',
              annexes=('wama/common/tests_mcp_client.py',)),
    Mechanism('identifier_language', 'Langue des identifiants (budget)',
              "Relève par AST les identifiants de code FRANÇAIS (classes, fonctions, arguments, "
              "variables, alias d'import ; accents = signal certain) et les borne par un BUDGET "
              "QUI NE PEUT QUE DESCENDRE : aucun chantier de renommage exigé, mais l'AJOUT "
              "devient impossible. Les méthodes `test_*` sont la seule exemption de doctrine ; "
              "les noms de classes de test le sont par défaut (zone grise, `--strict-classes` "
              "en donne le chiffre). Le test refuse aussi un budget qui garde de la MARGE — une "
              "marge est une autorisation d'en ajouter",
              'wama/common/management/commands/check_identifier_language.py',
              'AGENTS.md §Langue des identifiants',
              annexes=('wama/common/tests_identifier_language.py',),
              symbol='check_identifier_language'),
    Mechanism('docs_catalog', 'Catalogue & lecteur de docs',
              "Déclare les docs de référence (famille, AUDIENCE, journal) et les rend lisibles "
              "depuis WAMA en lecture seule (page `docs`, admins) ; `check_docs` en dérive sa "
              "liste, et un test refuse que la table d'AGENTS.md cite un doc non déclaré. Sert "
              "aussi la doc DÉVELOPPEUR : ses faits (`dev_docs.py` : parcours, registres, API "
              "des briques lue par AST), écrits en `.md` par les plans",
              'wama/common/docs_catalog.py', 'AGENTS.md §Trois docs, trois publics',
              annexes=('wama/common/dev_docs.py', 'wama/common/tests_docs_catalog.py')),
    # 2026-09-11 : 1ʳᵉ pièce de la mécanique des docs dérivées (ROADMAP §25) — les vérités
    # terrain des registres injectées dans les .md, au lieu d'y être recopiées.
    Mechanism('fact_tags', 'Faits en ligne (balises de registre)',
              "Une balise `WAMA:FAIT(registre/clé/champ)` dans un .md va chercher sa valeur dans "
              "le registre (`Registry.entries`) ; `doc_facts` la régénère, `--check` la "
              "confronte, et une balise qui ne se résout pas est CASSÉE. Généralise les blocs "
              "`WAMA:FAITS` (une fonction par fait) à n'importe quel champ de registre",
              'wama/common/fact_tags.py', 'docs/construction/suivi/ROADMAP.md §25',
              annexes=('wama/common/tests_fact_tags.py',)),
    Mechanism('doc_sections', 'Marquage des sections de doc',
              "Une balise `WAMA:SECTION(audience=…; type=…; nature=…; etat=…)` sous un titre dit "
              "à qui la section parle (développeur, utilisateur), quel genre de texte elle est "
              "(tutoriel, guide, référence, explication) et si elle CONSTATE ou VISE ; une "
              "sous-section hérite. `check_docs` contrôle le vocabulaire et la double "
              "vérification (constat ⇒ ✅, intention ⇒ 🔄/⏳) ; `extract` sert les docs dérivées",
              'wama/common/doc_sections.py', 'docs/construction/suivi/ROADMAP.md §25',
              annexes=('wama/common/tests_doc_sections.py',)),
    Mechanism('doc_plans', 'Docs dérivées par plan',
              "Un PLAN déclaré dans le catalogue des docs (extraits de sections marquées + faits "
              "de registre) produit un `.md` versionné, écrit par `doc_facts` ; `--check` refuse "
              "un fichier qui n'est plus ce que son plan produit — la confrontation doc → doc, "
              "gratuite parce que la dérivation est mécanique. Pour l'UTILISATEUR, une PORTE "
              "registre retient les intentions et ce que le registre ne confirme pas",
              'wama/common/doc_plans.py', 'docs/construction/suivi/ROADMAP.md §25',
              annexes=('wama/common/tests_doc_plans.py',)),
    Mechanism('templates_integrity', 'Intégrité des gabarits',
              "Attrape la famille de fautes qui a récidivé SEPT fois : le commentaire `{# … #}` "
              "MULTI-LIGNE, que le lexer de Django (pas de re.DOTALL) rend en TEXTE littéral — "
              "et le nom de balise avaleuse écrit dans un commentaire. Un scan de 5 s contre des "
              "diagnostics qui ont coûté des sessions. Depuis le 01/09, signale AUSSI tout "
              "`{% load %}` vers une bibliothèque de balises absente (garde posée le jour où un "
              "retrait de templatetag a laissé son load — page reader en TemplateSyntaxError)",
              'wama/common/management/commands/check_templates.py', 'AGENTS.md',
              annexes=('wama/common/tests_check_templates.py',),
              symbol='check_templates'),
    # Ces deux-là TOURNENT CHAQUE NUIT (`nightly_scenarios.py:137,145`) et étaient pourtant hors
    # carte — le pire cas : pas une brique morte, une garde active que personne ne trouve en
    # cherchant « qu'est-ce qui contrôle la sécurité ? ». Rattachées le 2026-08-27.
    Mechanism('dep_vulns', 'Vulnérabilités des dépendances',
              "CVE des paquets INSTALLÉS du venv courant via l'API OSV.dev (pas les requirements, "
              "qui sont des bornes basses). Contrat-cliquet : la dette connue vit dans une "
              "baseline versionnée par venv, toute vulnérabilité nouvelle est rouge",
              'wama/common/management/commands/check_dep_vulns.py', 'docs/construction/suivi/ROADMAP.md §16.10',
              symbol='check_dep_vulns'),
    Mechanism('secret_leaks', 'Fuites de secrets',
              "gitleaks sur l'historique git COMPLET + vérifie que le hook pre-commit est en "
              "place et non dérivé : un hook mort est une garde silencieusement absente, donc "
              "rouge et pas warning",
              'wama/common/management/commands/check_secret_leaks.py', 'docs/construction/suivi/ROADMAP.md §16.10',
              symbol='check_secret_leaks'),

    )),

    *_domain('Contenu & prompts', (
    Mechanism('prompt_pipeline', 'Pipeline de prompts',
              "Traduction/enrichissement centralisés, déclarés par PROMPT_TARGETS",
              'wama/common/utils/prompt_enrichment.py', 'docs/construction/ia/WAMA_LLM.md',
              annexes=('wama/common/utils/app_metadata.py',
                       'wama/common/utils/prompt_pipeline.py',
                       'wama/common/utils/prompt_skills.py',
                       'wama/common/utils/reference_comprehension.py',
                       'wama/common/static/common/js/wama-prompt-chips.js',
                       'wama/common/static/common/js/wama-prompt-enrich.js')),
    Mechanism('llm', 'Accès LLM',
              "Route unique vers les LLM (tiers déclaratifs, sélection catalogue, Ollama local)",
              'wama/common/utils/llm_utils.py', ''),
    Mechanism('assistant_skills', "Skills de rôle de l'assistant",
              "Posture et domaine de l'assistant (science, design, dev) + rappel du "
              "contexte de laboratoire, déclarés par domaine — distinct de l'enrichissement",
              'wama/common/utils/assistant_skills.py', 'docs/construction/suivi/ROADMAP.md §19.7'),
    Mechanism('claude_code', "Claude Code sur abonnement",
              "Délègue une tâche de développement au CLI Claude Code en headless — "
              "lecture seule par défaut, environnement construit sans la clé API",
              'wama/common/services/claude_code.py', 'docs/construction/suivi/ROADMAP.md §19.3'),
    Mechanism('gateway_identity', "Appariement d'identité de canal",
              "Relie une identité Matrix/Discord à un compte WAMA par code prouvé hors "
              "canal — la garde que tout adaptateur appelle avant d'agir",
              'wama/gateway/services.py', 'docs/construction/suivi/ROADMAP.md §19',
              annexes=('wama/gateway/models.py',)),
    # Un QR ENCODE, il ne PROUVE rien : celui d'appariement épargne la retape du code,
    # la preuve reste la session authentifiée (cf. docstring du module).
    Mechanism('qr', 'Générateur de QR codes',
              "Encode un texte/URL en PNG/SVG (segno, déterministe) — QR d'appariement "
              "de la passerelle aujourd'hui ; enrôlement TOTP et domaine Imager demain",
              'wama/common/utils/qr.py', 'docs/construction/suivi/ROADMAP.md §19'),
    Mechanism('assistant_engine', "Moteur de l'assistant IA",
              "Boucle agentique multi-surface (prompts, outils tool_api, local/cloud) — "
              "la vue web et /api/v1/assistant/chat/ en sont des clients",
              'wama/common/services/assistant_engine.py', '',
              # wama-avatar.js = le RENDU de l'assistant vocal (avatar 3D navigateur,
              # three.js/TalkingHead, greffé sur WamaApp.Speech — zéro VRAM serveur) : brique
              # FRONT du même mécanisme, donc annexe et pas entrée séparée.
              # wama-avatar-panel.js + _assistant_avatar.html (2026-09-22) = sa PRÉSENCE : le
              # conteneur en tête du volet de TOUTE page (base.html), la préférence durable
              # (`avatar`/`avatar_collapsed` du schéma assistant/params.py), le repli.
              # + le 22/09 (soir) : la VOIX commune (`wama-assistant-voice.js` — phrases, bouton
              # 🔊/🔇/⏹ qui arrête une lecture) et le MINI-CHAT du volet (`wama-assistant-chat.js`,
              # même fil `web` que l'accueil, servi par `views.ai_chat_thread`) : l'assistant se
              # parle depuis toute page, dans l'accordéon « Assistant ».
              annexes=('wama/common/static/common/js/wama-avatar.js',
                       'wama/common/static/common/js/wama-avatar-panel.js',
                       'wama/common/static/common/js/wama-assistant-voice.js',
                       'wama/common/static/common/js/wama-assistant-chat.js',
                       'wama/common/static/common/css/wama-assistant-panel.css',
                       'wama/common/templates/common/_assistant_avatar.html'),
              symbol='run_assistant_turn'),
    Mechanism('conversation_store', "Historique de conversation (serveur)",
              "L'historique de l'assistant côté SERVEUR — remplace le localStorage web et le "
              "dict en mémoire de la passerelle (perdus au changement de navigateur / au "
              "redémarrage). COUCHE AU-DESSUS du moteur, jamais une dépendance : "
              "run_assistant_turn continue d'accepter un history explicite (moteur sans état, "
              "testable sans base). Consommé par la vue web ET la passerelle de canaux "
              "(gateway/core, discord_bot) — cf. ROADMAP §19.5",
              'wama/common/services/conversation_store.py', 'docs/construction/suivi/ROADMAP.md §19.5',
              annexes=('wama/common/tests_conversation.py',),
              # `symbole` : ses clients l'importent par `from wama.common.services import
              # conversation_store` — le compteur d'imports ne voit pas cette graphie (même
              # faux positif que le middleware, cf. plus haut).
              symbol='conversation_store'),
    Mechanism('source_ingest', 'Ingest de source',
              "Télécharge une source distante vers le FileField, déclaré par WAMA_INGEST",
              'wama/common/utils/source_ingest.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/utils/url_ingest.py',)),
    # Garde de SORTIE, distincte de l'ingest : l'ingest sait CHERCHER, celle-ci dit OÙ il a le
    # droit d'aller. Séparées parce que tout nouvel appelant réseau doit la traverser, même
    # s'il n'a rien à voir avec WAMA_INGEST.
    Mechanism('url_guard', 'Garde des URL sortantes',
              "Valide toute cible de téléchargement pilotée par une saisie : schéma, "
              "identifiants, et adresses privées/bouclage/lien-local — anti-SSRF",
              'wama/common/utils/url_guard.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md'),
    # Distincte d'url_ingest : l'ingest livre un FICHIER aux apps ; celle-ci livre du TEXTE
    # borné à un prompt (recherche sans clé + lecture plafonnée, chaque lecture via url_guard).
    Mechanism('web_search', 'Recherche & lecture web',
              "Recherche internet + page → texte plafonné (octets ET caractères) pour "
              "l'investigation de l'assistant (outils search_web/read_web_page)",
              'wama/common/utils/web_search.py', 'docs/construction/ia/WAMA_LLM.md',
              symbol='search_web'),
    # L'index inverse « fichier → capacités » : cibles par PORT (travail/référence), jamais
    # par input_types à plat ; les mondes s'y déclarent par SONDE (wama_data pousse la sienne).
    Mechanism('intake', 'Intake universel de fichiers',
              "Que peut faire WAMA de ce fichier ? — ports d'app + lot + manifeste + "
              "médiathèque + sondes des mondes (outil assistant inspect_user_file)",
              'wama/common/utils/intake.py', 'docs/construction/ia/WAMA_LLM.md',
              symbol='capabilities_for_path'),
    Mechanism('document_export', 'Export document',
              "Génère PDF (fpdf2) / DOCX (python-docx) depuis les résultats d'app",
              'wama/common/utils/document_export.py', ''),

    )),

    *_domain('Manifestes & registres', (
    Mechanism('manifests', 'Manifestes',
              "Extraction/validation/projection des 7 kinds vers les registres",
              'wama/common/manifests/ingest.py', 'docs/construction/architecture/WAMA_MANIFEST_ARCHITECTURE.md',
              # Annexes complétées le 2026-08-31 (audit) : le dossier `manifests/` entrait au
              # balayage et ces modules — enveloppe, vocabulaire des kinds, table de projection,
              # les 7 kinds builtin — sont le CORPS du mécanisme, pas des voisins.
              annexes=('wama/common/services/library_index.py',
                       'wama/common/manifests/envelope.py',
                       'wama/common/manifests/kinds.py',
                       'wama/common/manifests/projection.py',
                       'wama/common/manifests/builtin/app.py',
                       'wama/common/manifests/builtin/dataset.py',
                       'wama/common/manifests/builtin/function.py',
                       'wama/common/manifests/builtin/library.py',
                       'wama/common/manifests/builtin/model.py',
                       'wama/common/manifests/builtin/pipeline.py',
                       'wama/common/manifests/builtin/project.py')),
    # Entrée créée le 2026-08-31 (audit) : la chaîne était HORS carte — 5 gabarits sur 7 sans
    # domicile ni annexe, dossier hors balayage, donc AUCUN signal possible. 5ᵉ occurrence de
    # la leçon « un dossier hors balayage naît invisible » (cf. doc_facts.py, dossiers_balayes).
    Mechanism('codegen', "Gabarits de génération d'app (marches S2 + B1)",
              "Rend le code CONVENTIONNEL d'une app depuis son manifeste — une cible par "
              "fichier (apps/urls/models/params/tasks/views/templates), consommées par "
              "`app_sandbox substitute` et le write-back ; le hors-convention reste un TROU "
              "NOMMÉ (stubs 501, commentaires [manifest-gen]), jamais un manque silencieux. "
              "Depuis le 02/09 (marche B1 CLOSE), le corps des TÂCHES se COMPOSE aussi : "
              "`backends/__init__.ROUTES` de l'app (nature → callable au contrat commun) "
              "monte au manifeste (processing.backend_routes) et tasks_gen émet l'appel — "
              "import relatif au paquet, la jumelle a CONVERTI (SUCCESS mesuré). "
              "DEUX SAVEURS depuis le 03/09 (2ᵉ app routée, describer) : `RESULT` déclare "
              "ce que les backends produisent — 'file' (le backend écrit output_path) ou "
              "'text' (il REND le texte, la tâche le persiste dans la colonne déclarée et "
              "publie l'aperçu partiel) ; `NATURE_FIELD` nomme la colonne de nature. "
              "⚠ Un fichier substitué doit exposer TOUT ce que les fichiers COPIÉS lui "
              "importent : params_gen émet l'alias `<X> = <X>_JSON` (le models copié importe "
              "la graphie courte — ImportError au rendu de CHAQUE card sinon)",
              'wama/common/manifests/codegen/templates_gen.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/manifests/codegen/apps_gen.py',
                       'wama/common/manifests/codegen/urls_gen.py',
                       'wama/common/manifests/codegen/models_gen.py',
                       'wama/common/manifests/codegen/params_gen.py',
                       'wama/common/manifests/codegen/tasks_gen.py',
                       'wama/common/manifests/codegen/views_gen.py')),
    Mechanism('backend_inventory', 'Vivier des backends (registre DÉRIVÉ)',
              "Inventaire des moteurs de WAMA, dérivé À CHAQUE AFFICHAGE des déclarations "
              "`wama/<app>/backends/` (ROUTES/RESULT/NATURE_FIELD + classes BaseModelBackend "
              "trouvées jusque dans les SOUS-MODULES) recoupées au catalogue AIModel. Deux "
              "usages : la vision d'ensemble (12ᵉ registre, page /common/backends/) et le "
              "VOISINAGE que le LLM de la marche B trie pour s'inspirer du backend le plus "
              "approchant (signature « natures → saveur », paquets, VRAM, modèles servis). "
              "Ne stocke RIEN et n'a pas de rafraîchisseur — une page qui DÉRIVE ne peut pas "
              "diverger de ses sources. Ne cite aucune app : il parcourt les apps installées "
              "(le registre ne connaît jamais ses producteurs). "
              "⚠ MISE À JOUR 2026-09-06/07 — le lien FIN EXISTE désormais et `backend_ref` "
              "n'absout plus : le modèle déclare son moteur (`composition.runtime.engine`), le "
              "backend déclare celui qu'il pilote (`ENGINE`) et ce qu'il sert "
              "(`SUPPORTED_MODELS`), et l'inventaire porte les COORDONNÉES D'IMPORT pour "
              "résoudre PARESSEUSEMENT. Mesuré : 108/116 modèles déclarent leur moteur "
              "(14 la veille), 97 résolvent leur backend réel. `backend_ref` ne sert plus "
              "qu'à la PROVENANCE du lien",
              'wama/common/services/backend_inventory.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/templates/common/backends.html',
                       'wama/common/tests_backend_inventory.py')),
    Mechanism('backend_resolution', 'Résolution de backend par DÉCLARATION',
              "Une app ne demande plus un MODULE, elle demande « le backend qui sait exécuter "
              "ce modèle » : `backend_for_model()` va de `composition.runtime.engine` (moitié "
              "modèle) à `BaseModelBackend.ENGINE` (moitié backend), départagé par "
              "`SUPPORTED_MODELS` quand le moteur est PARTAGÉ — `diffusers` est piloté par 8 "
              "backends, `transformers` par 4. L'import de la classe est CIBLÉ et TARDIF : le "
              "registre reste statique. C'est ce qui rend l'EMPLACEMENT PHYSIQUE des backends "
              "indifférent, préalable à leur passage au substrat transversal. "
              "⚠ Rend None plutôt qu'un tirage quand rien ne tranche — une erreur silencieuse "
              "coûte plus cher qu'un refus ; et ne rend QUE des sous-classes du contrat (le "
              "porteur du démon Ollama n'en est pas un)",
              'wama/common/backends/manager.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              symbol='backend_for_model',
              annexes=('wama/common/management/commands/check_backend_links.py',
                       'wama/common/tests_backend_inventory.py')),
    Mechanism('model_declarations', "Passe-plat des déclarations de modèle",
              "Lire la déclaration d'un modèle SANS importer l'app qui la porte : applique la "
              "convention `wama/<app>/utils/model_config.py::<APP>_MODELS`, ne connaît aucune "
              "app, et surtout ne touche AUCUNE BASE. "
              "⚠ Le catalogue `AIModel` porte la même information, mais le lire ajouterait une "
              "dépendance ORM à chaque backend — or c'est justement l'absence de Django qui les "
              "rend déplaçables. On lirait la bonne donnée en détruisant la propriété cherchée",
              'wama/common/utils/model_declarations.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              symbol='declaration',
              annexes=('wama/common/tests_backend_inventory.py',)),
    Mechanism('backend_isolation', "Environnement d'exécution d'un backend",
              "`ISOLATION` déclare où tourne un backend (`venv:<chemin>` | `service:<url>`, "
              "vide = venv principal). Sans elle le GRISAGE MENT : `missing_packages()` "
              "interroge `find_spec` dans CE processus, verdict muet sur un backend qui vit "
              "ailleurs. Le défaut est UN venv — l'isolement se DÉCLARE, ne se génère jamais : "
              "son coût n'est pas le disque mais la VRAM, chaque processus isolé étant un "
              "détenteur que le gouverneur ne voit pas. Zéro isolement aujourd'hui",
              'wama/common/backends/base.py', 'docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md',
              symbol='ISOLATION',
              annexes=('wama/common/tests_backend_inventory.py',)),
    Mechanism('hf_weights', 'Routage des poids hors HuggingFace',
              "QUATRE leviers pour tenir la règle « modèle principal catégorisé, "
              "sous-dépendances au cache partagé » (ROADMAP §5b), et le choix est imposé par la "
              "LIB, pas par le goût : A `cache_dir=` — B un CHEMIN local (`poids_locaux`) — "
              "C la variable propre à la lib, posée dans settings (`DEEPFACE_HOME`, "
              "`AUDIOCRAFT_CACHE_DIR`) — D `hf_cache_scope`, DERNIER RECOURS déclaré. "
              "⚠ D restaure l'environnement mais JAMAIS LES FICHIERS : ce que la lib télécharge "
              "pendant la fenêtre reste dans le dossier du modèle — c'est ainsi que "
              "`timm/resnet18` a atterri chez table-transformer. Zéro mutation d'environnement "
              "dans le code aujourd'hui",
              'wama/common/utils/hf_weights.py', 'docs/construction/suivi/ROADMAP.md',
              symbol='poids_locaux',
              annexes=('wama/common/utils/hf_cache.py',
                       'wama/common/tests_hf_cache_routing.py')),
    Mechanism('result_tabs', 'Onglets de résultat TEXTE',
              "Un item peut avoir PLUSIEURS lectures d'un même résultat (transcription, "
              "diarisation, résumé, cohérence). Le schéma canonique ne portait qu'UN "
              "`result_text` — d'où deux modales à onglets quasi identiques, tracées au "
              "`REMOVAL_LEDGER R18` depuis le 22/07. Les facettes se déclarent désormais dans "
              "la SPEC DE DÉTAIL de l'app (donc extractibles au manifeste, facette `inspector`, "
              "et projetables), et un partial commun les rend. "
              "⚠ Ce n'est PAS une 2ᵉ mécanique de preview : la preview de CARD reste "
              "`PreviewRegistry`, et les autres apps n'ont qu'une lecture — ou plusieurs "
              "RÉSULTATS dans une seule preview (imager, `result_files`)",
              'wama/common/templates/common/_result_tabs.html', 'docs/construction/ui/CARD_DESIGN.md',
              annexes=('wama/common/utils/detail_registry.py',
                       'wama/common/tests_result_tabs.py')),
    Mechanism('apply_manifests', 'Application du corpus de manifestes',
              "Le sens ENTRANT du corpus : `manifest_export` écrit les manifestes DEPUIS les "
              "registres, rien ne les appliquait DANS l'autre sens. Sur une installation neuve, "
              "les 16 manifestes de librairies restaient lettre morte. "
              "⚠ Kind par kind, et le choix est de NATURE : `library` est une déclaration pure "
              "(aucune I/O) → appliquée à l'installation ; `model` NON, car le catalogue reflète "
              "le DISQUE et sa vérité est le balayage (déjà périodique) — l'appliquer créerait "
              "des lignes pour des poids absents. Dry-run par défaut",
              'wama/common/management/commands/apply_manifests.py',
              'docs/construction/architecture/WAMA_MANIFEST_ARCHITECTURE.md'),
    Mechanism('output_formats', 'Formats de sortie',
              "Source commune des formats+qualités de fichier par domaine (réutilise le vocabulaire converter)",
              'wama/common/utils/output_formats.py', ''),
    Mechanism('license_audit', 'Audit des licences',
              "Vue dérivée : licences+auteurs des 4 registres, traversée par app. "
              "Ne voit PAS le code vendorisé (`static/vendors/`, codeformer) — inventorié à "
              "la main dans LICENSING.md §3",
              'wama/common/services/license_audit.py', 'docs/construction/exploitation/LICENSING.md'),
    Mechanism('mechanisms_scan', 'Adoption des mécanismes',
              "Qui consomme quoi (imports + briques front), niveau APP vs infrastructure, et "
              "jonction registre↔grille : mécanisme adopté par des apps que rien ne vérifie",
              'wama/common/services/mecanismes_scan.py', 'docs/construction/architecture/WAMA_MECANISMES.md'),
    Mechanism('conformity', 'Grille de conformité',
              "Mesure les 8 facettes F1–F8 des apps par analyse du code réel",
              'wama/common/services/conformity_checker.py', 'docs/construction/architecture/WAMA_APP_CONVENTIONS.md'),
    # ⚠ Déclaré ICI et non entre deux groupes : hors d'un `_domain()` une entrée perd son
    # domaine, donc n'apparaît dans AUCUNE sous-table de la carte — invisible, pas fausse.
    # C'était son état jusqu'au 2026-08-22 (seul cas sur 88, trouvé par `tests_catalogues`).
    Mechanism('app_sandbox', "Bac à sable d'apps (jumelles exécutables)",
              "Jumelle <app>_NN coexistante pour comparaison Playwright + diff par témoins "
              "(route §10.3 marches S/S2) — registre sandbox_apps.json injecté au boot "
              "(INSTALLED_APPS/urls/gating/catalogue) ; create/drop symétriques + "
              "`substitute <label> <cible>` : remplace UN fichier copié par sa version "
              "GÉNÉRÉE (cibles = gabarits `codegen`), témoin `.temoin` préservé, re-mesure, "
              "auto-revert sur échec — verdicts journalisés au registre ; `revert <label> "
              "<cible>` ramène une cible au témoin à la demande. "
              "TROIS JUGES depuis le 03/09, chacun né d'un défaut qui RENDAIT (page 200) "
              "sans FONCTIONNER : ① cohérence de paquet par AST (tout `from .x import Y` "
              "intra-paquet, imports PARESSEUX compris, doit résoudre) ; ② couple "
              "views↔templates (substituer les templates seuls = boutons morts) ; ③ smoke "
              "« file HABITÉE » (témoin créé→page rendue→supprimé : une file vide ne rend "
              "AUCUNE card, donc ne teste rien du rendu de card). "
              "Le gate d'acceptation d'une jumelle reste sa BATTERIE UI auto-dérivée "
              "(11 scénarios `<label>.*` du registre nocturne) : describer_01 = 11/11",
              'wama/common/sandbox.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/management/commands/app_sandbox.py',
                       'wama/common/tests_sandbox_coherence.py')),

    )),

    *_domain("File d'attente & lots", (
    # Déclarés parce que AGENTS.md les nomme explicitement « ce qui existe déjà dans common/ —
    # à utiliser, ne pas recréer » : ne pas les tracer ici laisserait la carte en dessous des
    # instructions du dépôt.
    Mechanism('queue_duplication', 'Duplication et suppression sûres',
              "duplicate_instance() et safe_delete_file() — fichiers partagés entre items",
              'wama/common/utils/queue_duplication.py', 'docs/construction/architecture/WAMA_APP_CONVENTIONS.md'),
    Mechanism('batch', 'Import par lot',
              "Parsing des fichiers batch (txt/csv/pdf/docx) et cycle de vie du lot",
              'wama/common/utils/batch_parsers.py', 'docs/construction/ui/BATCH_FORMAT.md',
              annexes=('wama/common/utils/batch_common.py',
                       'wama/common/utils/batch_sync.py',
                       'wama/common/static/common/js/batch-import.js')),
    Mechanism('queue_view', 'Tri/filtrage de la file',
              "Tri + filtrage communs de la file unifiée, préférence persistée et PARTAGÉE entre apps",
              'wama/common/utils/queue_view.py', 'docs/construction/ui/CARD_DESIGN.md'),
    Mechanism('queue_manipulation', 'Manipulation directe de la file',
              "Endpoints génériques : sortir une card d'un batch, réordonner DANS un lot, "
              "ordonner la FILE (`reorder_queue`, 2026-09-04), déplacer, FUSIONNER (`merge`) et "
              "consolider. ⚠ `merge` ≠ `consolidate` : le premier fusionne en UN lot et REFUSE "
              "si les natures ne cohabitent pas (geste du drag&drop, on a visé une card) ; le "
              "second RANGE par nature en N lots (chemin d'import) et 5 apps le redéfinissent. "
              "La compatibilité n'est pas redéclarée : `group_key` reçoit la MÊME fonction que "
              "le `nature_of` de l'import (vérifié par AST, tests_queue_dnd)",
              'wama/common/utils/queue_manipulation.py', 'docs/construction/ui/CARD_DESIGN.md §3bis'),
    Mechanism('batch_views', 'Vues de lot (fabrique commune)',
              "Les six ACTIONS de lot en une fabrique — `make_batch_views` : batch_start, "
              "batch_update, batch_delete, batch_duplicate, batch_download, batch_status — "
              "paramétrée comme la fabrique de file (les deux formes de rattachement par "
              "`batch_elements`/`attach_to_batch`). EXTRAITE le 2026-09-22 des corps "
              "conventionnels du générateur d'apps (`views_gen`), qui la consomme ; les apps "
              "réelles les écrivaient chacune à la main (60 lectures de lot recopiées, "
              "`ROUTE §11 #36`) — ADOPTÉE 10/10 le 2026-09-23, spécificités en kwargs (jamais un "
              "`if app`), chaque élément lu portant `batch_link` (la ligne qui le porte) ; restent "
              "locaux, assumés, les `batch_download` multi-format et les `batch_update` à logique "
              "propre (critère `batch_views_common` : vrai ou partiel, plus jamais rouge)",
              'wama/common/utils/batch_views.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §11'),
    Mechanism('queue_dnd', 'Glisser-déposer et sélection multiple de la file',
              "Les QUATRE gestes de manipulation directe, hérités par les 12 apps sans qu'aucune "
              "n'écrive une ligne : déposer SUR une card change l'APPARTENANCE (entrer dans un "
              "lot / en former un), déposer ENTRE deux cards change l'ORDRE (file ou lot) ; "
              "sélection multiple clic/Ctrl/Maj, qui EST celle de l'inspecteur (une seule "
              "sélection dans WAMA — la brique ANNONCE `wama:selection-change`, l'inspecteur "
              "REND). Auto-monté sur `[data-wama-dnd]`, posé par le templatetag "
              "`queue_dnd_attrs` : une app qui ne le pose pas garde une file strictement inerte. "
              "SortableJS écarté (multi-sélection + fusion sur une card + règle « pas de CDN »)",
              'wama/common/static/common/js/wama-queue-dnd.js', 'docs/construction/ui/CARD_DESIGN.md §3bis',
              symbol='WamaQueueDnd',        # global de base.html : compté par son symbole
              annexes=('wama/common/static/common/css/wama-queue-dnd.css',
                       'wama/common/templatetags/wama_actions.py',
                       'wama/common/tests_queue_dnd.py')),
    Mechanism('history', 'Historique annuler / rétablir',
              "Deux piles + plafond + état des boutons + raccourcis Ctrl+Z / Ctrl+Maj+Z / Ctrl+Y. "
              "PORTABLE parce que la machinerie ne touche JAMAIS le modèle : elle ne le connaît "
              "que par `snapshot()` et `restore(state)`, que l'appelant fournit. La coalescence "
              "des rafales de frappe (`burstWindow`) est une OPTION, pas un acquis — elle n'a "
              "aucun sens sur un éditeur non textuel, où chaque mutation est déjà atomique. "
              "⚠⚠ La FILE D'ATTENTE ne peut PAS l'utiliser : ses gestes sont commis côté serveur "
              "à l'instant du dépôt, il n'y a pas de modèle client à photographier — son "
              "« annuler » est un REJEU D'OPÉRATION INVERSE, même mot, mécanisme différent. Les "
              "réunir ici donnerait une API qui MENT sur ce qu'elle garantit. "
              "DEUX consommateurs, et deux façons de marquer un cran — c'est l'ADOPTION qui l'a "
              "révélé : `push()` AVANT la mutation (transcriber, qui marque en tête de chaque "
              "opération) et `commit()` APRÈS (studio, dont les 9 opérations passent par UN "
              "entonnoir, `persistDraft`). La v1 n'offrait que `push()` : suffisant pour le "
              "consommateur dont elle sortait, insuffisant pour le suivant. `silence(fn)` couvre "
              "le chargement programmatique, et la garde de RÉ-ENTRANCE vit dans la brique — "
              "restaurer c'est muter (`loadGraph`→`clearCanvas`→`removeNode`→l'entonnoir), donc "
              "tout consommateur à entonnoir remplirait son historique de son propre travail",
              'wama/common/static/common/js/wama-history.js', 'docs/construction/ui/CARD_DESIGN.md',
              annexes=('wama/transcriber/static/transcriber/js/edit.js',
                       'wama/studio/static/studio/js/wama-studio.js')),
    Mechanism('queue_order', 'Ordre MANUEL de la file',
              "Position de l'entrée de file décidée par l'utilisateur (`QueueOrderMixin."
              "queue_index`, 13 modèles de batch) + 6ᵉ tri « Manuel » — le SEUL tri qui LIT une "
              "colonne au lieu de la calculer. `queue_index == 0` = jamais ordonné à la main, et "
              "passe EN TÊTE par récence : une file jamais manipulée s'affiche comme en tri "
              "`recent`, et un import arrivé après un classement manuel apparaît en haut au lieu "
              "de se noyer dans un ordre qu'il n'a pas connu. `reorder_queue` écrit 1..N",
              'wama/common/models.py', 'docs/construction/ui/CARD_DESIGN.md §3bis',
              annexes=('wama/common/utils/queue_view.py',
                       'wama/common/templates/common/_queue_toolbar.html')),
    Mechanism('queue_front', "File d'attente (front)",
              "Comportements communs des files : collapse de batch persisté, mode Solitaire "
              "(accordéon), toggle Ligne/Mosaïque, les 3 densités et le modificateur PILE "
              "(CARD_DESIGN §11.4/§11.9), focus card, clearCards, data-wama-*",
              'wama/common/static/common/js/wama-queue.js', 'docs/construction/ui/CARD_DESIGN.md',
              symbol='WamaQueue',           # global de base.html : compté par son symbole
              annexes=('wama/common/static/common/js/queue-actions.js',
                       'wama/common/templates/common/_queue_toolbar.html',
                       'wama/common/templates/common/_queue_actions.html',
                       'wama/common/templates/common/_batch_card.html')),
    Mechanism('queue_entry', "Entrée de file (card seule OU lot)",
              "Décide, pour une entrée de file, si elle s'affiche en card unique ou en card MÈRE "
              "avec ses filles repliables — et rend l'un ou l'autre. Le bloc vivait recopié À "
              "L'IDENTIQUE dans les gabarits d'app (10 au dernier compte — le partial fait foi) ; "
              "il n'a pu être centralisé (2026-08-25) qu'une fois "
              "deux verrous levés : `is_unitary` adopté (la décision se lit sur le modèle) et "
              "`elem` (les cards filles reçoivent leur élément sous le MÊME nom — avant, 8 "
              "graphies). Signature à 3 paramètres : `card_template`, plus `collapse_prefix` et "
              "`batch_key` pour la seule app à deux files sur une page (enhancer audio). ⚠ Tout "
              "le reste TRAVERSE PAR LE CONTEXTE — les ~9 paramètres de `_batch_card.html` sont "
              "fournis par l'app et passent au travers, sinon la signature atteindrait la "
              "quinzaine. Apparence uniformisée sur le TRANSCRIBER (référence), conforme à "
              "`CARD_DESIGN §11.2` (famille de lot = cyan #0dcaf0) : les 3 couleurs et 2 "
              "habillages qui coexistaient étaient des séquelles d'implémentations successives. "
              "Depuis le 2026-09-15 l'entrée porte `data-card-url` : quand une suppression réduit "
              "un lot à une card, `queue-actions.js` la redemande au serveur et la file se met à "
              "jour sans rechargement de la page (la vue dit l'état du lot : "
              "`batch_common.batch_state` ; la position d'une card seule : `is_batch_child`)",
              'wama/common/templates/common/_queue_entry.html', 'docs/construction/ui/CARD_DESIGN.md §11.2',
              annexes=('wama/common/utils/batch_common.py',
                       'wama/common/models.py',
                       'wama/common/static/common/js/queue-actions.js',
                       'wama/common/tests_queue_delete_contract.py')),
    Mechanism('output_naming', 'Nom du fichier de sortie',
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
              'wama/common/utils/output_naming.py', 'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md',
              annexes=('wama/common/backends/anonymize.py',)),
    Mechanism('media_integrity', 'Intégrité des médias',
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
              'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md', symbol='check_media_integrity'),
    Mechanism('work_dir', 'Dossier de travail jetable',
              "Les fichiers INTERMÉDIAIRES d'un traitement ne vivent pas dans `media/`. Mesuré le "
              "2026-08-25 : `media/avatarizer/` pesait 1,69 Go pour 2101 fichiers dont 99,6 % de "
              "PNG — les frames de CodeFormer, écrites dans le dossier de sortie du job et jamais "
              "nettoyées ; `job_11` portait 1715,7 Mo pour une vidéo de 0,70 Mo. `media/` ne "
              "contient que `<app>/<user>/input|output/` et `users/` (MEDIA_STORAGE_TIERING.md) : "
              "un fichier de travail y est sauvegardé par le miroir, compté par le tiering et "
              "servi par Apache pour rien. Le `with` rend le nettoyage STRUCTUREL au lieu d'être "
              "une convention qu'on oublie. ADOPTÉ par 5 sites (avatarizer/codeformer, "
              "describer/views, enhancer/views, reader/glm_ocr, describer/video_describer) ; "
              "le dernier site, la boucle vidéo de l'enhancer (ex-`tasks.py:534`), est porté depuis le "
              "26/08 et vit depuis le 21/09 dans sa route `enhancer/backends/media_backend.py:82` "
              "(la glu `enhancer/tasks.py:156` en ouvre un second pour ranger la sortie). ⚠⚠ L'audit AUTOMATIQUE "
              "des `mkdtemp` a mal classé 2 sites sur 6 — `glm_ocr` déléguait par contrat "
              "DOCUMENTÉ, `enhancer/tasks` nettoyait déjà — mais la lecture site par site a "
              "trouvé l'inverse, des fuites qu'aucun motif ne voyait : un `rmdir` conditionné à "
              "« si le dossier est vide » qui ne se déclenchait donc jamais, un nettoyage placé "
              "APRÈS l'appel qui sautait sur exception, et un `except ImportError` qui empêchait "
              "un repli d'exister. Un relevé par motif oriente ; il ne conclut pas. "
              "Porte aussi `purge_job_dir` : la suppression d'une card doit emporter le dossier du "
              "job — 13 dossiers `job_*` orphelins relevés contre 4 rattachés",
              'wama/common/utils/work_dir.py', 'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md',
              annexes=('wama/common/backends/codeformer_backend.py',
                       'wama/avatarizer/views.py')),
    Mechanism('console', 'Console utilisateur',
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
    Mechanism('notifications', 'Notifications de tâche',
              "notify_job() — fin de traitement, succès comme échec",
              'wama/common/utils/notifications.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md'),

    )),

    *_domain('UI générée', (
    # Les briques FRONT d'un mécanisme (js/partials) sont ses ANNEXES : même identité, le
    # comptage voit alors aussi les gabarits qui les référencent (balise <script>, include).
    Mechanism('param_schema', 'Schéma de paramètres',
              "Source unique des réglages d'app : volet droit, modales (item ET lot, "
              "`context`) et DÉFAUTS APPLICABLES d'un élément naissant (applicable_defaults, "
              "filtre show_if au vocabulaire du moteur JS) sont dérivés de lui. Depuis le "
              "01/09 il porte AUSSI LA cascade des valeurs effectives (effective_settings : "
              "défauts du schéma ← preset ← réglages POSÉS — formulation Fabien, ROADMAP "
              "§23.2bis) : la base ne stocke que le POSÉ (vide = « le preset décide »), les "
              "défauts restent au schéma — c'est ce qui rend un preset POSSIBLE, et ce qui a "
              "remplacé resolve_options du converter + les défauts en dur des backends",
              'wama/common/utils/param_schema.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/static/common/js/wama-params.js',
                       'wama/common/templates/common/_settings_modal_footer.html')),
    Mechanism('model_capabilities', 'Vocabulaire des capacités',
              "Canonicalise capabilities (tâche, modalités, entrées) — source du filtrage UI",
              'wama/common/utils/model_capabilities.py', 'docs/construction/ui/INPUT_MODEL_MATCHING.md',
              annexes=('wama/common/static/common/js/wama-model-caps.js',
                       'wama/common/static/common/js/wama-input-match.js',
                       # Côté SERVEUR de wama-input-match (meta catalogue + labels INPUT_TYPES),
                       # extrait de composer/imager le 2026-08-17 (adoption ×7).
                       'wama/common/utils/input_match.py',
                       # Spécialisation TTS du côté serveur : les DEUX apps à select de moteur
                       # TTS (synthesizer, avatarizer) lisent le même catalogue. Extrait de
                       # synthesizer/views.py au 2ᵉ consommateur, 2026-08-28.
                       'wama/common/tts/ui_meta.py',
                       'wama/common/static/common/js/wama-model-help.js')),
    Mechanism('detail_registry', 'Inspecteur — champs de détail',
              "Schéma canonique des infos d'item affichées au volet droit",
              'wama/common/utils/detail_registry.py', 'docs/construction/ui/INSPECTOR_DETAIL_FIELDS.md',
              annexes=('wama/common/static/common/js/wama-inspector.js',
                       'wama/common/static/common/js/wama-inspector-autofill.js',
                       'wama/common/templates/common/_inspector_actions.html',
                       'wama/common/templates/common/_inspector_banner.html')),
    Mechanism('preview', 'Preview unifiée',
              "Registre d'adaptateurs par modèle : la preview des cards vient du commun, pas des apps ; "
              "un MIME `model/…` ouvre la visionneuse 3D commune (`wama-3d-viewer.js`, three "
              "vendorisé), chargée À LA DEMANDE par l'importmap — sans importmap, téléchargement "
              "(2026-09-13, §17ter trou 2)",
              'wama/common/utils/preview_registry.py', '',
              annexes=('wama/common/utils/preview_utils.py',
                       'wama/common/static/common/js/media-preview.js',
                       'wama/common/static/common/js/wama-3d-viewer.js',
                       'wama/common/templates/common/_three_importmap.html')),
    Mechanism('card_gear', 'data-* du gear ⚙ des cards',
              "data-* du ⚙ DÉRIVÉS du schéma (contrat cardSettings de l'inspecteur, qui lit "
              "la RACINE de card PUIS le bouton) — schéma en objets Param OU en dicts "
              "(chemin des vues générées) ; booléens 'true'/'false', tous les params item "
              "émis (anti-résidus)",
              'wama/common/utils/card_gear.py', ''),
    Mechanism('card_chips', 'Chips méta des cards',
              "Chips des cards GÉNÉRÉS du schéma params (chip=True), groupés par section v3 "
              "(chips_by_section) ; `values` pour les réglages vivant en JSON (même assiette "
              "que card_gear), `extra` pour les chips d'app déjà formés. Porte aussi les "
              "réglages COMMUNS aux filles pour la card MÈRE (common_chips_for_items + "
              "partial _batch_meta_chips — slot meta_template, généralisation du pilote "
              "transcriber, porté aux 10 apps le 31/08) et les propriétés d'ENTRÉE "
              "(input_props_for, extraite du pilote reader)",
              'wama/common/utils/card_chips.py', 'docs/construction/ui/CARD_DESIGN.md §10.3',
              annexes=('wama/common/templates/common/_card_chips.html',
                       'wama/common/templates/common/_batch_meta_chips.html')),
    # Entrées créées le 2026-08-31 (audit) — trois briques du périmètre UI sans identité :
    # l'inspecteur n'existait sur la carte que comme annexe/domicile d'autres entrées, la
    # 6ᵉ action de card (⬇) n'avait aucune entrée, la déclaration du volet non plus.
    Mechanism('inspector', 'Inspecteur contextuel (volet droit)',
              "Trois étages (card / lot / file) : sélection → Infos + preview + actions "
              "clonées (cloneActions) + PARAMÈTRES reflétés (initFromSchema : panel "
              "read/apply dérivés du schéma, cardSettings via card_gear) ; hydrate aussi "
              "les previews de card (hydrateCardPreviews)",
              'wama/common/static/common/js/wama-inspector.js', 'docs/construction/ui/WAMA_VOLETS.md',
              annexes=('wama/common/templates/common/_inspector_actions.html',),
              symbol='WamaInspector'),      # global de base.html : compté par son symbole
    Mechanism('export_formats', 'Formats de téléchargement (⬇ late-binding)',
              "Vocabulaire commun des formats choisis AU TÉLÉCHARGEMENT (libellé, icône, "
              "groupe) + split-button dérivé de la déclaration export_binding — pendant "
              "late-binding d'output_formats ; 6ᵉ action de card. Depuis le 2026-09-18, porte "
              "aussi le REGISTRE des builders de rendu (`register_export_builder`, un par app "
              "late-binding, chemin pointé résolu à l'usage) : c'est ce qui permet au geste "
              "médiathèque de rendre le format choisi par LE MÊME code que le ⬇",
              'wama/common/utils/export_formats.py', 'docs/construction/architecture/WAMA_APP_CONVENTIONS.md §6.3',
              annexes=('wama/common/templates/common/_download_button.html',
                       'wama/common/templatetags/wama_actions.py')),
    Mechanism('volet', 'Déclaration du volet par la page',
              "Une page DÉCLARE les sections du volet droit qu'elle garde (retrait, jamais "
              "ajout) ; sans déclaration, l'état d'avant — les apps n'écrivent rien "
              "(context processor volet_defaut)",
              'wama/common/utils/volet.py', 'docs/construction/ui/WAMA_VOLETS.md §8'),
    Mechanism('app_modes', 'Domaines → modes',
              "Schéma déclaratif des onglets-domaine et modes par app — scope la file",
              'wama/common/utils/app_modes.py', 'docs/construction/ui/MODES_QUEUE_UX.md',
              annexes=('wama/common/static/common/js/wama-modes.js',)),
    Mechanism('app_base_js', 'Socle JS des apps',
              "Plomberie commune file/cards : csrfFetch, urls, Poller de progression, états vides",
              'wama/common/static/common/js/wama-app-base.js', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              symbol='WamaApp'),            # global de base.html : compté par son symbole
    Mechanism('state_presentation', "Présentation des états",
              "L'APPARENCE d'un état (libellé, classe de badge, classe de texte, icône) déclarée "
              "UNE fois et poussée au client (`window.WAMA_STATES`, par le processeur de contexte "
              "global — le mécanisme qui sert déjà `WAMA_APP_CATALOG`) : gabarits, maps JS et "
              "inspecteur en DÉRIVENT au lieu de la recopier. Mesuré le 2026-09-18 : CINQ "
              "écritures du même fait, dont une DANS le commun (le ternaire de `wama-inspector.js`, "
              "qui ne connaissait que 4 états sur 7). ⚠ Le VOCABULAIRE (valeurs, libellés, alias) "
              "reste au domicile du modèle : ce module l'IMPORTE et n'ajoute que l'UI — la couche "
              "modèle n'a pas à connaître `bg-warning`. Les couleurs, elles, restent au CSS",
              'wama/common/utils/state_presentation.py',
              'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.6',
              annexes=('wama/common/tests_status_ui.py',),
              depends_on=('app_base_js',)),
    # ── Briques d'INTERFACE communes (⚠ PAS des plugins — voir « rendu résolu » ci-dessus) ──
    # Déclarées le 2026-08-19 : elles vivaient dans `common/` sans être au registre — invisibles
    # de la carte, donc de la jonction avec la grille (le balayage ne regardait pas
    # `common/static/`). Elles sont toutes APPELÉES PAR LEUR NOM par leur hôte : ce sont donc
    # des mécanismes ordinaires, pas des rendus enfichables. `audio_player` est le seul
    # CANDIDAT au statut de rendu — il le deviendra le jour où l'aiguillage par mime de
    # `renderInlinePreview` sera un registre et non une cascade de `if`.
    Mechanism('audio_player', 'Lecteur audio (onde + transport)',
              "Widget autonome : onde canvas (pics serveur ou décodés), play/pause, exclusivité "
              "inter-lecteurs et inter-onglets ; monté par la preview dans le volet ET les cards",
              'wama/common/static/common/js/wama-audio-player.js', '',
              symbol='WamaAudioPlayer'),    # global de base.html : compté par son symbole
    Mechanism('shuttle', 'Shuttle J/K/L',
              "État de vitesse/direction de lecture (paliers éditeur) + binding clavier ; l'app "
              "fournit apply(speed) — la commande est commune, l'application au lecteur reste locale",
              'wama/common/static/common/js/wama-shuttle.js', ''),
    Mechanism('media_picker', 'Sélecteur de médiathèque',
              "Modale commune de choix d'un asset de la médiathèque (filtrée par type), rendue "
              "à l'appelant sous forme de File + méta",
              'wama/common/static/common/js/media-picker.js', '',
              symbol='MediaPicker'),        # global de base.html : compté par son symbole
    Mechanism('fm_notify', 'Signalement au gestionnaire de fichiers',
              "Noms d'événements centralisés (media:uploaded/processed/deleted) — l'arborescence "
              "du filemanager se rafraîchit sans que chaque app invente son event",
              'wama/common/static/common/js/wama-fm-notify.js', '',
              symbol='WamaFM'),             # global de base.html : compté par son symbole
    Mechanism('card_system', 'Card v3',
              "Dimensionnement déclaratif des pistes de card — dépend de l'app, des actions, "
              "des libellés (l'autre moitié vécue de la v3 — densités, pile — vit au front "
              "de file : queue_front, qui appelle WamaCardV3.measure)",
              'wama/common/static/common/js/wama-card-v3.js', 'docs/construction/ui/CARD_DESIGN.md §11',
              annexes=('wama/common/templates/common/_card_state.html',),
              symbol='WamaCardV3'),         # global de base.html : compté par son symbole
    Mechanism('static_versioning', 'Cache-busting statique',
              "`{% static_v %}` = `{% static %}` + `?v=<mtime>` : le navigateur re-télécharge "
              "un fichier statique dès qu'il change, le garde en cache sinon",
              'wama/common/templatetags/wama_static.py', '',
              # Consommé par la balise de gabarit, jamais par import Python : sans symbole,
              # le compteur (imports du module) rendait 0 — brique « morte » à 100+ pages.
              symbol='static_v'),
    Mechanism('new_item_card', 'Card « Nouvel élément »',
              "Card d'entrée dépliable commune — les 6 modalités du partial : dépôt, URL, "
              "médiathèque, lot, dossier, live + slot de référence typé (extra_zone) — "
              "auto-init",
              'wama/common/static/common/js/wama-new-item-card.js', 'docs/construction/ui/MODES_QUEUE_UX.md',
              annexes=('wama/common/templates/common/_new_item_card.html',)),
    # La card d'entrée porte les MODALITÉS ; celle-ci porte le GESTE d'envoi. Elles se
    # complètent : `new_item_card` déplie/replie, `batch_import` traite les fichiers de LOT,
    # `WamaApp.initUrlImport` le champ URL — et personne ne prenait le fichier ORDINAIRE.
    # Chaque app réécrivait sa boucle `handleFiles` (converter.js, reader.js…), donc une app
    # GÉNÉRÉE n'en avait aucune et ne pouvait créer aucune card, sans erreur console.
    Mechanism('import_front', "Voie d'import (front)",
              "Envoi d'un fichier vers l'endpoint upload de l'app (dépôt, clic — la "
              "médiathèque y ARRIVE par la card d'entrée, qui injecte le fichier dans le "
              "même input), délégation du LOT à batch_import, consolidation et "
              "rafraîchissement — agnostique du monde (ni MIME ni extension)",
              'wama/common/static/common/js/wama-import.js', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/templates/common/_app_scripts.html',),
              # ⚠ SYMBOLE, pas nom de fichier (2026-09-06) : une brique chargée GLOBALEMENT
              # n'est jamais citée par son fichier dans les apps, seulement par son global —
              # sans `symbole`, `folder_import` comptait 2 consommateurs pour 9 apps qui
              # appellent `WamaFolderImport.collect`. C'est la « maille trop grossière » de
              # `WAMA_VERIFICATION §5`, avec sa cause. Vaut pour toute brique de `base.html`.
              symbol='WamaImport'),
    Mechanism('cycle_button', 'Bouton de cycle',
              "Bouton commun ▶/⏹/↻ toujours vert — l'icône porte l'action, l'état vit sur la card",
              'wama/common/static/common/js/wama-cycle-button.js', '',
              annexes=('wama/common/templates/common/_cycle_button.html',),
              symbol='WamaCycleButton'),    # global de base.html : compté par son symbole
    Mechanism('progress_ui', 'Progression & ETA (front)',
              "Moteur ETA par débit observé + barres aux 3 niveaux : card, batch, globale",
              'wama/common/static/common/js/wama-eta.js', 'docs/construction/suivi/PROJECT_STATUS.md §10',
              annexes=('wama/common/static/common/js/wama-global-progress.js',
                       'wama/common/templates/common/_global_progress.html',
                       'wama/common/templates/common/_card_progress.html',
                       'wama/common/templates/common/_processing_time.html')),
    Mechanism('folder_import', 'Import de dossier récursif',
              "Traversée récursive d'un drop/webkitdirectory — brique F2 montée globale (base.html)",
              'wama/common/static/common/js/wama-folder-import.js', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              symbol='WamaFolderImport'),   # global de base.html : compté par son symbole

    )),

    *_domain('Données & infrastructure', (
    Mechanism('external_sources', 'Sources externes',
              "Registre DÉCLARATIF de ce que WAMA joint au dehors : adresse, réglage qui la "
              "surcharge, variable portant la clé d'API, attribution exigée par la licence, et "
              "surtout la PORTÉE (service local ou Internet) — d'où le traitement du proxy est "
              "DÉRIVÉ au lieu d'être choisi à la main par chaque appelant. Ajouter une "
              "plateforme = une entrée. ⚠ Ne déclare JAMAIS le client : chaque source a sa "
              "forme (JSON authentifié, parquet, HTML scrapé), le parseur reste chez le "
              "consommateur. La CLÉ peut être celle de l'instance (`api_key_env`) ou celle de "
              "CHACUN, posée au profil (`user_key`) : depuis le 2026-09-22 (décision de Fabien) "
              "les connecteurs de la médiathèque y sont déclarés (famille `media`) — adresse, "
              "proxy et sonde d'ici, clé de chaque utilisateur",
              'wama/common/external_sources.py', 'docs/construction/suivi/PROJECT_STATUS.md',
              annexes=('wama/common/utils/http_proxy.py',
                       'wama/common/utils/ollama_host.py',
                       'wama/media_library/providers/base.py')),
    Mechanism('units_display', "Unités d'affichage",
              "Moteur UNIQUE de conversion d'unités pour la PRÉSENTATION (pint) : la donnée "
              "reste dans SON unité (`WamaVariables.unit`, `ParamSpec.unit`), la préférence "
              "utilisateur (métrique/impérial) ne convertit qu'à l'écran — résolution par "
              "DIMENSION, une unité inconnue reste affichable — et un export qui convertit "
              "doit le DIRE. Un trou de donnée traverse en trou (None), jamais en valeur",
              'wama/common/utils/units.py', 'docs/construction/mondes/WAMA_DATA_WORLD.md §10 D27'),
    Mechanism('temporal_referential', 'Référentiel temporel (WAMA Data)',
              "Aligne des flux à cadences INCOMMENSURABLES et répond aux questions temporelles : "
              "quel échantillon à t, quels segments le contiennent, quel événement suit, et la vue "
              "DÉCIMÉE (min/max par tranche) sans laquelle aucun tracé n'est viable. N'interpole "
              "jamais : la valeur rendue est toujours un échantillon existant",
              'wama_data/core/temporal.py', 'docs/construction/mondes/WAMA_DATA_WORLD.md §2-§3'),
    Mechanism('data_import', 'Importer universel (WAMA Data)',
              "REGISTRE de capacités de lecture — aucun format privilégié : ajouter un format = "
              "déposer un lecteur, jamais éditer le moteur. Porte aussi l'HORODATAGE par flux "
              "(dont le ré-horodatage par fréquence théorique, qui n'interpole rien et ne "
              "s'applique que sur demande). ⚠ La MÉCANIQUE SQLite (ouverture en lecture seule, "
              "décodage UTF-8→cp1252 du texte des bases MATLAB, valeurs triées, les trois niveaux "
              "d'agrégation) est un socle partagé — un lecteur de base concret n'écrit plus que "
              "`can_read`, `probe` et `read`, c'est-à-dire sa seule connaissance du schéma",
              'wama_data/sources/__init__.py', 'docs/construction/mondes/WAMA_DATA_WORLD.md §6.6, §9terdecies',
              annexes=('wama_data/sources/_sqlite.py',
                       'wama_data/sources/trip.py',
                       'wama_data/sources/wdat.py',
                       'wama_data/sources/rtmaps.py',
                       'wama_data/sources/tabular.py')),
    Mechanism('data_frames_bridge', 'Pont référentiel ↔ cadres typés (WAMA Data)',
              "SEULE frontière entre les deux vocabulaires du monde Data : le référentiel "
              "(paresseux, indexé, sans pandas) et le `TypedFrame` que mangent toutes les "
              "fonctions du catalogue. Sans lui le référentiel n'avait AUCUN consommateur — non "
              "parce qu'on ne s'en servait pas, mais parce qu'on ne POUVAIT pas. Traite quatre "
              "pièges mesurés : le temps de SESSION (± offset) vs le temps local du flux, la "
              "colonne temporelle brute PÉRIMÉE après ré-horodatage, le contrat `rows` réel mais "
              "non déclaré, et la PROVENANCE — ce qui revient d'un calcul ne peut pas se déclarer "
              "acquis (`is_base=False` sans échappatoire)",
              'wama_data/frames.py', 'docs/construction/mondes/WAMA_DATA_WORLD.md §9quater.7'),
    Mechanism('data_view', "View-model d'exploration (WAMA Data)",
              "Une VUE déclare ce qu'on regarde — flux, fenêtre, résolution, colonnes dérivées — "
              "et rien de plus : sérialisable en JSON, donc rejouable et diffable, et on persiste "
              "ELLE plutôt que les valeurs (une colonne matérialisée se périme sans le dire). "
              "Rend EXÉCUTABLE la règle « une nouvelle table SSI la clé temporelle change » en la "
              "DÉRIVANT de la `FunctionCategory` : ajouter une fonction au catalogue la range du "
              "bon côté sans toucher le view-model. La séparation tables/annexes rend la règle "
              "visible à l'écran au lieu d'avoir à l'expliquer",
              'wama_data/view.py', 'docs/construction/mondes/WAMA_DATA_WORLD.md §9quater.4, §9quater.7'),
    Mechanism('data_naming', 'Noms dérivés (WAMA Data)',
              "DOMICILE UNIQUE de la règle « le nom se DÉRIVE des paramètres, il ne se saisit "
              "pas » : deux productions de mêmes réglages portent le même nom, deux réglages "
              "différents ne peuvent pas le partager. Elle était appliquée par QUATRE règles dans "
              "TROIS lieux — dont une f-string écrite en dur — avant l'audit du 23/08. Les anciens "
              "emplacements réexportent ; un test vérifie l'IDENTITÉ des fonctions, donc une "
              "redéfinition locale même à l'identique échoue. Sans dépendance, par nécessité : "
              "c'est ce qui permet à `conditions.py` de l'importer sans cycle",
              'wama_data/core/naming.py', 'docs/construction/mondes/WAMA_DATA_WORLD.md §9ter.6 B7, §9sexies.4'),
    Mechanism('data_containers', 'Écrivain de conteneur (WAMA Data)',
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
              'wama_data/containers/__init__.py', 'docs/construction/mondes/WAMA_DATA_WORLD.md §9quater.2, §9duodecies',
              annexes=('wama_data/containers/wdat.py',
                       'wama_data/containers/trip.py')),
    Mechanism('catalog_refresh', 'Actualisation des catalogues',
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
    Mechanism('data_types', 'Taxonomie des types de donnée',
              "Vocabulaire commun des sources et des fonctions : sous-typage + compatibilité de "
              "ports. `segments` y est LE type « portion de temps bornée » (situation, état, section)",
              'wama/common/catalog/data_types.py', 'docs/construction/mondes/WAMA_DATA_FUNCTION_CARDS.md §3',
              symbol='DataType'),
    Mechanism('ffmpeg', 'Accès ffmpeg',
              "Résolution centralisée du binaire et des conversions (échappatoire FFMPEG_BINARY)",
              'wama/common/utils/ffmpeg_utils.py', ''),
    Mechanism('mirror_sync', 'Sauvegarde & tirage',
              "Moteur unique de miroir (modèles, base, médias, secrets) et restauration",
              'wama/common/services/mirror_sync.py', '',
              annexes=('wama/common/services/config_backup.py',
                       'wama/common/services/media_backup.py',
                       'wama/model_manager/services/remote_backup.py')),
    Mechanism('retention', 'Rétention des médias',
              "Purge automatique des sorties au-delà de la durée choisie par l'utilisateur (FileField découverts)",
              'wama/common/services/retention.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md'),
    Mechanism('audio_decode', 'Décodage audio robuste',
              "Décode l'audio là où torchcodec/torchaudio sont cassés (WSL) : soundfile + repli ffmpeg. "
              "Annexe torchaudio_compat = l'autre forme du même problème : shims soundfile posés DANS "
              "torchaudio pour les libs tierces qui l'appellent en interne (Coqui, DeepFilterNet)",
              'wama/common/utils/audio_decode.py', '',
              annexes=('wama/common/utils/torchaudio_compat.py',)),
    # Rattaché le 2026-08-29 après un défaut de MA part, pas du code : j'ai déclaré deux fois de
    # suite qu'« aucun détecteur commun de nature ne existait » et qu'« aucune déclaration ne dit
    # les types d'entrée d'une app » — les DEUX existaient ici depuis longtemps, et le générateur
    # de vues rouvrait donc un arbitrage déjà tranché. Le module portait `APP_CATALOG`, dont la
    # carte parle abondamment ; sa TAXONOMIE, elle, n'était sur aucune carte. Une brique dont la
    # carte ne parle pas se fait réinventer — c'est précisément ce que ce registre existe pour
    # empêcher.
    Mechanism('media_taxonomy', "Taxonomie des natures & vocabulaire d'entrée",
              "Source UNIQUE des natures de média (image/video/audio/document/archive/dataset/3d "
              "— `text` RETIRÉ le 2026-08-30, arbitrage §S2bis.6bis : les fichiers texte sont "
              "des documents, la saisie est le jeton de RÔLE `prompt`) : détecte la nature d'un "
              "nom de fichier (`category_of_path`, défaut 'document') et normalise un vocabulaire "
              "(`normalize_types`) ; un MONDE pousse ses extensions par "
              "`register_category_extensions` (dataset ← sonde wama_data), jamais en dur. "
              "Porte AUSSI la déclaration par app de ce qu'elle accepte — "
              "`input_types` (les natures) et `input_extensions` (les extensions) — d'où le "
              "manifeste tire `body.ports.inputs[].types` et `body.identity.input_extensions`, "
              "l'axe UX ses `accepts` de domaine, le gabarit généré son `accept=` de dropzone, "
              "et la vue générée sa dérivation de nature CONTRAINTE au vocabulaire déclaré",
              'wama/common/app_registry.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              # ⚠ `symbole` OBLIGATOIRE : le domicile est un module TRÈS partagé (APP_CATALOG s'y
              # importe depuis des dizaines de vues). Sans lui, ce mécanisme hériterait du compte
              # d'importateurs du catalogue d'apps — un chiffre décoratif, le défaut que le champ
              # `symbole` a été créé pour corriger (cf. `scoped_visibility`).
              symbol='category_of_path',
              annexes=('wama/common/manifests/builtin/app.py',
                       'wama/common/manifests/codegen/templates_gen.py',
                       'wama/common/manifests/codegen/views_gen.py')),
    Mechanism('media_probe', 'Sonde média',
              "Durée/codec/dimensions/pages d'un média pour les propriétés de card (via ffmpeg_utils) ; "
              "depuis le 2026-09-13, un OBJET 3D livre sa table des matières glTF sans décodage "
              "(`probe_object3d` : format, faces, rig, animations) sous la clé `attributes` — ce "
              "que la médiathèque pose à l'ingest sur la nature `object3d` (A′)",
              'wama/common/utils/media_probe.py', 'docs/construction/suivi/ROADMAP.md §17ter'),
    Mechanism('asset_natures', "Natures d'assets de la médiathèque (A′)",
              "UNE déclaration par nature (`ASSET_NATURES` : libellé, catégorie ∈ MEDIA_CATEGORIES, "
              "extensions, icône, pivot, schéma d'attributs, `data_type` inter-mondes) dont "
              "`ASSET_TYPES`/`ALLOWED_EXTENSIONS`/`ASSET_TYPE_CATEGORY`/`TYPE_GROUPS` et les trois "
              "tables JS de la page DÉRIVENT ; `attributes` JSON sur SystemAsset/UserAsset "
              "normalisé au `save()` (alias de catégorie REFUSÉ, `resolve_asset_type` pour les "
              "puits qui ne disent qu'une catégorie) ; UNE porte de compatibilité `asset_accepts` "
              "à trois états. Précédent copié : `AIModel.capabilities` + CANONICAL_CAPABILITIES. "
              "Décision Fabien 2026-09-13 — ni colonnes ni table par nature, ni `tags`",
              'wama/media_library/natures.py', 'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md §9',
              annexes=('wama/media_library/models.py',
                       'wama/media_library/services.py',
                       'wama/media_library/tests_natures.py')),
    Mechanism('voice_refs', 'Voix de référence (médiathèque) et voix de clonage',
              "LA brique TTS des voix : `speaker_wav_for` (décidée par la CAPACITÉ du moteur, "
              "jamais par un nom de moteur), `resolve_speaker_wav` (sa_/ua_/cv_/nom d'avant), "
              "`describe_voice`, `voice_reference_groups` (optgroups dérivés d'une REQUÊTE sur "
              "`SystemAsset(voice)` + `attributes`), `ingest_voice_file` (le seul point d'entrée, "
              "ingest initial ET téléchargements). Les voix VIVENT en médiathèque depuis le "
              "2026-09-13 (28 versées, dossier `voice_references/` retiré) ; `tts_service.py` "
              "ne résout plus rien. Quatre consommateurs : synthesizer, avatarizer, "
              "`voice_options` (menus), assistant",
              'wama/common/tts/voice_refs.py', 'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md §9.4',
              annexes=('wama/common/utils/voice_options.py',
                       'wama/media_library/management/commands/ingest_voice_refs.py',
                       'wama/common/tests_voice_refs.py')),
    Mechanism('test_media_isolation', 'Médias de test isolés',
              "Le runner de tests redirige `MEDIA_ROOT` vers `media_tests/run-<id>/` — dossier "
              "SŒUR de `media/`, jamais dedans (servi, sauvegardé, miré) ; les exécutions "
              "orphelines (vides ou > 24 h, teardown jamais joué) se balaient à l'entrée de la "
              "suivante. Le nocturne, lui, écrit chez les COMPTES DE TEST dans `media/` (serveur "
              "vivant) et se balaie par NOM (`wama_temoin_*`, dossier temporaire compris). "
              "Question Fabien 2026-09-13 : « on ne change rien pour ça »",
              'wama/common/runners.py', 'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md §①bis',
              annexes=('wama/common/tests_media_tests_hygiene.py',)),
    Mechanism('video_utils', 'Utilitaires vidéo',
              "Extraction audio des vidéos + téléchargement YouTube/yt-dlp",
              'wama/common/utils/video_utils.py', ''),
    Mechanism('media_paths', 'Chemins média',
              "Emplacements canoniques des entrées/sorties par app et par utilisateur",
              'wama/common/utils/media_paths.py', ''),
    Mechanism('scoped_visibility', 'Visibilité et portée',
              "Privé / unité / public : filtrage des lectures, mutations inchangées",
              'wama/common/models.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md',
              symbol='ScopedVisibility'),
    Mechanism('org_sync', "Arbre organisationnel depuis l'annuaire",
              "ou=structures (SUPANN) → OrgUnit + parents ; peuple ce dont dépend le partage "
              "par unité (RAG labo, médiathèque). Lecture seule côté LDAP, idempotente",
              'wama/accounts/management/commands/sync_org_units.py',
              # ⚠ Pointait sur un souvenir d'agent (`reference_ldap_supann_orgunit`) : un
              # pointeur que personne lisant le dépôt ne peut suivre. Le document du domaine
              # est celui-là — `scoped_visibility`, l'autre moitié du mécanisme, l'y désigne déjà.
              'docs/construction/exploitation/PROFILES_PERMISSIONS.md',
              # `annexes` : la remontée d'attributs au PROFIL est l'autre moitié — elle marchait
              # déjà (signaux au login) ; c'est l'ARBRE qui manquait, d'où le domicile ici.
              annexes=('wama/accounts/ldap.py',)),
    # Rattaché le 2026-08-27 : c'est le POINT UNIQUE DE DÉCISION de l'accès aux apps (tier ×
    # rôles), et il n'était sur aucune carte. Son absence s'est payée — la fermeture du compte de
    # service `anonymous` avait été faite à la main sur la base vivante, donc défaite par toute
    # réinstallation, faute d'un endroit où l'invariant soit déclaré.
    Mechanism('app_access', "Accès aux éléments (apps aujourd'hui)",
              "Décide seul qui voit quel élément, sur DEUX axes qui se cumulent : le TIER du compte "
              "(anonymous < utilisateur < developpeur < admin, tranche en premier) et les RÔLES "
              "métier (groupes `role:*`, intersection avec la politique de l'app). Le compte de "
              "service `anonymous` y est FERMÉ par code, pas par état de base. Signature GÉNÉRALE "
              "depuis S2 — accessible(user, kind, element_id) : chaque FAMILLE d'élément déclare "
              "dans KIND_DECISION qui décide pour elle, un kind inconnu LÈVE, et une décision "
              "unique ne garde que ce que ses POINTS D'APPLICATION lisent réellement (§8.9)",
              'wama/accounts/permissions.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md',
              annexes=('wama/accounts/tests.py', 'wama/accounts/tests_access_points.py'),
              symbol='accessible'),
    # Ajouté le 2026-08-27 avec le jalon S1 (PROFILES_PERMISSIONS §8). Il est le VOISIN de
    # `app_access` et son exact complément — d'où sa place ici, collé à lui : `app_access` répond
    # « ai-je le DROIT ? », celui-ci « est-ce que je VEUX m'en servir ? ». Les confondre est le
    # défaut que ce mécanisme existe pour empêcher : une préférence ne décide JAMAIS d'un accès,
    # et aucune décision d'accès ne lit sa table.
    Mechanism('subscription', "Abonnement aux éléments de catalogue",
              "PRÉFÉRENCE d'affichage, appliquée APRÈS le droit et seulement à l'affichage : elle "
              "ne peut que RESTREINDRE ce à quoi l'utilisateur a déjà accès. Seules les EXCEPTIONS "
              "sont stockées (se réabonner efface la ligne) ; une nature d'élément s'ajoute par "
              "une entrée dans KINDS, et la page de catalogue hérite du mécanisme par deux "
              "attributs (`data-abo`, `data-abo-toggle`). Son PÉRIMÈTRE est celui du DROIT, pas "
              "d'APP_CATALOG : les surfaces transversales et Lab (extra_links) se masquent par la "
              "même clé `gate` que celle dont accessible() décide (§8.8.1)",
              'wama/common/services/subscriptions.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md',
              annexes=('wama/common/static/common/js/wama-subscription.js',
                       'wama/common/tests_subscriptions.py')),
    Mechanism('scoping', 'Accès scopé aux objets',
              "Deux chemins NOMMÉS pour lire un objet partageable depuis une vue (possédé / visible)",
              'wama/common/utils/scoping.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md'),
    Mechanism('user_settings', 'Réglages utilisateur par app',
              "Persistance cache user_{id}_{app}_{clé} avec défauts déclarés par l'app",
              'wama/common/utils/user_settings.py', ''),
    Mechanism('feature_flags', 'Bascules de fonctionnalités',
              "Registre de Feature par app + surcharges JSON de l'objet porteur — comparer AVEC/SANS",
              'wama/common/utils/feature_flags.py', ''),

    )),

    *_domain("Studio & surface d'outils (API)", (
    Mechanism('generic_runner', 'Runner générique du studio',
              "Exécute une app par son CONTRAT (triade tool_api normalisée) — zéro logique par app",
              'wama/studio/services/generic_runner.py', 'docs/construction/mondes/STUDIO_VISION.md',
              annexes=('wama/studio/services/launch.py',
                       'wama/studio/services/runners.py')),
    Mechanism('tool_api', "Surface d'outils",
              "Registre central TOOL_REGISTRY : triades add/start/status par app, gating F7 via execute_tool, descriptions dérivées des schémas",
              'wama/tool_api.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md'),
    Mechanism('api_v1', 'API REST v1',
              "Passerelle générique (token+session) sur TOOL_REGISTRY : lister/exécuter, gating F7 à l'annonce ET à l'exécution",
              'wama/api/v1/views.py', '',
              annexes=('wama/api/v1/urls.py',),
              symbol='api_v1'),
    )),
)


#: Modules de `common/` ASSUMÉS utilitaires locaux — PAS des mécanismes transversaux, et pas des
#: oublis non plus : chaque entrée porte sa raison, datée du triage. Le fait `mecanismes` les
#: retire du backlog « non rattachés » ; ce qui y reste est donc VRAIMENT à trancher. Un module
#: assumé qui gagne des consommateurs multi-apps doit repasser en `Mechanism` (ou en annexe).
ASSUMED_LOCAL = {
    'wama/common/utils/disk_utils.py': "plomberie disque (1 consommateur common)",
    'wama/common/utils/format_policy.py': "politique de formats de POIDS de modèle — chaîne modèles",
    'wama/common/utils/html_render.py': "rendu HTML→PDF, consommé par le converter seul",
    # `http_proxy.py` et `ollama_host.py` ont QUITTÉ cette liste le 2026-09-01 : ils sont
    # devenus les annexes du mécanisme `external_sources`. Ils n'étaient pas mal classés — le
    # mécanisme qui les rassemble n'existait pas encore, et une plomberie sans mécanisme
    # au-dessus n'a effectivement rien de transversal à déclarer.
    'wama/common/utils/lang_routing.py': "routage de langue — sera absorbé par le Translator (ROADMAP §10)",
    'wama/common/utils/log_rotation.py': "décalage des journaux au démarrage (politique : on décale, on ne vide pas)",
    'wama/common/utils/mime_utils.py': "détection MIME — helper fin (filemanager/studio)",
    'wama/common/utils/model_locations.py': "chemins de modèles — plomberie model_manager",
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


def by_key() -> dict:
    return {m.key: m for m in MECHANISMS}
