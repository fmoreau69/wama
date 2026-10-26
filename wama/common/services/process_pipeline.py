"""
Pipeline DÉCLARÉ d'une app — la pièce du moteur commun qui dit « cette card porte PLUSIEURS
process, dans cet ordre, et voici lesquels sont à (re)jouer ». Doc :
`WAMA_APP_GENERATION_ROUTE.md §10.6` points 3.2, 4.3 à 4.5 (marche P3, palier B) et décision n°11.

D'OÙ ÇA VIENT. Rien n'est inventé ici : c'est le registre des passes du cam_analyzer
(`wama_lab/cam_analyzer/utils/pass_tracking.py` — `Pass`, `pipeline_graph`, `pipeline_manifest`,
`recompute_stale`, le lancement ciblé) rendu indépendant de la session et de la caméra. Une app
déclare ses process comme le cam_analyzer déclare ses passes :

    PIPELINE = register_app_pipeline('composer', (
        ProcessSpec('plan', watched=('prompt', 'model'), applies=_plans_a_score),
        ProcessSpec('render', depends_on=('plan',), watched=('prompt', 'model', 'duration')),
    ), label='Composer — partition puis rendu')

  • chaque process est un nœud `function` du catalogue (`FunctionSpec binding: app`, clé
    `<app>.<clé>` — déclaré par l'app dans son `function_specs.py`) ;
  • le registre S'EXPORTE en manifeste `pipeline` (`register_pipeline_source`) : il s'ouvre au
    studio comme tout pipeline (« UNE représentation, DEUX éditeurs ») ;
  • l'exécution reste au squelette de tâche (`task_skeleton.run_item_task(pipeline=…,
    processes={clé: glu})`), qui joue les process retenus dans UNE tâche Celery — chacun sur la
    file que dit son drapeau `gpu` : la tâche se re-livre à l'autre file entre deux process
    (2026-10-14, cf. `gpu` ci-dessous) ;
  • l'état de chaque process vit sur sa ligne (`process_runs`), l'état de la card s'en DÉDUIT.

CE QUE CE MODULE DÉCIDE
  • l'ORDRE : celui du graphe (`manifests/builtin/pipeline.topo_order` — le tri du canvas) ;
  • ce qui est PÉRIMÉ (`refresh`) : un réglage surveillé a changé, la sortie d'un amont a été
    remplacée, un amont est lui-même périmé — `process_runs.stale_nodes` ;
  • ce qu'un lancement JOUE (`steps_to_run`) : les process qui ne sont pas à jour et tout leur
    aval ; une card entièrement à jour qu'on relance rejoue tout.

⚠ FRONTIÈRE (gardée par `tests_process_states`) : `STALE` est l'état d'une LIGNE. L'élément
garde ses cinq états tant que l'interface le lit (marche P6) — `card_state()` rend l'état
déduit à qui veut l'afficher, ce module ne l'écrit pas dans `status`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from wama.common.models import (JOB_AWAITING_RESOURCES, JOB_PENDING, JOB_RUNNING, JOB_STALE,
                                JOB_SUCCESS)
from wama.common.services import process_runs
from wama.common.services.process_runs import OPTIONAL, REQUIRED

#: Clé de la photo qui porte l'empreinte des sorties d'amont (« entrée remplacée », point 4.3).
#: Le `@` l'écarte de tout nom de réglage.
UPSTREAM_KEY = '@upstream'

#: Les formes du résultat lisible d'un process (`ProcessSpec.result_format`) : '' = texte brut.
RESULT_FORMATS = ('', 'markdown', 'coherence', 'segments')


def segments_text(segments) -> str:
    """Des SEGMENTS de parole (`result_format='segments'` : `[{speaker, time_range, text}]`) en
    texte — un tour par bloc, son locuteur et sa plage, puis ses mots. La forme de l'export TXT
    du transcriber, qui la lit d'ici."""
    return '\n\n'.join(f"[{s.get('speaker') or ''}]  {s.get('time_range') or ''}\n  {s.get('text') or ''}"
                       for s in segments or ())

#: Attribut posé sur un élément par `preload` : ses lignes d'exécution, lues une fois.
PRELOADED = '_process_rows'
#: … et, dans la même fenêtre, les réponses de `applies` par (process, modèle).
APPLIES_MEMO = '_process_applies'


def preload(items) -> None:
    """Lit en UNE requête les lignes d'exécution de tous ces éléments (même modèle) et les pose
    sur chacun — ce que `AppPipeline.rows` lit ensuite sans retourner en base.

    Pour les VUES seulement (une page de file : N cards, une requête) ; la tâche, elle, lit la
    base à chaque question. Mesuré le 2026-10-03 : sans cela la bande des process coûtait six
    requêtes par card (lignes relues par `refresh`, `card_rows` et `shown_state`).

    La même fenêtre retient les réponses de `applies` (2026-10-05) : celui du composer et du
    transcriber résout le backend du modèle — 0,56 s l'appel sur ce poste —, et la bande des
    process, l'ETA du lancement et la card posaient chacune la question."""
    items = [item for item in items if item is not None]
    grouped = process_runs.lines_by_item(items)
    pipeline = pipeline_of(items[0]) if items else None
    for item in items:
        setattr(item, PRELOADED, grouped.get(str(item.pk), []))
        item.__dict__.setdefault(APPLIES_MEMO, {})
        if pipeline is not None and pipeline.backfill_prior_runs(item):
            setattr(item, PRELOADED, list(process_runs.lines(item)))


def release(item) -> None:
    """Referme la fenêtre de `preload` sur cet élément : une instance gardée par l'appelant (un
    test, une vue qui écrit ensuite) ne relira ni des lignes ni des réponses périmées."""
    item.__dict__.pop(PRELOADED, None)
    item.__dict__.pop(APPLIES_MEMO, None)


