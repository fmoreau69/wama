"""
Gabarit `models.py` (palier A5, route §10.3) — squelette du SPINE + champs dérivés des params.

Cadrage A0 : 9/10 apps partagent le spine `Item(ProcessingTimeMixin, ScopedVisibility)` +
`Batch(BatchMixin, ScopedVisibility)` + table de liaison, réglages en champs individuels
(le converter est le déviant double — options JSON + batch FK-direct — et n'est jamais
rendu : CREATE-ONLY). Le gabarit rend :
  - le spine (user, fichier d'entrée, ingest, création, task_id/status/progress/error_message,
    Meta, __str__, propriété filename) depuis `processing.model_spec` (MESURÉ par
    introspection à l'extraction ; DÉCLARÉ pour une app neuve) ;
  - les champs d'OPTION depuis la facette `params` — l'INVERSE de `derive_from_model`
    (`param_schema._django_field_to_param`) : select→CharField+choices, toggle→BooleanField,
    number/range→Integer/FloatField, textarea→TextField, sinon CharField ;
  - un TROU marqué pour les champs de RÉSULTAT et la logique (properties, méthodes) —
    marche B, comme les corps de `tasks_gen`.

Un models.py EXISTANT est de la glu réelle avec des MIGRATIONS appliquées : jamais comparé,
jamais régénéré (contrat CREATE-ONLY de `_project_tasks`). Le juge du rendu = compilation +
couverture de champs vs le modèle réel (pilote transcriber, spine conforme) ; le juge
complet = pilote B.
"""
from __future__ import annotations

from pathlib import Path

# Libellés canoniques du vocabulaire de statuts (contrat F5) — une app neuve part de là.
# ⚠ Ils ne s'écrivent plus ICI : ils VIENNENT du vocabulaire commun (`common/models.py`),
# sinon chaque app générée naît avec un vocabulaire à elle. Mesuré le 2026-09-17 (marche P2,
# `ROUTE §10.6 4.2`) : cette table portait QUATRE états et ignorait `AWAITING_RESOURCES` — une
# app neuve ne pouvait donc pas afficher l'état que pose le gouverneur de ressources — et
# libellait `FAILURE` « Erreur » quand les 13 files du monde Médias affichent « Échec ».
# Import PARESSEUX : ce module est volontairement léger (`pathlib` seul) et la génération
# ne doit pas dépendre du cycle de chargement des apps Django.


def _status_labels() -> dict:
    from wama.common.models import JOB_STATUS_CHOICES
    return dict(JOB_STATUS_CHOICES)


# Champs posés par le spine : une entrée params homonyme serait un doublon, jamais rendue.
_SPINE_FIELDS = {'user', 'created_at', 'task_id', 'status', 'progress', 'error_message'}


def models_file_path(app_id: str) -> Path:
    import wama
    return Path(wama.__file__).parent / app_id / 'models.py'


def _champ_option(entry: dict) -> str:
    """Ligne de champ Django pour une entrée de schéma — inverse de `_django_field_to_param`."""
    nom = entry['name']
    t = entry.get('type')
    d = entry.get('default')
    choices = entry.get('choices') or None
    if choices:
        paires = [(c[0], str(c[1])) if isinstance(c, (list, tuple)) and len(c) >= 2
                  else (c, str(c)) for c in choices]
        longueur = max(32, max((len(str(v)) for v, _ in paires), default=0))
        rendu = ', '.join(f'({v!r}, {l!r})' for v, l in paires)
        defaut = d if d is not None else paires[0][0]
        return (f"{nom} = models.CharField(max_length={longueur}, "
                f"choices=[{rendu}], default={defaut!r})")
    if t == 'toggle':
        return f"{nom} = models.BooleanField(default={bool(d)})"
    if t == 'intent':
        # Le curseur rapide/qualité (`auto_model.intent_param`) : un entier 0-100, VIDE = suivre
        # le réglage de l'utilisateur puis équilibré (`quality_intent_of`). Forme majoritaire
        # du parc (converter, enhancer, composer, imager). Sans ce cas, il devenait un CharField.
        return f"{nom} = models.IntegerField(null=True, blank=True)"
    if t in ('number', 'range'):
        bornes = (d, entry.get('min'), entry.get('max'), entry.get('step'))
        if any(isinstance(x, float) for x in bornes):
            return f"{nom} = models.FloatField(default={float(d or 0)})"
        return f"{nom} = models.IntegerField(default={int(d or 0)})"
    if t == 'textarea':
        return f"{nom} = models.TextField(blank=True, default={str(d or '')!r})"
    return f"{nom} = models.CharField(max_length=255, blank=True, default={str(d or '')!r})"


