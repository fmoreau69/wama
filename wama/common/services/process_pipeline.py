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
    processes={clé: glu})`), qui joue les process retenus DANS une seule tâche Celery ;
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

from wama.common.models import JOB_AWAITING_RESOURCES, JOB_PENDING, JOB_RUNNING, JOB_SUCCESS
from wama.common.services import process_runs
from wama.common.services.process_runs import OPTIONAL, REQUIRED

#: Clé de la photo qui porte l'empreinte des sorties d'amont (« entrée remplacée », point 4.3).
#: Le `@` l'écarte de tout nom de réglage.
UPSTREAM_KEY = '@upstream'


@dataclass(frozen=True)
class ProcessSpec:
    """Un process d'un pipeline d'app — les champs de `pass_tracking.Pass` qui ne sont pas
    propres au cam_analyzer, plus le degré de liberté du point 3.2.

      key         identifiant du process dans SON pipeline = le nœud de sa ligne d'exécution ;
      label       libellé COURT pour la card (« Partition », « Rendu ») — le nom long est celui
                  du `FunctionSpec` au catalogue ; vide = la clé ;
      depends_on  amonts : ordre de lancement, et propagation de la péremption ;
      watched     réglages de l'ÉLÉMENT dont le changement rend le process périmé ;
      degree      `required` (son échec fait échouer la card) | `optional` ;
      function    clé du catalogue de fonctions quand elle diffère de `<app>.<key>` ;
      gpu         le process charge le GPU (dit à l'utilisateur, jamais une garde) ;
      share       part de la barre de progression de la card (poids relatif) ;
      applies     `(item, model_key) -> bool` : le process a-t-il lieu pour CET élément ? Absent =
                  toujours. C'est ce qui laisse un pipeline à deux process n'en jouer qu'un pour
                  un modèle qui ne sait pas faire le premier ;
      outputs     champs FICHIER de l'élément que le process ÉCRIT (`planned_score`,
                  `audio_output`) — ce qu'un lancement borné à ce process remplace, et rien
                  d'autre (`reset_outputs`). Déclaré : le lanceur ne lit pas la glu.
    """
    key: str
    label: str = ''
    depends_on: tuple = ()
    watched: tuple = ()
    degree: str = REQUIRED
    function: str = ''
    gpu: bool = False
    share: int = 1
    applies: Callable = None
    outputs: tuple = ()


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


def _output_lost(row) -> bool:
    """La ligne annonce une sortie que le disque ne porte plus."""
    if not row.output_ref:
        return False
    from django.conf import settings
    return not os.path.exists(os.path.join(settings.MEDIA_ROOT, row.output_ref))


class AppPipeline:
    """Le pipeline déclaré d'une app : ses `ProcessSpec`, et ce qui s'en dérive."""

    def __init__(self, app: str, specs, *, label: str, description: str = '',
                 source_ref: str = ''):
        self.app = app
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
        self.ordered()                      # un cycle se refuse à la DÉCLARATION, pas au lancement

    # ── Déclaration ─────────────────────────────────────────────────────────────────────────
    def spec(self, key: str) -> ProcessSpec:
        return self._by_key[key]

    def function_key(self, spec: ProcessSpec) -> str:
        """Clé `FUNCTION_CATALOG` du process — le nœud `function` qu'il devient au manifeste."""
        return spec.function or f'{self.app}.{spec.key}'

    def graph(self) -> dict:
        """Le registre sous la forme CANVAS du studio (`{nodes, links}`) — même forme que
        `pass_tracking.pipeline_graph` : un process = un nœud `function`, une dépendance = un
        lien. Les `params` portent ce qui est propre au process et absent du `FunctionSpec`."""
        from wama.common.manifests.builtin.pipeline import FUNCTION_NODE_PREFIX
        nodes = [{'id': spec.key, 'app': f'{FUNCTION_NODE_PREFIX}{self.function_key(spec)}',
                  'params': {'degree': spec.degree, 'gpu': spec.gpu,
                             'watched': list(spec.watched)}}
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
        """`{clé de process: ligne}` pour les process de CE pipeline qui ont déjà tourné."""
        return {row.node_id: row
                for row in process_runs.lines(item).filter(instance_key='',
                                                           node_id__in=list(self._by_key))}

    def snapshot(self, spec: ProcessSpec, item, rows: dict | None = None) -> dict:
        """Photo de ce que le process SURVEILLE aujourd'hui : ses réglages, et l'empreinte de la
        sortie de chacun de ses amonts qui a tourné (un amont sans ligne n'y figure pas)."""
        rows = self.rows(item) if rows is None else rows
        taken = process_runs.snapshot(item, spec.watched)
        upstream = {key: output_fingerprint(rows[key].output_ref)
                    for key in spec.depends_on if key in rows}
        if upstream:
            taken[UPSTREAM_KEY] = upstream
        return taken

    def applicable(self, item, model_key=None) -> list:
        """Les process qui ont lieu pour cet élément, dans l'ordre de lancement."""
        return [spec for spec in self.ordered()
                if spec.applies is None or spec.applies(item, model_key)]

    # ── Péremption, sélection, état ─────────────────────────────────────────────────────────
    def refresh(self, item) -> set:
        """Passe `STALE` les lignes en succès qui ne sont plus à jour ; rend leurs clés.

        Ne regarde que les process qui ONT une ligne : seul un résultat rendu peut être périmé,
        et un amont jamais lancé (un process qui n'avait pas lieu) ne périme personne.
        """
        rows = self.rows(item)
        if not rows:
            return set()
        known = [spec for spec in self.specs if spec.key in rows]
        stale = process_runs.stale_nodes(
            states={spec.key: rows[spec.key].status for spec in known},
            depends_on={spec.key: [d for d in spec.depends_on if d in rows] for spec in known},
            snapshots={spec.key: rows[spec.key].settings_snapshot or {} for spec in known},
            current={spec.key: self.snapshot(spec, item, rows) for spec in known})
        process_runs.mark_stale(item, stale)
        return stale

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
        if only is not None:
            by_key = {spec.key: spec for spec in steps}
            if only not in by_key:
                raise ValueError(f"process « {only} » : inconnu, ou sans objet pour cet élément")
            needed, pending = {only}, list(by_key[only].depends_on)
            while pending:
                key = pending.pop()
                if key in needed or key not in by_key:
                    continue
                if key in fresh and not _output_lost(fresh[key]):
                    continue                      # un amont encore valable est REPRIS
                needed.add(key)
                pending.extend(by_key[key].depends_on)
            return [spec for spec in steps if spec.key in needed]
        if all(spec.key in fresh for spec in steps):
            return steps
        todo = {spec.key for spec in steps
                if spec.key not in fresh or _output_lost(fresh[spec.key])}
        grown = True
        while grown:
            grown = False
            for spec in steps:
                if spec.key not in todo and any(d in todo for d in spec.depends_on):
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

    def card_state(self, item) -> str:
        """État de la card DÉDUIT de ses process (règle 4.4) — lu, jamais écrit dans l'élément."""
        self.refresh(item)
        rows = self.rows(item)
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
            rows = self.rows(item)
        if not rows:
            return status or JOB_PENDING
        return process_runs.aggregate(
            (rows[spec.key].status, spec.degree) for spec in self.specs if spec.key in rows)

    def card_rows(self, item, model_key=None) -> list:
        """Une ligne d'affichage par process de la card, dans l'ordre du graphe : ceux qui ont
        tourné, plus ceux qui ont lieu pour le modèle donné (`model_key` : le réglage quand il
        est désigné ; sous « auto », None — on ne devine pas le tirage, on montre ce qui a
        tourné). `{key, label, degree, status, duration_s, model_key, output_label, error}`."""
        self.refresh(item)
        rows = self.rows(item)
        out = []
        for spec in self.ordered():
            row = rows.get(spec.key)
            if row is None and not (model_key and (spec.applies is None
                                                  or spec.applies(item, model_key))):
                continue
            summary = (row.output_summary or {}) if row is not None else {}
            out.append({
                'key': spec.key,
                'label': spec.label or spec.key,
                'degree': spec.degree,
                'status': row.status if row is not None else JOB_PENDING,
                'duration_s': row.duration_s if row is not None else None,
                'model_key': row.model_key if row is not None else '',
                'output_label': summary.get('label') or '',
                'error': (row.error_message or '') if row is not None else '',
            })
        return out


#: Pipelines déclarés, par app — inscrits depuis le `function_specs.py` de chaque app. Lu par
#: la garde générique (`tests_process_pipeline.EveryAppPipelineTest`) : ce qu'une app déclare
#: ici est tenu pour toutes, sans un test par app.
APP_PIPELINES: dict = {}


def register_app_pipeline(app: str, specs, *, label: str, description: str = '',
                          source_ref: str = '') -> AppPipeline:
    """Déclare le pipeline d'une app et l'inscrit comme source de manifeste `pipeline` sous la
    clé de l'app (idempotent : une seconde déclaration remplace la première)."""
    from wama.common.manifests.builtin.pipeline import register_pipeline_source
    pipeline = AppPipeline(app, specs, label=label, description=description,
                           source_ref=source_ref)
    APP_PIPELINES[app] = pipeline
    register_pipeline_source(app, pipeline.manifest)
    return pipeline