@dataclass(frozen=True)
class ProcessSpec:
    """Un process d'un pipeline d'app — les champs de `pass_tracking.Pass` qui ne sont pas
    propres au cam_analyzer, plus le degré de liberté du point 3.2.

      key         identifiant du process dans SON pipeline = le nœud de sa ligne d'exécution ;
      label       libellé COURT pour la card (« Partition », « Rendu ») — le nom long est celui
                  du `FunctionSpec` au catalogue ; vide = la clé ;
      depends_on  amonts : ordre de lancement, et propagation de la péremption ;
      watched     champs de l'ÉLÉMENT HORS schéma dont le changement rend le process périmé
                  (fichiers d'entrée, `prompt_processed`…). Les RÉGLAGES du schéma déclarent
                  eux-mêmes les process qu'ils périment (`Param.stales`, 2026-10-05) ; ce que le
                  process surveille vraiment est `AppPipeline.watched_of(spec)` — l'union, dans
                  l'ordre du schéma puis de cette liste ;
      degree      `required` (son échec fait échouer la card) | `optional` ;
      function    clé du catalogue de fonctions quand elle diffère de `<app>.<key>` ;
      gpu         le process SOLLICITE LA CARTE GRAPHIQUE : un modèle chargé dans le worker, ou
                  un service local qui en charge un (Ollama hôte, service TTS). C'est une GARDE
                  depuis le 2026-10-14 (décision de Fabien : le gouverneur au grain du process,
                  pas de la card) — le squelette le joue sur la file GPU, le déclare au
                  gouverneur pendant qu'il tourne, et lui fait attendre sa VRAM ; un process sans
                  GPU (conversion, floutage, sortie, import) se joue sur la file par défaut et ne
                  tient pas la carte. Un appel LLM compte comme GPU tant que son modèle n'est
                  connu qu'à l'appel : le relâcher sur la file par défaut ferait charger l'Ollama
                  hôte EN CONCURRENCE des traitements — ce qui a fait tomber l'hôte le
                  2026-08-19 (`settings.py`, route de `model_manager.assess_proposed`). Jusque-là :
                  « dit à l'utilisateur, jamais une garde ». L'exception est `card_model` ;
      card_model  le process emploie LE modèle de la card — celui que le squelette tire avant la
                  boucle des process (`run_item_task(model_key=…)`, « auto » résolu). Si ce
                  tirage est DISTANT, le process ne tient pas la carte : ni file GPU, ni
                  déclaration au gouverneur, ni attente de VRAM (`ROADMAP §8d` étape 4, décision
                  de Fabien du 2026-10-14 : « si la tâche est prévue en distant, il ne faut pas
                  réserver de créneau »). Les AUTRES process GPU de la card (un résumé par Ollama
                  après une transcription distante) restent GPU, mais n'héritent plus du besoin
                  VRAM d'un modèle qu'ils n'emploient pas ;
      share       part de la barre de progression de la card (poids relatif) ;
      applies     `(item, model_key) -> bool` : le process a-t-il lieu pour CET élément ? Absent =
                  toujours. C'est ce qui laisse un pipeline à deux process n'en jouer qu'un pour
                  un modèle qui ne sait pas faire le premier ;
      outputs     champs FICHIER de l'élément que le process ÉCRIT (`planned_score`,
                  `audio_output`) — ce qu'un lancement borné à ce process remplace, et rien
                  d'autre (`reset_outputs`). Déclaré : le lanceur ne lit pas la glu ;
      toggle      champ BOOLÉEN de l'élément qui ACTIVE un process `optional` (`ROUTE §10.6`
                  3.2 : « l'utilisateur l'active ou non — c'est une option d'aujourd'hui » :
                  `enable_diarization`, `generate_summary`…). Désactivé, le process n'a pas lieu
                  et ne pèse plus sur l'état de la card (règle 4.4 : « les optional désactivés
                  sont ignorés ») ; la bande en fait une case à cocher. Distinct d'`applies`,
                  qui dit ce que le MODÈLE sait faire, pas ce que l'utilisateur veut.
      available   `() -> bool` : le process PEUT-il avoir lieu ICI — typiquement, un modèle de sa
                  tâche est installé (2026-10-03, `composer.extract_score`). Absent = toujours.
                  Distinct d'`applies`, qui juge un élément : `available` juge l'installation, et
                  c'est lui que lisent les ENTRÉES ÉTENDUES (`covering_inputs`).
      eta         chemin `module:attribut` (forme de `FunctionSpec.impl`, résolu paresseusement
                  par `function_catalog.resolve_impl`) vers `(élément) -> (clé, taille, unité[,
                  modèle chargé[, a priori]])` — l'ETA PAR PROCESS (`ROUTE §10.6` 4.5), celle que
                  sa glu apprend ; lue par `process_runs.launch_eta`. Absent = le process ne vaut
                  que sa dernière durée sur la card.
      result      chemin `module:attribut` (même forme qu'`eta`) vers `(élément) -> texte | None` :
                  le RÉSULTAT LISIBLE du process quand ce n'est pas un fichier — le texte d'une
                  transcription, ses tours par locuteur, un résumé, un rapport de cohérence
                  (décision de Fabien, 2026-10-12 : « le process porte sa sortie », comme il porte
                  ses fichiers dans `outputs`). C'est ce que l'aperçu commun montre en FACE du
                  process (`preview_utils`, `ROUTE §F3b`). Absent = le process n'a de résultat
                  lisible que par ses `outputs`.
      result_format  la FORME de ce résultat : '' (texte brut) ; 'markdown' — un résumé rédigé
                  par un LLM a des titres et des listes, que l'aperçu met alors en forme
                  (2026-10-13 : la modale propre du describer le faisait, la face commune
                  montrait les `##` bruts) ; 'coherence' — `result` rend alors le RAPPORT de la
                  brique commune `verify_text_coherence` (`llm_utils.build_coherence_report`),
                  que la face montre comme le faisaient les modales du describer et du
                  transcriber : score coloré, remarques, version proposée EN REGARD du texte
                  vérifié (2026-10-13, Fabien : « on ne doit rien perdre, on complète le
                  commun ») ; 'segments' — `result` rend des tours de parole
                  `[{speaker, time_range, text}]`, que la face montre un par un, le locuteur
                  dans sa couleur (la diarisation de la modale du transcriber, même jour).
      split_from  le process dont celui-ci a été DÉTACHÉ, en amont (2026-10-21 : la préparation
                  audio du transcriber, qui se faisait DANS `transcribe`). Une ligne de ce process
                  rendue AVANT le détachement — sa photo porte encore tous les réglages que
                  celui-ci surveille et son interrupteur, puisqu'elle les surveillait alors —
                  a fait son travail en
                  elle-même : elle VAUT pour lui tant que ces réglages n'ont pas changé
                  (`_held_within`). Sans cela, la card ancienne n'ayant aucune ligne du process
                  détaché, toute relance l'aurait joué et aurait rejoué son aval avec lui — une
                  transcription entière refaite pour un type de résumé changé. Inerte dès que
                  l'aval a été rendu de nouveau (sa photo ne porte plus ces réglages).
      upstream_switch  champ BOOLÉEN de l'élément qui dit si ce process LIT la sortie de ses
                  amonts du type qu'il consomme (les ports d'entrée de son `FunctionSpec`) ; à
                  faux, il lit l'entrée de la card, et ces amonts ne le concernent plus — ni sa
                  photo, ni sa péremption, ni sa relance (`read_upstreams`). Leur sortie reste
                  produite et ÉCOUTABLE. 2026-10-22, demande de Fabien : l'audio préparé sert
                  aussi l'intelligibilité pour la correction humaine — on doit pouvoir le
                  produire sans que la transcription l'écoute.
      checks      les MESURES SANS RÉFÉRENCE de la sortie de ce process — des clés du registre
                  commun (`result_evaluation.register_check`), jouées par le squelette quand la
                  card a réussi, gardées sur la LIGNE du process (`output_summary['checks']`) : la
                  bande des process les montre sur sa ligne, la face « Évaluation » de l'aperçu
                  avec les mesures contre une référence. 2026-10-22, décision de Fabien : la part
                  de la parole que couvre une transcription (`speech_coverage`) — un texte perdu
                  se voit, quel que soit le moteur.
    """
    key: str
    label: str = ''
    depends_on: tuple = ()
    watched: tuple = ()
    degree: str = REQUIRED
    function: str = ''
    gpu: bool = False
    card_model: bool = False
    share: int = 1
    applies: Callable = None
    outputs: tuple = ()
    toggle: str = ''
    available: Callable = None
    eta: object = None
    result: object = None
    result_format: str = ''
    split_from: str = ''
    upstream_switch: str = ''
    checks: tuple = ()


def output_fingerprint(ref: str) -> str:
    """Empreinte de la sortie d'un process (chemin relatif à MEDIA_ROOT) : celle de la brique
    commune `provenance.sha256_of` — la même que la RÉVISION garde de chaque sortie
    (`revisions.output_references`). Un fichier trop gros pour être lu est suivi par sa taille ;
    une sortie disparue a une empreinte à elle — son aval devient périmé."""
    if not ref:
        return ''
    from django.conf import settings
    from wama.common.utils.provenance import sha256_of
    path = os.path.join(settings.MEDIA_ROOT, ref)
    digest = sha256_of(path)
    if digest:
        return digest
    try:
        return f'size:{os.path.getsize(path)}'
    except OSError:
        return f'missing:{ref}'


def _fingerprint_of(row) -> str:
    """Empreinte de ce qu'un process a RENDU : celle que sa glu a déclarée (`output_fingerprint`
    du retour — une sortie qui n'est pas un fichier : le texte d'une transcription, des segments
    en base), sinon celle du fichier de `output_ref`."""
    declared = (row.output_summary or {}).get('fingerprint')
    return str(declared) if declared else output_fingerprint(row.output_ref)


def _output_lost(row) -> bool:
    """La ligne annonce une sortie que le disque ne porte plus."""
    if not row.output_ref:
        return False
    from django.conf import settings
    return not os.path.exists(os.path.join(settings.MEDIA_ROOT, row.output_ref))