def _declares_step_outputs(app_id: str) -> bool:
    """L'app déclare-t-elle un pipeline dont un process a des SORTIES fichier (`pipeline_decl`) ?"""
    from wama.common.manifests.codegen.pipeline_decl import declared_pipeline, process_specs
    pipeline, _ = declared_pipeline(app_id)
    steps = process_specs(pipeline) if pipeline else []
    return len(steps) >= 2 and any(s['outputs'] for s in steps)


def declared_result_fields(body: dict, input_field: str = '') -> list:
    """Champs de RÉSULTAT que le manifeste DÉCLARE déjà : `[(nom, 'text' | 'file')]`, dans
    l'ordre de déclaration, sans doublon ni champ d'entrée.

    Deux déclarations les nomment : `processing.backend_result` (`{field, kind}`) et le schéma
    de détail (`inspector.detail_spec.result_file` / `result_text`).
    ⚠ PAS l'aperçu (`inspector.preview.file_field`) : il désigne parfois une ENTRÉE — l'avatar
    déposé de l'avatarizer, l'image de référence de l'imager (mesuré par la contre-épreuve du
    2026-09-30). Il a son propre accesseur, `declared_preview_field`.

    ⚠ POURQUOI (mesuré le 2026-09-30 sur la 1ʳᵉ app créée de zéro, l'Editor) : le squelette
    laissait ces champs au « TROU DE GLU » alors que les trois déclarations étaient là — et
    `apps_gen`, lui, enregistrait l'aperçu sur `output_file` : l'app générée aurait cassé à la
    première card. *Une facette DÉCLARÉE et non projetée est un manque de GABARIT, pas un trou
    de glu* (leçon S2bis, `ROUTE §10.3`).
    """
    proc = body.get('processing') or {}
    insp = body.get('inspector') or {}
    spec = insp.get('detail_spec') or {}
    found = []

    def add(name, kind):
        # Un champ de résultat se GÉNÈRE quand la spec le NOMME (chaîne). Les formes calculées
        # (liste « premier non vide », constante, valeur selon la présence — `spec_value`) ne
        # désignent pas UN champ à créer : elles sont ignorées ici.
        if not isinstance(name, str):
            return
        if name and name != input_field and name not in (n for n, _ in found):
            found.append((name, kind))

    br = proc.get('backend_result') or {}
    if isinstance(br, dict) and br.get('field'):
        add(br['field'], 'text' if br.get('kind') == 'text' else 'file')
    add(spec.get('result_file'), 'file')
    add(spec.get('result_text'), 'text')
    return found


def declared_preview_field(body: dict) -> str:
    """Le champ fichier que l'aperçu déclare (`inspector.preview.file_field`), ou ''.
    `apps_gen` l'enregistre tel quel : il doit donc EXISTER sur le modèle généré."""
    return ((body.get('inspector') or {}).get('preview') or {}).get('file_field') or ''


def _is_django_model(path: str) -> bool:
    """La base désignée par `path` (`module.Classe`) est-elle un modèle Django ? Une base
    illisible est tenue pour un mixin pur : `models.Model` sera ajouté, jamais oublié."""
    try:
        from django.db import models as _m
        from django.utils.module_loading import import_string
        return issubclass(import_string(path), _m.Model)
    except Exception:
        return False


