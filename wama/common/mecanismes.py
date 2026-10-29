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
    #
    # ⭐ 2026-10-19 (décision de Fabien, `ROUTE §F3b` « trois niveaux ») : la BRIQUE UI
    # (`common/surfaces.py`) est l'héritière de ce plugin — un TOUT, posé par l'utilisateur ou le
    # Studio, mesuré par sa compatibilité. Elle est COMPOSÉE de mécanismes (ceux qui tiennent les
    # scripts qu'elle charge), elle n'en est pas un ; une page COMPOSE des briques. La page des
    # briques UI l'avait oublié le 18/10, en rangeant les mécanismes d'interface comme une famille
    # de briques (« Système ») — c'est la confusion que ce paragraphe interdisait déjà.


def _domain(name: str, mechanisms: tuple) -> tuple:
    """Pose le domaine sur un groupe d'entrées : le nom du domaine ne s'écrit qu'UNE fois."""
    from dataclasses import replace
    return tuple(replace(m, domain=name) for m in mechanisms)


#: Le domaine des MÉCANISMES DE L'INTERFACE — les pièces que l'on voit et manipule, partagées par
#: toutes les pages. Rangé le 2026-10-18 : les mécanismes d'interface égarés y sont entrés, les
#: pièces sans rien de visible (réponses par morceaux, cache-busting, grille des temps, notation
#: MIDI) en sont sorties. ⚠ La page des briques UI en avait fait une famille de briques
#: (« Système ») ; retiré le 2026-10-19 — un mécanisme est une PIÈCE, la page montre les briques
#: et, pour chacune, les mécanismes qui la composent (`ROUTE §F3b`, « trois niveaux »).
UI_DOMAIN = 'UI générée'