def declared_stales(app: str) -> dict:
    """`{process: [réglages]}` — ce que chaque réglage du schéma de `app` déclare périmer
    (`Param.stales`), dans l'ordre du schéma, TOUS les schémas déclarés réunis (une app à
    plusieurs domaines — imager image + vidéo — en a plusieurs ; un nom n'y compte qu'une fois).
    Lu par `AppPipeline.watched_of` et par sa garde. `{}` pour une app sans schéma."""
    from wama.common.utils.param_schema import _pget, declared_param_schemas
    out, seen = {}, set()
    for schema in ((declared_param_schemas(app) or {}).get('schemas') or {}).values():
        for param in schema:
            name = _pget(param, 'name')
            if name in seen:
                continue
            seen.add(name)
            for process in (_pget(param, 'stales') or ()):
                out.setdefault(process, []).append(name)
    return out


class AppPipeline:
    """Le pipeline déclaré d'une app : ses `ProcessSpec`, et ce qui s'en dérive."""

    def __init__(self, app: str, specs, *, label: str, description: str = '',
                 source_ref: str = '', model_of=None):
        self.app = app
        self.model_of = model_of
        self.specs = tuple(specs)
        self.label = label
        self.description = description
        self.source_ref = source_ref or f'{app}.function_specs:PIPELINE'
        self._by_key = {spec.key: spec for spec in self.specs}
        if len(self._by_key) != len(self.specs):
            raise ValueError(f"pipeline de {app} : clé de process dupliquée")
        for spec in self.specs:
            unknown = [d for d in spec.depends_on if d not in self._by_key]
            if unknown:
                raise ValueError(f"pipeline de {app} : « {spec.key} » dépend de "
                                 f"{', '.join(unknown)}, qui n'y est pas déclaré")
            if spec.degree not in (REQUIRED, OPTIONAL):
                raise ValueError(f"pipeline de {app} : degré « {spec.degree} » inconnu")
            if spec.toggle and spec.degree != OPTIONAL:
                raise ValueError(f"pipeline de {app} : « {spec.key} » porte un interrupteur "
                                 f"(`toggle`) mais n'est pas `optional`")
            if spec.split_from and spec.key not in getattr(
                    self._by_key.get(spec.split_from), 'depends_on', ()):
                raise ValueError(f"pipeline de {app} : « {spec.key} » se dit détaché de "
                                 f"« {spec.split_from} » (`split_from`), qui doit en dépendre")
            if spec.result_format not in RESULT_FORMATS:
                raise ValueError(f"pipeline de {app} : forme de résultat « {spec.result_format} » "
                                 f"inconnue ({', '.join(f or '(texte)' for f in RESULT_FORMATS)})")
            if spec.checks:
                from wama.common.services.result_evaluation import CHECKS
                unknown = [c for c in spec.checks if c not in CHECKS]
                if unknown:
                    raise ValueError(f"pipeline de {app} : « {spec.key} » déclare des mesures "
                                     f"inconnues ({', '.join(unknown)}) — `register_check`")
        self.ordered()                      # un cycle se refuse à la DÉCLARATION, pas au lancement

    # ── Déclaration ─────────────────────────────────────────────────────────────────────────
    def spec(self, key: str) -> ProcessSpec:
        return self._by_key[key]

    def requested_model(self, item):
        """Le modèle que la card DEMANDE (`model_of`, déclaré une fois par l'app) — ce que
        lisent la bande des process, la vue de progression et le ▶ d'un process. `None` : le
        modèle n'est connu qu'au lancement (composer sous « auto »), ou l'app ne déclare rien."""
        if self.model_of is None:
            return None
        try:
            return self.model_of(item)
        except Exception:
            return None

    def function_key(self, spec: ProcessSpec) -> str:
        """Clé `FUNCTION_CATALOG` du process — le nœud `function` qu'il devient au manifeste."""
        return spec.function or f'{self.app}.{spec.key}'

    def watched_of(self, spec: ProcessSpec) -> tuple:
        """Ce que le process SURVEILLE : les réglages du schéma de l'app qui le nomment dans leur
        `stales` (ordre du schéma, tous domaines confondus — imager image + vidéo), puis les
        champs hors schéma de `spec.watched`. Ce que lisent la photo, l'export et la bande.

        Avant le 2026-10-05, la liste était écrite à la main dans chaque `function_specs.py` :
        `check_redundancy` la relevait dans les SIX pipelines comme des noms recopiés du schéma.
        Calculé une fois par process : le schéma ne change pas pendant la vie du processus."""
        cache = self.__dict__.setdefault('_watched_cache', {})
        if spec.key not in cache:
            names = list(declared_stales(self.app).get(spec.key, ()))
            cache[spec.key] = tuple(dict.fromkeys(names + list(spec.watched)))
        return cache[spec.key]

    # ── Entrées ÉTENDUES par le pipeline (2026-10-03) ───────────────────────────────────────
    # Un modèle déclare ce qu'IL consomme (catalogue). Au sein d'un pipeline, un process AMONT
    # peut lui fabriquer l'une de ses entrées depuis une autre : `composer.extract_score` tire la
    # partition (que YuE2 suit) de l'audio d'un cover (que YuE2 ne prend pas). La card, la
    # création, l'outil de l'assistant et le tirage « auto » doivent alors savoir que ce modèle
    # accepte l'audio. Écrit d'abord dans le composer (`accepts_input`), DÉRIVÉ ici des
    # déclarations : les types des ports viennent des `FunctionSpec`, la disponibilité
    # d'`available` — aucune app ne réécrit la règle.

    def _ports(self, spec: ProcessSpec):
        """(entrées, sorties) du `FunctionSpec` du process — listes de `PortSpec`, vides s'il
        n'est pas déclaré au catalogue."""
        from wama.common.catalog import function_catalog as fc
        declared = fc.get(self.function_key(spec))
        if declared is None:
            return [], []
        return list(declared.inputs or []), list(declared.outputs or [])

    def output_type(self, spec: ProcessSpec) -> str:
        """Le TYPE de ce que le process rend — celui du premier port de sortie de son
        `FunctionSpec` (une nature média ou un type de donnée, `app_registry.known_port_types`),
        '' s'il n'est pas déclaré. C'est lui qui choisit le rendu d'une face d'aperçu."""
        outputs = self._ports(spec)[1]
        return outputs[0].data_type if outputs else ''

    @staticmethod
    def declared_result(spec: ProcessSpec, item):
        """Ce que rend la déclaration `ProcessSpec.result` pour cet élément, TEL QUEL : un texte,
        un rapport (`result_format='coherence'`), ou None — sans déclaration, ou déclaration
        illisible (dite au journal, jamais levée : un aperçu ne casse pas pour un lecteur, comme
        `process_runs.process_eta`)."""
        declared = spec.result
        if not declared:
            return None
        try:
            if isinstance(declared, str):
                from wama.common.catalog.function_catalog import resolve_impl
                declared = resolve_impl(declared)
            return declared(item) or None
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "[process_pipeline] résultat du process « %s » illisible", spec.key, exc_info=True)
            return None

    @staticmethod
    def result_text(spec: ProcessSpec, value):
        """Le TEXTE d'un résultat déclaré : un rapport de cohérence s'écrit par la brique commune
        (`llm_utils.coherence_report_text`), des segments par `segments_text` ; tout autre
        résultat est déjà son texte."""
        if not value:
            return None
        if spec.result_format == 'coherence' and isinstance(value, dict):
            from wama.common.utils.llm_utils import coherence_report_text
            return coherence_report_text(value)
        if spec.result_format == 'segments' and isinstance(value, (list, tuple)):
            return segments_text(value)
        return str(value)

    @classmethod
    def readable_result(cls, spec: ProcessSpec, item):
        """Le résultat LISIBLE déclaré du process pour cet élément : un texte, ou None."""
        return cls.result_text(spec, cls.declared_result(spec, item))

    def _bridges(self):
        """`[(ports que l'amont PREND, ports de l'aval qu'il ALIMENTE)]` des process disponibles
        ICI : un process alimente, chez ses process DIRECTEMENT en aval (`depends_on`), les
        entrées du TYPE de l'une de ses sorties.

        Aucune notion de process « terminal » : elle désignait le dernier process comme celui du
        modèle, ce qu'un process de SORTIE en aval du rendu (format, qualité) aurait faussé —
        relevé le jour même, avant qu'il n'arrive. Seule la structure DÉCLARÉE compte."""
        out = []
        for spec in self.specs:
            if not self.can_run(spec):
                continue
            inputs, outputs = self._ports(spec)
            gives = {p.data_type for p in outputs}
            fed = set()
            for downstream in self.specs:
                if spec.key in downstream.depends_on:
                    fed |= {p.key for p in self._ports(downstream)[0] if p.data_type in gives}
            if fed:
                out.append(({p.key for p in inputs}, fed))
        return out

    def covering_inputs(self, port: str) -> set:
        """Les ports par lesquels un modèle accepte `port` au sein du pipeline : `port` lui-même,
        plus toute entrée qu'alimente un amont disponible qui PREND `port`. Un modèle qui
        consomme l'un d'eux accepte `port`."""
        covering = {port}
        for takes, fed in self._bridges():
            if port in takes:
                covering |= fed
        return covering

    def extended_inputs(self, ports) -> set:
        """Ce qu'accepte, au sein du pipeline, un modèle qui consomme `ports` : ses ports, plus
        ce que PREND tout amont disponible qui alimente l'un d'eux."""
        consumed = set(ports or ())
        accepted = set(consumed)
        for takes, fed in self._bridges():
            if fed & consumed:
                accepted |= takes
        return accepted

    def graph(self) -> dict:
        """Le registre sous la forme CANVAS du studio (`{nodes, links}`) — même forme que
        `pass_tracking.pipeline_graph` : un process = un nœud `function`, une dépendance = un
        lien. Le `process` du nœud porte ce qui est propre au process et absent du `FunctionSpec`
        — sa DÉCLARATION ; ses `params` restent ses VALEURS de réglage (vides ici : un registre
        ne décide rien pour l'utilisateur). Séparés le 2026-10-18 (ROUTE §10.6 3.2, D1) : la
        déclaration vivait dans `params`, que l'inspecteur du Studio écrit."""
        from wama.common.manifests.builtin.pipeline import FUNCTION_NODE_PREFIX
        # `label`, `outputs`, `share` exportés depuis le 2026-10-05 (session Writer) : le
        # GÉNÉRATEUR relit ce manifeste pour écrire `function_specs.py`, les colonnes de sortie et
        # la remise à zéro d'un ▶ borné — sans eux, un pipeline exporté puis régénéré perdait
        # ce que `reset_outputs` remplace. Ajout pur : un champ vide n'est pas écrit.
        nodes = [{'id': spec.key, 'app': f'{FUNCTION_NODE_PREFIX}{self.function_key(spec)}',
                  'params': {},
                  'process': {'degree': spec.degree, 'gpu': spec.gpu,
                             'watched': list(self.watched_of(spec)),
                             **({'toggle': spec.toggle} if spec.toggle else {}),
                             # 2026-10-14 (ROADMAP §8d étape 4) : écrit seulement quand il est
                             # vrai — ajout pur, les autres pipelines exportés ne bougent pas.
                             **({'card_model': True} if spec.card_model else {}),
                             # 2026-10-22 : écrit seulement quand il est posé (ajout pur).
                             **({'upstream_switch': spec.upstream_switch}
                                if spec.upstream_switch else {}),
                             **({'label': spec.label} if spec.label else {}),
                             **({'outputs': list(spec.outputs)} if spec.outputs else {}),
                             **({'share': spec.share} if spec.share != 1 else {}),
                             **({'eta': spec.eta} if isinstance(spec.eta, str) and spec.eta
                                else {}),
                             **({'result': spec.result}
                                if isinstance(spec.result, str) and spec.result else {}),
                             **({'result_format': spec.result_format}
                                if spec.result_format else {}),
                             # 2026-10-22 : écrit seulement quand il est posé (ajout pur).
                             **({'checks': list(spec.checks)} if spec.checks else {})}}
                 for spec in self.specs]
        links = [{'from': upstream, 'to': spec.key, 'to_port': None}
                 for spec in self.specs for upstream in spec.depends_on]
        return {'nodes': nodes, 'links': links}

    def manifest(self) -> dict:
        """Manifeste `pipeline` du registre — exporté par `manifest_export --kind pipeline`."""
        from wama.common.app_registry import app_world
        from wama.common.manifests.builtin.pipeline import graph_to_body
        body = graph_to_body(self.graph())
        return {
            'manifest_kind': 'pipeline',
            'key': self.app,
            'schema_version': '1.0',
            'name': f"{self.label} ({len(body['nodes'])} process)",
            'description': self.description or (
                "Pipeline déclaré en code : chaque process est un nœud `function` du catalogue, "
                "chaque dépendance un lien."),
            'world': app_world(self.app),
            'owner': None,
            'visibility': 'public',
            'projects': [],
            'source': {'type': 'extract', 'ref': self.source_ref},
            'body': body,
        }

    def ordered(self, keys=None) -> list:
        """Les process (tous, ou ceux de `keys`) dans l'ordre topologique du graphe."""
        from wama.common.manifests.builtin.pipeline import topo_order
        wanted = None if keys is None else set(keys)
        return [self._by_key[node['id']] for node in topo_order(self.graph())
                if wanted is None or node['id'] in wanted]

    # ── Lecture des lignes ──────────────────────────────────────────────────────────────────
    def rows(self, item) -> dict:
        """`{clé de process: ligne}` pour les process de CE pipeline qui ont déjà tourné — lues
        de ce que `preload` a posé sur l'élément (une requête pour toute une page), sinon de la
        base."""
        loaded = getattr(item, PRELOADED, None)
        if loaded is not None:
            return {row.node_id: row for row in loaded
                    if row.instance_key == '' and row.node_id in self._by_key}
        return {row.node_id: row
                for row in process_runs.lines(item).filter(instance_key='',
                                                           node_id__in=list(self._by_key))}

    def read_upstreams(self, spec: ProcessSpec, item) -> tuple:
        """Les amonts que le process LIT pour cet élément : tous (`depends_on`), sauf — quand son
        interrupteur `upstream_switch` est à faux — ceux qui rendent un type qu'il consomme (ses
        ports d'entrée) : il lit alors l'entrée de la card, et leur sortie ne le concerne plus. Ce
        que lisent la photo, la péremption, la relance et `upstream_output`."""
        if not spec.upstream_switch or getattr(item, spec.upstream_switch, True):
            return tuple(spec.depends_on)
        consumed = {port.data_type for port in self._ports(spec)[0]}
        return tuple(key for key in spec.depends_on
                     if self.output_type(self._by_key[key]) not in consumed)

    def snapshot(self, spec: ProcessSpec, item, rows: dict | None = None) -> dict:
        """Photo de ce que le process SURVEILLE aujourd'hui : ses réglages, et l'empreinte de la
        sortie de chacun des amonts qu'il LIT (`read_upstreams`) qui a tourné ET compte encore
        (`_live_rows` : un amont sans ligne, ou qui n'a plus lieu, n'y figure pas)."""
        rows = self._live_rows(item) if rows is None else rows
        taken = process_runs.snapshot(item, self.watched_of(spec))
        upstream = {key: _fingerprint_of(rows[key])
                    for key in self.read_upstreams(spec, item) if key in rows}
        if upstream:
            taken[UPSTREAM_KEY] = upstream
        return taken

    @staticmethod
    def enabled(spec: ProcessSpec, item) -> bool:
        """Le process est-il ACTIVÉ pour cet élément ? Toujours, sauf un `optional` dont
        l'interrupteur (`toggle`) est à faux."""
        return not spec.toggle or bool(getattr(item, spec.toggle, False))

    @staticmethod
    def can_run(spec: ProcessSpec) -> bool:
        """Le process PEUT-il avoir lieu ici (`available`) ? Une disponibilité illisible vaut NON :
        un process qui ne peut pas tourner ne doit pas être retenu au lancement."""
        if spec.available is None:
            return True
        try:
            return bool(spec.available())
        except Exception:
            return False

    def takes_place(self, spec: ProcessSpec, item, model_key=None) -> bool:
        """LE lieu où l'on décide qu'un process a lieu pour un élément : activé (`toggle`),
        disponible ici (`available`) et servi par le modèle (`applies`). Un process ALTERNATIF
        (le `plan` du composer face à `extract_score`) pose la question de son rival ICI, pour
        qu'elle n'ait qu'une réponse."""
        return (self.enabled(spec, item) and self.can_run(spec)
                and self.applies(spec, item, model_key))

    @staticmethod
    def applies(spec: ProcessSpec, item, model_key=None) -> bool:
        """Le modèle sert-il ce process pour cet élément (`ProcessSpec.applies`) ? Dans une
        fenêtre de `preload`, la réponse est retenue par (process, modèle) : hors d'elle (la
        tâche), elle est reposée à chaque fois."""
        if spec.applies is None:
            return True
        memo = getattr(item, '__dict__', {}).get(APPLIES_MEMO)
        if memo is None:
            return bool(spec.applies(item, model_key))
        key = (spec.key, model_key)
        if key not in memo:
            memo[key] = bool(spec.applies(item, model_key))
        return memo[key]

    def applicable(self, item, model_key=None) -> list:
        """Les process qui ont lieu pour cet élément, dans l'ordre de lancement (`takes_place`)."""
        return [spec for spec in self.ordered() if self.takes_place(spec, item, model_key)]

    def still_counts(self, spec: ProcessSpec, item, model_key=None) -> bool:
        """La ligne de ce process COMPTE-t-elle encore pour l'élément — pour la péremption, l'état
        de la card, la photo de son aval ? Oui tant que l'ÉLÉMENT le demande : un `optional`
        désactivé ne compte plus (règle 4.4), ni un process que le modèle ne sert plus pour lui
        (`applies` : un nivellement décoché, un audio de cover retiré). Sous un modèle encore
        inconnu (« auto » non tiré, `requested_model` → None), seul l'interrupteur juge : on ne
        devine pas le tirage (`card_rows`). La DISPONIBILITÉ (`available`, ce qui est installé
        ici) ne juge pas : désinstaller un modèle ne change pas la card, ses résultats valent.

        Avant le 2026-10-21, seul l'interrupteur jugeait : la ligne d'un amont qui n'avait plus
        lieu restait, périmée par le réglage qui l'écartait — et son aval, rejoué sans lui,
        redevenait périmé à chaque relecture (mesuré : `refresh` → {'render'} après la relance,
        card à jamais « périmée »). Le composer y était exposé (cover retiré après extraction),
        la préparation audio du transcriber l'aurait été à chaque nivellement décoché."""
        if not self.enabled(spec, item):
            return False
        return model_key is None or self.applies(spec, item, model_key)

    def output_of(self, item, key: str, model_key=None) -> str:
        """Le fichier (relatif à MEDIA_ROOT) que le process `key` a rendu à cet élément et que son
        aval doit LIRE — le premier de ses `outputs` que l'élément porte ; '' quand le process n'a
        pas lieu pour lui (`takes_place`, le même lieu que le lancement), ou qu'il n'a rien rendu.
        Un aval lit donc la sortie de son amont par CE geste, jamais par le champ seul : une card
        dont le nivellement est décoché garde son ancien audio préparé, que la transcription ne
        doit plus écouter (2026-10-21 ; le composer le disait à la main pour ses partitions)."""
        spec = self.spec(key)
        if not self.takes_place(spec, item, model_key):
            return ''
        for field in spec.outputs:
            value = getattr(item, field, None)
            name = getattr(value, 'name', value) if value else ''
            if isinstance(name, str) and name:
                return name
        return ''

    def produced_fields(self, item) -> list:
        """Les champs FICHIER de l'élément que ses process ont ÉCRITS — ce dont une copie repart
        sans (`duplicate_instance`, 2026-10-21) : le champ déclaré d'un process (`outputs`) quand ce
        process a lieu pour l'élément (au modèle qu'il demande), ou qu'une de ses lignes
        d'exécution a rendu ce fichier (un ancien résultat). Un champ déclaré qui n'est ni l'un ni
        l'autre a été DONNÉ par l'utilisateur : l'audio d'un avatarizer « standalone » est la sortie
        déclarée de `speak`, qui n'a lieu qu'en mode « pipeline » — la copie le garde. Rien n'est
        nommé par app : les vues recopiaient ces listes à la main, en deux exemplaires (vue de la
        card, fabrique des lots), et elles avaient dérivé (`parts_score` du composer)."""
        model_key = self.requested_model(item)
        rows = self.rows(item)
        produced = []
        for spec in self.specs:
            row = rows.get(spec.key)
            # Sous « auto » non tiré, `applies` juge sans modèle ; une ligne passée tranche alors.
            takes_place = self.takes_place(spec, item, model_key)
            for field in spec.outputs:
                value = getattr(item, field, None)
                name = getattr(value, 'name', value) if value else ''
                if not name or field in produced:
                    continue
                if takes_place or (row is not None and row.output_ref == name):
                    produced.append(field)
        return produced

    def upstream_output(self, item, key: str, data_type: str, model_key=None) -> str:
        """Le fichier de type `data_type` (une nature de PORT : `audio`, `score`…) que le process
        `key` LIT de son amont — la sortie (`output_of`) du plus PROCHE de ses amonts, de proche
        en proche par `depends_on` et le plus en aval d'abord, qui rend ce type (le port de sortie
        de son `FunctionSpec`), a lieu pour l'élément ET a rendu son fichier. '' quand aucun : le
        process lit alors l'entrée de la card. Un amont qui a lieu sans avoir rendu (son process
        a échoué — sa ligne le dit, et l'aval s'en trouve périmé) laisse la place au précédent :
        une transformation de plus qui manque ne fait pas écouter l'original.

        La donnée suit les liens que le pipeline DÉCLARE (2026-10-21) : la transcription écoute
        l'audio débruité, sinon nivelé, sinon l'original ; les locuteurs, en aval d'elle, le même
        — sans que la glu nomme ses amonts. Le rendu du composer suit la partition extraite ou
        écrite, deux amonts exclusifs (`applies`). Seuls les amonts LUS comptent
        (`read_upstreams`) : un process dont l'interrupteur `upstream_switch` est coupé lit
        l'entrée de la card pour le type qu'il consomme (2026-10-22)."""
        spec = self.spec(key)
        if (spec.upstream_switch and not getattr(item, spec.upstream_switch, True)
                and data_type in {port.data_type for port in self._ports(spec)[0]}):
            return ''
        order = {s.key: index for index, s in enumerate(self.ordered())}
        seen, pending = set(), list(self.read_upstreams(spec, item))
        while pending:
            upstream = pending.pop()
            if upstream not in seen:
                seen.add(upstream)
                pending.extend(self.read_upstreams(self.spec(upstream), item))
        for upstream in sorted(seen, key=lambda name: -order[name]):
            if self.output_type(self.spec(upstream)) == data_type:
                found = self.output_of(item, upstream, model_key)
                if found:
                    return found
        return ''

    def input_of(self, item, key: str, data_type: str, model_key=None) -> str:
        """Le CHEMIN du fichier de type `data_type` que le process `key` lit : la sortie de son
        amont (`upstream_output`), sinon l'entrée PRINCIPALE de la card (le champ que l'app
        déclare à l'aperçu, `PreviewRegistry.register(file_field=…)`, sans en juger le type : une
        vidéo porte le son qu'un process transcrit). '' sans fichier. Le geste de toute
        lecture de « ce que ce process a écouté » : la glu du transcriber, et les mesures sans
        référence de sa sortie (2026-10-22)."""
        from django.conf import settings
        from wama.common.utils.preview_registry import PreviewRegistry
        upstream = self.upstream_output(item, key, data_type, model_key)
        if upstream:
            return os.path.join(settings.MEDIA_ROOT, upstream)
        field = (PreviewRegistry.get(self.app) or {}).get('file_field') or ''
        value = getattr(item, field, None) if field else None
        return value.path if value and getattr(value, 'name', '') else ''

    def backfill_prior_runs(self, item) -> dict:
        """BACKFILL (le mot de `backfill_platform_refs` : poser après coup ce qu'un enregistrement
        antérieur n'a pas reçu). Le même pour toutes les apps à pipeline — rien n'y dépend de
        l'app ; « adoption », son premier nom (13/10), se lisait comme l'adoption d'une BRIQUE par
        une app et a fait croire le transcriber à part (relevé par Fabien, 2026-10-14).

        Un élément RÉUSSI avant que son app ne déclare ce pipeline n'a aucune ligne : rien n'y
        était « à jour », donc toute relance rejouait TOUT — le ▶ « Locuteurs » d'une transcription
        du 28/09 (pipeline du 03/10) réécoutait l'audio entier (constat de Fabien, 2026-10-13 ;
        65 transcriptions seulement avaient une ligne).

        Son succès PROUVE que ses process `required` ont rendu (règle 4.4 : l'échec d'un required
        fait échouer la card) : ils reçoivent une ligne `SUCCESS`, photo des réglages d'aujourd'hui
        — ceux qui ont produit le résultat, l'élément n'ayant pas été relancé depuis. Un `optional`
        n'en reçoit pas : on ne sait pas s'il a tourné, il reste à jouer. Rien pour un élément qui
        a déjà une ligne de ce pipeline, ou qui n'est pas réussi. Rend `{clé: ligne}` posées.

        Appelé par `preload` (toute page de file, toute card relue) et par `begin_processing`
        (tout lancement, avant le passage à RUNNING) : un ▶ venu de l'assistant ou d'une action
        programmée, sur une card qu'aucune page n'a relue, rejouait sinon tout (mesuré le
        2026-10-14 : 372 transcriptions réussies encore sans ligne). La photo est celle de la
        première de ces lectures, donc AVANT qu'un réglage n'y change."""
        if getattr(item, 'status', None) != JOB_SUCCESS or self.rows(item):
            return {}
        model_key = self.requested_model(item)
        backfilled = {}
        for spec in self.applicable(item, model_key):
            if spec.degree != REQUIRED:
                continue
            output_ref = next((getattr(item, f).name for f in spec.outputs
                               if getattr(getattr(item, f, None), 'name', '')), '')
            row = process_runs.safely(
                process_runs.succeed, item, spec.key, process_key=self.function_key(spec),
                output_ref=output_ref, model_key=model_key or '',
                output_summary={'backfilled': True},
                settings_snapshot=self.snapshot(spec, item, backfilled))
            if row is not None:
                backfilled[spec.key] = row
        return backfilled

    # ── Péremption, sélection, état ─────────────────────────────────────────────────────────
    def refresh(self, item) -> set:
        """Passe `STALE` les lignes en succès qui ne sont plus à jour ; rend leurs clés.

        Ne regarde que les process qui ONT une ligne : seul un résultat rendu peut être périmé,
        et un amont jamais lancé (un process qui n'avait pas lieu) ne périme personne. Une ligne
        qui ne compte plus (`still_counts` : `optional` désactivé, process qui n'a plus lieu) est
        ignorée : ni périmée, ni cause de péremption (règle 4.4) — c'est son ABSENCE de la photo
        de l'aval qui périme celui-ci, une fois, s'il avait été rendu avec elle.
        """
        rows = self._live_rows(item)
        if not rows:
            return set()
        known = [spec for spec in self.specs if spec.key in rows]
        stale = process_runs.stale_nodes(
            states={spec.key: rows[spec.key].status for spec in known},
            depends_on={spec.key: [d for d in self.read_upstreams(spec, item) if d in rows]
                        for spec in known},
            snapshots={spec.key: rows[spec.key].settings_snapshot or {} for spec in known},
            current=self._current_photos(item, known, rows))
        if stale:
            process_runs.mark_stale(item, stale)
            for key in stale:             # les lignes déjà lues (préchargées) disent la même chose
                rows[key].status = JOB_STALE
        return stale

    def _current_photos(self, item, known, rows) -> dict:
        """La photo d'AUJOURD'HUI de chaque ligne connue — celle qu'elle prendrait maintenant
        (`snapshot`), plus, pour une ligne qui vaut pour un process détaché d'elle
        (`_held_within`), les réglages que celui-ci surveille : elle les a photographiés quand
        elle faisait son travail, leur changement la périme."""
        current = {spec.key: self.snapshot(spec, item, rows) for spec in known}
        for split, host in self._held(rows).items():
            if host in current:
                current[host] = {**current[host], **process_runs.snapshot(
                    item, self._split_settings(self._by_key[split]))}
        return current

    def _split_settings(self, spec: ProcessSpec) -> tuple:
        """Les réglages qui décident du travail d'un process détaché : ceux qu'il surveille, et
        son interrupteur — que son aval d'origine surveillait quand il faisait ce travail."""
        return tuple(dict.fromkeys(self.watched_of(spec) + ((spec.toggle,) if spec.toggle else ())))

    def _held_within(self, spec: ProcessSpec, rows: dict):
        """La ligne qui VAUT pour le process `spec` détaché d'elle (`ProcessSpec.split_from`) :
        celle de son aval d'origine, rendue avant le détachement — sa photo porte tous les
        réglages que `spec` surveille. None : rien de détaché, `spec` a sa propre ligne, ou la
        ligne de l'aval a été rendue depuis le détachement."""
        if not spec.split_from or spec.key in rows:
            return None
        row = rows.get(spec.split_from)
        settings = self._split_settings(spec)
        photo = (row.settings_snapshot or {}) if row is not None else {}
        if not settings or any(name not in photo for name in settings):
            return None
        return row

    def _held(self, rows: dict) -> dict:
        """`{process détaché: process dont la ligne vaut pour lui}` (`_held_within`)."""
        return {spec.key: spec.split_from for spec in self.specs
                if self._held_within(spec, rows) is not None}

    def _live_rows(self, item) -> dict:
        """Les lignes qui COMPTENT encore (`still_counts`, au modèle que la card demande) — ce
        que lisent la péremption, l'état de la card et la photo d'un aval."""
        rows = self.rows(item)
        model_key = self.requested_model(item)
        return {key: row for key, row in rows.items()
                if self.still_counts(self._by_key[key], item, model_key)}

    def up_to_date(self, item) -> dict:
        """`{clé: ligne}` des process en succès après `refresh` — ceux que rien n'a périmés."""
        self.refresh(item)
        return {key: row for key, row in self.rows(item).items() if row.status == JOB_SUCCESS}

    def resumes_from(self, item, key: str, model_key=None) -> bool:
        """Ce lancement REPREND-il le résultat du process `key` sans le rejouer ? Vrai quand le
        process a lieu pour cet élément et que `steps_to_run` ne le retient pas. C'est la
        question qu'une app pose avant un tirage « auto » : un rendu relancé seul doit employer
        le modèle qui a produit ce qu'il reprend."""
        if key not in {spec.key for spec in self.applicable(item, model_key)}:
            return False
        return key not in {spec.key for spec in self.steps_to_run(item, model_key)}

    def steps_to_run(self, item, model_key=None, only: str | None = None) -> list:
        """Les process qu'un lancement joue, dans l'ordre : ceux qui ne sont pas à jour, et tout
        leur aval. Tous à jour → tous (l'utilisateur redemande un résultat).

        `only` (P5, ▶ par process) : CE process, qu'il soit à jour ou non, précédé des seuls
        amonts qui ne le sont plus (de proche en proche) — jamais son aval, qui se périmera de
        lui-même à la relecture (sa sortie d'amont aura changé). Un process inconnu ou sans objet
        pour cet élément est refusé en le disant.

        ⚠ « Tous à jour » se lit sur les ÉTATS, avant de regarder les fichiers : le lanceur a
        déjà retiré l'ancienne sortie de la card quand la tâche pose cette question (`reset` de
        `begin_processing`) — la lire d'abord ferait d'une relance complète une reprise du
        dernier process. Une sortie disparue ne compte que pour ce qu'on s'apprête à REPRENDRE.
        """
        steps = self.applicable(item, model_key)
        fresh = self.up_to_date(item)
        # Un process DÉTACHÉ dont la ligne d'origine vaut encore (`_held_within`, et elle est à
        # jour : ses réglages n'ont pas changé) est REPRIS comme un process à jour — sans ligne.
        held = {key for key, host in self._held(self._live_rows(item)).items() if host in fresh}
        if only is not None:
            by_key = {spec.key: spec for spec in steps}
            if only not in by_key:
                raise ValueError(f"process « {only} » : inconnu, ou sans objet pour cet élément")
            needed, pending = {only}, list(self.read_upstreams(by_key[only], item))
            while pending:
                key = pending.pop()
                if key in needed or key not in by_key:
                    continue
                if (key in fresh and not _output_lost(fresh[key])) or key in held:
                    continue                      # un amont encore valable est REPRIS
                needed.add(key)
                pending.extend(self.read_upstreams(by_key[key], item))
            return [spec for spec in steps if spec.key in needed]
        if all(spec.key in fresh or spec.key in held for spec in steps):
            return steps
        todo = {spec.key for spec in steps if spec.key not in held
                and (spec.key not in fresh or _output_lost(fresh[spec.key]))}
        grown = True
        while grown:
            grown = False
            for spec in steps:
                if spec.key not in todo and any(d in todo for d in self.read_upstreams(spec, item)):
                    todo.add(spec.key)
                    grown = True
        return [spec for spec in steps if spec.key in todo]

    def reset_outputs(self, item, keys) -> list:
        """Remise à zéro AVANT un lancement borné : les sorties des seuls process `keys` sont
        remplacées (`safe_delete_file`, la règle d'une relance), les autres restent — relancer la
        partition seule ne doit pas emporter l'audio. Rend les champs vidés ; l'appelant SAUVE."""
        from wama.common.utils.queue_duplication import safe_delete_file
        cleared = []
        for key in keys:
            for field in self.spec(key).outputs:
                safe_delete_file(item, field)
                setattr(item, field, None)
                cleared.append(field)
        return cleared

    def release_absent(self, item) -> list:
        """Relance COMPLÈTE de la card (son ▶, pas celui d'un process) : un process qui ne compte
        plus pour l'élément (`still_counts` — désactivé, ou que l'élément ne demande plus) perd sa
        ligne et sa sortie. La sortie est LIBÉRÉE (`release_card_file` : elle reste sur le disque,
        l'utilisateur est prévenu, c'est lui qui la supprime), jamais effacée : une partition
        corrigée à la main ne disparaît pas sans retour. Rend les champs vidés.

        Décision de Fabien (2026-10-22) : *« on devrait retirer l'audio pré-traité si on désactive
        le pré-traitement dans les réglages et que l'on relance la tâche complète »* — et seulement
        alors : un ▶ borné (« le prétraitement seul ») garde tout, l'audio produit sert ensuite aux
        étapes qu'on relance. Jusque-là le fichier restait sur la card, montré par l'aperçu alors
        que la page de correction ne le proposait plus."""
        from wama.common.utils.queue_duplication import release_card_file
        rows = self.rows(item)
        model_key = self.requested_model(item)
        gone = [spec for spec in self.specs
                if spec.key in rows and not self.still_counts(spec, item, model_key)]
        cleared = []
        for spec in gone:
            for field in spec.outputs:
                if getattr(getattr(item, field, None), 'name', ''):
                    release_card_file(item, field)
                    setattr(item, field, None)
                    cleared.append(field)
        if cleared:
            item.save(update_fields=cleared)
        if gone:
            process_runs.lines(item).filter(instance_key='',
                                            node_id__in=[s.key for s in gone]).delete()
        return cleared

    def card_state(self, item) -> str:
        """État de la card DÉDUIT des lignes qui comptent encore (`still_counts`, règle 4.4) — lu,
        jamais écrit dans l'élément."""
        self.refresh(item)
        rows = self._live_rows(item)
        return process_runs.aggregate(
            (rows[spec.key].status, spec.degree) for spec in self.specs if spec.key in rows)

    # ── Ce que la CARD affiche (P5) ─────────────────────────────────────────────────────────
    def shown_state(self, item, rows: dict | None = None) -> str:
        """L'état que la card MONTRE — l'adaptateur unique de `§10.6` 5.1 (le bouton de cycle,
        le point d'état et la bordure le lisent, jamais `item.status` en dur).

        L'élément reste la vérité de ce qui est EN VOL : `RUNNING` / `AWAITING_RESOURCES` sont
        posés par le lanceur avant qu'aucune ligne n'existe. Hors de ces deux états, les lignes
        disent plus que lui (un rendu périmé sous un élément « réussi ») : on montre l'état
        déduit dès qu'un process a tourné. Sans ligne, l'élément seul."""
        status = getattr(item, 'status', None)
        if status in (JOB_RUNNING, JOB_AWAITING_RESOURCES):
            return status
        if rows is None:
            self.refresh(item)
            rows = self._live_rows(item)
        if not rows:
            return status or JOB_PENDING
        return process_runs.aggregate(
            (rows[spec.key].status, spec.degree) for spec in self.specs if spec.key in rows)

    def card_rows(self, item, model_key=None) -> list:
        """Une ligne d'affichage par process de la card, dans l'ordre du graphe : ceux qui ont
        tourné, plus ceux qui ont lieu pour le modèle donné (`model_key` : le réglage quand il
        est désigné ; sous « auto », None — on ne devine pas le tirage, on montre ce qui a
        tourné). `{key, label, degree, status, duration_s, model_key, output_label, error}`, plus
        la colonne de chacun dans le graphe (`_columns`) — d'où les branches de la bande."""
        self.refresh(item)
        rows = self.rows(item)
        held = self._held(self._live_rows(item))
        out = []
        for spec in self.ordered():
            row = rows.get(spec.key)
            # Une ligne jamais jouée : montrée si le process a lieu pour ce modèle et PEUT avoir
            # lieu ici (`can_run`). L'interrupteur, lui, n'en retire pas : un optionnel désactivé
            # reste visible, en case à cocher.
            if row is None and not (model_key and self.can_run(spec)
                                    and self.applies(spec, item, model_key)):
                continue
            # Une ligne d'un process qui n'a PLUS lieu pour ce modèle (nivellement décoché) ne se
            # montre plus : elle ne pèse plus sur la card (`still_counts`), la bande le dit pareil.
            if row is not None and model_key and not self.applies(spec, item, model_key):
                continue
            summary = (row.output_summary or {}) if row is not None else {}
            host = rows.get(held.get(spec.key, ''))
            if row is None and host is not None:
                # Un process DÉTACHÉ, fait dans la ligne d'origine (`_held_within`) : son état est
                # celui de cette ligne, et la bande le dit.
                summary = {'label': f"fait dans « {self._by_key[host.node_id].label or host.node_id} »"}
            out.append({
                'key': spec.key,
                'label': spec.label or spec.key,
                'degree': spec.degree,
                'status': (row.status if row is not None
                           else host.status if host is not None else JOB_PENDING),
                'duration_s': row.duration_s if row is not None else None,
                'model_key': row.model_key if row is not None else '',
                'output_label': summary.get('label') or '',
                'error': (row.error_message or '') if row is not None else '',
                # Les réglages que CE process surveille : ce que son ⚙ montre (P5, 5.1).
                'watched': list(self.watched_of(spec)),
                # L'interrupteur d'un `optional` (case à cocher de la bande) et son état.
                'toggle': spec.toggle,
                'enabled': self.enabled(spec, item),
                # Les mesures sans référence de sa sortie (`ProcessSpec.checks`, 2026-10-22).
                'checks': list(summary.get('checks') or []) if row is not None else [],
            })
        return self._columns(item, out)

    def _columns(self, item, out: list) -> list:
        """Range les lignes de la bande en COLONNES, comme le studio dispose le graphe (une colonne
        par profondeur, `node_depths`) : les process d'une même profondeur s'empilent, et une
        BRANCHE (deux process qui lisent le même amont, ou deux racines) se voit à côté de sa
        sœur au lieu de s'aligner à la suite de la chaîne (2026-10-26, demande de Fabien : « la
        dérivation comme c'est natif dans le studio »). Aucune déclaration de plus : le graphe
        est celui des `depends_on` que l'élément LIT (`read_upstreams`).

        Chaque ligne gagne `column` (rang parmi les colonnes montrées, sans trou), `after` (les
        libellés des amonts MONTRÉS les plus proches, à travers ceux qui ne le sont pas) et
        `branch_end` (ne nourrit aucun process montré alors qu'une colonne suit : une sortie de
        côté). Ordre rendu : par colonne, puis dans l'ordre du graphe — un ordre topologique, la
        profondeur croissant strictement le long d'un lien."""
        from wama.common.manifests.builtin.pipeline import node_depths
        upstreams = {spec.key: self.read_upstreams(spec, item) for spec in self.specs}
        depth = node_depths(list(upstreams), [{'from': up, 'to': key}
                                              for key, ups in upstreams.items() for up in ups])
        shown = {row['key']: row['label'] for row in out}
        rank = {d: i for i, d in enumerate(sorted({depth[key] for key in shown}))}

        def nearest(key, seen=frozenset()):
            found = []
            for up in upstreams.get(key, ()):
                if up not in seen:
                    found += [up] if up in shown else nearest(up, seen | {up})
            return found

        fed = set()
        for row in out:
            ups = list(dict.fromkeys(nearest(row['key'])))
            fed.update(ups)
            row['column'] = rank[depth[row['key']]]
            row['after'] = [shown[up] for up in ups]
        last = max((row['column'] for row in out), default=0)
        for row in out:
            row['branch_end'] = row['key'] not in fed and row['column'] < last
        order = {row['key']: index for index, row in enumerate(out)}
        return sorted(out, key=lambda row: (row['column'], order[row['key']]))