def _render_from_data(app_id: str, data: dict, ingest: dict = None,
                      item_name: str = '') -> str:
    """Rendu FIDÈLE depuis la facette `data` (marche S2) : chaque modèle avec ses champs tels
    que les migrations les sérialisent (`MigrationWriter.serialize` à l'extraction) — la
    fidélité de schéma est PAR CONSTRUCTION, verdict mesurable = makemigrations « No
    changes » sur la jumelle. La GLU (properties, __str__, méthodes) reste le trou déclaré
    des marches B — le SCHÉMA, lui, est complet.

    ⚠ `WAMA_INGEST` N'EST PLUS DANS CE TROU (2026-08-22, sur question posée en session a propos des
    « sous-chemins parallèles »). Il l'était par CONSTRUCTION : ce rendu part du sérialiseur
    de migrations, qui ne voit que des CHAMPS — or `WAMA_INGEST` est un attribut de classe
    sans champ correspondant, donc structurellement invisible ici. Le rendu frère (squelette
    A5, app créée de zéro) l'émettait, lui, depuis `processing.ingest` : **les deux chemins
    ne produisaient pas la même app**, et c'est exactement le piège soupçonné — le champ URL
    de la card vient d'un troisième endroit (les CAPACITÉS, côté gabarit), si bien qu'une app
    régénérée pouvait AFFICHER le champ sans rien derrière pour résoudre l'URL.
    Mesuré : les 10 apps déclarent `WAMA_INGEST` (enhancer deux fois) et toutes le perdaient.
    Le manifeste le porte (`processing.ingest`) — il n'y avait plus de raison de l'abandonner.
    Les `*_CHOICES`, eux, survivent : l'introspection les recopie inline dans `choices=`."""
    from ..builtin.app import _GEN_MARK
    mark = _GEN_MARK.format(app_id=app_id)
    imports = set()
    blocs = []
    for m in data.get('models') or []:
        corps = []
        mgr = m.get('manager')
        if mgr:
            mod, cls = mgr.rsplit('.', 1)
            imports.add(f'from {mod} import {cls}')
            corps.append('    # Manager par défaut du modèle SOURCE (les vues en dépendent — visible_to()…).')
            corps.append(f'    objects = {cls}()')
            corps.append('')
        # Déclaration d'ingest sur le modèle d'ITEM (source_ingest.ensure_local_input la lit
        # en tête de tâche). Invisible au sérialiseur de champs : elle vient du manifeste.
        if ingest and item_name and m.get('name') == item_name:
            corps.append('    # Ingest déclaratif commun (source_ingest.ensure_local_input).')
            corps.append(f'    WAMA_INGEST = {dict(ingest)!r}')
            corps.append('')
        for f in m.get('fields') or []:
            if f.get('_error'):
                corps.append(f"    # CHAMP INSÉRIALISABLE {f['name']} — trou documenté : {f['_error']}")
                continue
            path = f['class']
            if path.startswith('django.db.models'):
                cls_expr = 'models.' + path.rsplit('.', 1)[1]
            else:
                mod, cls = path.rsplit('.', 1)
                imports.add(f'from {mod} import {cls}')
                cls_expr = cls
            morceaux = [a['expr'] for a in f.get('args') or []]
            morceaux += [f"{k}={v['expr']}" for k, v in (f.get('kwargs') or {}).items()]
            for val in list(f.get('args') or []) + list((f.get('kwargs') or {}).values()):
                imports.update(val.get('imports') or [])
            corps.append(f"    {f['name']} = {cls_expr}({', '.join(morceaux)})")
        meta = m.get('meta') or {}
        if meta:
            corps.append('')
            corps.append('    class Meta:')
            if meta.get('ordering'):
                corps.append(f"        ordering = {meta['ordering']!r}")
            if meta.get('unique_together'):
                corps.append(f"        unique_together = {meta['unique_together']!r}")
        # Les BASES COMMUNES du modèle source (mixins du substrat, facette `data` depuis le
        # 2026-10-07) : leur comportement est partagé, pas de la glu. `models.Model` ferme la
        # liste quand aucune n'en dérive (un mixin pur : `BatchMixin`).
        bases = []
        for path in m.get('bases') or []:
            mod, cls = path.rsplit('.', 1)
            imports.add(f'from {mod} import {cls}')
            bases.append(cls)
        if not any(_is_django_model(p) for p in m.get('bases') or []):
            bases.append('models.Model')
        blocs.append(f"class {m['name']}({', '.join(bases)}):\n" + '\n'.join(corps or ['    pass']))

    tete = [
        '"""',
        f'{mark} — models.py GÉNÉRÉ depuis la facette `data` (marche S2, spine introspecté).',
        '',
        'SCHÉMA COMPLET par construction (sérialiseur des migrations à l\'extraction).',
        'La GLU reste le trou déclaré (marche B) : WAMA_INGEST, properties, __str__, méthodes.',
        'CREATE-ONLY après le premier makemigrations (même contrat que le gabarit A5).',
        '"""',
        'from django.db import models',
        *sorted(i for i in imports if i != 'from django.db import models'),
        '', '',
    ]
    return '\n'.join(tete) + '\n\n\n'.join(blocs) + '\n'