#: ⚠ ORDRE : par domaine (= ordre des sous-tables de la carte) ; alphabétique à la génération.
MECHANISMS = (
    *_domain('Ressources & exécution', (
    Mechanism('runtime_side', "Côté d'exécution (qui met une tâche en file)",
              "Tout passe côté WSL, rien côté Windows, sauf les tests à la demande (règle de "
              "Fabien, 2026-09-29) : sous tests et hors WSL le broker est EN MÉMOIRE, l'envoi "
              "Windows est écrit au journal, la synchro de démarrage n'est pas dispatchée. Une "
              "décision, lue par `settings`, `wama/celery.py` et `model_manager`",
              'wama/common/services/runtime_side.py',
              'docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md',
              annexes=('wama/common/tests/tests_runtime_side.py',)),
    Mechanism('resource_governor', 'Gouverneur de ressources',
              "Arbitre GPU/CPU/RAM entre process : réservation, résidence, priorités. Une ligne "
              "de réservation ou de tâche dont le process écrivain est MORT (même espace de pid) "
              "sort sans attendre son TTL (29/09 : 4 lignes sur 8 après une relance, ~24 Go "
              "fantômes retranchés du tirage). Une ligne « tâche en cours » vaut pour UN process "
              "GPU de la card depuis le 2026-10-14 ; `resident_here_gb` dit ce que CE process "
              "tient déjà d'un modèle (un rechargement idempotent n'est pas un besoin)",
              'wama/common/services/resource_governor.py', 'docs/construction/suivi/PROJECT_STATUS.md §0'),
    Mechanism('backend_contract', 'Contrat de backend',
              "Cycle de vie commun des porteurs de modèle — ALIMENTATION du gouverneur "
              "(enveloppe load/unload/process à toute profondeur d'héritage) et CAPACITÉS "
              "déclarées par le moteur (supports_*), lues par le catalogue",
              'wama/common/backends/base.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/backends/manager.py',
                       # Garde GÉNÉRIQUE du contrat de génération (29/09, défaut FLUX.2 Klein).
                       'wama/common/tests/tests_generation_params_contract.py'),
              # ⚠ `symbole` OBLIGATOIRE ici, et pour une raison différente de `scoped_visibility` :
              # le domicile n'est pas un module partagé, c'est son NOM DE FEUILLE qui est banal.
              # Le repli « import relatif » du compteur (`from …base import`) capturait alors
              # TOUS les `from .base import` du dépôt — 100 consommateurs annoncés au premier
              # rendu, mesuré le 2026-08-13, pour ~25 réels. Même piège pour l'annexe
              # `manager.py`. Règle : domicile au nom générique (base/manager/models/utils) ⇒
              # renseigner le symbole, sinon le chiffre est décoratif.
              symbol='BaseModelBackend'),
    Mechanism('task_skeleton', 'Squelette de tâche',
              "Enchaînement commun des tâches Celery d'item : gardes, progress, statuts, ETA. "
              "Depuis le 2026-10-14 le gouverneur y est au grain du PROCESS : avant chaque "
              "process GPU (`ProcessSpec.gpu`), attente de VRAM (besoin déclaré, sinon celui du "
              "modèle de la card, moins ce que le worker tient) et déclaration « en cours » ; "
              "chaque process se joue sur SA file (GPU ou par défaut), la tâche se re-livrant à "
              "l'autre entre deux process (`queue_of`, barre et durées du lancement reportées). "
              "2026-10-21 : la MÉMOIRE DU LANCEMENT (`ctx.remember`/`recall`, le modèle retenu "
              "gardé d'une livraison à l'autre) et la PLACE d'un fichier de sortie "
              "(`ctx.output_place` : dossier de sortie de l'app au domicile de l'utilisateur, nom "
              "commun) ; 2026-10-22 : adoptée par toutes les glues (sous-dossier par nature, série, "
              "famille FICHIER sans identifiant), l'arrêt COOPÉRATIF d'un lancement remplacé",
              'wama/common/utils/task_skeleton.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/tests/tests_process_governance.py',),
              depends_on=('process_runs', 'resource_governor', 'model_readiness')),
    # Ajouté le 2026-10-02 (pipeline porté par la card, marche P3 — route §10.6 points 4.1 à 4.4).
    # Généralise le suivi de passes du cam_analyzer (`AnalysisPass`, `pass_tracking`) : c'est la
    # 1ʳᵉ pièce du moteur commun, écrite par le squelette pour son unique process.
    Mechanism('process_runs', "Lignes d'exécution des process",
              "UNE ligne par (élément, nœud du pipeline, clé d'instance) : état du process sur les "
              "six états communs, photo des réglages surveillés, modèle EMPLOYÉ (lisible pendant "
              "un « auto »), sortie, durée. Dit ce qui est périmé (`stale_nodes` : réglage "
              "surveillé changé, puis cascade) et déduit l'état d'une card de ses process "
              "(`aggregate`). L'élément reste la vérité lue par l'interface tant qu'il porte "
              "`status` ; l'arrêt et la réconciliation referment les lignes ouvertes. Le "
              "lancement y écrit son PLAN (`plan` : ses process `PENDING`, avec sa tâche) ; "
              "l'ETA d'un process (`step_eta_seconds`, règle des passes du cam_analyzer) et celle "
              "d'une card, la somme de ce que joue son lancement (`launch_eta`, 2026-10-05). "
              "2026-10-27 : une sortie PERDUE (fichier désigné, absent du disque, `output_lost`) "
              "ne périme pas son aval — seule une empreinte DIFFÉRENTE périme — : elle se dit "
              "(bande des process, résultats du studio) et se rejoue. 2026-10-28 : une ligne dont "
              "l'élément a disparu sans passer par son retrait (cascade, témoins du nocturne, "
              "jumelle retirée) se balaie chaque nuit (`forget_orphans`)",
              'wama/common/services/process_runs.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/tests/tests_process_runs.py',
                       'wama/common/tests/tests_process_eta.py'),
              depends_on=('item_revisions',)),
    # Ajouté le 2026-10-02 (P3 palier B, décision n°11) : le registre des passes du cam_analyzer
    # rendu indépendant de la session — 1er adopteur, le composer (`plan` → `render`).
    Mechanism('process_pipeline', "Pipeline déclaré d'une app (plusieurs process)",
              "Une app DÉCLARE les process de sa card (`ProcessSpec` : amonts, réglages "
              "surveillés, degré, condition d'application) comme le cam_analyzer déclare ses "
              "passes ; le registre devient un manifeste `pipeline` à nœuds `function` "
              "(`register_app_pipeline`). Dit ce qu'un lancement JOUE (`steps_to_run` : ce qui "
              "n'est plus à jour et son aval ; une card à jour relancée rejoue tout), ce qui est "
              "PÉRIMÉ (`refresh` : réglage changé, sortie d'amont remplacée, cascade) et l'état "
              "déduit de la card (`card_state`). L'exécution reste au squelette de tâche "
              "(`run_item_task(pipeline=…, processes=…)`), une ligne d'exécution par process. "
              "Une VUE lit dans une fenêtre (`preload` … `release`) : lignes lues une fois, "
              "réponses de `applies` retenues par (process, modèle) — un `applies` peut résoudre "
              "le backend du modèle (0,56 s l'appel, mesuré le 2026-10-05). 2026-10-21 : une "
              "ligne ne COMPTE que tant que l'élément demande son process (`still_counts` — un "
              "amont qui n'a plus lieu ne laisse plus son aval périmé à jamais) ; un aval LIT la "
              "sortie de son amont par un geste (`output_of`, `upstream_output` : le plus proche "
              "amont qui rend ce type) ; un process DÉTACHÉ de son aval (`split_from`) garde "
              "valables les lignes rendues avant le détachement ; ce que les process ont ÉCRIT "
              "(`produced_fields`), dont une copie repart sans. 2026-10-22 : une relance COMPLÈTE "
              "libère ce qui ne compte plus (`release_absent`) ; un process peut ne pas LIRE ses "
              "amonts (`upstream_switch`, `read_upstreams`)",
              'wama/common/services/process_pipeline.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/tests/tests_process_pipeline.py',),
              depends_on=('process_runs', 'input_provenance')),
    Mechanism('model_readiness', 'Modèle installé par la route au moment du besoin',
              "DEPUIS LE 2026-10-16 (décision de Fabien : « la dérive arrive si l'installation n'est "
              "pas complète ; prévenir l'utilisateur ; la tâche attendra ») : un modèle du catalogue "
              "ABSENT qu'une tâche demande est installé PAR LA ROUTE (`ensure_installed` → "
              "`request_install` : garde d'espace, journal, jeton), l'utilisateur est prévenu, la "
              "tâche rend son worker et revient (`ServiceNotReady`) ; refus ou échec = la tâche "
              "échoue en le disant, une installation échouée n'est pas relancée en boucle. Appelée "
              "par le squelette (modèle de la card), par toute glu qui charge un modèle "
              "(`ctx.ensure_model`, 2026-10-18 : imager, reader, describer, synthesizer, "
              "avatarizer, anonymizer, diarisation et alignement du transcriber, glu générée ; "
              "2026-10-19 : process secondaires du composer, partition extraite et partition "
              "complète — dont le modèle se CHOISIT sur la card), "
              "par le studio et le cam_analyzer (re-livraison Celery, `redeliver_later`) ; "
              "`install_and_wait` pour une commande (le banc). "
              "L'annonce d'origine (`warn_if_weights_missing`) reste pour la seule ligne que la route "
              "ne sait pas installer. — Historique : un modèle jamais utilisé télécharge ses poids "
              "À LA PREMIÈRE EXÉCUTION (37 appels "
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
              annexes=('wama/common/tests/tests_model_readiness.py',),
              depends_on=('model_installer',)),
    Mechanism('file_cache', 'Cache par empreinte de fichier',
              "Garde une valeur calculée depuis un fichier (lecture AST, rendu markdown, compte "
              "de lignes) tant que son empreinte — date de modification, taille — n'a pas "
              "changé : un fichier modifié est relu, jamais servi périmé. Extrait le 2026-09-14 : "
              "le catalogue des docs portait le geste en dur, et l'inventaire des backends "
              "relisait 6 237 fois des fichiers pour UNE extraction de manifeste (48 résolutions "
              "d'un même vivier). ⚠ Ne convient qu'à ce qui ne dépend QUE du fichier",
              'wama/common/file_cache.py', '',
              annexes=('wama/common/tests/tests_file_cache.py',)),
    Mechanism('task_progress', 'Progression de tâche longue',
              "Avancement d'une tâche Celery HORS file d'items publié dans le cache "
              "(F5-proof) + garde « déjà en cours » vérifiée auprès de Celery ; "
              "pendant navigateur = WamaApp.Poller",
              'wama/common/utils/task_progress.py',
              'wama/model_manager/PROSPECTION_PIPELINE.md'),
    Mechanism('process_control', 'Gardes de process',
              "Anti-boucle-de-crash (redélivrance) et réconciliation des tâches orphelines ; "
              "solde des tâches d'un worker MORT (preuve : processus disparu) au démarrage du "
              "worker relancé (`worker_ready`) et par la surveillance des workers "
              "(`scripts/worker_watchdog.sh` → `manage.py worker_died`) ; relance d'un élément "
              "EN COURS sur accord confirmé (`grant_replace`, `api/replace-grant/`), la tâche "
              "remplacée ou arrêtée se retirant d'elle-même (`task_skeleton.LaunchSuperseded`)",
              'wama/common/utils/process_control.py', 'docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md',
              annexes=('wama/celery.py', 'wama/common/management/commands/worker_died.py',
                       'scripts/worker_watchdog.sh', 'scripts/wama_services.sh')),
    Mechanism('memory_manager', 'Mémoire GPU',
              "Garantit la VRAM avant un chargement, la reprend sur les autres modèles, "
              "et réessaie après libération sur erreur CUDA",
              'wama/model_manager/services/memory_manager.py', 'docs/construction/suivi/PROJECT_STATUS.md §0',
              annexes=('wama/model_manager/services/memory_monitor.py',
                       'wama/model_manager/services/memory_cleaner.py',
                       'wama/model_manager/services/memory_diagnostics.py')),
    Mechanism('eta', 'ETA auto-apprenante',
              "Estimation de durée par a-priori puis moyenne mobile, rangée par LIEU DE CALCUL "
              "(le matériel, ou la source d'un modèle distant : `compute_place`, 2026-10-26) ; "
              "un modèle CHAUD — distant, ou résident selon le gouverneur (`is_warm`) — ne paie "
              "pas de chargement, et quand l'appelant ne sait pas, c'est le gouverneur qui tranche "
              "(`pays_load`, 2026-10-27 : il était supposé chargé) ; "
              "sous la clé de catalogue d'un modèle, c'est aussi sa VITESSE D'INFÉRENCE, que le "
              "banc calibre et que le curseur rapide/qualité de toutes les apps compare "
              "(`comparable_speeds` → `model_selector.intent_choice`, 2026-10-11)",
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
              "— sans lui les 11 scénarios d'une jumelle skippent (mesuré 2026-08-30). "
              "Le registre se REMPLIT AU PREMIER USAGE (2026-10-20) : une app déclare son "
              "enregistreur dans son `ready()` (`add_registrar`, chemin `module:fonction`) au lieu "
              "de l'exécuter — l'enregistrement chargeait toute la configuration d'URL (et torch) "
              "dans chaque processus Django",
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
                       'wama/common/services/ui_smoke_panel.py',
                       'wama/common/services/ui_smoke_preview.py',
                       'wama/common/services/ui_smoke_surfaces.py',
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
    Mechanism('remote_mounts', 'Dossiers connectés distants (rclone)',
              "Monte un stockage distant comme un dossier du filemanager : nuage WebDAV, partage "
              "réseau SMB, Google Drive, OneDrive — chacun DÉCLARÉ comme type de stockage "
              "(champs saisis, connexion par le navigateur), la nature de ses options lue dans "
              "rclone. Secret chiffré passé par l'environnement, proxy de la source, accès "
              "vérifié avant montage, remontage au redémarrage, révocation au retrait "
              "(2026-10-10/11). Le montage du noyau (cifs) ne reste que le repli sans rclone",
              'wama/filemanager/remote_mounts.py', 'docs/construction/suivi/ROADMAP.md'),
    Mechanism('user_file_search', "Retrouver un fichier de l'utilisateur, dossiers connectés compris",
              "Recherche PAR NOM (casse et accents ignorés) dans ce que l'arbre du gestionnaire "
              "montre — temporaires, entrées et sorties de chaque app LUES à `_app_folders_config`, "
              "dossiers connectés résolus par `resolve_mount_path` : aucune liste de dossiers. "
              "Bornée par racine (temps, entrées) et une racine tronquée est DITE (`incomplete`). "
              "Porte aussi `mounted_file` : `designate` et les outils acceptent `mounts/…`, COPIÉ "
              "à l'entrée d'une app, jamais déplacé (2026-10-11, outil `find_user_files`). ⚠ La "
              "recherche du gestionnaire (`api_search`, 25 dossiers écrits à la main, sans les "
              "dossiers connectés) reste à rallier",
              'wama/common/services/user_files.py',
              'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md',
              annexes=('wama/common/tests/tests_assistant_reach.py',)),
    Mechanism('system_monitor', 'Moniteur système',
              "Mesure unifiée CPU/RAM/GPU/disque (WSL + hôte Windows) — barre de ressources, model manager",
              'wama/common/services/system_monitor.py', '',
              annexes=('wama/common/static/common/js/system-stats.js',)),
    Mechanism('tts_service_client', 'Client du service TTS',
              "L'appel POST /tts UNIQUE vers le microservice TTS (payload contractuel, 503 "
              "« loading » → TTSServiceLoadingError, WAV temporaire ou bytes) ; les POLITIQUES "
              "(retry Celery, chunking, replis) restent aux appelants — extrait 2026-08-28 : "
              "4 exemplaires vivaient dans le dépôt, un seul détectait le 503. Depuis le "
              "2026-10-10 le service ÉCOUTE aussi : `stt_via_service` (POST /stt, Whisper "
              "chaud, conversation vocale de l'assistant) partage le même appel et la même "
              "traduction d'erreurs (`_post`). Le service lui-même (uvicorn :8001) vit à côté "
              "du client depuis le 2026-10-28 (`service.py`, ex-`tts_service.py` à la racine). "
              "Et la voix AU FIL DE L'EAU (2026-10-28) : `tts_stream_via_service` → POST "
              "/tts/stream (PCM 16 bits, `TTSBackend.synthesize_stream`), joué par le canal "
              "commun (`WamaApp.Speech.stream`) ou l'avatar (`WamaAvatar.streamPlayer`)",
              'wama/common/tts/service_client.py', 'docs/construction/ui/MODES_QUEUE_UX.md §2bis',
              annexes=('wama/common/tts/service.py', 'wama/common/tests/tests_tts_stream.py')),
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
              "Choisit UN modèle : capacités, entrées, priorités, budget VRAM, qualité — parmi "
              "ceux que le compte voit (`user=`, `ROADMAP §29` : sans compte, le système seul)",
              'wama/model_manager/services/model_selector.py', 'docs/construction/ui/INPUT_MODEL_MATCHING.md'),
    Mechanism('auto_model', 'Auto-sélection (« auto » au select)',
              "Valeur « auto » d'un select de modèle : résolution AU LANCEMENT sur le "
              "domaine que le schéma déclare pour ses options (options_query), prévision "
              "affichée sous le select (options_auto) + curseur de QUALITÉ continu 0-100 "
              "(intent_param, poids dans le score de select_model) ; `candidates_with` = le "
              "BESOIN qui filtre avant le classement (capacité = valeur, ex. `scale`=4)",
              'wama/common/utils/auto_model.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md'),
    Mechanism('model_keys', 'Clé de catalogue ↔ identifiant',
              "UNE lecture de `<source>:<identifiant>` pour tout WAMA : seul le PREMIER segment "
              "est la source, reconnue au vocabulaire `ModelSource` (`ollama:qwen3:4b` → "
              "`qwen3:4b`, là où un `rsplit` rendait `4b`). `catalog_key` est la tolérance "
              "d'ENTRÉE d'une app passée aux clés entières (valeur nue → sa source, `auto` "
              "intact). Née au portage F4b de l'imager (2026-09-29) ; consommée par l'imager, "
              "l'ETA (`make_key`) et `declaration_for`. ⚠ Une douzaine de conversions à la main "
              "vivent encore dans le dépôt (relevé du 29/09) — elles s'y rallient au fil des "
              "portages, pas en passe aveugle. `backend_model_id` (2026-10-07) est l'AUTRE "
              "lecture : l'identifiant qu'un backend déclare dans `SUPPORTED_MODELS` (dernier "
              "segment, règle de `backend_for_model`, écrite quatre fois en ligne jusque-là) — "
              "elle seule sépare de `model_id` une clé à trois segments (`github:owner/repo:tag`)",
              # Pas de `symbol` : `catalog_key` est aussi un nom de VARIABLE locale (composer,
              # enhancer, avatarizer) — compté par symbole, il leur attribuait une adoption fausse.
              # Le repli « feuille » compte l'import du module, qui est la vraie adoption.
              'wama/common/utils/model_keys.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §F4b'),
    Mechanism('model_coverage', 'Couverture multi-modèles',
              "Choisit un ENSEMBLE de modèles couvrant des classes (couverture ou spécialisation) ; "
              "depuis le 10/10, `models_per_class` en ajoute plusieurs par classe (rappel d'abord) "
              "et les départage par leur taux manqué MESURÉ quand le lot entier l'est",
              'wama/common/services/model_coverage.py', ''),
    Mechanism('surfaces', 'Surfaces — pages d\'édition composées de briques',
              "Une page d'édition DÉCLARÉE par l'app (emplacements, champs lus, champ écrit et "
              "sa validation, process que l'écriture périme), servie par des vues COMMUNES et "
              "composée de briques UI universelles — déplaçables, redimensionnables (gridstack), "
              "historique commun. 1ʳᵉ surface : la correction des détections de l'anonymizer "
              "(2026-10-10). Registre `ui_bricks` = le catalogue des briques. 2ᵉ (2026-10-13) : "
              "le fond du Writer — un champ FICHIER s'édite comme texte (règles communes), la "
              "surface se déclare au manifeste (facette `surfaces`) et se génère ; refus 409 sur "
              "état périmé et verrou doux pour toutes les surfaces ; la VERSION écoutée d'un média lu "
              "gardée sur la card (`sources_setting`, 2026-10-22) ; brique « Versions » : reprendre "
              "le texte d'une révision GARDÉE, un geste d'édition annulable. 3ᵉ (2026-10-15) : la "
              "partition du composer — champs ALTERNATIFS (sortie de l'un de deux process), "
              "briques `score_view` (gravure abcjs, notes jouées colorées, glisser = transposer) "
              "et `media_transport`, sur l'AXE partagé de la surface (`ctx.axis()`). 2026-10-18 : "
              "chaque surface DÉCLARE son élément témoin (`witness`), sur lequel le nocturne "
              "l'ouvre et capture ses briques — les vignettes du catalogue (`thumbnail`), qui "
              "montre aussi les composants SYSTÈME (domaine `UI_DOMAIN`). 2026-10-21 : disposition "
              "par compte, FIGÉE par défaut pour tous ; deux ZONES (`BrickSlot.zone`) — la grille "
              "et la COLONNE du volet droit, une brique passant de l'une à l'autre. 2026-10-26 : "
              "des briques EMPILÉES en un panneau (`stacks`, affichage seul — le transport, la "
              "ligne de temps et l'écriture fixés ensemble) et un panneau ÉPINGLÉ à un bord de la "
              "fenêtre (haut, bas, gauche, droite : la page se referme derrière lui), gardés avec "
              "la disposition — `WAMA_VOLETS §3-ter`, scénario `common.surface_stack`. 2026-10-28 : "
              "la DISPOSITION sort du noyau en brique commune (`wama-brick-layout.js`), pour que "
              "les pages d'apps la montent sans le noyau d'édition ; tout panneau s'ouvre DANS UNE "
              "AUTRE FENÊTRE (déplacé, pas recréé ; gestes relayés à la page)",
              'wama/common/surfaces.py',
              'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §F3b',
              annexes=('wama/common/surface_views.py',
                       'wama/common/templates/common/surface.html',
                       'wama/common/static/common/js/surfaces/wama-surface.js',
                       'wama/common/static/common/js/wama-brick-layout.js',
                       'wama/common/static/common/js/wama-detections.js',
                       'wama/common/static/common/js/wama-score.js',
                       'wama/common/manifests/codegen/surfaces_gen.py',
                       'wama/common/tests/tests_surfaces.py'),
              depends_on=('media_axis',)),
    Mechanism('document_layout', 'Mise en forme AJUSTÉE d\'un document (fond en sections)',
              "Le fond Markdown découpé en sections (règle de la brique `text_sections`, tenue sous "
              "V8), un PLAN d'après la part de mots changés par section (`text_metrics`) : un bout "
              "de phrase se remplace dans la forme sans modèle, une section très modifiée se remet "
              "en forme seule, une structure qui change refait tout. Base = les fichiers de "
              "révision GARDÉS + la photo de ce que le process surveille (`ctx.previous_snapshot`) ; "
              "repères `data-wama-section` ; réponse de modèle sans « ```html », avec son charset. "
              "Montrée au rôle `codegen` pour le process qu'une surface rejoue (2026-10-13)",
              'wama/common/utils/document_sections.py', 'docs/construction/suivi/ROADMAP.md §21.5',
              annexes=('wama/common/tests/tests_document_sections.py',)),
    Mechanism('detection_ensemble', 'Détection par un ensemble de modèles',
              "L'UNION des documents `detections` de plusieurs détecteurs, quelle que soit leur "
              "famille (2026-10-10) : les modèles ultralytics ensemble par `Anonymize`, chacun des "
              "autres par SON backend (porte `backend_instance_for_key`). Un détecteur image par "
              "image n'écrit que `detect_frames` : la boucle sur le média est commune "
              "(`FrameDetectionBackend` — SAM3, EgoBlur, RT-DETR). Consommé par l'anonymizer et "
              "par le banc de rappel (`bench --task detect-recall`), qui mesure par le MÊME chemin",
              'wama/common/services/detection_ensemble.py', 'docs/construction/ia/WAMA_QUALITE.md',
              annexes=('wama/common/backends/detection_base.py',
                       'wama/common/tests/tests_detection_ensemble.py'),
              depends_on=('detections_document',)),
    Mechanism('pii_detection', 'Détection des DONNÉES PERSONNELLES d\'un texte (contrat)',
              "Le contrat de la tâche `pii-detection` (2026-10-28) — `detect_entities(text, "
              "language)` rend des passages {start, end, entity, score} au VOCABULAIRE COMMUN "
              "(`privacy.entities` : clés de Presidio + identifiants français, libellé "
              "d'occultation entre crochets dans la langue du texte). Écrit AVANT les détecteurs ; "
              "LIANT dans `TASK_CONTRACTS` ; essayé par le smoke `PIIDetectionBackend`. Chaque "
              "détecteur entre dans l'union que Presidio orchestre (`common/privacy`) par un "
              "adaptateur — ROADMAP §16.4bis",
              'wama/common/backends/pii_detection_base.py',
              'docs/construction/suivi/ROADMAP.md §16.4bis',
              annexes=('wama/common/privacy/__init__.py',
                       'wama/common/privacy/entities.py',
                       'wama/common/backends/bardsai_pii_backend.py',
                       'wama/common/backends/gliner2_pii_backend.py',
                       'wama/common/tests/tests_pii_detection_contract.py')),
    Mechanism('privacy', 'Confidentialité — détecter puis OCCULTER les données personnelles',
              "La brique commune (2026-10-28, ROADMAP §16.4bis) : Presidio ORCHESTRE une union de "
              "détecteurs — ses motifs à chiffre de contrôle, les identifiants français (NIR clé 97, "
              "SIREN/SIRET Luhn) et chaque modèle `pii-detection` INSTALLÉ qui couvre la langue du "
              "texte, par son backend (adaptateur `BackendRecognizer`, porte commune) ; moteur de "
              "langue SANS modèle (`spacy.blank`), adresses validées hors ligne. Rend un document "
              "`detections` en forme TEXTE (`span`), corrigeable par l'humain ; occulte par libellé "
              "entre crochets dans la langue du texte. Un détecteur qui ne se charge pas est NOMMÉ "
              "(`unavailable`). Service uvicorn 127.0.0.1:8003 dans le paquet, client qui retombe "
              "sur le moteur en process service éteint et REFUSE sur délai (jamais « rien trouvé »). "
              "LA PORTE avant un modèle distant (`gate`, 2026-10-28) : par niveau d'hébergement, le "
              "geste choisi au profil (`cloud_privacy`) — pseudonymiser de façon réversible par "
              "défaut chez un cloud commercial, valeurs remises dans la réponse et dans le flux ; "
              "détection impossible ⇒ rien ne part. Branchée sur `chat_with_source` et l'abonnement "
              "Claude Code. Consommateurs prévus : domaine document de l'Anonymizer, mémoire",
              'wama/common/privacy/engine.py',
              'docs/construction/suivi/ROADMAP.md §16.4bis',
              annexes=('wama/common/privacy/recognizers.py',
                       'wama/common/privacy/service.py',
                       'wama/common/privacy/service_client.py',
                       'wama/common/privacy/gate.py',
                       'wama/common/tests/tests_privacy.py',
                       'wama/common/tests/tests_privacy_gate.py'),
              depends_on=('pii_detection', 'detections_document', 'external_sources',
                          'document_text')),
    Mechanism('document_text', 'Couche TEXTE d\'un document — lire, réécrire sur place',
              "Lire les passages d'un document (segments : page d'un PDF natif, paragraphe `w:p` "
              "d'un DOCX — corps, tableaux, zones de texte, en-têtes, pieds, commentaires, notes —, "
              "TXT entier) puis les RÉÉCRIRE SUR PLACE en conservant tout le reste (2026-10-28) : "
              "PDF par caviardage réel (`apply_redactions`, texte supprimé, métadonnées effacées, "
              "fichier réécrit en entier), DOCX au niveau du XML (premier morceau touché, "
              "suppressions du suivi des modifications retirées), TXT dans son encodage. Commune à "
              "l'occultation de `privacy` (Anonymizer, domaine document) et au Translator (traduire "
              "en gardant la forme). Unité `block` (2026-10-29) : un PDF par blocs, chacun réécrit "
              "dans le style qui y domine (famille, gras, italique, taille, couleur, interlignage, "
              "alignement, sens d'écriture), agrandi dans la place libre avant d'être réduit ; un "
              "tableau, cellule par cellule ; une figure (zone `picture` de `pymupdf-layout`), "
              "étiquette par étiquette. `markup=True` : des balises `<tN>` rendent à chaque "
              "passage d'un paragraphe ou d'un bloc SA mise en forme. Le Writer reste le geste de "
              "qui veut REVOIR la mise en forme — ROADMAP §16.4bis, vision §5.4",
              'wama/common/utils/document_text.py',
              'docs/construction/suivi/ROADMAP.md §16.4bis',
              annexes=('wama/common/tests/tests_document_text.py',)),
    Mechanism('model_quality', 'Indice de qualité a priori',
              "Ordonne les modèles autrement que par la taille (params EFFECTIFS √(totaux×actifs), contexte, quantif.). "
              "DÉFAUTS MESURÉS (2026-10-28) : une mesure sans référence qui prend un modèle en défaut (même entrée, "
              "mêmes réglages qu'un autre modèle) le PROPOSE (`propose_defect`), un administrateur valide, le défaut vit "
              "sur la ligne du catalogue (manifeste `model`, `quality.defect`) — GRISÉ au select avec sa raison et sorti "
              "du tirage automatique, comme un modèle sans backend",
              'wama/model_manager/services/model_quality.py', ''),
    Mechanism('benchmark_sync', 'Benchmark tiers confronté',
              "Étage 2 qualité (a priori < benchmark < mesure) : AA + Elo Arena (texte, image, vidéo, VISION, document) + Open ASR (WER, sens 'bas') + MTEB (embeddings, jeu FRANÇAIS déclaré) appariés au catalogue, prospection incluse. "
              "Depuis le 10/10 : la MUSIQUE d'AA (chansons, instrumental) et les CLASSEMENTS des "
              "jeux de référence officiels du Hub (olmOCR-Bench, MDPBench, Real5-OmniDocBench, "
              "ParseBench — valeurs déclarées, `provenance` par entrée) ; appariement par DÉPÔT "
              "exact avant la famille + version ; `provenance` (indépendant / vérifié / "
              "auto-déclaré) et `matched_by` écrits avec chaque banc, rang centile réservé aux "
              "bancs indépendants ; banc mis en file À L'INSTALLATION (`queue_benchmarks`), "
              "synchro chaque nuit, cache disque des sources",
              'wama/model_manager/services/benchmark_sync.py', 'docs/construction/ia/WAMA_QUALITE.md',
              annexes=('wama/model_manager/management/commands/sync_benchmarks.py',)),
    Mechanism('internal_quality', 'Mesure interne des modèles',
              "Étage 3 qualité : ce que WAMA a MESURÉ elle-même contre une référence humaine "
              "(`ResultEvaluation`), agrégé par modèle — taux de CORPUS, échelle nommée "
              "`internal_<métrique>_<protocole>`, sens, rang parmi les modèles mesurés sur les "
              "MÊMES références, accumulation dite. RABATTUE À LA LECTURE (jamais écrite au "
              "catalogue) : elle n'entre dans aucun tri tant que Q3 n'est pas tranchée, et "
              "`sync_benchmarks`, qui remplace `benchmark_meta`, ne peut pas l'effacer",
              'wama/model_manager/services/internal_quality.py', 'docs/construction/ia/WAMA_QUALITE.md',
              annexes=('wama/model_manager/tests/tests_internal_quality.py',),
              depends_on=('result_evaluation',)),
    Mechanism('bench', 'Banc de comparaison',
              "Mesures comparables par TÂCHE sur un échantillon (latence, sorties, saturation) ; "
              "`text-generation` mesure le DÉBIT d'un LLM Ollama (jetons/s, prefill, chargement) "
              "et nourrit la boucle d'ETA (`ModelRuntimeStat`, unité token) — des coûts, jamais "
              "une qualité",
              'wama/model_manager/services/bench.py', 'docs/construction/suivi/ROADMAP.md §16.2',
              # Ses tests sont SON corps, pas des consommateurs (2026-10-12 : deux fichiers de
              # test l'importaient sans être annexés, et le compte « 0 » devenait faux).
              # `tests.py` et `tests_benchmark_chain.py` du model manager aussi (2026-10-17) : ils
              # importent le banc en RELATIF (`from ..services import bench`), forme que le
              # balayage ne résolvait pas avant.
              annexes=('wama/model_manager/management/commands/bench.py',
                       'wama/model_manager/tests/tests_bench_boxes.py',
                       'wama/model_manager/tests/tests_bench_upscale.py',
                       'wama/model_manager/tests/tests.py',
                       'wama/model_manager/tests/tests_benchmark_chain.py'),
              # Plus « autonome » depuis le 2026-10-18 : la découverte du catalogue lit la
              # déclaration de son instrument LPIPS (`LPIPS_FILES`, ligne `quality-metric` que la
              # route installe) — un consommateur réel, que le compte doit montrer.
              ),
    Mechanism('provenance', 'Provenance de modèle',
              "Identité chez l'éditeur (licence, auteur, plateforme, publications arXiv de la "
              "carte), posée VIA le manifeste ; les publications s'affichent dans l'onglet "
              "« À propos » de chaque app (modèles de ses selects de catalogue, 2026-10-10)",
              'wama/model_manager/services/provenance.py', '',
              annexes=('wama/model_manager/services/weights_metadata.py',
                       'wama/common/services/model_publications.py')),
    Mechanism('prospection', 'Prospection de modèles',
              "Veille déterministe HuggingFace/Ollama + évaluation multi-agents (dry-run) ; "
              "versions GitHub lues sur `github_api` (fichiers, licence et facteur DÉCLARÉS, "
              "empreinte lue ou MESURÉE) pour le scout (`--github owner/repo:tag`, 2026-10-07) ; "
              "les CLASSEMENTS des bancs (tâche et rang, `seed_benchmark_candidates`) et les "
              "SUCCESSEURS déclarés par l'auteur (`new_version`, `seed_hf_successors`) sont des "
              "sources de candidats (2026-10-10)",
              'wama/model_manager/services/prospector.py',
              'wama/model_manager/PROSPECTION_PIPELINE.md',
              annexes=('wama/model_manager/services/prospect_agents.py',
                       'wama/model_manager/services/prospect_ollama.py',
                       'wama/model_manager/services/ollama_registry.py',
                       'wama/model_manager/services/update_checker.py')),
    Mechanism('model_registry_discovery', 'Découverte de modèles',
              "Découverte unifiée des modèles (apps + sources externes), synchronisée vers le "
              "catalogue AIModel. Ollama (2026-10-12) : un manifeste INTERNE du démon (étiquette = "
              "empreinte sha256, `is_ollama_runner_alias`) n'est pas un modèle ; seul un relevé "
              "du DÉMON (`ollama_listed`) prouve un retrait fait hors de WAMA — la ligne reçoit "
              "alors la marque d'une désinstallation (`uninstalled_q`)",
              'wama/model_manager/services/model_registry.py', '',
              annexes=('wama/model_manager/services/model_sync.py',
                       'wama/model_manager/services/file_watcher.py')),
    Mechanism('model_installer', 'Installation de modèles',
              "Pipeline accept→download→register : télécharge au bon endroit puis enregistre au "
              "catalogue. UNE route depuis l'extérieur, `request_install` (bouton, assistant, "
              "`pull_model <clé|org/dépôt|nom Ollama>` — un nom se PROPOSE d'abord "
              "(`seed_hf_search`, `seed_ollama_candidate`) —, marcheur d'app "
              "`install_requirements` ; garde "
              "d'espace disque, tâche Celery, journal — seule à appeler `dispatch_install`) ; "
              "`AIModel.is_installable` en dit la règle à la page. Un pilote INTERNE "
              "(`install_from_spec`), un par source : ollama, hf, yolo, github (poids d'une "
              "VERSION GitHub, tag exact + empreinte épinglée, disposition calquée sur HF, "
              "2026-10-07), files (les fichiers qu'une app DÉCLARE, chacun avec son ORIGINE "
              "parmi les sources déclarées — dépôt du Hub figé au commit, version GitHub, adresse "
              "fixe d'une source « poids » — taille et empreinte épinglées, 2026-10-11 : "
              "CodeFormer, MuseTalk, enhancer, Face Analyzer, DeepFace le 12/10, MuScriptor le "
              "16/10 — le jeton d'un dépôt du Hub à accès contrôlé n'est envoyé qu'aux origines "
              "`huggingface` ; la "
              "désinstallation retire ces fichiers-là seulement, `remove_declared_files`) ; "
              "`download_asset` = le "
              "téléchargement contrôlé commun aux pilotes à "
              "fichier (empreinte d'un fichier en place : `provenance.sha256_of`). Dépôt à "
              "ACCÈS CONTRÔLÉ (`AIModel.gated`) : le jeton est celui du compte qui lance "
              "(`api_keys.download_token`), sinon celui de l'instance (`HF_TOKEN`, `.env`). "
              "Route `library` (`install_library`) : PyPI par nom, pin exact — refuse URL, "
              "`git+`, `file:`, `-e` et contrainte lâche ; `constraints.pip` (pins passés par "
              "`-c`) et `constraints.no_deps` (installer SANS les dépendances quand leur "
              "résolution déplacerait le venv, 2026-10-01 ; pendant backend : `PIP_NO_DEPS`) ; "
              "voie VENDOR pour un dépôt épinglé au commit. AUCUNE DÉRIVE (`AGENTS.md`, "
              "2026-10-16) : rien ne télécharge un poids ni ne lance pip à côté — contrôle "
              "`tests_install_route`, budget des dérives existantes qui ne peut que descendre",
              'wama/model_manager/services/model_installer.py', '',
              # Route `library` (install_library) : voie pip ici, voie VENDOR (dépôt épinglé au
              # commit + correctif, ROADMAP D-a, 2026-09-30) dans son exécuteur délégué.
              annexes=('wama/model_manager/services/vendor_installer.py',
                       'wama/common/tests/tests_install_route.py')),
    Mechanism('install_history', 'Journal des installations',
              "Date chaque installation et désinstallation (modèle, librairie) avec son issue et "
              "sa VOIE (model manager, assistant, marcheur d'app, ligne de commande), aux points "
              "uniques de la route ; couche « Installations » du calendrier, inscrite par "
              "`register_instance_layer`. Best-effort : n'échoue jamais une installation",
              'wama/model_manager/services/install_history.py', 'docs/construction/ia/WAMA_MEMORY.md'),
    Mechanism('vision_probe', 'Sonde vision',
              "Décrit une image via un modèle multimodal Ollama local — le SEUL client de vision "
              "depuis le 2026-10-20 : le Describer (images, images-clés de vidéo) y passe, avec "
              "le banc, le smoke UI, les fichiers de référence et les outils de l'assistant ; "
              "son chargement se mesure à la carte (`ollama_host.measured_load`). Par l'appel "
              "COMMUN `ollama_chat` depuis le 2026-10-21, à la TEMPÉRATURE de la card (vide = celle "
              "du modèle)",
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
                       'wama/common/memory/dev_ai.py'),
              depends_on=('vector_service',)),
    Mechanism('vector_service', 'Service de vectorisation',
              "Un ESPACE de vecteurs par nature de média — `text` (qwen3-embedding, celui du RAG) "
              "et `media` (EmbeddingGemma-2, texte ET image : une requête écrite retrouve une "
              "image) —, un moteur UNIQUE (préparation des entrées, appel au fournisseur, "
              "contrôle des dimensions) exécuté par un service uvicorn 127.0.0.1:8002 "
              "(`service.py`, dans son paquet comme le service TTS depuis le 2026-10-28 — "
              "ex-`vector_service.py` à la racine) et son client ; "
              "service éteint, le même moteur tourne dans le process appelant. Deux "
              "espaces ne se comparent jamais ; un fournisseur distant n'entre que s'il sert le "
              "MÊME espace ; le modèle local manquant s'installe par la route (`model_key`) ; la "
              "VRAM se demande au gouverneur sur la ligne de RÉSIDENCE du modèle à l'Ollama hôte "
              "(`ollama_host_owner`, une par modèle), pour le besoin que porte sa ligne de "
              "catalogue — un chargement observé se MESURE à la carte et y est rendu "
              "(`ollama_host.measured_load`, 2026-10-20, qui mesure aussi les conversations)",
              'wama/common/vectors/service_client.py',
              'docs/construction/ia/WAMA_MEMORY.md §7sexies',
              # Le service est une annexe depuis qu'il vit dans son paquet (2026-10-28) : à la
              # racine (`vector_service.py`), il n'était que nommé dans le rôle.
              annexes=('wama/common/vectors/spaces.py',
                       'wama/common/vectors/engine.py',
                       'wama/common/vectors/service.py'),
              depends_on=('resource_governor', 'external_sources')),
    Mechanism('media_index', 'Recherche de la file par contenu',
              "« voiture » retrouve l'élément dont l'IMAGE montre une voiture, sans que son nom le "
              "dise : les images de chaque élément de file (`file_references.card_files`, surfaces "
              "de `DetailRegistry`) vectorisées dans l'espace `media` (table `MediaVector`), par "
              "une tâche de la file GPU au palier bas (`common.index_media`) — lancée par le GESTE "
              "de chercher dans une file et par le lot de nuit, jamais par un battement. La barre "
              "de file commune demande au serveur les cards dont une image répond (écart à une "
              "requête neutre, mesuré), droits de lecture appliqués, et les montre en plus du "
              "filtre par le nom (2026-10-19)",
              'wama/common/vectors/media_index.py',
              'docs/construction/ia/WAMA_MEMORY.md §7sexies',
              annexes=('wama/common/vectors/views.py',),
              depends_on=('vector_service', 'detail_registry', 'file_references', 'filter_bar',
                          'preview', 'resource_governor', 'model_readiness')),
    Mechanism('memory_project', 'Projection des faits en souvenirs',
              "RunOutcome → MemoryItem par OBJET (mécanique, sans modèle, idempotente)",
              'wama/common/memory/project.py', 'docs/construction/ia/WAMA_MEMORY.md §7'),
    # Mécanisme À PART, et non annexe de `memory` : il a sa propre GARDE (le prédicat du lecteur
    # de docs) et sa propre porte d'écriture (projection déclarée, pas le geste d'un utilisateur).
    Mechanism('docs_corpus', "Corpus système — la doc de WAMA pour l'assistant",
              "Projette la doc DÉCLARÉE (`docs_catalog`) en fragments rappelables, découpés par "
              "section ; qui lit quoi = le prédicat du lecteur de docs ; hors du RAG des "
              "utilisateurs par construction ; outils `search_docs` / `read_doc`",
              'wama/common/memory/docs_corpus.py', 'docs/construction/ia/WAMA_MEMORY.md §7quinquies'),
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
              "geste. ⭐ Depuis le 2026-09-27 le geste DÉPLACE au lieu de copier (décision de "
              "Fabien : « un fichier ajouté à la médiathèque doit aller dans la médiathèque ») et "
              "`file_references.repoint` fait SUIVRE tous ses porteurs — la card d'origine "
              "comprise, sinon ranger un résultat le ferait disparaître de sa card. Le RETRAIT est "
              "l'inverse exact : le fichier retourne à l'endroit noté par l'ajout "
              "(`attributes.moved_from`) tant qu'un porteur le désigne, et ne part avec l'asset "
              "que s'il n'en a plus. Même brique (`move_into_library`) pour la seconde porte, "
              "l'ajout d'un fichier du dossier temporaire (`tool_api.add_to_media_library`). Le "
              "PARTAGE n'a rien à suivre : il sert le chemin RÉEL de la ligne.",
              'wama/media_library/services.py', 'docs/construction/ui/CARD_DESIGN.md §2bis',
              symbol='export_item_to_library',
              depends_on=('asset_natures',)),
    Mechanism('item_revisions', "Révisions d'un élément (historique DANS la card)",
              "Chaque résultat produit donne à l'élément une révision numérotée — réglages dérivés "
              "du schéma, fichiers et leur empreinte, instruction — rattachée au fait `produit` de "
              "`RunOutcome` (un journal, pas deux) ; une révision PUBLIÉE est une version. Capture "
              "posée une fois dans le squelette de tâche : zéro ligne par app, la file ne voit rien. "
              "Une app qui le DÉCLARE (`keep_outputs`, le Writer d'abord, 2026-10-13) GARDE la copie "
              "des fichiers de ses 20 dernières révisions + des publiées (`KeptOutputsMixin`, liste "
              "déclarée à la rétention) ; au-delà la révision dit « fichier purgé ». "
              "⏳ Restaurer d'un geste, les dix apps, volet Historique : marches suivantes",
              'wama/common/services/revisions.py',
              'docs/construction/exploitation/WAMA_COLLABORATION.md §7.1',
              annexes=('wama/common/tests/tests_kept_revision_outputs.py',)),
    Mechanism('item_sharing', "Partage d'un élément ou d'un lot (1ʳᵉ interface)",
              "LE GESTE qui manquait au mécanisme de visibilité : `PROFILES_PERMISSIONS §7.5` "
              "disait « il n'existe AUCUNE interface de partage » (il fallait l'admin Django). "
              "Écrit `visibility` + son scope sur l'élément ET son lot — ou sur le lot ET ses "
              "éléments : les DEUX sens sont exigés, le filtre de lecture s'appliquant aux deux "
              "niveaux (un lot partagé aux éléments privés s'affiche VIDE chez le destinataire). "
              "Portées OFFRABLES dérivées de l'utilisateur (unités qui le couvrent, projets dont "
              "il est membre) : une portée sans cible réelle n'est pas proposée. Lecture seule "
              "par construction — l'écriture est le jalon S3 `AccessGrant`, et la modale le DIT. "
              "Depuis le 2026-10-01 : « Dupliquer » une card reçue (`scoping.duplicable_or_404`) et "
              "« Transférer à… » (`card_transfer` : possédés déplacés, désignés copiés). "
              "Depuis le 2026-10-02 : le RANGEMENT chez le destinataire (`reception`, §3bis.2) — "
              "« Retirer de ma file » ≠ supprimer, « Réafficher », SON ordre manuel ; une ligne par "
              "destinataire et par ENTRÉE de file (`ReceivedEntry`), qui ne porte aucun droit. "
              "Depuis le 2026-10-03 : la card reçue en LECTURE SEULE (pastille des deux côtés, "
              "▶ 🗑 → encart, ⚙ en consultation), les MODES déclarés (`SHARE_MODES`, deux "
              "grisés) et les DEMANDES d'accès (`ObjectGrant` : la demande et le droit sont la "
              "même ligne ; la propriété s'accorde, elle cède la card). Puis la COLLABORATION "
              "(E1-E5) : `scoping.editable_or_404` / `can_edit` (lancement, réglages, arrêt, "
              "correction — jamais la suppression), fin notifiée aux deux, verrou doux "
              "(`edit_lock`), réglages tracés au journal, retrait depuis « Mes partages ». "
              "Depuis le 2026-10-06 : le partage À UNE PERSONNE (`share_with_person` — une ligne "
              "`ObjectGrant` accordée, lue par `scoped_visible_q(…, model=)` en extension des "
              "portées ; mode lecture ou collaboration) et le destinataire PRÉVENU (N1 : "
              "`share_received` ; membres d'un projet aussi, unité et public non) ; chaque partage "
              "par portée DATÉ par une ligne `ObjectGrant` sans bénéficiaire (mémoire, jamais "
              "lue pour décider qui voit). Depuis le 2026-10-07 : une fille partagée arrive SEULE "
              "(`batch_common.visible_members`) ; l'enregistrement préparé sur un état PÉRIMÉ est "
              "refusé (`edit_lock.state_token` / `stale_edit`, 409) et le verrou doux tient aussi "
              "la page de correction (`WamaCardMenu.holdEditLock`)",
              'wama/common/services/sharing.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md',
              annexes=('wama/common/static/common/js/wama-share.js',
                       'wama/common/services/card_transfer.py',
                       'wama/common/services/reception.py',
                       'wama/common/services/access_requests.py',
                       # « Demander la promotion » d'un élément d'auteur : la demande est une
                       # ligne `ObjectGrant` de niveau `system` (ROADMAP §29 6a, 20/10).
                       'wama/common/static/common/js/wama-promotion.js',
                       'wama/common/services/edit_lock.py')),
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
              annexes=(),
              depends_on=('file_references',)),
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
              "Une entrée d'une LISTE DE CHEMINS déclarée (`path_list_fields`, les images d'une "
              "génération de l'imager) désigne au même titre qu'un `FileField` : chaque question et "
              "chaque geste lit les deux formes (D35, 2026-10-02). 2026-10-28 : un déplacement fait "
              "aussi suivre les LIGNES D'EXÉCUTION (`ProcessRun.output_ref`, tous les mondes), qui "
              "ne comptent pas comme des cards qui utilisent le fichier ; `referenced_paths` est LA "
              "lecture de tout ce que la base désigne (audit des médias, tirage borné). "
              "⚠ `filemanager.UserFile` est exclu : c'est l'index du gestionnaire lui-même",
              'wama/common/utils/file_references.py',
              'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md',
              annexes=('wama/common/tests/tests_file_references.py',
                       'wama/common/tests/tests_card_listed_files.py')),
    Mechanism('journal', "Journal transversal de l'utilisateur",
              "Tout ce qu'il a lancé, toutes apps — DÉRIVÉ de detail_registry, aucune ligne par app",
              'wama/common/services/journal.py', 'docs/construction/ia/WAMA_MEMORY.md §9bis'),
    Mechanism('calendar', "Calendrier de l'utilisateur et plages réservées",
              "Le journal sur l'axe du TEMPS — mêmes sources (Médias, Lab, Studio), intervalle "
              "d'exécution reconstruit de RunOutcome + processing_seconds ou des champs de fin du "
              "modèle, création des lots ; PRÉVU : fin des traitements en cours (débit observé, "
              "début lu au gouverneur) et passages de purge ; plus la maintenance planifiée (beat) "
              "et ses plages RÉSERVÉES à durée mesurée (tests nocturnes). Projette, n'écrit rien",
              'wama/common/services/calendar.py', 'docs/construction/ia/WAMA_MEMORY.md §9bis.1',
              annexes=('wama/common/static/common/js/wama-calendar.js',
                       'wama/common/tests/tests_calendar.py')),
    Mechanism('scheduled_actions', "Actions programmées (le QUAND)",
              "Programmer le lancement d'une card, d'une sélection ou d'un lot — menu commun, "
              "pastille sur la card, fichier batch (`--when`/`--at`) — depuis UN schéma "
              "(`schedule_params`). L'heure venue, `execute_tool` au nom de l'utilisateur (même "
              "porte que l'assistant) ; placement hors plages RÉSERVÉES ; le ▶ annule sans "
              "confirmation ; jamais de relance d'un élément lancé à la main entre-temps",
              'wama/common/services/scheduled_actions.py',
              'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.6',
              annexes=('wama/common/static/common/js/wama-schedule.js',
                       'wama/common/tests/tests_scheduled_actions.py')),
    Mechanism('global_queue', "File globale GPU (où en est chaque tâche)",
              "Lue, jamais devinée : ce qui tourne au gouverneur, ce que le worker GPU TIENT au "
              "broker (`unacked` : tâche en cours non déclarée, orphelin écarté, différé à son "
              "échéance), ce qui attend dans les listes dans l'ordre de consommation. Heures "
              "prévues = somme de durées MESURÉES (file sérielle) ; place et durée des traitements "
              "des autres, jamais leur titre (une tâche système se nomme). Nourrit le placement "
              "`auto`, la pastille « En file », le calendrier et l'API de l'assistant (`place_of`)",
              'wama/common/services/global_queue.py',
              'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.6',
              annexes=('wama/common/tests/tests_global_queue.py',)),
    Mechanism('rag_gesture', "Ajout au RAG (geste explicite)",
              "Bouton dans l'INSPECTEUR + page « Mon RAG » ; texte pris au schéma canonique, "
              "aucune ligne par app. Pas de balayage : l'entrée au RAG est un geste, par décision. "
              "Surfaces : inspecteur, menu « … » des cards, arbre de fichiers et assistant "
              "(outils `add_item_to_rag` / `add_file_to_rag`) — UN endpoint, deux gestes de la "
              "brique (`memory.index.add_item_to_rag` / `add_file_to_rag`, 2026-10-14) : un "
              "élément par son texte canonique, un FICHIER remonté à l'élément dont il est la "
              "sortie, sinon lu s'il porte déjà du texte (`reference_comprehension.read_document_text`) "
              "et refusé, en le disant, s'il n'en porte pas",
              'wama/common/static/common/js/wama-inspector.js', 'docs/construction/ia/WAMA_MEMORY.md §7ter',
              # Le domicile est le JS : c'est LUI qui rend le geste universel (inspecteur global).
              # Les vues sont l'annexe serveur — la seule porte d'écriture offerte à l'UI.
              annexes=('wama/common/templates/common/rag.html',),
              symbol='rag/ajouter',
              depends_on=('inspector', 'memory')),
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
              annexes=('wama/common/tests/tests_text_metrics.py',)),
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
              "ne charge aucun modèle : il reçoit le geste d'alignement. Bornes "
              "(`move_boundary`, `split_turn`) : déplacer la jonction de deux tours ou couper un "
              "tour, toujours ENTRE deux mots et sans en perdre un — un texte corrigé se réancre "
              "d'abord sur la référence ASR. Plage (`replace_span`) : une plage retranscrite "
              "remplace les mots qui s'y disaient, ou remplit un blanc d'un tour neuf",
              'wama/common/services/word_anchoring.py', 'wama/transcriber/TRANSCRIBER_CORRECTION.md §10.5',
              annexes=('wama/common/tests/tests_word_anchoring.py',
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
              "`has_reference_result` — un test refuse l'une sans l'autre. 2026-10-22 : les "
              "MESURES SANS RÉFÉRENCE d'une sortie (`register_check`), déclarées par process "
              "(`ProcessSpec.checks`), jouées par le squelette, gardées sur la ligne du process et "
              "montrées par la bande des process et la face « Évaluation » — la part de la parole "
              "qu'une transcription couvre, avec « Relancer avec » le modèle local",
              'wama/common/services/result_evaluation.py', 'docs/construction/ia/WAMA_QUALITE.md',
              annexes=('wama/common/tests/tests_result_evaluation.py',
                       'wama/common/static/common/js/wama-evaluation.js',
                       'wama/common/templates/common/_batch_evaluation_line.html',
                       'wama/common/templates/common/_batch_agreement_line.html'),
              depends_on=('text_metrics', 'divergence')),
    # 2026-09-30 : « qui a dit quoi » et « qui parle quand » — mesures rangées sous le modèle qui
    # ATTRIBUE les locuteurs (le diariseur), jamais sous le moteur ASR.
    Mechanism('diarization_metrics', 'Métriques de diarisation à vérité terrain (cpWER / DER)',
              "cpWER : un WER où le mot prêté au mauvais locuteur compte (appariement optimal des "
              "locuteurs) ; DER : parole manquée + fausse alarme + confusion sur le temps "
              "(pyannote.metrics). Une mesure sans objet (sortie non diarisée, pas de temps) rend "
              "None, jamais zéro",
              'wama/common/services/diarization_metrics.py', 'docs/construction/ia/WAMA_QUALITE.md',
              annexes=('wama/common/tests/tests_diarization_metrics.py',),
              depends_on=('text_metrics',)),
    # Rattaché le 2026-08-27, en même temps que son extension aux skills : la brique existait
    # depuis longtemps sans figurer sur la carte — donc invisible à qui cherche « qu'est-ce qui
    # contrôle la doc ? ». C'est précisément le trou que ce mécanisme sert à fermer ailleurs.
    Mechanism('docs_integrity', 'Intégrité doc → code',
              "Vérifie que chaque chemin, ligne et renvoi .md cité par la doc ET par les skills "
              "existe encore ; gate nocturne sur les CIBLES distinctes, pas sur les références",
              'wama/common/management/commands/check_docs.py', 'AGENTS.md §Fichiers de référence',
              annexes=('wama/common/tests/tests_check_docs.py',),
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
              annexes=('wama/model_manager/tests/tests_cloud_models.py',)),
    # 2026-10-14 (ROADMAP §8d étape 3, décision de Fabien : « un fonctionnement unique, commun et
    # centralisé ») : cinq endroits géraient un refus de débit chacun à sa façon, aucun ne comptait.
    Mechanism('source_quota', 'Quotas des services externes',
              "UNE brique pour tout service externe qui limite son débit : la NOTE de saturation "
              "(un refus récent ou une panne écarte la source du tirage automatique), le COMPTE "
              "de chaque appel servi par (source, portée de la clé, modèle) sur une fenêtre "
              "glissante, et les PLAFONDS — déclarés au registre des sources "
              "(`ExternalSource.quotas`, par source ou par groupe de modèles) ou APPRIS au "
              "premier refus réel. Un modèle dont le quota est atteint sort du tirage AVANT le "
              "refus. Portée = la CLÉ (personnelle, ou d'instance partagée par tous)",
              'wama/common/services/source_quota.py',
              'docs/construction/suivi/ROADMAP.md §8d',
              annexes=('wama/common/tests/tests_source_quota.py',)),
    Mechanism('secret_crypto', "Chiffrement RÉVERSIBLE des secrets d'utilisateur",
              "Les clés d'API de fournisseurs cloud sont chiffrées en base, pas hachées : WAMA doit "
              "les RELIRE pour appeler le fournisseur à la place de l'utilisateur. Clé DÉRIVÉE de "
              "`SECRET_KEY` par HKDF avec une étiquette d'usage (décision Fabien : pas de clé de "
              "plus dans `.env`) — on ne chiffre pas avec la valeur qui signe les sessions. "
              "⚠ La rotation de `SECRET_KEY` est le piège : le déchiffrement essaie la courante "
              "puis les `SECRET_KEY_FALLBACKS`, dont `rotate_secrets` ne garde que TROIS",
              'wama/common/utils/secret_crypto.py',
              'docs/construction/suivi/ROADMAP.md §8d',
              annexes=('wama/accounts/tests/tests_api_keys.py',)),
    Mechanism('mcp_server', 'Serveur MCP (adaptateur mince sur tool_api)',
              "Un seul contrat d'outils pour TOUS les cerveaux (Ollama, Claude Code, Albert, un "
              "IDE) : `tools/list` = le registre filtré par `tool_accessible`, `tools/call` = "
              "`execute_tool` — LA porte unique. Adaptateur MINCE : aucun protocole maison, "
              "`tool_descriptions()` dérive déjà nom/description/schéma. DEUX surfaces, DEUX "
              "process : `wama` (prod) et `wama-dev`, jamais chargés ensemble. Client de la "
              "surface `wama` : l'abonnement Claude Code (2026-10-23) ; les deux process sont "
              "ARRÊTÉS à chaque relance (`start_wama_prod.sh`, ils survivaient avec du code "
              "périmé) ; la mesure d'accès : `llm_gateway_check --provider claude_code`",
              'wama/common/services/mcp_server.py',
              'docs/construction/suivi/ROADMAP.md §8d',
              annexes=('wama/common/management/commands/run_mcp_server.py',
                       'wama/common/tests/tests_mcp_server.py')),
              # Déclaré « autonome » (point d'entrée de process, importé par personne) jusqu'au
              # 2026-09-22 : depuis, `mcp_client` lui emprunte le chemin d'endpoint (`MCP_PATH`)
              # — un consommateur, donc plus autonome (garde `tests_catalogues`).
    Mechanism('dev_tools', 'Outils de DÉVELOPPEMENT (surface MCP « wama-dev »)',
              "Rôles wama-dev-ai (librarian, model, scout, integrator, codegen) et bac à sable "
              "d'apps, exposés à un client MCP. ⚠ JAMAIS chargé dans le process de PRODUCTION "
              "(ROADMAP §16 : défense en profondeur > scope de jeton) — ni dans `TOOL_REGISTRY` ni "
              "importé par `tool_api` ; seul `run_mcp_server --surface dev` l'importe, et "
              "`tests_mcp_dev_tools` le garde. Les rôles écrivent une PROPOSITION dans "
              "`wama-dev-ai/outputs/` et n'appliquent rien. Outils d'INSPECTION réservés aux "
              "administrateurs (`dev_inspect` : base en lecture, logs, code ; colonnes "
              "sensibles jamais rendues)",
              'wama/common/services/dev_tools.py',
              'docs/construction/suivi/ROADMAP.md §8d',
              annexes=('wama/common/services/dev_inspect.py',
                       'wama/common/tests/tests_mcp_dev_tools.py',
                       'wama/common/tests/tests_dev_inspect.py')),
    Mechanism('development_models', 'Modèles de NIVEAU DÉVELOPPEMENT (bridage « qualité max »)',
              "UN domicile pour « quel modèle a le droit de travailler sur le code » : plancher "
              "sur le score coding du banc tiers (≥ 40) + déclaration explicite pour le seul "
              "distant non mesuré (albert:gpt-oss-120b), curseur imposé à 100 (réflexion), "
              "distants SOUVERAINS admis dès « cloud si saturé », et REFUS lisible plutôt qu'un "
              "petit modèle en repli. Lu par l'assistant (domaine dev, bascule en cours de tour "
              "dès qu'une compétence dev ou un outil dev_* est appelé, domaine collant au fil) et "
              "par les rôles wama-dev-ai (`role_utils.resolve_model`) — décision Fabien 22/09 "
              "après un tour réel où qwen3.5:4b inventait des jumelles. SECOND PLANCHER au même "
              "domicile (29/09) : `AGENT_CODING_FLOOR` (30) borne le tirage AUTOMATIQUE de tout tour "
              "d'assistant OUTILLÉ, et `escalation_model` choisit le modèle qui REPREND un tour "
              "inventé (`assistant_engine._invented_turn`)",
              'wama/common/services/development_models.py',
              'docs/construction/ia/WAMA_LLM.md',
              annexes=('wama/common/tests/tests_development_models.py',)),
    Mechanism('mcp_client', "L'assistant, CLIENT MCP de la surface de développement",
              "Le moteur de l'assistant RELAIE les outils `dev_*` (rôles wama-dev-ai, bac à "
              "sable) à la surface « wama-dev » par le protocole — process séparé, §16 tenu : "
              "rien n'est importé, la porte (droits à chaque appel, arguments admis) reste celle "
              "du serveur. Annoncés aux seuls développeurs/admins ; serveur absent = aucun outil, "
              "l'assistant répond quand même. Étape 5 de §8d, moitié dev (2026-09-22). Il "
              "porte l'adresse et le jeton de TOUTE surface (`surface_url`, `api_key`), lus aussi "
              "par l'abonnement Claude Code et la mesure (2026-10-23)",
              'wama/common/services/mcp_client.py',
              'docs/construction/suivi/ROADMAP.md §8d',
              annexes=('wama/common/tests/tests_mcp_client.py',)),
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
              annexes=('wama/common/tests/tests_identifier_language.py',),
              symbol='check_identifier_language'),
    Mechanism('docs_catalog', 'Catalogue & lecteur de docs',
              "Déclare les docs de référence (famille, AUDIENCE, journal) et les rend lisibles "
              "depuis WAMA en lecture seule (page `docs`, admins) ; `check_docs` en dérive sa "
              "liste, et un test refuse que la table d'AGENTS.md cite un doc non déclaré. Sert "
              "aussi la doc DÉVELOPPEUR : ses faits (`dev_docs.py` : parcours, registres, API "
              "des briques lue par AST), écrits en `.md` par les plans",
              'wama/common/docs_catalog.py', 'AGENTS.md §Trois docs, trois publics',
              annexes=('wama/common/dev_docs.py', 'wama/common/tests/tests_docs_catalog.py')),
    # 2026-09-11 : 1ʳᵉ pièce de la mécanique des docs dérivées (ROADMAP §25) — les vérités
    # terrain des registres injectées dans les .md, au lieu d'y être recopiées.
    Mechanism('fact_tags', 'Faits en ligne (balises de registre)',
              "Une balise `WAMA:FAIT(registre/clé/champ)` dans un .md va chercher sa valeur dans "
              "le registre (`Registry.entries`) ; `doc_facts` la régénère, `--check` la "
              "confronte, et une balise qui ne se résout pas est CASSÉE. Généralise les blocs "
              "`WAMA:FAITS` (une fonction par fait) à n'importe quel champ de registre",
              'wama/common/fact_tags.py', 'docs/construction/suivi/ROADMAP.md §25',
              annexes=('wama/common/tests/tests_fact_tags.py',)),
    Mechanism('doc_sections', 'Marquage des sections de doc',
              "Une balise `WAMA:SECTION(audience=…; type=…; nature=…; etat=…)` sous un titre dit "
              "à qui la section parle (développeur, utilisateur), quel genre de texte elle est "
              "(tutoriel, guide, référence, explication) et si elle CONSTATE ou VISE ; une "
              "sous-section hérite. `check_docs` contrôle le vocabulaire et la double "
              "vérification (constat ⇒ ✅, intention ⇒ 🔄/⏳) ; `extract` sert les docs dérivées",
              'wama/common/doc_sections.py', 'docs/construction/suivi/ROADMAP.md §25',
              annexes=('wama/common/tests/tests_doc_sections.py',)),
    Mechanism('doc_plans', 'Docs dérivées par plan',
              "Un PLAN déclaré dans le catalogue des docs (extraits de sections marquées + faits "
              "de registre) produit un `.md` versionné, écrit par `doc_facts` ; `--check` refuse "
              "un fichier qui n'est plus ce que son plan produit — la confrontation doc → doc, "
              "gratuite parce que la dérivation est mécanique. Pour l'UTILISATEUR, une PORTE "
              "registre retient les intentions et ce que le registre ne confirme pas",
              'wama/common/doc_plans.py', 'docs/construction/suivi/ROADMAP.md §25',
              annexes=('wama/common/tests/tests_doc_plans.py',)),
    Mechanism('templates_integrity', 'Intégrité des gabarits',
              "Attrape la famille de fautes qui a récidivé SEPT fois : le commentaire `{# … #}` "
              "MULTI-LIGNE, que le lexer de Django (pas de re.DOTALL) rend en TEXTE littéral — "
              "et le nom de balise avaleuse écrit dans un commentaire. Un scan de 5 s contre des "
              "diagnostics qui ont coûté des sessions. Depuis le 01/09, signale AUSSI tout "
              "`{% load %}` vers une bibliothèque de balises absente (garde posée le jour où un "
              "retrait de templatetag a laissé son load — page reader en TemplateSyntaxError)",
              'wama/common/management/commands/check_templates.py', 'AGENTS.md',
              annexes=('wama/common/tests/tests_check_templates.py',),
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
              "gitleaks sur l'historique git COMPLET, aucune ligne d'attribution dans les "
              "messages, et vérifie que les hooks git versionnés (pre-commit, commit-msg, "
              "pre-push — ce dernier voit aussi les commits faits par commit-tree) sont en "
              "place et non dérivés : un hook mort est une garde silencieusement absente, donc "
              "rouge et pas warning",
              'wama/common/management/commands/check_secret_leaks.py', 'docs/construction/suivi/ROADMAP.md §16.10',
              symbol='check_secret_leaks'),

    )),

    *_domain('Contenu & prompts', (
    Mechanism('prompt_pipeline', 'Pipeline de prompts',
              "Traduction/enrichissement centralisés, déclarés par PROMPT_TARGETS ; fichiers de "
              "référence compris et repliés (`reference_field`), lus pour leur CONTENU ou leur "
              "FORME (`reference_reading`, 05/10 — le modèle de mise en page du Writer)",
              'wama/common/utils/prompt_enrichment.py', 'docs/construction/ia/WAMA_LLM.md',
              annexes=('wama/common/utils/app_metadata.py',
                       'wama/common/utils/prompt_pipeline.py',
                       'wama/common/utils/prompt_skills.py',
                       # Les skills d'un COMPTE (`common.PromptSkill`, ROADMAP §29, 20/10).
                       'wama/common/services/user_skills.py',
                       # Les mots-clés d'un auteur (`PromptKeyword`, ROADMAP §29 4ter, 27/10).
                       'wama/media_library/keywords.py',
                       'wama/common/utils/reference_comprehension.py',
                       'wama/common/static/common/js/wama-prompt-chips.js',
                       'wama/common/static/common/js/wama-prompt-enrich.js')),
    # Promu d'`ASSUMED_LOCAL` le 2026-10-16 (« un module assumé qui gagne des consommateurs
    # multi-apps doit repasser en `Mechanism` ») : il servait déjà le pipeline de prompts de TOUTES
    # les apps et l'assistant, sans figurer à la carte — l'assistant, à qui l'on demandait une app
    # de traduction, est parti d'un dépôt externe faute de la trouver. Il devient le moteur de
    # l'app Translator (décision de Fabien).
    Mechanism('translator', 'Traduction de texte',
              "Traduit un texte d'une langue à l'autre : passthrough si source = cible, cache "
              "(clé : modèle, langues, glossaire, texte), glossaire de termes à ne pas traduire, "
              "découpage par paragraphes, `on_chunk` pour l'aperçu « pendant ». Le modèle est "
              "une CLÉ DE CATALOGUE (défaut `ollama:translategemma:12b`) : locale par la voie "
              "Ollama gouvernée, distante par `chat_with_catalog_model` avec la clé de "
              "l'utilisateur. `lang_routing` DÉCIDE quand traduire une consigne avant un modèle "
              "qui ne parle pas sa langue ; le service EXÉCUTE. API ÉTROITE d'une app (2026-10-28) : "
              "`translate_text` et `translate_document` — un document TRADUIT EN GARDANT SA FORME, "
              "bloc par bloc, réécrit à sa place par la couche texte commune (`document_text`, "
              "unité `block`) ; c'est elle que le rôle `codegen` reçoit quand le schéma d'une app "
              "déclare la spécialité `translation` (`options_resolution`)",
              'wama/common/utils/translator.py', 'docs/construction/suivi/ROADMAP.md §10',
              annexes=('wama/common/utils/lang_routing.py',
                       'wama/common/tests/tests_translator.py'),
              depends_on=('llm', 'document_text')),
    Mechanism('llm', 'Accès LLM',
              "Route unique vers les LLM (tiers déclaratifs, sélection catalogue, Ollama local). "
              "`chat_with_catalog_model` (2026-09-30) : un appel désigné par une CLÉ DE CATALOGUE "
              "(`auto`, `ollama:…`, `albert:…`, `anthropic:…`), lue par `model_keys.split_key` — "
              "ce qu'appelle une app dont le réglage « Modèle » est tiré du catalogue (route F4b). "
              "`chat_with_source` (2026-10-01) : l'appel à un fournisseur DÉCLARÉ avec la clé de "
              "l'UTILISATEUR (garde commune `cloud_access`, refus levé avec son statut) — partagé "
              "par l'assistant et les apps, il vivait en privé dans l'assistant. "
              "`auto` y est REFUSÉ : il se tire AVANT l'appel — `auto_model.resolve_model_choice` "
              "dans une app (le chemin de la prévision « Prévu : … »), `modele_par_defaut` hors "
              "app (2026-10-01 : un repli interne faisait annoncer un modèle et en lancer un autre). "
              "La TEMPÉRATURE (2026-10-21) : `None` = celle du MODÈLE, rien n'est envoyé, en local "
              "comme en distant ; une tâche sans réglage passe `STEADY_TEMPERATURE` par son nom. "
              "La GRAINE et le TOP P (2026-10-22) : `seed`, `top_p` explicites, rien d'envoyé sans "
              "réglage, à une source distante compatible OpenAI seulement",
              'wama/common/utils/llm_utils.py', ''),
    Mechanism('assistant_skills', "Skills de rôle de l'assistant",
              "Posture et domaine de l'assistant (science, design, dev) + rappel du "
              "contexte de laboratoire, déclarés par domaine — distinct de l'enrichissement",
              'wama/common/utils/assistant_skills.py', 'docs/construction/suivi/ROADMAP.md §19.7'),
    Mechanism('claude_code', "Claude Code sur abonnement",
              "Délègue une tâche de développement au CLI Claude Code en headless — "
              "lecture seule par défaut, environnement construit sans la clé API. Pour un "
              "compte, le CLI reçoit la surface MCP `wama` (`--mcp-config` seule lue, jeton "
              "d'API par l'environnement, outils `mcp__wama`) : il voit les outils de WAMA, par "
              "la porte `execute_tool` (2026-10-23). Binaire Windows : ses secrets passent par "
              "`WSLENV`, sans quoi l'interop les perdait — le jeton personnel compris",
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
              # + le 26/09 : UN SEUL RENDU DE CHAT. L'accueil portait le sien (282 lignes écrites
              # à la main) pour le même fil ; il DÉCLARE maintenant la brique (`data-density`
              # full / compact). Et le FLUX (levier 5, `WAMA_LLM §1bis`) : `ai_chat_stream` (SSE)
              # + le portier `_TokenGate` du moteur — la réflexion et les appels d'outils arrivent
              # par le même canal que la réponse, il faut trancher sans attendre la fin.
              # + le 2026-10-10 : l'ÉCOUTE (`wama-assistant-listen.js`) — dictée et CONVERSATION
              # vocale sur les deux densités du chat, transcription LOCALE (`views.speech_to_text`
              # → `/stt` du service vocal, Whisper), reprise de parole si le navigateur annule
              # l'écho. Remplace la dictée du navigateur, qui envoyait l'audio à Google.
              # + le 2026-10-11 : le MOTEUR d'écoute (`common/tts/speech_input.py`) — Albert
              # quand le profil ouvre un modèle de transcription distant au tirage automatique,
              # le local sinon et en repli ; filtre de parole au service vocal (`/speech-only`) ;
              # génériques de sous-titres inventés retirés.
              # + le 2026-10-12 : l'écoute SANS chat (`capture()` de la même brique) — le port
              # « en direct » (Speak) du transcriber s'y rallie et quitte la reconnaissance du
              # navigateur (Google).
              # + le 2026-10-28 : la FIN DE TOUR (`common/tts/end_of_turn.py`) — Smart Turn,
              # ligne du catalogue installée par la route, jugé au service vocal (`/end-of-turn`)
              # après 300 ms de pause : net, il avance ou retient la fin de phrase ; incertain,
              # le silence décide comme avant.
              annexes=('wama/common/tts/speech_input.py',
                       'wama/common/tts/end_of_turn.py',
                       'wama/common/static/common/js/wama-avatar.js',
                       'wama/common/static/common/js/wama-avatar-panel.js',
                       'wama/common/static/common/js/wama-assistant-voice.js',
                       'wama/common/static/common/js/wama-assistant-chat.js',
                       'wama/common/static/common/js/wama-assistant-listen.js',
                       'wama/common/static/common/css/wama-assistant-panel.css',
                       'wama/common/templates/common/_assistant_avatar.html'),
              symbol='run_assistant_turn'),
    Mechanism('page_navigation', "Pages qu'un utilisateur peut ouvrir (« emmène-moi sur… »)",
              "Les pages du menu Applications — apps du catalogue et surfaces déclarées, lues par "
              "`get_app_groups` — filtrées par le DROIT du menu (`accessible_apps`) mais pas par la "
              "préférence d'affichage, qui ne retire aucun droit. Sert l'outil `open_page` ; le chat "
              "web suit la page une fois la réponse dite (`applyActions`, 2026-10-11). Et depuis "
              "le 2026-10-14 les pages du COMPTE (profil, journal, calendrier, catalogues…), "
              "DÉCLARÉES par l'app qui les porte (`register_account_page`) : le menu du compte en "
              "est GÉNÉRÉ, et leur droit est celui de la requête réelle (`can_open_page` : "
              "fermeture au visiteur, politique du chemin, décorateur de la vue) — une garde de "
              "PARITÉ confronte chaque déclaration à la réponse de sa vue",
              'wama/common/services/navigation.py', 'docs/construction/ia/WAMA_LLM.md',
              annexes=(),
              depends_on=('app_access', 'app_worlds')),
    Mechanism('conversation_store', "Historique de conversation (serveur)",
              "L'historique de l'assistant côté SERVEUR — remplace le localStorage web et le "
              "dict en mémoire de la passerelle (perdus au changement de navigateur / au "
              "redémarrage). COUCHE AU-DESSUS du moteur, jamais une dépendance : "
              "run_assistant_turn continue d'accepter un history explicite (moteur sans état, "
              "testable sans base). Consommé par la vue web ET la passerelle de canaux "
              "(gateway/core, discord_bot) — cf. ROADMAP §19.5",
              'wama/common/services/conversation_store.py', 'docs/construction/suivi/ROADMAP.md §19.5',
              annexes=('wama/common/tests/tests_conversation.py',),
              # `symbole` : ses clients l'importent par `from wama.common.services import
              # conversation_store` — le compteur d'imports ne voit pas cette graphie (même
              # faux positif que le middleware, cf. plus haut).
              symbol='conversation_store'),
    # Ajouté le 2026-10-18 (Fabien : « l'assistant ne semble pas recevoir de trigger quand un
    # travail est terminé, alors qu'une notification arrive »).
    Mechanism('job_follow_ups', "Fin de tâche racontée dans le fil d'origine",
              "La fin d'un traitement (notification `job_done`/`job_failed`, qui DÉSIGNE l'élément) "
              "racontée dans le fil de l'assistant d'où la tâche a été demandée : origine LUE dans "
              "les étapes d'outils persistées (`tool_api.items_of_step`), geste « statut » "
              "RÉELLEMENT joué, sorties déclarées, enregistrement au fil — une fois, sous verrou, "
              "AVANT publication (`tell`). Commun aux surfaces : la passerelle la relève par un "
              "curseur de canal, joint les fichiers, et republie au retour du canal ce que le fil a "
              "raconté (`told_since`) et que le salon ne montre pas ; le "
              "fil WEB par la relève de la cloche (`wama:notifications`), le chat la DIT. Une fin "
              "arrivée PENDANT le tour qui l'a lancée part avec sa réponse (`notices_of_turn`, "
              "joint par `conversation_turn` ; `tell` raconte une seule fois). Et l'entre-deux "
              "(2026-10-20) : les éléments encore en cours suivis SOUS la réponse, dans l'état de "
              "leur card (`turn_jobs` → `tool_api.job_progress`, `api/ai-chat/jobs/`), leur fin "
              "demandant la relève",
              'wama/common/services/job_follow_ups.py', 'docs/construction/suivi/ROADMAP.md §19.2',
              annexes=('wama/gateway/core.py', 'wama/common/static/common/js/wama-assistant-chat.js',
                       'wama/common/tests/tests_job_follow_ups_web.py'),
              depends_on=('conversation_store', 'notifications')),
    Mechanism('source_ingest', 'Ingest de source',
              "Télécharge une source distante vers le FileField, déclaré par WAMA_INGEST. "
              "⭐ Depuis le 2026-10-13 (décision de Fabien) : DÈS LA CRÉATION, hors requête — "
              "récepteur `post_save` sur tout modèle à WAMA_INGEST → tâche `common.ingest_source` "
              "(file default) ; le lancement rattrape un échec et attend un téléchargement en "
              "cours (verrou partagé). `derive` (chemin pointé) DÉCLARÉ dans la spec ; une page "
              "web gardée en `.html` ; nature d'une URL AVANT téléchargement : "
              "`url_ingest.url_nature` (même table que la décision page/média). Depuis le "
              "2026-10-20 : `download_to_user`, l'URL d'une entrée qui n'est pas encore une card "
              "(card d'entrée du Studio) — mêmes primitives, déposée dans l'espace du compte "
              "comme un fichier du gestionnaire ; `declared_mode`, le mode que l'app destinataire "
              "DÉCLARE dans son `WAMA_INGEST`",
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
              symbol='search_web',
              depends_on=('search_engines',)),
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
              "Extraction/validation/projection des 7 kinds vers les registres. Le corpus "
              "versionné suit le registre À CHAUD par UNE porte (`corpus.follow` : installation, "
              "validation d'une proposition, désinstallation — 2026-10-12), que le runner de "
              "tests coupe",
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
                       'wama/common/manifests/builtin/project.py',
                       # La porte du corpus à chaud (2026-10-12) et sa garde « une seule porte ».
                       'wama/common/manifests/corpus.py',
                       'wama/common/tests/tests_manifest_corpus.py',
                       # À QUI EST un élément, enveloppe ↔ ligne de registre, et « seul le
                       # système entre au corpus » (ROADMAP §29, étape 2 — 2026-10-18).
                       'wama/common/manifests/ownership.py',
                       'wama/common/tests/tests_manifest_ownership.py')),
    Mechanism('manifest_proposals', 'Propositions de manifestes (geste « Valider »)',
              "Le cycle sandbox → vérifié → promu (WAMA_MANIFEST_ARCHITECTURE §4) reçoit son "
              "premier appelant (29/09) : un rôle LLM DÉPOSE son manifeste au magasin (bac à "
              "sable), le model manager en montre le PLAN (champs comblés, divergences NON "
              "appliquées, erreurs), « Valider » SUPERPOSE à l'extraction en ne comblant que des "
              "vides (un manifeste brut effaçait la licence), projette, promeut, exporte au "
              "corpus ; « Rejeter » ne passe pas par un_ingest, qui déferait une projection "
              "jamais faite. Depuis le 18/10 (ROADMAP §29) la file lit la DEMANDE de promotion, "
              "plus le privé, et valider rend l'élément au SYSTÈME, plus à l'admin qui valide",
              'wama/common/manifests/proposals.py',
              'docs/construction/architecture/WAMA_MANIFEST_ARCHITECTURE.md',
              depends_on=('manifests',),
              annexes=('wama/common/tests/tests_manifest_proposals.py',)),
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
              "la graphie courte — ImportError au rendu de CHAQUE card sinon). "
              "PLUSIEURS PROCESS depuis le 05/10 (le Writer, patron composer, décision n°11) : "
              "le pipeline se lit par la CLÉ (`pipeline_decl` : corpus, sinon brouillons), "
              "`function_specs_gen` écrit FunctionSpec + register_app_pipeline (le process "
              "« Sortie » commun = output_spec), tasks_gen une glu par process (`process=`), "
              "models_gen une colonne par sortie et par port, views_gen `start_process`",
              'wama/common/manifests/codegen/templates_gen.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/manifests/codegen/apps_gen.py',
                       'wama/common/manifests/codegen/urls_gen.py',
                       'wama/common/manifests/codegen/models_gen.py',
                       'wama/common/manifests/codegen/params_gen.py',
                       'wama/common/manifests/codegen/tasks_gen.py',
                       'wama/common/manifests/codegen/views_gen.py',
                       'wama/common/manifests/codegen/function_specs_gen.py',
                       'wama/common/manifests/codegen/pipeline_decl.py')),
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
                       'wama/common/tests/tests_backend_inventory.py')),
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
              "porteur du démon Ollama n'en est pas un). Depuis le 29/09 la TÂCHE voyage : un "
              "contrat LIANT (`backend_inventory.TASK_CONTRACTS`) écarte un backend qui n'en "
              "dérive pas — un upscaler n'exécute pas un modèle texte→image, même seul sur "
              "`onnxruntime`. L'AUTRE moitié du routage depuis le 05/10 : `route_for_nature` "
              "suit la décision d'APP (`backends/__init__.ROUTES`, nature d'entrée → fonction "
              "au contrat commun), import relatif au paquet appelant — recopiée quatre fois "
              "avant (enhancer, describer, corps émis par tasks_gen, conversion inline) et "
              "contournée par la tâche du converter (`if/elif` à la main). LA PORTE DE "
              "LANCEMENT depuis le 07/10 : `backend_instance_for_key` (instance par clé, clé "
              "posée, clé d'accès d'un modèle DISTANT par `authorize()`) + `run_contract` "
              "(méthode de travail du contrat de tâche, réglages par leur nom de schéma, "
              "fichiers par le nom de leur PORT — la règle de `generic_runner.port_arguments` "
              "un cran plus bas) — une app ne connaît plus ses moteurs, et `tasks_gen` "
              "compose sur elle le corps d'une app qui choisit son modèle par tâche (08/10)",
              'wama/common/backends/manager.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              symbol='backend_for_model',
              annexes=('wama/common/management/commands/check_backend_links.py',
                       'wama/common/tests/tests_backend_inventory.py',
                       'wama/common/tests/tests_backend_contract_routing.py',
                       'wama/common/tests/tests_route_for_nature.py',
                       'wama/common/tests/tests_backend_by_key.py',
                       'wama/common/tests/tests_tasks_gen_model_route.py')),
    Mechanism('backend_proposals', 'Backends PROPOSÉS par un rôle LLM (marche B2)',
              "Le rôle `backend` (wama-dev-ai/run_backend.py) écrit le backend d'un modèle "
              "installé ; ce module le JUGE (forme : contrat, ENGINE, SUPPORTED_MODELS au niveau "
              "module, interdits cache HF / téléchargement ; résolution SIMULÉE par le vivier ; "
              "smoke CPU PAR CONTRAT, `SMOKES`) puis, sur « Valider » au model manager, l'ÉCRIT "
              "dans `wama/common/backends/` — contrôles REFAITS, jamais par-dessus un module, rien "
              "de commité. Levée ciblée de la règle « l'agent n'écrit pas dans wama/ » (Fabien, "
              "29/09). Smoke image : deux images DISTINCTES ; smoke parole (2026-10-02) : un extrait "
              "réel des corpus d'évaluation, calé sur la référence, texte + segments ordonnés + WER "
              "≤ 75 % (garde-fou contre l'absurde, pas un critère de qualité)",
              'wama/common/services/backend_proposals.py',
              'wama/model_manager/PROSPECTION_PIPELINE.md',
              depends_on=('backend_inventory', 'model_components', 'result_evaluation',
                          'audio_decode'),
              annexes=('wama/common/tests/tests_backend_proposals.py',)),
    Mechanism('model_components', 'Fichiers des composants DÉCLARÉS',
              "Une CLÉ de catalogue → `{rôle: Path}` des composants de `composition.components`, "
              "dans la révision que désigne `refs/main` ; un manque LÈVE avec son rôle. La moitié "
              "« exécution » de l'anatomie déclarée (l'installation en est l'autre) : un backend "
              "généré l'appelle au lieu de réécrire la recherche de snapshot "
              "(`kokoro_onnx_backend` la codait à la main)",
              'wama/common/utils/model_components.py',
              'wama/model_manager/PROSPECTION_PIPELINE.md'),
    Mechanism('onnx_providers', "Fournisseurs d'exécution ONNX",
              "`onnx_providers()` : CUDA, DirectML, CoreML puis CPU en repli ; `cpu_only` pour un "
              "smoke qui ne dispute pas la carte. Extrait d'`AIUpscaler` le 29/09 au moment où un "
              "second backend onnxruntime arrivait (texte→image) — le module porte aussi la "
              "conversion/inspection de poids ONNX, plomberie de la chaîne modèles",
              'wama/common/utils/onnx_utils.py', 'wama/model_manager/PROSPECTION_PIPELINE.md',
              symbol='onnx_providers'),
    Mechanism('model_declarations', "Passe-plat des déclarations de modèle",
              "Lire la déclaration d'un modèle SANS importer l'app qui la porte : applique la "
              "convention `wama/<app>/utils/model_config.py::<APP>_MODELS`, ne connaît aucune "
              "app, et surtout ne touche AUCUNE BASE. "
              "⚠ Le catalogue `AIModel` porte la même information, mais le lire ajouterait une "
              "dépendance ORM à chaque backend — or c'est justement l'absence de Django qui les "
              "rend déplaçables. On lirait la bonne donnée en détruisant la propriété cherchée",
              'wama/common/utils/model_declarations.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              symbol='declaration',
              annexes=('wama/common/tests/tests_backend_inventory.py',)),
    Mechanism('backend_isolation', "Environnement d'exécution d'un backend",
              "`ISOLATION` déclare où tourne un backend (`venv:<chemin>` | `service:<url>`, "
              "vide = venv principal). Sans elle le GRISAGE MENT : `missing_packages()` "
              "interroge `find_spec` dans CE processus, verdict muet sur un backend qui vit "
              "ailleurs. Le défaut est UN venv — l'isolement se DÉCLARE, ne se génère jamais : "
              "son coût n'est pas le disque mais la VRAM, chaque processus isolé étant un "
              "détenteur que le gouverneur ne voit pas. Zéro isolement aujourd'hui",
              'wama/common/backends/base.py', 'docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md',
              symbol='ISOLATION',
              annexes=('wama/common/tests/tests_backend_inventory.py',)),
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
                       'wama/common/tests/tests_hf_cache_routing.py')),
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
    Mechanism('output_formats', 'Réglages de sortie (formats, agrandissement)',
              "Source commune des formats+qualités de fichier par domaine (réutilise le vocabulaire "
              "converter) ET leur APPLICATION : `apply_output_settings` enchaîne agrandissement "
              "(image) puis conversion après n'importe quel backend (2026-09-30). L'agrandissement "
              "(`output_upscale`, opt-in `include_upscale`) tire l'upscaler du catalogue — tâche "
              "`upscale`, capacité `scale` = facteur, curseur qualité de l'item — sans nommer ni "
              "modèle ni app ; il vivait dans UN backend (diffusers, LANCZOS ×2), ignoré des autres. "
              "`render_outputs` (2026-10-03) GARDE le fichier d'origine (`<nom>.native<ext>`, champ "
              "`native_outputs` du mixin `NativeOutputsMixin`, déclaré à la rétention) tant que ces "
              "réglages le transforment : le process « sortie » d'une app se rejoue SEUL, sans "
              "regénérer",
              'wama/common/utils/output_formats.py',
              'docs/construction/architecture/WAMA_APP_CONVENTIONS.md §6.4'),
    Mechanism('output_process', 'Process « Sortie » d\'une card',
              "Le second temps de toute app qui rend un fichier, en process À PART : "
              "`output_spec` (le `ProcessSpec`, qui surveille format / qualité / agrandissement) "
              "et `output_step` (la glu, au contrat du squelette). La glu du MOTEUR n'a que "
              "trois gestes : `drop_previous_outputs`, `generated(...)`, et l'enveloppe de tâche "
              "appelle `forget_lost_generation`. Changer de format ne rejoue plus le moteur "
              "(2026-10-03) — imager, composer, synthesizer, anonymizer, enhancer ×2. Un ancien "
              "rendu n'est retiré que sous les deux règles de `safe_delete_file` : il vit chez "
              "l'app de la card (`owns_file`) et aucune autre card ne le désigne. `output_step("
              "transform=, apply=)` : le même process pour une transformation PROPRE à l'app — "
              "l'amélioration faciale de l'avatarizer (process « Visage », 2026-10-04)",
              'wama/common/services/output_process.py',
              'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.6',
              annexes=(),
              depends_on=('output_formats',)),
    Mechanism('detections_document', "Document de détections (type `detections` sur disque)",
              "Les objets détectés d'un média, frame par frame (boîte, contour en polygones, piste) "
              "— le type de donnée commun `detections` écrit sur disque (2026-10-04, décision de "
              "Fabien : détection et floutage séparés dans l'anonymizer). Écrit par un process "
              "« Détection », relu par le floutage (`blur_utils.blur_detections` ; les formes "
              "segmentées toutes ensemble, `blur_shapes`, mêmes finitions qu'un rectangle ; "
              "réécriture image par image `rewrite_media`) et par l'aperçu (`draw`) ; "
              "interpolation des trous d'un objet à la lecture (`by_frame`, la forme suit la "
              "boîte déduite) — même objet par la piste OU par une position plausible, le "
              "réglage seul pour limite, le centre comblé en COURBE (2026-10-05, card #1026) ; "
              "et PROLONGÉ de quelques images avant sa première détection et après sa dernière "
              "(`max_extrapolation`, réglage séparé). Recouvrement, courbe et extrapolation sont "
              "les primitives communes de `wama_data/functions` (`box_iou`, `hermite_gap`, "
              "`extrapolate_speed_accel`), celles du cam_analyzer. Sans Django ni app : la Data "
              "et le Lab peuvent le lire",
              'wama/common/utils/detections.py',
              'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.6',
              annexes=('wama/common/utils/blur_utils.py',),
              depends_on=('video_render',)),
    Mechanism('video_render', "Rendu vidéo image par image, à horodatages d'origine",
              "Réécrit une vidéo en passant chaque image par une transformation de l'app, en UN "
              "encodage dans le conteneur demandé (celui de l'entrée : le moins de conversions "
              "possible), les codecs étant ceux d'une conversion vers ce format "
              "(`converter.video_backend.rendering_encoding`) : chaque image à SON horodatage "
              "d'origine (PyAV — une cadence variable garde ses temps), l'audio de la source "
              "RECOPIÉ à ses propres temps, jamais étiré (décisions de Fabien, 2026-10-28). La "
              "taille de sortie est celle de l'image transformée. Né pour le floutage "
              "(`detections.rewrite_media` : anonymizer, cam_analyzer), sorti en brique le "
              "2026-10-29 pour l'agrandissement vidéo de l'enhancer, qui sortait MUET",
              'wama/common/utils/video_render.py',
              'docs/construction/architecture/WAMA_APP_CONVENTIONS.md',
              annexes=('wama/common/tests/tests_video_render.py',)),
    Mechanism('during_preview_variants', "Aperçu « pendant » à plusieurs vues",
              "Un worker publie plusieurs vues du même instant (`publish_partial(variant=, label=)`, "
              "publieur de partiels limité dans le temps `PartialFrames` — frames JPEG, et le SON "
              "déjà produit en WAV avec ses pics depuis le 2026-10-20) ; la face PENDANT de "
              "l'aperçu les liste et sert celle demandée (`?variant=`), le volet et la visionneuse "
              "affichent le bouton de bascule (`WamaMediaPreview.variantToggle`, brique d'aperçu "
              "`preview` — il vivait dans l'inspecteur jusqu'au 2026-10-13). Né le 2026-10-04 pour "
              "basculer entre détection et floutage de l'anonymizer — toute app peut publier ses vues",
              'wama/common/utils/preview_utils.py',
              'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.6',
              symbol='PartialFrames'),
    Mechanism('process_start_view', "▶ d'un process (fabrique commune)",
              "La vue `start/<pk>/<process>/` d'une app à pipeline — `make_process_start_view` "
              "(2026-10-04) : process connu, ayant lieu pour cette card (`AppPipeline.applicable`), "
              "anti-course (`begin_processing`), tâche lancée bornée à ce process. Écrite à la main "
              "dans six apps avec trois formes de refus ; mêmes crochets que `make_batch_views` "
              "(`task_for`, `reset_on_start`). Le pipeline se lit de l'app de l'élément "
              "(`pipeline_of`), il n'est pas un argument. Le geste est `start_one_process` : "
              "la vue et l'outil `start_<app>(…, process=…)` de l'assistant l'appellent tous deux "
              "(2026-10-14)",
              'wama/common/utils/process_views.py',
              'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.6',
              depends_on=('process_pipeline',)),
    Mechanism('item_views', "▶ d'une card, ▶ et 🗑 de la file (fabrique commune)",
              "Les vues `start`, `start_all` et `clear_all` d'une app — `make_item_views` "
              "(2026-10-29, ROUTE §11 #39) : anti-course (`begin_processing`), remise à zéro de "
              "l'app sous le verrou, cache de progression purgé, tâche envoyée ; « tout lancer » "
              "selon la sélection DÉCLARÉE (`pending` / `pending_exclude`, noms de `TRIAD_SPECS`) "
              "et, s'il en porte, les réglages postés vérifiés sur toute la file avant le premier "
              "lancement ; « tout effacer » sans les éléments en cours, par le geste de retrait "
              "de `batch_delete` (`discard_element`). Trente copies dans dix apps. La fabrique "
              "INSCRIT sa déclaration par modèle (`declaration_for`) : l'outil `start_<app>` de "
              "l'assistant la lit — un geste, deux portes, comme `start_one_process`",
              'wama/common/utils/item_views.py',
              'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §11',
              depends_on=('progress_views',)),
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
              "(11 scénarios `<label>.*` du registre nocturne) : describer_01 = 11/11. "
              "Depuis le 2026-10-20 : la chaîne en UNE commande (`substitute <label> "
              "a,b+c,…`, seconde passe des groupes revenus, puis leur union — `models` compris quand "
              "le modèle copié tient le nœud), et UN sous-processus de juge par "
              "substitution (`check`, page, file habitée) — un démarrage de Django coûte ≈ 60 s "
              "sous WSL",
              'wama/common/sandbox.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/management/commands/app_sandbox.py',
                       'wama/common/tests/tests_sandbox_coherence.py')),

    )),

    *_domain("File d'attente & lots", (
    # Déclarés parce que AGENTS.md les nomme explicitement « ce qui existe déjà dans common/ —
    # à utiliser, ne pas recréer » : ne pas les tracer ici laisserait la carte en dessous des
    # instructions du dépôt.
    # Retirer une card LIBÈRE ses fichiers au lieu de les effacer (2026-09-30, MEDIA_STORAGE_TIERING
    # D34) : `release_card_file` décide, `released_files` prévient (annonce, notification, info en
    # rouge) et ne supprime que sur le geste de l'utilisateur. D35 (2026-10-01) : le retrait se
    # fait à l'échelle de la CARD (`release_card_files`), listes de chemins déclarées comprises.
    Mechanism('queue_duplication', 'Duplication et suppression sûres',
              "duplicate_instance(), release_card_files() (retirer une card libère TOUT ce qu'elle "
              "porte et prévient : ses champs fichier et ses listes de chemins déclarées, lus par "
              "`file_references.listed_paths` ; release_card_file() = le même geste pour un champ) et "
              "safe_delete_file() (relance) — fichiers partagés entre items ; la confirmation "
              "commune d'un retrait (`WamaApp.ask`) demande d'avance « supprimer aussi le "
              "fichier ? », case décochée (`released_files.freed_by`)",
              'wama/common/utils/queue_duplication.py', 'docs/construction/architecture/WAMA_APP_CONVENTIONS.md',
              annexes=('wama/common/services/released_files.py',
                       'wama/common/static/common/js/released-files.js')),
    Mechanism('batch', 'Import par lot',
              "Parsing des fichiers batch (txt/csv/pdf/docx) et cycle de vie du lot. Depuis le "
              "2026-10-20 : `parse_batch_lines` (les lignes normalisées, toutes familles) et "
              "`line_to_ports` (une ligne rangée dans les PORTS d'un nœud : colonne au nom d'un "
              "port, rôles `-i`/`-p`/`-r` en alias, refus nommé) — lus par le Studio",
              'wama/common/utils/batch_parsers.py', 'docs/construction/ui/BATCH_FORMAT.md',
              annexes=('wama/common/utils/batch_common.py',
                       'wama/common/utils/batch_sync.py',
                       'wama/common/static/common/js/batch-import.js')),
    Mechanism('queue_view', 'Tri/filtrage de la file',
              "Tri + filtrage communs de la file unifiée, préférence persistée et PARTAGÉE entre apps",
              'wama/common/utils/queue_view.py', 'docs/construction/ui/CARD_DESIGN.md',
              depends_on=('queue_order',)),
    Mechanism('queue_manipulation', 'Manipulation directe de la file',
              "Endpoints génériques : sortir une card d'un batch, réordonner DANS un lot, "
              "ordonner la FILE (`reorder_queue`, 2026-09-04), déplacer, FUSIONNER (`merge`) et "
              "consolider. ⚠ `merge` ≠ `consolidate` : le premier fusionne en UN lot et REFUSE "
              "si les natures ne cohabitent pas (geste du drag&drop, on a visé une card) ; le "
              "second RANGE par nature en N lots. La nature est déclarée UNE fois (`group_key`) "
              "et la fabrique INSCRIT le regroupement à l'arrivée de son modèle : "
              "`consolidate_arrival`, appelé par tout chemin d'arrivée (dépôt de N fichiers, "
              "import du gestionnaire de fichiers, fichier de lot) — aucune app ne le "
              "redéfinit depuis le 2026-10-16 (tests_arrival_consolidation)",
              'wama/common/utils/queue_manipulation.py', 'docs/construction/ui/CARD_DESIGN.md §3bis'),
    Mechanism('batch_views', 'Vues de lot (fabrique commune)',
              "Les six ACTIONS de lot en une fabrique — `make_batch_views` : batch_start, "
              "batch_update, batch_delete, batch_duplicate, batch_download, batch_status — "
              "et l'ÉCRIVAIN de ZIP partagé avec la file (`zip_elements`, 2026-10-17 : rendu "
              "late-binding, sinon les sorties DÉCLARÉES de la card ; nommage déclaré ici une fois ; "
              "`ResultArchive` depuis le 2026-10-20, qui range dans UN ZIP les cards de plusieurs "
              "apps — celui d'une exécution du Studio ; `lot_overview`, la règle d'état d'un lot "
              "de `batch_status`, extraite le même jour pour le run de lot du Studio) — "
              "paramétrée comme la fabrique de file "
              "(les deux formes de rattachement par "
              "`batch_elements`/`attach_to_batch`). EXTRAITE le 2026-09-22 des corps "
              "conventionnels du générateur d'apps (`views_gen`), qui la consomme ; les apps "
              "réelles les écrivaient chacune à la main (60 lectures de lot recopiées, "
              "`ROUTE §11 #36`) — ADOPTÉE 10/10 le 2026-09-23, spécificités en kwargs (jamais un "
              "`if app`), chaque élément lu portant `batch_link` (la ligne qui le porte). Plus aucune "
              "vue de lot locale depuis le 2026-10-02 : le ZIP multi-format lit les formats "
              "DÉCLARÉS et le rendu ENREGISTRÉ (`export_formats`), et `batch_update` appelle la "
              "fonction de réglage de l'APP, celle de sa route d'élément (`apply_settings` — le "
              "lot et l'élément ne peuvent plus diverger ; refus = 400, aucune fille écrite). "
              "Critère `batch_views_common` VRAI 10/10 ; garde générique "
              "`tests_item_settings_contract.BatchSettingsFollowTheItemRouteTest`",
              'wama/common/utils/batch_views.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §11'),
    Mechanism('progress_views', 'Vues de progression (fabrique commune)',
              "Le suivi d'UNE card (`progress`), la barre de FILE (`global_progress`) et le ZIP "
              "de cette file (`download_all`, 2026-10-17 : la même déclaration `queryset` / "
              "`domains`, les entrées par `batch_views.zip_elements`) en une "
              "fabrique — `make_progress_views` (`ROUTE §11 #37`, 2026-10-03). Les dix apps les "
              "écrivaient à la main : trois formules de progression d'ensemble, quatre "
              "vocabulaires de clés que le JS commun absorbait. UNE formule, celle du contrat de "
              "la barre commune (réussi = 100, en cours = sa progression vivante, échec et attente "
              "= 0 : un échec n'est pas terminé), un vocabulaire COMPLET ; les spécificités en "
              "crochets (`eta_for` = le triplet d'ETA, déclaré UNE fois dans le module de tâches "
              "— `<app>_eta_key_size`, que la glu rend aussi à `record_run` — pour une app à un "
              "seul process ; une card à process est estimée par `process_runs.launch_eta`), "
              "`extra`, "
              "`progress_of` — même crochet que `batch_views` —, `pipeline_model` pour la bande "
              "des process, `domains` pour une barre par domaine ; utilisateur par défaut : "
              "connecté, sinon anonyme). Le générateur d'apps la consomme. Critère "
              "`progress_views_common` ; contrat générique "
              "`tests_item_lifecycle_contract` (clés d'une card et de la file, toutes les apps)",
              'wama/common/utils/progress_views.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §11',
              annexes=('wama/common/tests/tests_progress_views.py',
                       'wama/common/tests/tests_queue_zip.py'),
              depends_on=('task_skeleton', 'batch_views')),
    # Ajouté le 2026-10-03 (P5, 5.3) : la décision du 2026-08-25 (`MODES_QUEUE_UX §5ter`) enfin
    # construite — elle attendait une MÉMOIRE que les modèles de lot n'avaient pas.
    Mechanism('batch_settings', "Réglages de référence d'un lot (promotion fille ↔ mère)",
              "UNE ligne par lot (`BatchSettings`, adressée comme `ProcessRun`) : ce que la mère "
              "TIENT pour référence — posé par sa ⚙ (`batch_update` la retient désormais) ou PROMU "
              "d'une fille (`batch_promote`, POST `source=`) ; « ↓ réaligner » (`batch_realign`) la "
              "repose sur toutes les filles et efface les écarts individuels. La charge utile est "
              "DÉCLARÉE (`promote_payload`), par défaut les réglages du SCHÉMA lus par la règle de "
              "la révision ; le monde Data y mettra son protocole — même geste, deux charges. Les "
              "trois gestes écrivent par le chemin de la ⚙ de lot (deux temps, un refus n'écrit "
              "rien) ; la référence suit la duplication et part avec la suppression. Surfaces : "
              "bouton ↓ de la card mère (désactivé et DISANT pourquoi sans référence), entrée "
              "« Promouvoir ses réglages au lot » du menu « … » d'une fille. 9 apps câblées + le "
              "générateur ; le composer suit avec son câblage pipeline",
              'wama/common/services/batch_settings.py', 'docs/construction/ui/MODES_QUEUE_UX.md §5ter',
              annexes=('wama/common/tests/tests_batch_views.py',),
              depends_on=('batch_views', 'item_revisions')),
    # Ajouté le 2026-10-19 (demande de Fabien : « seul le numéro identifie un batch »).
    Mechanism('batch_identity', "Identité d'un lot (titre, ce qui varie, nom donné)",
              "Ce que la card mère, le volet, le menu « Ajouter à un lot », le calendrier, la page "
              "des partages et les notifications DISENT d'un lot — tout LU, rien déclaré : l'ENTRÉE "
              "de chaque élément (spec de la fiche Infos, son vrai nom par la provenance), "
              "l'ORIGINE (fichier de lot, sinon dossier commun des sources), ce qui VARIE (réglages "
              "`chip=True`, `card_chips.varying_chips_for_items`), et le NOM donné à la main "
              "(`BatchLabel`, adressé comme `BatchSettings`), qui prime. Titre : nom donné, entrée "
              "commune, fichier de lot, dossier, sinon plage des entrées. Deux requêtes par page, "
              "posées par `batch_common.attach_identities` dans les TROIS constructeurs de file "
              "(`build_batches_list`, le converter, l'index généré en FK directe). Geste « Renommer "
              "le lot… » du menu de la card mère → `common:api_batch_label` (`editable_or_404`)",
              'wama/common/services/batch_identity.py', 'docs/construction/ui/CARD_DESIGN.md §3quater',
              annexes=('wama/common/tests/tests_batch_identity.py',
                       'wama/common/templates/common/_batch_card.html'),
              depends_on=('batch_settings', 'card_chips', 'detail_registry')),
    Mechanism('queue_order', 'Ordre MANUEL de la file',
              "Position de l'entrée de file décidée par l'utilisateur (`QueueOrderMixin."
              "queue_index`, 13 modèles de batch) + 6ᵉ tri « Manuel » — le SEUL tri qui LIT une "
              "colonne au lieu de la calculer. `queue_index == 0` = jamais ordonné à la main, et "
              "passe EN TÊTE par récence : une file jamais manipulée s'affiche comme en tri "
              "`recent`, et un import arrivé après un classement manuel apparaît en haut au lieu "
              "de se noyer dans un ordre qu'il n'a pas connu. `reorder_queue` écrit 1..N",
              'wama/common/models.py', 'docs/construction/ui/CARD_DESIGN.md §3bis',
              annexes=(),
              symbol='QueueOrderMixin'),
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
              "le dernier site, la boucle vidéo de l'enhancer (ex-`tasks.py:534`), porté le 26/08, "
              "n'écrit plus d'intermédiaire depuis le 2026-10-29 (rendu commun `video_render`, qui "
              "agrandit et encode au fil de la lecture) ; la glu `enhancer/tasks.py` garde le sien "
              "pour ranger la sortie. ⚠⚠ L'audit AUTOMATIQUE "
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
    Mechanism('notifications', 'Notifications',
              "notify_job_end() — LA fin d'un traitement (squelette de tâche) : e-mail "
              "(notify_job) et notification DANS WAMA au propriétaire selon ses préférences, "
              "puis aux collaborateurs ; la notification DÉSIGNE son élément (app + type + id), "
              "ce que relève la passerelle pour poster la fin dans le fil d'origine (2026-10-06) ; "
              "notify_in_app() — DANS WAMA (badge de l'en-tête, page /common/notifications/, "
              "lu / non lu) ; SOUND_BY_KIND — les types qui SONNENT dans la page (fin de "
              "traitement), selon le réglage « Son dans WAMA » du profil ; notify_admins() — "
              "les deux canaux vers les administrateurs (mort d'un worker)",
              'wama/common/utils/notifications.py', 'docs/construction/exploitation/WAMA_COLLABORATION.md',
              annexes=('wama/common/context_processors.py',
                       'wama/common/templates/common/notifications.html')),

    )),

    *_domain(UI_DOMAIN, (
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
              "remplacé resolve_options du converter + les défauts en dur des backends. Depuis le "
              "12/10 (ROUTE §10.6 3.3bis, R1) c'est LA forme de tous les mondes : le pont "
              "`param_from_spec` projette les `ParamSpec` d'une fonction sans perte, le Studio rend "
              "tous ses nœuds par WamaParams (renderer commun `media_picker`, `isGesture`), et la "
              "PORTE des refus (`schema_refusals`/`checked_values` : choix hors liste, nombre "
              "illisible ou hors grille) est lue par la porte des outils, le lancement d'un graphe, "
              "l'exécution d'une fonction et le moteur de vue Data. Depuis le 18/10 un PORTEUR "
              "peut valoir une LISTE, lue « l'une de » par les deux juges de `show_if` (la nature "
              "encore inconnue de ce que reçoit un nœud du Studio : les réglages de chaque nature "
              "possible se montrent), et la réduction de la ⚙ d'UN process a son jumeau serveur "
              "(`scoped_names` ⟷ `scopedSchema`), lu par le nœud d'étape et son exécuteur. La "
              "TEMPÉRATURE commune (2026-10-21) : `temperature_param(<champ modèle>)`, type "
              "`temperature` (vide = celle du modèle), lié à son modèle par une LISTE de `cap_from` "
              "(`cap_bindings` ⟷ `capBindings`) — grisé s'il ne tire pas, valeur de l'éditeur "
              "rappelée, borné au maximum et au minimum du moteur, une ligne qui dit si le "
              "résultat est REPRODUCTIBLE (2026-10-22). Et une condition `show_if` dont le champ "
              "n'est pas RENDU dans le conteneur ne cache rien (même date). Un réglage `advanced` "
              "sans groupe se range dans le groupe « Avancé » replié sur TOUTE surface, la "
              "température comprise (même date), avec ses deux voisins `seed_param` / "
              "`top_p_param` (types `seed`, `top_p`) ; vide = un CHOIX pour les trois "
              "(`EMPTY_IS_NONE_TYPES`), la graine de l'imager comprise",
              'wama/common/utils/param_schema.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/static/common/js/wama-params.js',
                       'wama/common/templates/common/_settings_modal_footer.html')),
    Mechanism('model_capabilities', 'Vocabulaire des capacités',
              "Canonicalise capabilities (tâche, modalités, entrées) — source du filtrage UI ; "
              "`category` (vocabulaire fermé `CATEGORY_LABELS`) range un select de modèle en "
              "optgroups (`options_group=\"category\"`, 2026-09-29) ; bornes de TAILLE "
              "(`native_resolution`/`min_resolution`/`max_resolution`, `resolution_bounds`) "
              "pour l'image comme la vidéo — les tailles proposées en dérivent (2026-09-30) ; la "
              "TEMPÉRATURE d'un modèle qui tire, quel que soit son type (2026-10-21) : `params` ∋ "
              "`temperature`, `recommended_temperature` (Ollama : son fichier de modèle), "
              "`max_temperature` ; la graine et le top_p (2026-10-22) : `params` ∋ `seed` / "
              "`top_p`, `recommended_top_p`, déclarés par le moteur (`reads_seed`, `default_top_p`)",
              'wama/common/utils/model_capabilities.py', 'docs/construction/ui/INPUT_MODEL_MATCHING.md',
              annexes=('wama/common/static/common/js/wama-model-caps.js',
                       'wama/common/static/common/js/wama-input-match.js',
                       # Côté SERVEUR de wama-input-match (meta catalogue + labels INPUT_TYPES),
                       # extrait de composer/imager le 2026-08-17 (adoption ×7) ; `card_match`
                       # (2026-10-21) : la card d'une app à côté de son volet généré (Studio).
                       'wama/common/utils/input_match.py',
                       # Spécialisation TTS du côté serveur : les DEUX apps à select de moteur
                       # TTS (synthesizer, avatarizer) lisent le même catalogue. Extrait de
                       # synthesizer/views.py au 2ᵉ consommateur, 2026-08-28.
                       'wama/common/tts/ui_meta.py',
                       'wama/common/static/common/js/wama-model-help.js')),
    Mechanism('detail_registry', 'Inspecteur — champs de détail',
              "Schéma canonique des infos d'item affichées au volet droit",
              'wama/common/utils/detail_registry.py', 'docs/construction/ui/INSPECTOR_DETAIL_FIELDS.md',
              annexes=('wama/common/static/common/js/wama-inspector-autofill.js',
                       'wama/common/templates/common/_inspector_banner.html')),
    Mechanism('preview', 'Preview unifiée',
              "Registre d'adaptateurs par modèle : la preview des cards vient du commun, pas des apps ; "
              "un MIME `model/…` ouvre la visionneuse 3D commune (`wama-3d-viewer.js`, three "
              "vendorisé), chargée À LA DEMANDE par l'importmap — sans importmap, téléchargement "
              "(2026-09-13, §17ter trou 2). Les faces entre Entrée et Sortie sont les PROCESS du "
              "pipeline de la card, DÉRIVÉES de ce qu'il déclare (`_process_faces`, 2026-10-12 — "
              "elles se déclaraient à la main, `register(faces=)`, R119) : libellé du process, "
              "résultat lisible (`ProcessSpec.result`, un texte) ou fichiers (`outputs`), rendu par "
              "le TYPE du port de sortie — des `detections` dessinées sur l'entrée par "
              "`WamaPreviewOverlay` (options de dessin : `register(overlay_options=)`) ; une face "
              "qui montre ce que montre déjà une autre n'est pas une étape de plus. La dernière face "
              "qui montre l'entrée est la référence de Comparer, ouvert aux VIDÉOS synchronisées "
              "(2026-10-05). La modale "
              "porte les mêmes faces d'où qu'on l'ouvre (volet, vignette de card), suit la "
              "face PENDANT en direct avec ses vues — par le MÊME suiveur que le volet "
              "(`followDuring`) —, et son PLEIN ÉCRAN est elle-même agrandie "
              "(la surcouche image seule ne sert plus qu'aux galeries sans élément). Depuis le "
              "2026-10-12 : la face Entrée se lit, comme la Sortie, dans les clés canoniques du "
              "detail (`source_file`, sinon `source_text`) sous la règle des ports (travail, sinon "
              "prompt, jamais référence) ; UNE fabrique de face fichier (`file_face`, texte d'un "
              ".docx extrait) sert les cards ET le filemanager ; un texte inline voyage sous la "
              "seule clé `content` ; une card ouvre son entrée par le geste commun "
              "`.preview-media-link` (geste nocturne `<app>.preview`). Depuis le 2026-10-13, UNE "
              "brique front (`media-preview.js`, `WamaMediaPreview`) porte tout l'aperçu : rendu "
              "en ligne (cards, volet, fenêtre de sélection), bascule des faces COMMUNE au volet et "
              "à la visionneuse (`sidesBar`, Pendant compris — le volet en avait sa copie), "
              "Comparer (`compareFaces`, `compareView` ; fichier par fichier pour une sortie multiple, "
              "titré par ses deux fichiers), suiveur Pendant, visionneuse, et UNE "
              "navigation : une séquence (les cards de la file, les fichiers d'un dossier du "
              "gestionnaire, une galerie) puis les fichiers d'une sortie multiple — ←/→ fichier "
              "par fichier puis élément voisin, ↑/↓ d'élément en élément, face gardée, volet "
              "resynchronisé à la fermeture ; le volet et le gestionnaire de fichiers en sont "
              "consommateurs (geste nocturne `common.preview_navigation`). Depuis le soir du "
              "2026-10-13, la FORME d'un résultat de process se déclare "
              "(`ProcessSpec.result_format`) : markdown mis en forme, RAPPORT de cohérence "
              "(score coloré, version proposée en regard du texte vérifié), tours de PAROLE "
              "(`segments`, le locuteur dans sa couleur) ; la face « Évaluation » (mesure contre "
              "la référence, `result_evaluation`) vient APRÈS la Sortie (`sides.after`) ; la "
              "visionneuse offre les TÉLÉCHARGEMENTS que l'app déclare (`export_formats`) et "
              "compte les mots de toute face texte — ce que portaient les modales propres du "
              "describer et du transcriber, retirées (R125, R126). Depuis le 2026-10-20, la CARD "
              "suit la face PENDANT comme le volet et la visionneuse (`followCard`, par le même "
              "suiveur et le même rendu en ligne) : son hôte de sortie, ou l'hôte d'attente "
              "`data-card-during` que chaque card pose à l'adresse de son élément — le describer "
              "y écrivait seul son texte partiel, le transcriber le recopiait dans le panneau de "
              "Speak (R158, R162). Depuis le 2026-10-28, la VIGNETTE d'un fichier est une brique "
              "(`tileHtml` : l'image, la 1ʳᵉ image d'une vidéo, sinon l'icône de la famille du "
              "type), décidée par le type que le serveur résout — lue par la grille d'une sortie "
              "multiple, la fenêtre de sélection et la médiathèque, qui l'écrivaient chacune et "
              "dont la dernière décidait par la nature de l'onglet (R183). Le même jour, "
              "l'AFFICHEUR DE FACES d'un élément devient commun (`faceViewer` : face par défaut, "
              "Pendant suivi puis Sortie, onglets, Comparer, double-clic vers la visionneuse) — le "
              "volet le portait seul pour son hôte unique ; il l'emprunte, et chaque ligne de job "
              "de l'échange de l'assistant le monte sous sa barre (geste `common.preview_chat_job`)",
              'wama/common/utils/preview_registry.py', '',
              annexes=('wama/common/utils/preview_utils.py',
                       'wama/common/static/common/js/media-preview.js',
                       'wama/common/static/common/js/wama-preview-overlay.js',
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
              "transcriber, porté aux 10 apps le 31/08), leur pendant, ce qui VARIE d'une fille "
              "à l'autre (varying_chips_for_items, identité du lot, 2026-10-19) et les propriétés d'ENTRÉE "
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
              "read/apply dérivés du schéma, cardSettings via card_gear) ; son aperçu (rendu, "
              "faces, visionneuse) vient de la brique `preview` (`media-preview.js`, 2026-10-13 — "
              "il l'hébergeait, et recopiait la bascule des faces)",
              'wama/common/static/common/js/wama-inspector.js', 'docs/construction/ui/WAMA_VOLETS.md',
              annexes=('wama/common/templates/common/_inspector_actions.html',),
              symbol='WamaInspector',
              depends_on=('detail_registry',)),      # global de base.html : compté par son symbole
    Mechanism('export_formats', 'Formats de téléchargement (⬇ late-binding)',
              "Vocabulaire commun des formats choisis AU TÉLÉCHARGEMENT (libellé, icône, "
              "groupe) + split-button dérivé de la déclaration export_binding — pendant "
              "late-binding d'output_formats ; 6ᵉ action de card. Depuis le 2026-09-18, porte "
              "aussi le REGISTRE des builders de rendu (`register_export_builder`, un par app "
              "late-binding, chemin pointé résolu à l'usage) : c'est ce qui permet au geste "
              "médiathèque de rendre le format choisi par LE MÊME code que le ⬇. Depuis le "
              "2026-10-02 le ZIP de LOT lit les deux mêmes déclarations (fabrique "
              "`make_batch_views`, format borné par `requested_format`, bouton de la card mère "
              "rendu par ce même ⬇) : les trois niveaux — card, lot, barre de file — parlent "
              "`?format=`. Depuis le 2026-10-13 la visionneuse commune offre les mêmes formats, "
              "et ce qu'un ÉLÉMENT ne peut pas rendre se déclare (`register_export_missing` : le "
              "`json` du reader sans résultat brut), lu par le ⬇ de la card (`item=`) et par elle",
              'wama/common/utils/export_formats.py', 'docs/construction/architecture/WAMA_APP_CONVENTIONS.md §6.3',
              annexes=('wama/common/templates/common/_download_button.html',
                       'wama/common/templatetags/wama_actions.py')),
    Mechanism('volet', 'Déclaration du volet par la page',
              "Une page DÉCLARE les sections du volet droit qu'elle garde (retrait, jamais "
              "ajout) ; sans déclaration, l'état d'avant — les apps n'écrivent rien "
              "(context processor volet_defaut). 2026-10-28 : ses sections sont des panneaux de "
              "la disposition COMMUNE (`wama-brick-layout.js`, sans grille au centre) — "
              "réordonnées, retaillées, empilées, épinglées à un bord, gardées par compte et par "
              "page (`PANEL_SLOTS`, route `panel_layout`, validées par `clean_layout`) ; le volet "
              "reste celui d'avant tant que le compte n'a rien disposé, une section masquée retire "
              "son panneau (`setShown`) ; `arrangeable=False` pour une page qui a sa disposition "
              "(surface) ou la fera brique par brique (cam_analyzer) — scénario "
              "`common.panel_layout`. Même jour, étape ④ : la card d'entrée, la progression, la "
              "barre de la file et la file d'une page d'app sont les briques de la grille du "
              "centre, dans la même disposition (`centre_slots`, un jeu par domaine, marques "
              "`data-wama-brick` posées par les pièces communes ; à la hauteur de leur contenu "
              "sauf la file) — scénario `common.centre_layout`",
              'wama/common/utils/volet.py', 'docs/construction/ui/WAMA_VOLETS.md §8',
              annexes=('wama/common/panel_views.py',
                       'wama/common/static/common/js/wama-panel-layout.js')),
    Mechanism('app_modes', 'Domaines → modes',
              "Schéma déclaratif des onglets-domaine et modes par app — scope la file ; un domaine "
              "NOMME son schéma de réglages (`params_schema`), sa surface est la clé de son modèle "
              "d'élément et le domaine d'un élément se dérive (`element_domain`) ; un mode "
              "est un RÉGLAGE (`mode_param`) qui borne le menu de modèles (`options_mode`)",
              'wama/common/utils/app_modes.py', 'docs/construction/ui/MODES_QUEUE_UX.md',
              annexes=('wama/common/static/common/js/wama-modes.js',)),
    Mechanism('app_base_js', 'Socle JS des apps',
              "Plomberie commune file/cards : csrfFetch, urls et `Poller` — LA boucle "
              "d'interrogation du navigateur : jamais deux requêtes en vol, muette en onglet caché "
              "(2026-10-13 ; toute boucle des apps passe par lui, garde `tests_poller_js`) ; "
              "`loadScript` / `loadStyle` — LE chargement à la demande d'un module ou d'une feuille "
              "(2026-10-28 : trois copies privées réunies, garde `tests_script_loader`)",
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
              annexes=('wama/common/tests/tests_status_ui.py',),
              depends_on=('app_base_js',)),
    # ── Briques d'INTERFACE communes (⚠ PAS des plugins — voir « rendu résolu » ci-dessus) ──
    # Déclarées le 2026-08-19 : elles vivaient dans `common/` sans être au registre — invisibles
    # de la carte, donc de la jonction avec la grille (le balayage ne regardait pas
    # `common/static/`). Elles sont toutes APPELÉES PAR LEUR NOM par leur hôte : ce sont donc
    # des mécanismes ordinaires, pas des rendus enfichables. `audio_player` est le seul
    # CANDIDAT au statut de rendu — il le deviendra le jour où l'aiguillage par mime de
    # `renderInline` (`media-preview.js`) sera un registre et non une cascade de `if`.
    Mechanism('audio_player', 'Lecteur audio (onde + transport)',
              "Widget autonome : onde canvas (pics serveur ou décodés), play/pause, exclusivité "
              "inter-lecteurs et inter-onglets ; monté par la preview dans le volet ET les cards",
              'wama/common/static/common/js/wama-audio-player.js', '',
              symbol='WamaAudioPlayer'),    # global de base.html : compté par son symbole
    Mechanism('shuttle', 'Shuttle J/K/L',
              "État de vitesse/direction de lecture (paliers éditeur) + binding clavier ; l'app "
              "fournit apply(speed) — la commande est commune ; depuis le 2026-10-15 elle peut "
              "s'appliquer à l'AXE commun (`axis.shuttle`) plutôt qu'à un lecteur",
              'wama/common/static/common/js/wama-shuttle.js', ''),
    Mechanism('media_axis', 'Axe de temps partagé (transport commun)',
              "L'AXE auquel les vues s'abonnent et que le magnéto pilote — jamais une vue "
              "(`WAMA_DATA_WORLD §5bis`) : lecture, pause, aller, sauts, vitesse signée, shuttle ; "
              "un média attaché est l'horloge en avant, l'axe avance seul et le recale en arrière "
              "(lecture silencieuse) ; vitesse CHOISIE distincte du cran de shuttle ; clavier du "
              "magnéto. Né le 2026-10-15 avec la partition du composer ; l'éditeur du transcriber y "
              "est porté le 2026-10-20 (parité geste par geste, `transcriber.editor_parity`) ; le "
              "cam_analyzer reste à porter (matrice de parité). Le 2026-10-21 : le TRANSPORT commun "
              "montable partout (`wama-transport.js`), les règles des SEGMENTS sans DOM "
              "(`wama-segments.js`) et les PICS FINS d'un média au commun (`waveform.dense_peaks`, "
              "fichier dérivé au dossier caché comme la copie de lecture). Le même jour, "
              "REDÉCOUPAGE décidé par Fabien — quatre niveaux, aucun ne connaît les autres : l'axe "
              "(le temps), le transport (ses COMMANDES seulement), les VUES qui le regardent (la "
              "ligne de temps `wama-timeline.js` : onde fenêtrée et couches, bande de qualité, "
              "minimap, zoom, outil Bornes) et les OUTILS DE DOMAINE (l'écriture à la lecture, "
              "brique `playback_writing`) ; un « aller à » se dit aux abonnés (`seek(t, 'goto')`)",
              'wama/common/static/common/js/wama-axis.js',
              'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §F3b',
              annexes=('wama/common/static/common/js/wama-transport.js',
                       'wama/common/static/common/js/wama-timeline.js',
                       'wama/common/static/common/js/wama-segments.js',
                       'wama/common/utils/waveform.py',
                       'wama/common/services/ui_smoke_editor.py'),
              depends_on=('shuttle',)),
    Mechanism('brick_keys', 'Clavier des briques (une touche, un propriétaire)',
              "Le module unique qui reçoit les frappes et les distribue selon la règle décidée par "
              "Fabien le 2026-10-29 : une touche déjà prise plus près du focus n'est pas "
              "redistribuée ; sous une couche ouverte (modale, panneau), seule une couche INSCRITE "
              "la reçoit (la visionneuse, le menu de card) ; une saisie ne passe que les touches "
              "déclarées (Ctrl+Espace) ; la brique qui a la main d'abord, puis les PRIORITAIRES (le "
              "transport) ; un observateur suit sans prendre. TOUTES les briques y sont inscrites "
              "depuis le même jour (aucune n'écoute plus le clavier de la page elle-même, "
              "`tests_surfaces.PageKeyListenersTest`). Les touches de chaque brique se "
              "DÉCLARENT au registre des briques (`surfaces.UIBrick.shortcuts`), d'où la liste de la "
              "brique Actions et du catalogue",
              'wama/common/static/common/js/wama-keys.js',
              'docs/construction/ui/WAMA_VOLETS.md §3-ter',
              symbol='WamaKeys',            # global de base.html : compté par son symbole
              annexes=('wama/common/surfaces.py',
                       'wama/common/tests/tests_surfaces.py',
                       'wama/common/services/ui_smoke_layout.py')),
    Mechanism('playhead_follow', 'Suivre la tête de lecture (traitement au fil de la lecture)',
              "Le navigateur pose un curseur, une tâche longue le suit tranche par tranche, modèle "
              "gardé chargé, et s'arrête d'elle-même (arrêt demandé, 90 s d'inactivité, traitement "
              "prioritaire à laisser passer). Verrou de lancement, verrou vivant, refroidissement : "
              "chacun a son cas vécu. L'app fournit le chargement, la tranche et la question « dois-je "
              "céder ? » — jamais la mécanique. Extrait du mode Live du cam_analyzer quand le "
              "transcriber en est devenu le 2ᵉ utilisateur ; première forme du curseur de session",
              'wama/common/services/playhead_follow.py',
              'docs/construction/mondes/WAMA_DATA_WORLD.md §5',
              annexes=('wama/common/tests/tests_playhead_follow.py',
                       'wama_lab/cam_analyzer/tests/tests_live_follow.py')),
    Mechanism('media_picker', 'Sélecteur de médiathèque',
              "Modale commune de choix d'un asset de la médiathèque (filtrée par type), rendue "
              "à l'appelant sous forme de File + méta (`onSelect`), ou de l'asset SEUL, sans "
              "téléchargement, pour qui le DÉSIGNE (`onPick`, 2026-09-28 — la tuile de card)",
              'wama/common/static/common/js/media-picker.js', '',
              symbol='MediaPicker'),        # global de base.html : compté par son symbole
    Mechanism('fm_notify', 'Signalement au gestionnaire de fichiers',
              "Noms d'événements centralisés (media:uploaded/processed/deleted) — l'arborescence "
              "du filemanager se rafraîchit sans que chaque app invente son event. Et "
              "`WamaFM.upload` (2026-10-18) : le DÉPÔT dans l'espace de l'utilisateur, geste "
              "partagé avec Discord et l'API (`enregistrer_fichier_utilisateur`) — le glisser-"
              "déposer sur le chat de l'assistant et la zone « Mes Fichiers » de l'accueil",
              'wama/common/static/common/js/wama-fm-notify.js', '',
              symbol='WamaFM'),             # global de base.html : compté par son symbole
    Mechanism('card_system', 'Card v3',
              "Dimensionnement déclaratif des pistes de card — dépend de l'app, des actions, "
              "des libellés (l'autre moitié vécue de la v3 — densités, pile — vit au front "
              "de file : queue_front, qui appelle WamaCardV3.measure)",
              'wama/common/static/common/js/wama-card-v3.js', 'docs/construction/ui/CARD_DESIGN.md §11',
              annexes=('wama/common/templates/common/_card_state.html',),
              symbol='WamaCardV3'),         # global de base.html : compté par son symbole
    # Ajouté le 2026-10-03 (ROUTE §11 #25) : le socle existait depuis le 2026-08-22, rattaché
    # en simple annexe d'`import_front` — donc ni compté ni vérifié pour lui-même, à 0/10 dans
    # le parc réel pendant six semaines.
    Mechanism('app_scripts', "Socle JS d'application",
              "La couche JS commune d'une page d'app — `_app_scripts.html` : formulaires du "
              "schéma (wama-params), ETA, lots, card d'entrée, voie d'import, barre de file ; "
              "options déclarées (appariement entrée ↔ modèle, capacités, modes, chips de "
              "prompt). Ce que `base.html` charge déjà n'y est PAS (une double exécution = deux "
              "écouteurs : le player audio muet du 18/08). Adopté par les 10 apps le 2026-10-03 "
              "(chaque gabarit recopiait ses balises ; l'anonymizer avait oublié la barre de "
              "file, sept scripts globaux étaient rechargés). Critère `app_scripts_common` ; "
              "garde `tests_item_lifecycle_contract` (socle présent, aucun script chargé deux "
              "fois sauf les idempotents déclarés)",
              'wama/common/templates/common/_app_scripts.html', 'docs/construction/architecture/WAMA_APP_CONVENTIONS.md'),
    Mechanism('new_item_card', 'Card « Nouvel élément »',
              "Card d'entrée dépliable commune — les 6 modalités du partial : dépôt, URL, "
              "médiathèque, lot, dossier, live + slot de référence typé (extra_zone) — "
              "auto-init. v4 : un onglet par PORT, ses tuiles dans un ordre CONSTANT sur tous les "
              "ports — Importer · Médiathèque · URL, du plus proche au plus distant (Fabien, "
              "2026-10-01, `CARD_DESIGN §11.11 B`)",
              'wama/common/static/common/js/wama-new-item-card.js', 'docs/construction/ui/MODES_QUEUE_UX.md',
              annexes=('wama/common/templates/common/_new_item_card.html',
                       'wama/common/templates/common/_new_item_card_v4.html')),
    # Le geste d'AJOUT du mode attache : la card porte une consigne, le fichier est JOINT, un
    # bouton crée l'élément. Quatre apps l'écrivaient chacune, le générateur en émettait une 5ᵉ.
    Mechanism('add_to_queue', "Ajout à la file (mode attache)",
              "Bouton « Ajouter à la file » de la card d'entrée : consigne + réglages du volet + "
              "fichier joint ou désigné par port (`appendInput`), URL postée seulement si l'élément "
              "la garde (sinon refusée, motif dit), rien n'est lancé (règle des deux temps). Côté "
              "serveur : `received_inputs`. Forme d'entrée DÉDUITE de l'obligation des ports "
              "(`app_registry.entry_form`, 2026-10-19 — dépôt / attache / mixte), lue par la card v4, "
              "le générateur (`views_gen.card_entry`) et `WamaImport({attach: 'card'})`. Adoptée le jour même "
              "par imager, avatarizer, composer et synthesizer (leur formulaire maison retiré). "
              "`ports: 'card'` (05/10) : les ports relus sur la card v4 à chaque envoi, chacun "
              "posté sous son nom — le relevé que le composer et le générateur écrivaient chacun ; "
              "lus par la brique de la card (`WamaInputSlots.filePorts`, 2026-10-20), la seule "
              "lecture des onglets hors d'elle",
              'wama/common/static/common/js/wama-app-base.js', 'docs/construction/ui/CARD_DESIGN.md',
              annexes=('wama/common/manifests/codegen/templates_gen.py',
                       'wama/common/manifests/codegen/views_gen.py'),
              symbol='addToQueue'),
    # Ajouté le 2026-10-16 (le Translator « à la DeepL », décision de Fabien).
    Mechanism('instant_result', 'Résultat instantané de la saisie',
              "Sous la consigne de la card d'entrée, ce que l'app rendrait — PENDANT la frappe, sans "
              "rien mettre en file. Capacité d'app DÉCLARÉE (`instant_preview`, lue par "
              "`instant_result_url`) ; une source, la route `instant` du manifeste, d'où dérivent "
              "la vue générée (la glu `tasks.instant_result` sur un élément NON enregistré, "
              "réglages par la cascade de l'ajout), sa route et le trou de glu. Délai de saisie, "
              "seule la dernière réponse s'affiche (`CARD_DESIGN §11.11 D bis`)",
              'wama/common/static/common/js/wama-instant.js', 'docs/construction/ui/CARD_DESIGN.md',
              annexes=('wama/common/tests/tests_instant_result.py',),
              depends_on=('new_item_card',)),
    # La card d'entrée porte les MODALITÉS ; celle-ci porte le GESTE d'envoi. Elles se
    # complètent : `new_item_card` déplie/replie, `batch_import` traite les fichiers de LOT,
    # `WamaApp.initUrlImport` le champ URL — et personne ne prenait le fichier ORDINAIRE.
    # Chaque app réécrivait sa boucle `handleFiles` (converter.js, reader.js…), donc une app
    # GÉNÉRÉE n'en avait aucune et ne pouvait créer aucune card, sans erreur console.
    Mechanism('import_front', "Voie d'import (front)",
              "Envoi d'un fichier vers l'endpoint upload de l'app (dépôt, clic), délégation du "
              "LOT à batch_import, consolidation et rafraîchissement — agnostique du monde (ni "
              "MIME ni extension). ⭐ Depuis le 2026-09-28 elle DÉSIGNE aussi "
              "(`handleDesignations` : médiathèque, arbre — `<champ>__designated`, pointé par le "
              "serveur) et se retrouve par l'id de sa zone ou de son input (`forElement`)",
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
    Mechanism('themes', "Thèmes et tokens de couleur",
              "Les thèmes DÉCLARÉS (`THEMES` : clé, libellé, mode natif de Bootstrap), passés à "
              "toute page par le contexte et posés par base.html sur `<html>` (`data-wama-theme`, "
              "`data-bs-theme`) ; leurs VALEURS dans `wama-theme.css`, un bloc par thème, chargé "
              "avant toute feuille. Un composant lit un token (`var(--wama-text-label)`), il "
              "n'écrit plus de couleur : la card commune est le 1ᵉʳ adopteur (2026-10-17). "
              "`common.contrast` joue chaque thème déclaré ; `tests_theme` exige que chaque thème "
              "définisse chaque token et tient le BUDGET des couleurs écrites en dur, qui ne peut "
              "que descendre. Le CLAIR (2026-10-18) est le miroir de luminance du sombre "
              "(`theme_mirror.mirror`, contrastes conservés), sauf les fixes et surfaces que "
              "`themes.py` déclare ; une région fixe son thème par `data-wama-theme` (îlot). "
              "Un thème DÉRIVÉ (`Theme.base`, 2026-10-19 : Université Gustave Eiffel, La Suite "
              "numérique) reçoit toutes les valeurs de sa base par la liste de sélecteurs de son "
              "bloc et ne redéfinit que son identité, chaque couleur venant de sa charte "
              "(`CHARTERS`) ; La Suite se décline aussi en sombre, dérivé du sombre. Un thème "
              "peut porter le logo de sa charte (`Theme.logo`, UGE) : la barre du haut les pose "
              "tous, la feuille ne montre que celui du thème actif ; une police sous licence "
              "commerciale est NOMMÉE, jamais servie (`LICENSED_FONTS`, TT Norms) ; une police "
              "libre est SERVIE, vendorisée par `update_vendors.sh` et déclarée par sa charte "
              "(`CHARTERS[…]['font']`, Roboto Flex pour La Suite, 2026-10-20). "
              "Le compte CHOISIT au Profil (2026-10-19) un thème déclaré — le SOMBRE par défaut — "
              "ou « Automatique », qui suit le mode du système (`wama-theme.js`, résolu avant le "
              "premier rendu) ; `theme_choice`, réglage durable `user_settings`. Un thème "
              "PERSONNALISÉ (2026-10-20, `Theme.generated` : clair ou sombre) naît d'une couleur "
              "d'accent cliquée au Profil (`PALETTES`, ou le sélecteur) : `theme_generator` en "
              "GÉNÈRE le bloc d'identité, chaque texte ajusté à 4,5:1 sur les fonds de sa base, "
              "posé par base.html dans `#wama-theme-generated`. Un thème de CHARTE (même jour) "
              "naît d'un PDF lu au Profil (`theme_charter` : les règles relèvent les couleurs "
              "écrites, le LLM local choisit parmi elles la principale, le nom, la police ; un "
              "humain valide) ; ses graines vivent sur une ligne `UserTheme` qui a une "
              "provenance — privée, partagée par `sharing.partager`, système une fois promue "
              "par un admin",
              'wama/common/themes.py', 'docs/construction/suivi/ROADMAP.md §28',
              annexes=('wama/common/static/common/css/wama-theme.css',
                       'wama/common/static/common/js/wama-theme.js',
                       'wama/common/theme_mirror.py',
                       'wama/common/theme_generator.py',
                       'wama/common/theme_charter.py',
                       'wama/common/tests/tests_theme.py')),

    Mechanism('filter_bar', 'Barre de filtrage',
              "Recherche + facettes EN DIRECT ; options dérivées du DOM (client) ou déclarées "
              "(server). Depuis le 2026-09-08 la recherche est un OUTIL du registre de barre "
              "(`toolbar_registry`), donc la même dans les registres et dans les 12 files. "
              "Masquage PAR CLASSE (`.wama-f-hors-filtre`) et non par `style.display` : une "
              "cible à `display` inline (l'entrée unitaire de file est en `display:contents`) "
              "ne survivait pas à la restauration. `data-cible-dans` BORNE la recherche — sans "
              "quoi deux files sur une même page se filtreraient l'une l'autre. `data-cible-vivante` "
              "(2026-09-28, calendrier) : une liste RE-RENDUE par un composant est relue à chaque "
              "application, et le composant appelle `WamaFilterBar.refresh(barre)` après rendu. "
              "Mode `remote` (2026-10-01, médiathèque) : la page charge sa liste elle-même, la "
              "barre émet `wama:filter-change` ({q, facets, sort}) ; outil de tri `sort_by` déclaré "
              "par la page",
              'wama/common/static/common/js/wama-filter-bar.js', 'docs/construction/ui/CARD_DESIGN.md',
              annexes=('wama/common/templates/common/_filter_bar.html',),
              symbol='WamaFilterBar'),      # global de base.html : compté par son symbole
    Mechanism('panel_toggle', "Repli des volets latéraux par leur frontière",
              "Un clic sur la FRONTIÈRE d'un volet (explorateur, panneau) le replie ou le rouvre, "
              "sur toute page : au repos rien de plus que le liseré, au survol une ligne et une "
              "pastille à chevron qui suit le pointeur ; volet replié, une trace fine au bord de la "
              "fenêtre. État par NAVIGATEUR (localStorage), appliqué avant le premier rendu. La "
              "place des volets a une SOURCE UNIQUE : les marges `--wama-left-gutter` / "
              "`--wama-right-gutter` (0 replié ou sans volet) que lisent le "
              "corps, l'en-tête et les barres fixes des pages ; une règle qui se calerait sur la "
              "largeur brute d'un volet est refusée par `tests_panel_toggle`. Au doigt (tablette), "
              "la pastille reste visible. Après chaque bascule : `resize` + `wama:panels`. DEUX "
              "CONTEXTES DE LARGEUR (2026-10-12) : sous le point de rupture `lg` de Bootstrap "
              "(tablette en portrait, fenêtre étroite), volets repliés d'office, un seul ouvert à "
              "la fois, mémoire à part — le choix fait en grand n'est jamais écrasé "
              "(`WamaPanelsContext`, posé par base.html avant le premier rendu). La barre du haut "
              "et le pied sont des grilles `1fr auto 1fr` : rien ne s'y chevauche, les libellés "
              "s'effacent derrière leur icône quand la barre manque de place (requête de "
              "conteneur) ; mesuré chaque nuit par `common.layout.tablet`",
              'wama/common/static/common/js/wama-panel-toggle.js', 'docs/construction/ui/WAMA_VOLETS.md',
              annexes=('wama/common/static/common/css/wama-panel-toggle.css',
                       'wama/common/services/ui_smoke_layout.py'),
              symbol='WamaPanels'),         # global de base.html : compté par son symbole
    Mechanism('touch', "WAMA au doigt (écrans tactiles)",
              "Une règle commune, montée par base.html EN DERNIER, pour tout écran dont le "
              "pointeur principal est un doigt — critère UNIQUE `(pointer: coarse)` : commandes à "
              "44 px au moins (boutons, onglets, menus, titres repliables, `[role=button]`), cases, "
              "interrupteurs et curseurs à 24 px au moins — des PLANCHERS, jamais des tailles. Et "
              "la convention « révélé au survol » : `.wama-reveal-host` sur l'hôte, `.wama-reveal` "
              "sur l'action — montrée au survol, au clavier, et TOUJOURS au doigt ; son inverse "
              "`.wama-reveal-hide` pour ce qui lui cède la place. Une règle "
              "`:hover` locale qui révélerait un élément est refusée par `tests_touch`. Les "
              "briques affinent chez elles, sur le même critère (process des cards v3, lecteur "
              "audio, saisie de l'assistant, ports du studio, variante « large » de l'explorateur)",
              'wama/common/static/common/css/wama-touch.css',
              'docs/construction/architecture/WAMA_APP_CONVENTIONS.md',
              annexes=('wama/common/tests/tests_touch.py',),
              symbol='wama-reveal'),        # classe CSS : comptée par les gabarits/JS qui la posent
    Mechanism('gestures', "Gestes au pointeur (glisser, défiler, pincer, appui long)",
              "Montée par base.html, pour toute page des trois mondes (ROADMAP §27, étape 3, "
              "2026-10-16). Trois choses : (1) `WamaGestures.track(el, {start, move, end, pinch})` "
              "suit un pointeur sur une surface qui dessine elle-même — seuil entre clic et glisser, "
              "boutons de souris filtrés, PINCEMENT à deux doigts ; Pointer Events, donc souris, "
              "stylet et doigt par le même code (canvas du studio, onde de l'éditeur du "
              "transcriber) ; (2) le glisser HTML5 AU DOIGT, sur tout `[draggable=\"true\"]` : appui "
              "long puis le doigt bouge → `dragstart`/`dragover`/`drop`/`dragend` avec un "
              "`dataTransfer` réel, vignette qui suit, liste qui défile au bord — la file, la "
              "palette du studio et l'ordre des segments marchent au doigt sans une ligne chez eux, "
              "et la souris garde son glisser natif ; (3) l'APPUI LONG : l'infobulle (`title`) d'une "
              "commande sans la déclencher, sinon un `contextmenu` (menu de card, arbre — l'iPad "
              "n'en émet pas) ; sur ce qu'on glisse, il soulève : bouger glisse, relâcher ouvre le "
              "menu. Une page n'écrit ni `touchstart` pour un geste porté ici, ni "
              "mousedown/mousemove pour suivre un glisser ; mesuré chaque nuit sur de vrais "
              "événements tactiles par `common.gestures.touch`, et les mêmes pages à la souris "
              "par `common.gestures.mouse` (la garde du PC)",
              'wama/common/static/common/js/wama-gestures.js',
              'docs/construction/architecture/WAMA_APP_CONVENTIONS.md',
              annexes=('wama/common/tests/tests_gestures.py',
                       'wama/common/services/ui_smoke_layout.py'),
              symbol='WamaGestures'),       # global de base.html : compté par son symbole
    # Ajouté le 2026-10-26 (décision de Fabien : « la brique commune, méticuleusement, sans rien
    # casser, sans rien perdre ») : quatre sites ouvraient caméra ou micro chacun à sa façon.
    Mechanism('media_capture', "Capture caméra / micro du navigateur",
              "Montée par base.html avant ses consommateurs : TOUTE ouverture de la caméra ou du "
              "micro passe par `WamaCapture` — contexte sécurisé vérifié avant de rien demander, "
              "refus EXPLIQUÉ par périphérique (autorisation, absence, occupé), périphérique choisi "
              "et repli sur celui par défaut, liste des périphériques AVEC leurs noms (la demande "
              "d'autorisation qu'elle exige est refermée aussitôt), réglages accordés et zoom "
              "matériel, enregistrement, permission lue sans rien demander, pistes rendues à "
              "l'arrêt et au `pagehide`. Consommée par l'écoute de l'assistant (et le Speak du "
              "transcriber, par elle), l'enregistrement de la médiathèque, les mains et le temps "
              "réel du Face Analyzer ; aucune page n'appelle `getUserMedia` elle-même (garde "
              "`tests_capture`), et les consommateurs sont rejoués chaque nuit "
              "(`common.capture.ui`). Elle ouvre le périphérique, elle ne traite pas le flux",
              'wama/common/static/common/js/wama-capture.js',
              'docs/construction/architecture/WAMA_APP_CONVENTIONS.md',
              annexes=('wama/common/tests/tests_capture.py', 'wama/common/services/ui_smoke_capture.py'),
              symbol='WamaCapture'),        # global de base.html : compté par son symbole
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
              "n'attend pas le réseau). Depuis le 2026-10-14, un fichier qui n'est la sortie de "
              "RIEN (dépôt temporaire, entrée d'app, dossier connecté) a « Ajouter au RAG » sur "
              "le FICHIER, et une sélection de N fichiers « Ajouter N fichiers au RAG » "
              "(`entreesPourChemins`). ⚠ Le menu est posé sur `document.body` : une card "
              "vit dans un conteneur à `overflow` qui le rognerait. Le « … » suit les cards INSÉRÉES "
              "ou REMPLACÉES après le chargement (observation de la file, 2026-09-15)",
              'wama/common/static/common/js/wama-card-menu.js', 'docs/construction/ui/CARD_DESIGN.md',
              symbol='WamaCardMenu'),
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
    Mechanism('queue_front', "File d'attente (front)",
              "Comportements communs des files : collapse de batch persisté, mode Solitaire "
              "(accordéon), toggle Ligne/Mosaïque, les 3 densités et le modificateur PILE "
              "(CARD_DESIGN §11.4/§11.9), focus card, clearCards, data-wama-*. Et la FILE "
              "elle-même, pièce unique depuis le 2026-10-20 (`_queue.html` : barre, conteneur, "
              "entrées, état vide — routes lues sous leurs orthographes admises, état vide "
              "TOUJOURS rendu et basculé ici) : les dix apps et le générateur l'incluent",
              'wama/common/static/common/js/wama-queue.js', 'docs/construction/ui/CARD_DESIGN.md',
              symbol='WamaQueue',           # global de base.html : compté par son symbole
              annexes=('wama/common/static/common/js/queue-actions.js',
                       'wama/common/templates/common/_queue.html',
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
              annexes=('wama/common/tests/tests_queue_delete_contract.py',),
              depends_on=('queue_order', 'batch', 'queue_front')),
    Mechanism('queue_dnd', 'Glisser-déposer et sélection multiple de la file',
              "Les QUATRE gestes de manipulation directe, hérités par les 12 apps sans qu'aucune "
              "n'écrive une ligne : déposer SUR une card change l'APPARTENANCE (entrer dans un "
              "lot / en former un), déposer ENTRE deux cards change l'ORDRE (file ou lot) ; "
              "sélection multiple clic/Ctrl/Maj, qui EST celle de l'inspecteur (une seule "
              "sélection dans WAMA — la brique ANNONCE `wama:selection-change`, l'inspecteur "
              "REND). Une CASE en tête de chaque card la dessine (2026-10-16) : la cocher AJOUTE "
              "à la sélection, comme Ctrl+clic — à la souris sans clavier comme au doigt ; "
              "visible au survol, cochée ou dès qu'une sélection est en cours. Le SURVOL d'une "
              "card de file est une règle commune (`wama-inspector.css`), aucune app n'écrit le "
              "sien. Auto-monté sur `[data-wama-dnd]`, posé par le templatetag "
              "`queue_dnd_attrs` : une app qui ne le pose pas garde une file strictement inerte. "
              "SortableJS écarté (multi-sélection + fusion sur une card + règle « pas de CDN »)",
              'wama/common/static/common/js/wama-queue-dnd.js', 'docs/construction/ui/CARD_DESIGN.md §3bis',
              symbol='WamaQueueDnd',        # global de base.html : compté par son symbole
              annexes=('wama/common/static/common/css/wama-queue-dnd.css',
                       'wama/common/templatetags/wama_actions.py',
                       'wama/common/tests/tests_queue_dnd.py')),
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
              annexes=('wama/studio/static/studio/js/wama-studio.js',)),
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
    Mechanism('notification_panel', 'Panneau de la cloche',
              "Un clic sur la cloche ouvre ses notifications SANS quitter la page (2026-10-13) : "
              "ouvrir, lu / non lu, supprimer (avec « Annuler »), tout lire, et les gestes PROPRES "
              "à un type — déclarés par le serveur (STYLE_BY_KIND, ACTIONS_BY_KIND : « Accorder / "
              "Refuser » une demande d'accès), la page ne connaît aucun type. Ouvrir le panneau ne "
              "marque rien comme lu ; le lien de la cloche reste la page complète (Ctrl-clic)",
              'wama/common/services/notification_panel.py',
              'docs/construction/exploitation/WAMA_COLLABORATION.md',
              annexes=('wama/common/static/common/js/wama-notifications.js',
                       'wama/common/static/common/css/wama-notifications.css')),
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
              "proxy et sonde d'ici, clé de chaque utilisateur. Depuis le 2026-10-07 (décision "
              "de Fabien), la clé d'INSTANCE se pose par un admin sur la page « Sources "
              "externes » (`accounts.InstanceApiKey`, chiffrée) et prime sur le `.env`, qui "
              "reste le repli ; une source `shareable` (clés d'application : ILaaS) peut la "
              "PARTAGER avec les comptes sans clé — la clé personnelle prime toujours. Le champ "
              "de saisie est UNE brique (`WamaKeyField`) pour le profil et la page. Une clé "
              "FACULTATIVE (`api_key_optional`, 2026-10-12 : le jeton de `github_api`) "
              "relève un quota sans rendre la source « non configurée » quand elle manque. La "
              "FORME des clés se déclare aussi (`api_key_prefix`, 2026-10-26, mesurée sur des "
              "clés réelles) : une clé tronquée est refusée au dépôt (`api_keys.key_shape_error`, "
              "dans `store_key`, le geste des deux écrans). Une "
              "PLATEFORME de modèles déclare la fiche d'un modèle (`model_page`, 2026-10-22) : "
              "`model_platforms()` est le vocabulaire de `AIModel.platform_ref`, "
              "`model_page_url()` en rend la page (lien de card, validation du manifeste "
              "`model`), `hf_repo()` en tire le dépôt du Hub — la seule lecture du dépôt "
              "d'un modèle depuis le 2026-10-27 (`hf_id` ne se lit plus) ; un fournisseur "
              "distant se DIT par `remote_origin_label` — "
              "hébergement · fournisseur · coût — partout où il est nommé",
              'wama/common/external_sources.py', 'docs/construction/suivi/PROJECT_STATUS.md',
              annexes=('wama/common/utils/http_proxy.py',
                       'wama/common/utils/ollama_host.py',
                       'wama/media_library/providers/base.py',
                       'wama/accounts/api_keys.py',
                       'wama/common/static/common/js/wama-key-field.js')),
    Mechanism('search_engines', 'Moteurs de recherche web',
              "Un adaptateur par moteur (Exa, Staan, SearXNG, DuckDuckGo) derrière UN contrat : "
              "l'inventaire vient des sources `kind='recherche'` du registre, jamais d'une liste "
              "écrite dans le code appelant. Le choix a DEUX étages — défaut d'instance "
              "(`WAMA_SEARCH_ENGINE`) et préférence de chacun au profil qui le surcharge —, et un "
              "moteur à clé n'est proposé qu'à qui a posé la sienne. Né le 2026-09-26 (décision "
              "de Fabien) : la recherche de l'assistant était câblée sur UN moteur écrit en dur, "
              "et le jour où il a cessé de répondre autre chose qu'un défi anti-robot, la surface "
              "entière est tombée sans recours. ⚠ Un moteur qui répond autre chose que des "
              "résultats LÈVE (`SearchEngineUnavailable`) au lieu de rendre une liste vide : un "
              "échec qui emprunte la forme d'un succès se croit",
              'wama/common/search_engines/registry.py', 'docs/construction/ia/WAMA_LLM.md',
              annexes=('wama/common/search_engines/base.py',),
              depends_on=('external_sources',)),
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
              "sur place, avec propagation aux autres workers gunicorn. Depuis le 2026-10-13 : "
              "LIRE les registres (pages, model manager compris) relève du droit d'accès "
              "`registries`, tout compte sauf le visiteur ; les GÉRER — actualiser, et pour les "
              "modèles installer, supprimer, prospecter, libérer la carte — d'UNE règle, "
              "`can_manage_registries` (profil développeur ou administrateur)",
              'wama/common/registries.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md',
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
              "Moteur unique de miroir (modèles, base, médias, secrets) et restauration "
              "(`restore_backup`). 2026-10-27 : le tirage d'une perte PARTIELLE ne recopie que "
              "les fichiers absents (`keep_existing`, `--missing-only`) — un fichier modifié "
              "depuis la sauvegarde n'est plus remplacé par sa version ancienne ; 2026-10-28 : le "
              "tirage BORNÉ à ce que la base connaît encore (`keep`, `--known-only` : comptes réels, "
              "médiathèque, fichiers qu'une card hors compte de test référence) ; procédure : "
              "skill `restauration`",
              'wama/common/services/mirror_sync.py', '',
              annexes=('wama/common/services/config_backup.py',
                       'wama/common/services/media_backup.py',
                       'wama/model_manager/services/remote_backup.py')),
    Mechanism('retention', 'Rétention des médias',
              "Purge automatique des sorties au-delà de la durée choisie par l'utilisateur (FileField découverts)",
              'wama/common/services/retention.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md'),
    Mechanism('audio_decode', 'Décodage audio robuste',
              "Décode l'audio là où torchcodec/torchaudio sont cassés (WSL) : soundfile + repli ffmpeg. "
              "`decode_audio` laisse un WAV à sa fréquence NATIVE ; un modèle de parole passe par "
              "`decode_audio_at` (fréquence GARANTIE, `resample`) — 2026-10-01, cinq consommateurs. "
              "Annexe torchaudio_compat = l'autre forme du même problème : shims soundfile posés DANS "
              "torchaudio pour les libs tierces qui l'appellent en interne (Coqui, DeepFilterNet)",
              'wama/common/utils/audio_decode.py', '',
              annexes=('wama/common/utils/torchaudio_compat.py',)),
    Mechanism('speech_activity', 'Activité vocale (le VAD garde-t-il la parole ?)',
              "Confronte, sur quelques fenêtres du média, ce que le filtre de parole Silero retient à "
              "ce que l'énergie du signal dit actif : un VAD qui garde bien moins que l'actif rejette "
              "une parole lointaine. L'appelant décide (le transcriber transcrit alors sans filtre, "
              "réglage `vad_mode` auto) ; mesuré sur deux entretiens le 2026-09-25. "
              "`pause_windows` (2026-10-02) : fenêtres bornées couvrant TOUT l'audio, coupées au "
              "creux d'énergie — pour un moteur à fenêtre fixe sans repères de temps (FrWhisper) ; "
              "`quietest_point` : la même coupe sur un extrait seul, qu'emploie le découpage des "
              "audios longs du transcriber (`workers._split_audio_chunks`, plus de coupe à "
              "intervalle fixe). `speech_coverage` (2026-10-22) : la part de la parole que les "
              "segments rendus couvrent — un texte perdu se voit, quel que soit le moteur",
              'wama/common/utils/speech_activity.py',
              'wama/transcriber/TRANSCRIBER_CORRECTION.md §8',
              annexes=('wama/common/tests/tests_speech_activity.py',)),
    # Rattachés le 2026-09-30 : deux traitements du SIGNAL de parole, sans modèle, qui n'étaient
    # pas sur la carte — le nivellement vivait depuis le 29/09 comme réglage du transcriber.
    Mechanism('speech_leveling', 'Nivellement de la parole',
              "Automation de niveau qui suit les mots : les passages sont égalisés (vers −20 dBFS), "
              "les silences gardent le gain des mots voisins (le bruit n'est pas pompé) ; le niveau "
              "de parole ne sort jamais plus bas qu'il n'est entré, puis le signal monte jusqu'à une "
              "crête de −0,2 dBFS (2026-10-21), crêtes limitées en douceur. Réglage optionnel du "
              "transcriber, MESURÉ dans les lots d'évaluation",
              'wama/common/utils/speech_leveling.py', 'docs/construction/ia/WAMA_QUALITE.md',
              annexes=('wama/common/tests/tests_speech_leveling.py',)),
    Mechanism('audio_degradation', 'Dégradation contrôlée d\'un enregistrement de parole',
              "Profils DÉCLARÉS (bruit rose à un rapport signal/bruit donné, champ lointain : "
              "réverbération, atténuation) appliqués de façon déterministe à un corpus propre, pour "
              "évaluer les prétraitements sur une qualité CONNUE — à confronter à un corpus réel de "
              "qualité moyenne avant d'en faire un test d'évaluation",
              'wama/common/utils/audio_degradation.py', 'docs/construction/ia/WAMA_QUALITE.md',
              annexes=('wama/common/tests/tests_audio_degradation.py',)),
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
    Mechanism('content_language', "Langue d'un contenu (écrit, parlé)",
              "La langue d'un TEXTE (`langid`, balises de section retirées, verdict peu sûr = "
              "inconnue — les paroles du composer, 2026-10-05) et celle d'un AUDIO (Whisper sur "
              "plusieurs passages — la langue d'un fichier proposée, le transcriber). Deux faces, "
              "une question : en quelle langue est ce contenu ? — jamais une heuristique d'app "
              "(celle du describer, morte, est retirée le jour même)",
              'wama/common/utils/text_language.py', 'docs/construction/ia/WAMA_LLM.md',
              annexes=('wama/common/utils/spoken_language.py',)),
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
                       'wama/media_library/tests/tests_natures.py')),
    Mechanism('voice_refs', 'Voix de référence (médiathèque) et voix de clonage',
              "LA brique TTS des voix : `speaker_wav_for` (décidée par la CAPACITÉ du moteur, "
              "jamais par un nom de moteur, et qui TRANSMET la langue depuis le 2026-09-27), "
              "`resolve_speaker_wav` (sa_/ua_/cv_/nom d'avant), `default_voice_for_language` "
              "(« Voix par défaut » = la voix de référence de la LANGUE choisie, dans l'ordre "
              "du menu ; sans elle c'était un clip anglophone quelle que soit la langue), "
              "`describe_voice`, `voice_reference_groups` (optgroups dérivés d'une REQUÊTE sur "
              "`SystemAsset(voice)` + `attributes`), `ingest_voice_file` (le seul point d'entrée, "
              "ingest initial ET téléchargements). Les voix VIVENT en médiathèque depuis le "
              "2026-09-13 (28 versées, dossier `voice_references/` retiré) ; le service TTS "
              "ne résout plus rien. Quatre consommateurs : synthesizer, avatarizer, "
              "`voice_options` (menus), assistant. Depuis le 2026-10-28, les voix PROPRES d'un "
              "moteur (Phonon, Kokoro, Bark — `TTSBackend.VOICES`, portées par le catalogue) : un "
              "groupe par jeu de modèles qui les nomment (`engine_voice_groups`, `data-models`), "
              "jugées dans les DEUX sens par une règle commune du navigateur "
              "(`WamaModelCaps.voiceFits` : sous un modèle, ses voix ; une voix choisie grise les "
              "autres modèles, `WamaInputMatch.voiceSlot`), et portées au tirage « auto » "
              "(`voice_draw_constraint`, clé `voice` d'`options_resolution` — lancement et "
              "prévision) ; et la voix de l'ASSISTANT — modèle choisi ou tiré « auto », le plus "
              "rapide en temps réel sauf voix choisie (`assistant_voice`)",
              'wama/common/tts/voice_refs.py', 'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md §9.4',
              annexes=('wama/common/utils/voice_options.py',
                       'wama/common/tts/assistant_voice.py',
                       'wama/common/tests/tests_voice_choice.py',
                       'wama/media_library/management/commands/ingest_voice_refs.py',
                       'wama/common/tests/tests_voice_refs.py')),
    Mechanism('tts_text', 'Le texte À DIRE (préparation avant vocalisation)',
              "`text_for_speech` (la chaîne, dans un ordre dont chaque place se justifie) et "
              "`make_audible` (la mise en forme visuelle traduite en respirations : puce de tête, "
              "point en fin de ligne non ponctuée, tiret d'incise → virgule, `/` → « ou »). "
              "⚠ Le domaine était écrit DEUX FOIS, sous le MÊME NOM de fonction : la vue de "
              "vocalisation avait les emojis, le Markdown et les respirations, "
              "`synthesizer/utils/text_extractor.py` avait les URL et les e-mails — donc le "
              "synthesizer, dont le métier est de lire un document à voix haute, lisait les listes "
              "d'un trait. Unifié le 2026-09-26 (demande de Fabien) ; le nom du synthesizer "
              "DÉLÈGUE, ses six appelants sont intacts. Consommateurs : la vue `kokoro_tts` (donc "
              "toute surface qui vocalise — accueil, volet, canaux) et le synthesizer. Depuis le "
              "2026-10-18 (défauts entendus, mesurés par aller-retour voix → transcription) : "
              "parenthèses dites en incises (`say_incises`), emphase courte en majuscules "
              "(`say_emphasis`), code en ligne dit, et "
              "`pause_segments` — où la voix respire, et combien : les réglages de pauses "
              "(déclarés une fois, `common/tts/constants.VOICE_PAUSE_SETTINGS`) de l'assistant et "
              "du synthesizer, posés pour TOUT moteur par leur contrat commun "
              "(`tts_base.TTSBackend.synthesize`). Le second nettoyage du navigateur est RETIRÉ. "
              "Depuis le 2026-10-27, le LEXIQUE de prononciation (`lexicon`) : le fichier système "
              "`common/tts/pronunciations.json` et les lignes d'un compte (registre "
              "`pronunciations`), qu'un moteur dit par l'orthographe (`respell_with_lexicon`, au "
              "contrat commun) ou par les phonèmes (`phonemes_with_lexicon`, Kokoro) — joint à la "
              "demande par `tts_via_service(user=)`, le service vocal n'ayant pas Django ; une "
              "entrée `exact_case` ne vaut que dans sa casse (les unités, « 8 Go », 2026-10-28)",
              'wama/common/utils/tts_text.py', 'docs/construction/ia/WAMA_LLM.md §1bis',
              annexes=('wama/common/tests/tests_tts_text.py',
                       'wama/synthesizer/utils/text_extractor.py',
                       'wama/common/backends/tts_base.py',
                       'wama/common/tests/tests_tts_backend_pauses.py',
                       'wama/common/tts/pronunciations.json',
                       'wama/common/services/user_pronunciations.py',
                       'wama/common/tests/tests_pronunciations.py'),
              symbol='text_for_speech'),
    Mechanism('test_media_isolation', 'Médias de test isolés',
              "Le runner de tests redirige `MEDIA_ROOT` vers `media_tests/run-<id>/` — dossier "
              "SŒUR de `media/`, jamais dedans (servi, sauvegardé, miré) ; les exécutions "
              "orphelines (vides ou > 24 h, teardown jamais joué) se balaient à l'entrée de la "
              "suivante. Le nocturne, lui, écrit chez les COMPTES DE TEST dans `media/` (serveur "
              "vivant) et se balaie par NOM (`wama_temoin_*`, dossier temporaire compris). "
              "Question Fabien 2026-09-13 : « on ne change rien pour ça ». Même raison pour le "
              "CORPUS de manifestes, versionné (2026-10-12) : le runner pose "
              "`MANIFEST_CORPUS_SYNC = False`, qui coupe la porte `manifests.corpus.follow` — "
              "une installation, une validation ou une désinstallation jouée en base de test ne "
              "réécrit ni ne retire jamais un fichier réel",
              'wama/common/runners.py', 'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md §①bis',
              annexes=('wama/common/tests/tests_media_tests_hygiene.py',)),
    Mechanism('media_guard', 'Garde-fou des médias (processus)',
              "Posé par `CommonConfig.ready()` dans TOUT processus Django (gunicorn, Celery, "
              "commandes, scripts `django.setup()`, tests) : `shutil.rmtree` refuse, par "
              "`PermissionError` que `ignore_errors` n'avale pas, d'effacer la racine des médias "
              "lue au démarrage, `users/`, `media_library/` ou un dossier qui les contient. Né de "
              "la perte TOTALE du 2026-10-27 (un `setUp` qui effaçait `settings.MEDIA_ROOT`, lancé "
              "hors du lanceur de tests). Et la CAUSE : un test de Django refuse de démarrer hors "
              "de `manage.py test` — sur les vrais médias, la vraie base, ou dans un processus "
              "dont le cache et le broker Celery sont les vrais (`runtime_side`). Les pendants AST, "
              "dans les tests d'hygiène, interdisent de passer `MEDIA_ROOT` à un `rmtree`, "
              "d'importer `rmtree` par son nom et de jouer une suite hors de `manage.py test`",
              'wama/common/utils/media_guard.py', 'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md §10',
              annexes=('wama/common/tests/tests_media_guard.py',)),
    Mechanism('video_utils', 'Utilitaires vidéo',
              "Extraction audio des vidéos + téléchargement YouTube/yt-dlp",
              'wama/common/utils/video_utils.py', ''),
    Mechanism('playback_copy', 'Copie de lecture des vidéos',
              "Une vidéo qu'une card porte et que le navigateur ne lit pas (conteneur, profil "
              "H.264, pixels — pas le seul nom du codec) reçoit, DÈS SON IMPORT et quelle que soit "
              "la voie, une copie de lecture H.264 servie par l'aperçu SEULEMENT ; l'original "
              "reste intact pour les traitements (2026-10-06, décision de Fabien). Rangée dans le "
              "dossier CACHÉ de l'utilisateur (`users/<id>/.preview/`), jamais à côté de "
              "l'original ni dans un dossier connecté ; balayée quand l'original part ; ni "
              "orpheline pour l'intégrité, ni dédupliquée, ni sauvegardée. Récepteur générique sur "
              "les champs fichier, tâche `common.make_playback_copy` (CPU), rattrapage "
              "`manage.py playback_copies`. Le verdict lit la sonde COMMUNE "
              "(`media_probe.probe_video_format`) ; l'écriture partage le geste de `ensure_h264`",
              'wama/common/utils/video_compat.py',
              'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md',
              annexes=('wama/common/management/commands/playback_copies.py',),
              depends_on=('media_probe', 'preview')),
    Mechanism('media_paths', 'Chemins média',
              "Emplacements canoniques des entrées/sorties par app et par utilisateur "
              "(`app_media_dir` : `users/<uid>/<app>/input|output`). ⭐ Depuis le 2026-09-23 la "
              "brique décide aussi POINTER ou COPIER (`reference_or_copy`, décision de Fabien, "
              "cible annoncée le 12/09) : une source déjà sous `users/<uid>/` du MÊME utilisateur "
              "est désignée telle quelle — un `FileField` est déjà un pointeur, l'aperçu commun "
              "sert `/media/<chemin stocké>` — tandis qu'un dépôt depuis le poste, un dossier "
              "connecté (hors `MEDIA_ROOT`, et un traitement ne lit pas un disque réseau), une URL "
              "ou l'arbre d'AUTRUI se copient. ⚠ Une app qui lit ses entrées PAR DOSSIER "
              "(cam_analyzer, RTMaps) garde la copie, et son site le dit. ⭐ Depuis le "
              "2026-09-28 : un asset SYSTÈME actif se pointe aussi, `readable_by` est LA règle "
              "de ce qu'un utilisateur peut désigner, et `received_inputs` est ce qu'une vue "
              "d'upload REÇOIT — un fichier téléversé ou DÉSIGNÉ (`<champ>__designated` : "
              "médiathèque, arbre), par la même vue, avec l'état du volet ; `designate` est la "
              "même désignation pour les outils de l'assistant (`tool_api.add_to_*`). ⭐ Depuis "
              "le 2026-09-29 : un asset de médiathèque PARTAGÉ (labo, projet, public) est "
              "désignable et POINTÉ par les personnes concernées — même règle de visibilité que "
              "la liste (`scoping.listable_by`), le compte anonyme n'en hérite pas. Depuis le "
              "2026-10-20 : `check_designation`, les gardes de `designate` sans pointer ni copier "
              "— pour qui RETIENT une désignation avant qu'une app la reçoive (card d'entrée du "
              "Studio) ; depuis le 2026-10-22, `designated_file`, le fichier DISQUE de la "
              "désignation (dossier connecté compris) pour qui la LIT sans la recevoir (lot, « Jeu "
              "de données » et Sortie du Studio : `MEDIA_ROOT/<chemin>` manquait un montage)",
              'wama/common/utils/media_paths.py',
              'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md'),
    Mechanism('scoped_visibility', 'Visibilité et portée',
              "Privé / unité / public : filtrage des lectures, mutations inchangées. Depuis le "
              "2026-10-18 (`ROADMAP §29` étape 3), les éléments d'un CATALOGUE aussi : "
              "`catalogue_visible_q` (système et publics pour tous, les siens, sa portée ; tout "
              "pour l'admin), dont le premier porteur est `AIModel` — la provenance naît au geste "
              "d'installation, et `accessible(user, 'model', clé)` la lit sur la ligne. Depuis le "
              "2026-10-19 (étape 4) : `UserFunction` par le même filtre, une fonction du CODE par "
              "l'app qui la porte (`Registry.element_app`, `function_catalog.accessible_specs`), "
              "et `StudioPipeline` porté comme une card (`listable_by`, `owned_or_404`)",
              'wama/common/models.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md',
              symbol='ScopedVisibility',
              annexes=('wama/model_manager/tests/tests_model_provenance.py',
                       'wama/common/tests/tests_function_provenance.py',
                       'wama/common/tests/tests_pipeline_provenance.py')),
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
              "unique ne garde que ce que ses POINTS D'APPLICATION lisent réellement (§8.9). "
              "Un outil gardé est une PAGE (card ou `register_surface`) ou, depuis le 2026-10-13, "
              "un OUTIL SANS PAGE (`register_pageless_tool` : gestionnaire de fichiers, "
              "assistant — routes résolues comme celles de toute app, l'assistant gardé aussi dans "
              "`conversation_turn`). `access_cases()` énumère tous les cas pour la présentation ; "
              "depuis le 2026-10-20, la CONSTELLATION des utilisateurs (`accounts/constellation.py`) "
              "montre ces décisions compte par compte, avec unités, projets, partages, apports et "
              "activité — page admin, intégrée à la présentation, jouée chaque nuit "
              "(`accounts.constellation.ui`) ; les deux vues montrent les mêmes outils "
              "(`presented_apps`)",
              'wama/accounts/permissions.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md',
              annexes=('wama/accounts/tests/tests_anonymous_closure.py', 'wama/accounts/tests/tests_access_points.py',
                       'wama/accounts/constellation.py', 'wama/common/services/ui_smoke_accounts.py'),
              symbol='accessible'),
    # Ajouté le 2026-10-21 (GO de Fabien : « une brique commune réutilisable pour différents
    # registres »). La constellation des utilisateurs en fut extraite, sans changement visible.
    Mechanism('proximity_scenes', "Scènes de proximité (constellations 3D)",
              "Une scène DÉCLARE ce qu'elle montre — couches, facteurs de distance pondérés "
              "(relationnel, catégoriel, numérique), sortes de groupes, mesures, textes — et UNE "
              "brique la monte : nœuds, sphères de verre qui enveloppent leurs membres, liens "
              "animés, volet de détail, curseurs, mode intégré. Déclarée par son domaine dans le "
              "`ready()` de son app ; une scène qui projette un registre (`registry`) donne à la "
              "page de ce registre son bouton « Constellation » (`scene_button`). Scènes : les "
              "utilisateurs (premier consommateur, son adresse gardée), les licences, les modèles ; "
              "une scène de la page commune est jouée chaque nuit (`common.scene.<clé>.ui`). La "
              "légende filtre ; les MAINS pilotent toute scène à la webcam — interface GLOBALE de "
              "la barre du haut (pointeur et pincement universels, ce qu'une page déclare en cible), "
              "MediaPipe dans le navigateur, modèle des gestes installé par la route",
              'wama/common/scenes.py', 'docs/construction/ui/WAMA_SCENES_3D.md',
              annexes=('wama/common/static/common/js/wama-constellation.js',
                       'wama/common/static/common/css/wama-constellation.css',
                       'wama/common/templates/common/constellation.html',
                       'wama/common/scene_views.py', 'wama/common/services/license_scene.py',
                       'wama/model_manager/services/model_scene.py',
                       'wama/common/services/ui_smoke_scenes.py', 'wama/common/tests/tests_scenes.py',
                       'wama/common/hand_gestures.py', 'wama/common/static/common/js/wama-hands.js',
                       'wama/common/static/common/js/wama-hands-ui.js',
                       'wama/common/static/common/css/wama-hands.css',
                       'wama/common/tests/tests_hands.py'),
              depends_on=('app_access',)),
    # Ajouté le 2026-10-04 (décision de Fabien : « option 1, persistance par session »). Collé à
    # `app_access` parce qu'il en est le prolongement : la décision dit QUELLE app est ouverte au
    # visiteur (`public`), celui-ci dit SOUS QUELLE IDENTITÉ il y agit.
    Mechanism('visitor_identity', "Identité de session du visiteur sans compte",
              "Sur une app déclarée `public` (le converter, app d'essai), un visiteur non connecté "
              "agit sous un COMPTE TECHNIQUE propre à sa session (`wama_visitor_<jeton>`, tier "
              "`anonymous`, aucun rôle), créé à son premier geste par l'intergiciel d'accès et "
              "purgé avec ses éléments ET ses fichiers après sa durée de vie. Une identité, pas une "
              "étiquette : toute la logique de propriété existante (file, `users/<id>/`, portée) "
              "vaut pour lui sans retoucher une vue d'app. Bornes dans `settings` (taille, nombre "
              "d'éléments, identités neuves par adresse) ; routes qui font lire au serveur une "
              "adresse ou un chemin fermées ; aucun post-traitement GPU. Sur toute autre app, le "
              "visiteur VOIT et ne fait rien (403 de la même garde). `is_guest_account` = le "
              "prédicat unique « compte de visiteur » (partagé ou de session)",
              'wama/accounts/visitors.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md',
              annexes=('wama/accounts/middleware.py', 'wama/accounts/tests/tests_visitors.py'),
              symbol='attach'),
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
              "d'APP_CATALOG : les surfaces transversales et Lab (`register_surface`) se masquent par "
              "la même clé `gate` que celle dont accessible() décide (§8.8.1)",
              'wama/common/services/subscriptions.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md',
              annexes=('wama/common/static/common/js/wama-subscription.js',
                       'wama/common/tests/tests_subscriptions.py')),
    # Ajouté le 2026-10-02 (pipeline porté par la card, marche P1 — route §10.6 point 6.1). Le
    # monde était DÉDUIT du groupe de la matrice d'accès, les surfaces hors catalogue écrites
    # dans le substrat (`extra_links`) et le journal recevait le monde par un second chemin.
    # Étendu le 2026-10-16 à l'IDENTITÉ (Fabien : « des infos des apps ne vivent pas dans le
    # calendrier ») : la lecture du nom, née dans `services/calendar.py`, avait six jumeaux.
    Mechanism('app_worlds', "Identité et monde déclarés d'une app",
              "Chaque app DÉCLARE son monde (media | data | lab | transverse) et son identité : dans "
              "son entrée d'APP_CATALOG, ou — hors catalogue — depuis son `ready()` "
              "(`register_app_world` ; `register_surface`, qui porte aussi l'identité de sa page ; "
              "`register_pageless_tool`, pour un outil gardé sans page). DEUX lectures, et seulement "
              "elles : `app_world()` (le manifeste d'app, le monde d'une fonction, le menu, `/apps/`, "
              "le journal, le calendrier) et `app_identity()` — libellé, couleur, icône complète, "
              "page, description, monde — pour tout ce qui NOMME une app (calendrier, journal, « Mon "
              "RAG », scène et page des droits, menu « Envoyer vers », phrases des outils de "
              "l'assistant, nom d'une source de modèle — `model_manager.models.source_identity`). "
              "Rien ne déduit un monde d'un libellé de navigation, et rien ne lit une "
              "déclaration hors du registre (garde `AppIdentityTest`)",
              'wama/common/app_registry.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              # Domicile très partagé (APP_CATALOG) : compté par son symbole, cf. `media_taxonomy`.
              symbol='app_world'),
    Mechanism('scoping', 'Accès scopé aux objets',
              "Deux chemins NOMMÉS pour lire un objet partageable depuis une vue (possédé / visible)",
              'wama/common/utils/scoping.py', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md'),
    Mechanism('user_settings', 'Réglages utilisateur par app',
              "Réglages durables en base (UserAppSetting, cache devant) ; réglages du VOLET dérivés "
              "du schéma — lire, garder, remettre à zéro, faire naître un élément, deux routes JSON "
              "(`*_panel_settings`, `new_element_settings`, `make_panel_settings_views`)",
              'wama/common/utils/user_settings.py', ''),
    Mechanism('feature_flags', 'Bascules de fonctionnalités',
              "Registre de Feature par app + surcharges JSON de l'objet porteur — comparer AVEC/SANS",
              'wama/common/utils/feature_flags.py', ''),

    Mechanism('ranged_response', 'Servir un fichier par morceaux (HTTP Range)',
              "Réponse 206 à une requête `Range` — ce qui rend un média seekable au-delà du "
              "déjà-téléchargé ; sert `/media/` (`wama/urls.py`) et la vidéo du cam_analyzer, "
              "dont la règle a été extraite (2026-10-15)",
              'wama/common/utils/ranged_response.py',
              'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §F3b',
              annexes=('wama/common/tests/tests_ranged_response.py',)),
    Mechanism('static_versioning', 'Cache-busting statique',
              "`{% static_v %}` = `{% static %}` + `?v=<mtime>` : le navigateur re-télécharge "
              "un fichier statique dès qu'il change, le garde en cache sinon",
              'wama/common/templatetags/wama_static.py', '',
              # Consommé par la balise de gabarit, jamais par import Python : sans symbole,
              # le compteur (imports du module) rendait 0 — brique « morte » à 100+ pages.
              symbol='static_v'),
    Mechanism('audio_rhythm', 'Grille des temps d\'un audio',
              "L'instant de chaque temps joué d'un audio et les hauteurs qui y sonnent (chroma par "
              "temps), en cache par fichier et date — de quoi caler une partition TEMPS PAR TEMPS "
              "sur ce qui est joué plutôt que par son tempo écrit (né le 2026-10-16 : #754 écrit à "
              "88, joué à 89,1). Ne connaît aucune partition ; le calage est `WamaScore.align`",
              'wama/common/utils/audio_rhythm.py',
              'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §F3b',
              depends_on=('audio_decode',)),
    Mechanism('midi_score', 'Notation d\'un MIDI multi-instrument (MIDI → ABC)',
              "Un MIDI à une piste par instrument → une partition ABC lisible : une voix par "
              "instrument (libellé français), clavier sur deux portées, batterie en portée de "
              "percussion, accords, liaisons, altérations par mesure. Sur la métrique du MIDI quand "
              "le moteur en a trouvé une, sinon sur les temps JOUÉS de l'audio (`audio_rhythm`), "
              "anacrouse comprise. Né le 2026-10-16 pour la partition complète du composer "
              "(MuScriptor, tâche `audio-to-midi`) ; ne connaît aucun moteur. Porte aussi la "
              "LECTURE MIDI commune (`read_midi` : tempos, mesure, tonalité, marqueurs, une partie "
              "par piste et canal), que le moteur YuE2 consomme pour suivre une partition MIDI",
              'wama/common/utils/midi_score.py',
              'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §F3b',
              annexes=('wama/common/tests/tests_midi_score.py',)),
    )),

    *_domain("Studio & surface d'outils (API)", (
    Mechanism('generic_runner', 'Runner générique du studio',
              "Exécute une app par son CONTRAT (triade tool_api normalisée) — zéro logique par app",
              'wama/studio/services/generic_runner.py', 'docs/construction/mondes/STUDIO_VISION.md',
              annexes=('wama/studio/services/launch.py',
                       'wama/studio/services/runners.py',
                       # Les réglages d'un nœud sous la forme commune (R1) et les nœuds INTÉGRÉS
                       # que le Studio inscrit au registre commun (R2, ROUTE §10.6 3.3bis).
                       'wama/studio/services/node_params.py',
                       'wama/studio/services/builtin_nodes.py',
                       # Le GRAPHE porteur de valeurs (2026-10-18, ROUTE §10.6 3.3bis règle 5) :
                       # ce que fournit chaque nœud, ce que reçoit un nœud — LE parcours que lit
                       # aussi le diagnostic des liens.
                       'wama/studio/services/graph_flow.py',
                       # Les RÉSULTATS d'un run (le bout de chaque branche) et leur ZIP, écrit par
                       # l'écrivain du ⬇ de la file (2026-10-20).
                       'wama/studio/services/run_results.py',
                       # La PALETTE d'un compte, seule règle de ce qu'il peut poser et lancer, et
                       # la raison d'un nœud qu'elle n'offre pas (2026-10-19, ROADMAP §16.11).
                       'wama/studio/services/palette.py',
                       # Les cards d'entrée MÉDIAS et le LOT (2026-10-20, STUDIO_VISION §Entrées
                       # du Studio) : port « Entrée de card », lot déplié en runs enfants, URL
                       # téléchargée au lancement ; la modale reprend la card v4 de l'app.
                       'wama/studio/services/entries.py',
                       'wama/studio/static/studio/js/wama-studio-entry.js')),
    Mechanism('tool_api', "Surface d'outils",
              "Registre central TOOL_REGISTRY : triades add/start/status par app, gating F7 via execute_tool, descriptions dérivées des schémas. "
              "Chaque outil DÉCLARE son effet sur sa fonction (`tool_effect` : lecture / écriture / destruction, 2026-10-28) — "
              "les outils d'un sous-agent (`sub_agent_tools`) et les annotations MCP en DÉRIVENT",
              'wama/tool_api.py', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
              annexes=('wama/common/tests/tests_tool_effects.py',)),
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
    'wama/common/utils/html_render.py': ("rendu HTML→PDF par Chromium — converter, avatar 3D (lanceur), export "
                                         "PDF des pages de l'accueil (2026-10-07)"),
    'wama/common/services/page_pdf.py': ("export PDF des présentations et rapports de l'accueil, servis en "
                                         "processus (2026-10-07) — substrat seul, aucune app"),
    # `http_proxy.py` et `ollama_host.py` ont QUITTÉ cette liste le 2026-09-01 : ils sont
    # devenus les annexes du mécanisme `external_sources`. Ils n'étaient pas mal classés — le
    # mécanisme qui les rassemble n'existait pas encore, et une plomberie sans mécanisme
    # au-dessus n'a effectivement rien de transversal à déclarer.
    'wama/common/utils/log_rotation.py': "décalage des journaux au démarrage (politique : on décale, on ne vide pas)",
    'wama/common/utils/mime_utils.py': "détection MIME — helper fin (filemanager/studio)",
    'wama/common/utils/model_locations.py': "chemins de modèles — plomberie model_manager",
    'wama/common/utils/safetensors_utils.py': "inspection de poids safetensors — plomberie chaîne modèles",
    'wama/common/utils/voice_options.py': "pendant VOIX d'output_formats (avatarizer) — promouvoir si adoption s'élargit",
    'wama/model_manager/services/format_converter.py': "conversion de formats de poids — plomberie chaîne modèles (avec format_policy)",
    # Triage du 2026-08-13 (les 3 dernières entrées du backlog) — aucun n'était mort, mes
    # « 0 apps » ne comptaient pas wama_lab :
    'wama/common/utils/intervals.py': "algèbre d'intervalles — cam_analyzer (coverage) seul consommateur",
    'wama/common/utils/whisper_utils.py': "transcription d'un fichier pour les apps hors transcriber (describer, avatarizer) par le gestionnaire du transcriber — Whisper large-v3 sans clé, toute clé de catalogue de transcription sinon, découpage compris (13/10) ; plus de double chemin de chargement (13/08)",
    # 2026-08-27 : la page du registre `skills`. Le service ne porte AUCUN mécanisme propre — il
    # dérive `prompt_skills/*.md` × PROMPT_TARGETS × DOMAINES pour un seul gabarit. Les mécanismes
    # qu'il donne à VOIR sont déjà déclarés (`prompt_pipeline`, `assistant_skills`, `registres`).
    'wama/common/services/skills_catalog.py': "dérivation d'affichage du catalogue de skills — consommée par la vue `skills_catalog` seule",
    # 2026-10-29 : la lecture de l'en-tête `---` … `---` que recopiaient le catalogue des skills et
    # `check_skills`, et dont la réponse d'olmOCR-2 avait besoin — plomberie de texte, pas un mécanisme.
    'wama/common/utils/front_matter.py': "en-tête `---` d'un texte (SKILL.md, réponse d'olmOCR-2) — trois lecteurs, une lecture",
}


def by_key() -> dict:
    return {m.key: m for m in MECHANISMS}