#: Pipelines déclarés, par app — inscrits depuis le `function_specs.py` de chaque app. Lu par
#: la garde générique (`tests_process_pipeline.EveryAppPipelineTest`) : ce qu'une app déclare
#: ici est tenu pour toutes, sans un test par app.
APP_PIPELINES: dict = {}


def register_app_pipeline(app: str, specs, *, label: str, description: str = '',
                          source_ref: str = '', model_of=None) -> AppPipeline:
    """Déclare le pipeline d'une app et l'inscrit comme source de manifeste `pipeline` sous la
    clé de l'app (idempotent : une seconde déclaration remplace la première).

    `model_of` : `callable(élément) -> clé de modèle` — « le modèle que la card demande », dit
    UNE fois (`AppPipeline.requested_model`). Chaque app le redisait à la bande des process, à
    la vue de progression et au ▶ d'un process (2026-10-04)."""
    from wama.common.manifests.builtin.pipeline import register_pipeline_source
    pipeline = AppPipeline(app, specs, label=label, description=description,
                           source_ref=source_ref, model_of=model_of)
    APP_PIPELINES[app] = pipeline
    register_pipeline_source(app, pipeline.manifest)
    return pipeline


_declarations_loaded = False


def _load_declarations() -> None:
    """Importe les modules déclarants des apps installées (`function_specs` / `functions`) —
    c'est LEUR import qui inscrit un pipeline. Une fois par processus.

    ⚠ Défaut vécu le 2026-10-03, 500 sur la page du composer EN SERVICE : dans un processus web
    qui n'a encore importé aucun `function_specs` (gunicorn frais), `APP_PIPELINES` est vide et
    « pas de pipeline » était lu comme une réponse. Le serveur de dev et les tests l'importaient
    par d'autres chemins — le défaut ne se voyait que sur le live."""
    global _declarations_loaded
    if _declarations_loaded:
        return
    _declarations_loaded = True
    try:
        from wama.common.catalog import function_catalog
        function_catalog.load_all()
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "[process_pipeline] déclarations des apps non chargées", exc_info=True)