def render_models(manifest: dict) -> tuple:
    """(source, raison) — models.py. Depuis la facette `data` (spine INTROSPECTÉ, fidèle au
    schéma) quand elle est là — repli sur le squelette A5 (spine conventionnel + params)
    pour une app SANS existant (création de zéro). Jamais de fichier partiel."""
    from ..builtin.app import _GEN_MARK, _params_facet
    app_id = manifest.get('key')
    body = manifest.get('body') or {}
    data = body.get('data') or {}
    proc = body.get('processing') or {}
    if data.get('models'):
        # Le chemin INTROSPECTÉ reçoit désormais l'ingest et le nom du modèle d'item : sans
        # eux il rendait une app au schéma parfait mais SANS sa déclaration d'ingest, quand
        # le chemin frère (squelette) la posait — deux rendus, deux comportements.
        return _render_from_data(
            app_id, data,
            ingest=proc.get('ingest') or {},
            item_name=((proc.get('model_spec') or {}).get('item') or {}).get('name') or '',
        ), None
    spec = proc.get('model_spec') or {}
    item = spec.get('item') or {}
    if not item.get('name'):
        return None, 'processing.model_spec.item absent (DetailRegistry non renseigné ?)'

    facet = _params_facet(manifest)
    schemas = (facet or {}).get('schemas') or {}
    entrees = {e.get('name'): e for e in (schemas.get((facet or {}).get('primary')) or [])
               if isinstance(e, dict)}
    options = [n for n in (item.get('params_fields') or []) if n not in _SPINE_FIELDS]
    manquants = [n for n in options if n not in entrees]
    if manquants:
        return None, f"params_fields sans entrée de schéma : {', '.join(manquants)}"

    mark = _GEN_MARK.format(app_id=app_id)
    ingest = proc.get('ingest') or {}
    input_field = item.get('input_field') or ingest.get('target') or 'input_file'
    name_field = ingest.get('name_field')
    source_field = ingest.get('source')
    taken = set(_SPINE_FIELDS) | set(options) | {input_field, name_field, source_field}
    results = [(n, k) for n, k in declared_result_fields(body, input_field) if n not in taken]
    # Le fichier que l'aperçu désigne, s'il n'est ni l'entrée ni un résultat : une ENTRÉE de plus
    # (avatar, image de référence) — rangé côté entrées, jamais présumé résultat.
    preview_field = declared_preview_field(body)
    if preview_field and preview_field not in taken | {n for n, _ in results}:
        results.append((preview_field, 'input_file'))
    status_labels = _status_labels()
    statuses = proc.get('statuses') or list(status_labels)
    ordering = item.get('ordering') or ['-created_at']
    nom_item = item['name']

    l = [
        '"""',
        f"{mark} — models.py GÉNÉRÉ par write_back_app (facette processing, gabarit A5).",
        '',
        'SQUELETTE : spine conventionnel (cadrage A0) + champs d\'option dérivés de la facette',
        'params (inverse de derive_from_model). Les champs de RÉSULTAT et la logique métier',
        '(properties, méthodes) sont le TROU de la marche B. Après le premier makemigrations,',
        'ce fichier devient de la GLU RÉELLE : write_back ne le touchera plus jamais',
        '(CREATE-ONLY) — le faire évoluer À LA MAIN, migrations comprises.',
        '"""',
        'from django.contrib.auth.models import User',
        'from django.db import models',
        '',
        'from wama.common.models import (BatchMixin, ProcessingTimeMixin, ScopedManager,',
        '                                ScopedVisibility)',
        ('from wama.common.utils.media_paths import upload_to_user_input, upload_to_user_output'
         if any(k == 'file' for _n, k in results) or _declares_step_outputs(app_id)
         else 'from wama.common.utils.media_paths import upload_to_user_input'),
        '',
        '',
        f'class {nom_item}(ProcessingTimeMixin, ScopedVisibility):',
        '    # Partage F7 : lectures via visible_to()/visible_or_404, mutations par user.',
        '    objects = ScopedManager()',
        '',
    ]
    if ingest:
        l += ['    # Ingest déclaratif commun (source_ingest.ensure_local_input).',
              f'    WAMA_INGEST = {dict(ingest)!r}',
              '']
    rn = item.get('user_related_name') or f'{app_id}_items'
    l += [f"    user = models.ForeignKey(User, on_delete=models.CASCADE, "
          f"related_name='{rn}')",
          f"    {input_field} = models.FileField(upload_to=upload_to_user_input('{app_id}'), "
          f"blank=True, null=True)"]
    if name_field:
        l += [f"    {name_field} = models.CharField(max_length=255, blank=True, default='')"]
    if source_field:
        l += [f"    {source_field} = models.CharField(max_length=2000, blank=True, default='')"]
    l += ['    created_at = models.DateTimeField(auto_now_add=True)', '']
    if options:
        l += ["    # Options (facette params — l'inverse de derive_from_model)"]
        l += [f'    {_champ_option(entrees[n])}' for n in options]
        l += ['']
    l += ['    # État de traitement (spine F5)',
          "    task_id = models.CharField(max_length=255, blank=True, default='')",
          '    STATUS_CHOICES = [']
    l += [f"        ('{s}', '{status_labels.get(s, s.title())}')," for s in statuses]
    # Longueur DÉRIVÉE des états : la valeur figée à 16 datait d'avant `AWAITING_RESOURCES`
    # (18 caractères) — la 1ʳᵉ app créée de zéro (Editor, 2026-09-30) est tombée dessus au
    # `makemigrations` (fields.E009) ; relire les `choices` ne l'aurait jamais montré.
    status_len = max(20, max((len(s) for s in statuses), default=0))
    l += ["    ]",
          f"    status = models.CharField(max_length={status_len}, choices=STATUS_CHOICES, "
          "default='PENDING')",
          '    progress = models.IntegerField(default=0)',
          "    error_message = models.TextField(blank=True, default='')",
          '']
    if results:
        # Champs de RÉSULTAT DÉCLARÉS au manifeste (`declared_result_fields`) : projetés ici,
        # ils ne sont plus un trou. Les autres (non déclarés) restent la marche B.
        l += ['    # Résultat (déclaré au manifeste : backend_result / detail_spec / preview)']
        for nom, kind in results:
            if kind == 'text':
                l.append(f"    {nom} = models.TextField(blank=True, default='')")
            elif kind == 'input_file':
                l.append(f"    {nom} = models.FileField(upload_to=upload_to_user_input("
                         f"'{app_id}'), max_length=500, blank=True, null=True)")
            else:
                l.append(f"    {nom} = models.FileField(upload_to=upload_to_user_output("
                         f"'{app_id}'), max_length=500, blank=True, null=True)")
        l += ['']
    # App à PLUSIEURS process (2026-10-05, patron composer — décision n°11, ROUTE §10.6) : le
    # pipeline se lit par la CLÉ (`pipeline_decl`). Deux familles de colonnes en DÉRIVENT :
    #  • les SORTIES déclarées des process (`ProcessSpec.outputs` : `planned_score` au composer) —
    #    des FICHIERS de la card : retrait, rétention, révisions et l'empreinte « entrée remplacée »
    #    ne savent suivre qu'un fichier ;
    #  • les PORTS d'entrée fichier de l'app autres que l'entrée principale, nommés comme LUI
    #    (`reference_score` au composer : la card, l'outil et le nœud du studio disent le même
    #    nom — « un port = l'argument du même nom »). Réservé aux apps à pipeline : sur les dix
    #    apps réelles, un port n'est PAS une colonne du même nom (mesuré le 2026-10-05) ; la
    #    règle vaut pour les ports NOUVEAUX, pas en rattrapage.
    from wama.common.manifests.codegen.pipeline_decl import declared_pipeline, process_specs
    _pipeline, _ = declared_pipeline(app_id)
    _steps = process_specs(_pipeline) if _pipeline else []
    if len(_steps) >= 2:
        have = taken | {n for n, _k in results}
        step_outputs = [o for s in _steps for o in s['outputs'] if o not in have]
        ports = [p.get('id') for p in ((body.get('ports') or {}).get('inputs') or [])
                 if p.get('group') in ('travail', 'reference') and p.get('id')
                 and p.get('id') not in have and p.get('id') not in step_outputs]
        if step_outputs or ports:
            l += ['    # Pipeline de la card (function_specs.PIPELINE) — sorties des process, ports.']
        for nom in dict.fromkeys(step_outputs):
            l.append(f"    {nom} = models.FileField(upload_to=upload_to_user_output("
                     f"'{app_id}'), max_length=500, blank=True, null=True)")
        for nom in dict.fromkeys(ports):
            l.append(f"    {nom} = models.FileField(upload_to=upload_to_user_input("
                     f"'{app_id}'), max_length=500, blank=True, null=True)")
        if step_outputs or ports:
            l += ['']
    l += [f'    # TROU DE GLU {mark} — autres champs de RÉSULTAT (non déclarés au manifeste)',
          '    # et logique métier : marche B, puis migration dédiée. Le spine ne bouge pas.',
          '',
          '    class Meta:',
          f'        ordering = {list(ordering)!r}',
          '',
          '    def __str__(self):',
          f'        return f"{nom_item} {{self.id}} ({{self.filename}})"',
          '',
          '    @property',
          '    def filename(self):',
          '        import os']
    if name_field:
        l += [f'        if self.{name_field}:',
              f'            return self.{name_field}']
    l += [f'        return os.path.basename(self.{input_field}.name) '
          f'if self.{input_field} else \'\'']

    batch = spec.get('batch') or {}
    if batch.get('name') and batch.get('link_name'):
        rn_b = batch.get('user_related_name') or f'batch_{app_id}s'
        vn = batch.get('verbose_name') or f'Batch {app_id}'
        vnp = batch.get('verbose_name_plural') or f'Batchs {app_id}'
        item_field = batch.get('link_item_field') or 'item'
        l += ['',
              '',
              f"class {batch['name']}(BatchMixin, ScopedVisibility):",
              f'    """Groupe d\'items créé depuis un fichier batch (unité de partage F7)."""',
              '    objects = ScopedManager()',
              '',
              f"    user = models.ForeignKey(User, on_delete=models.CASCADE, "
              f"related_name='{rn_b}')",
              '    created_at = models.DateTimeField(auto_now_add=True)',
              f"    batch_file = models.FileField(upload_to=upload_to_user_input('{app_id}'), "
              f"blank=True, null=True)",
              '    total = models.IntegerField(default=0)',
              '',
              '    class Meta:',
              f'        verbose_name = {vn!r}',
              f'        verbose_name_plural = {vnp!r}',
              "        ordering = ['-created_at']",
              '',
              '    def __str__(self):',
              '        return f"Batch #{self.id} — {self.user.username} ({self.total} items)"',
              '',
              '',
              f"class {batch['link_name']}(models.Model):",
              f'    """Lien {batch["name"]} ⟷ {nom_item}."""',
              f"    {batch.get('link_batch_field') or 'batch'} = "
              f"models.ForeignKey({batch['name']}, on_delete=models.CASCADE, "
              f"related_name='{batch.get('link_batch_related') or 'items'}')",
              f"    {item_field} = models.OneToOneField(",
              f"        {nom_item}, on_delete=models.CASCADE,",
              f"        related_name='{batch.get('link_item_related') or 'batch_item'}', "
              f"null=True, blank=True,",
              '    )',
              '    row_index = models.IntegerField(default=0)',
              '',
              '    class Meta:',
              "        ordering = ['row_index']"]
    l.append('')
    return '\n'.join(l), None
