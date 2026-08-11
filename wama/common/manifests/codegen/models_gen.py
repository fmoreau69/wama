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
_STATUS_LABELS = {'PENDING': 'En attente', 'RUNNING': 'En cours',
                  'SUCCESS': 'Terminé', 'FAILURE': 'Erreur'}
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
    if t in ('number', 'range'):
        bornes = (d, entry.get('min'), entry.get('max'), entry.get('step'))
        if any(isinstance(x, float) for x in bornes):
            return f"{nom} = models.FloatField(default={float(d or 0)})"
        return f"{nom} = models.IntegerField(default={int(d or 0)})"
    if t == 'textarea':
        return f"{nom} = models.TextField(blank=True, default={str(d or '')!r})"
    return f"{nom} = models.CharField(max_length=255, blank=True, default={str(d or '')!r})"


def render_models(manifest: dict) -> tuple:
    """(source, raison) — models.py squelette complet, ou (None, raison) si la facette ne
    porte pas de quoi le rendre. Jamais de fichier partiel."""
    from ..builtin.app import _GEN_MARK, _params_facet
    app_id = manifest.get('key')
    body = manifest.get('body') or {}
    proc = body.get('processing') or {}
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
    statuses = proc.get('statuses') or list(_STATUS_LABELS)
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
        'from wama.common.utils.media_paths import upload_to_user_input',
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
    l += [f"        ('{s}', '{_STATUS_LABELS.get(s, s.title())}')," for s in statuses]
    l += ["    ]",
          "    status = models.CharField(max_length=16, choices=STATUS_CHOICES, "
          "default='PENDING')",
          '    progress = models.IntegerField(default=0)',
          "    error_message = models.TextField(blank=True, default='')",
          '',
          f'    # TROU DE GLU {mark} — champs de RÉSULTAT à générer (marche B),',
          '    # puis migration dédiée. Le spine ci-dessus ne bouge pas.',
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