def process_of_function(function_key: str):
    """`(pipeline, ProcessSpec)` de l'ÉTAPE de card qu'est la fonction `function_key` — le process
    d'un pipeline d'app que le catalogue expose comme nœud `function:<clé>` —, ou `(None, None)`
    (fonction pure, passe du Lab, fonction d'une app à un seul process).

    Une lecture, deux usages au Studio (ROUTE §10.6 3.3bis, D2, 2026-10-18) : le nœud montre les
    réglages de la ⚙ de CETTE étape (`watched_of`), et l'exécuteur la lance comme le ▶ de l'étape
    sur la card. Avant, le nœud montrait l'identifiant que réclame la tâche et lançait la tâche
    ENTIÈRE de l'app."""
    _load_declarations()
    for pipeline in APP_PIPELINES.values():
        for spec in pipeline.specs:
            if pipeline.function_key(spec) == function_key:
                return pipeline, spec
    return None, None


def pipeline_of(item) -> AppPipeline | None:
    """Le pipeline déclaré par l'app de cet élément, ou None (app à un seul process). Charge
    les déclarations des apps si ce processus ne l'a pas encore fait."""
    try:
        label = item._meta.app_label
    except AttributeError:
        return None
    return app_pipeline(label)


def app_pipeline(app: str) -> AppPipeline | None:
    """Le pipeline déclaré par l'app `app`, ou None — même lecture que `pipeline_of`, quand on
    n'a qu'un NOM d'app (la page de base, qui range les réglages par process, 2026-10-26). Lire
    `APP_PIPELINES` sans elle, c'est le défaut du 2026-10-03 (`_load_declarations`)."""
    if app not in APP_PIPELINES:
        _load_declarations()
    return APP_PIPELINES.get(app)


#: Valeur par défaut de `model_key` : le modèle DÉCLARÉ par le pipeline (`requested_model`).
DECLARED = object()


def card_view(item, model_key=DECLARED, preloaded: bool = False):
    """Ce que la card et la vue de progression montrent du PIPELINE d'un élément (`§10.6` 5.1) :
    `(lignes de process, état montré, libellé de cet état)` — par l'adaptateur unique
    (`AppPipeline.shown_state`), jamais `status` en dur. `model_key` : le réglage quand il est
    désigné ; sous « auto » None (on montre ce qui a tourné). `None` si l'app n'a pas de
    pipeline : la card lit alors `status`, la bande ne se rend pas.

    Les lignes sont lues UNE fois : ici pour un élément seul, ou par la page pour toutes ses
    cards (`preload(items)` puis `preloaded=True`) — jamais relues à chaque question."""
    pipeline = pipeline_of(item)
    if pipeline is None:
        return None
    if model_key is DECLARED:
        model_key = pipeline.requested_model(item)
    from wama.common.models import PROCESS_STATUS_CHOICES
    if not preloaded:
        preload([item])
    try:
        rows = pipeline.card_rows(item, model_key)
        state = pipeline.shown_state(item)
    finally:
        if not preloaded:
            # Les lignes lues pour CETTE question ne restent pas sur l'élément : une instance
            # gardée par l'appelant (un test, une vue qui écrit ensuite) relirait du périmé.
            release(item)
    return rows, state, dict(PROCESS_STATUS_CHOICES).get(state, state)


def decorate(item, model_key=DECLARED, preloaded: bool = False):
    """Pose `processes`, `shown_state`, `shown_state_label` sur l'élément — ce que lisent les
    gabarits (`_card_processes.html`, `_cycle_button.html` via `elem.shown_state|default:
    elem.status`). Point d'attache des apps GÉNÉRÉES (`views_gen._decorer`) ; une app réelle
    l'appelle de sa propre décoration. Sans pipeline : ne pose rien, rend None."""
    view = card_view(item, model_key, preloaded=preloaded)
    if view is None:
        return None
    item.processes, item.shown_state, item.shown_state_label = view
    return view


def decorate_cards(items, each=None) -> list:
    """Les cards d'une PAGE : leurs lignes d'exécution lues en UNE requête (`preload`), puis
    chacune décorée — par `each(item, preloaded=True)` (la décoration de l'app : chips +
    process) ou, sans elle, par `decorate`. Rend la liste des éléments."""
    items = [item for item in items if item is not None]
    preload(items)
    for item in items:
        if each is not None:
            each(item, preloaded=True)
        else:
            decorate(item, preloaded=True)
    return items
