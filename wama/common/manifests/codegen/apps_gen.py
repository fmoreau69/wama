"""
Gabarit `apps.py` (palier A3b, route §10.3) — le `ready()` rendu depuis la facette `inspector`.

Rendable UNIQUEMENT quand la registration detail est DÉCLARATIVE (`inspector.detail_spec`,
posée par `register_app_detail_spec` — A3a) : une app à adapter code (logique irréductible,
ex. transcriber) n'est PAS régénérable ici et le rendu la refuse — jamais de fichier qui
perdrait une logique. Le rendu compose exclusivement des briques communes :
`register_batch_sync` (si `processing.batch_link_model`), `register_app_preview`
(`inspector.preview`), `register_app_detail_spec` (`inspector.detail_spec`).

Limite consignée : les kwargs étendus de `register_app_preview` (duration/width/height/
properties_field — describer, enhancer) ne sont pas retenus par PreviewRegistry, donc pas
extraits : leurs apps restent hors gabarit tant que la rétention n'est pas ajoutée (bac
« porter »).
"""
from __future__ import annotations

import pprint
from pathlib import Path


def apps_file_path(app_id: str) -> Path:
    import wama
    return Path(wama.__file__).parent / app_id / 'apps.py'


def _config_class(app_id: str) -> str:
    return ''.join(p.title() for p in app_id.split('_')) + 'Config'


def render_apps(manifest: dict) -> tuple:
    """(source, raison) — apps.py complet, ou (None, raison) si la facette ne porte pas de
    quoi le régénérer sans perte (detail code, item_model inconnu…)."""
    from ..builtin.app import _GEN_MARK
    app_id = manifest.get('key')
    body = manifest.get('body') or {}
    insp = body.get('inspector') or {}
    proc = body.get('processing') or {}
    item_model = proc.get('item_model')
    spec = insp.get('detail_spec')
    if not item_model:
        return None, 'processing.item_model absent'
    if insp.get('detail_registered') and not spec:
        return None, ('detail enregistré par ADAPTER CODE (logique irréductible) — '
                      'non régénérable, passer par register_app_detail_spec d\'abord')
    verbose = (body.get('identity') or {}).get('verbose_name') or manifest.get('name') or app_id
    link = proc.get('batch_link_model')
    preview = insp.get('preview') if insp.get('preview_registered') else None

    mark = _GEN_MARK.format(app_id=app_id)
    modeles = [item_model] + ([link] if link else [])
    lignes = [
        '"""',
        f"{mark} — apps.py GÉNÉRÉ par write_back_app (facette inspector, gabarit A3b).",
        '',
        'Le ready() ne fait que COMPOSER des briques communes depuis des déclarations',
        '(batch_sync, preview, spec detail). Ne pas éditer à la main : rejouer write_back',
        'après modification du manifeste.',
        '"""',
        'from django.apps import AppConfig',
        '',
        '',
        f'class {_config_class(app_id)}(AppConfig):',
        "    default_auto_field = 'django.db.models.BigAutoField'",
        f"    name = 'wama.{app_id}'",
        f"    verbose_name = {verbose!r}",
        '',
        '    def ready(self):',
        f"        from .models import {', '.join(modeles)}",
    ]
    if link:
        lignes += [
            '        try:',
            '            from wama.common.utils.batch_sync import register_batch_sync',
            f'            register_batch_sync({link})',
            '        except Exception:',
            '            pass',
        ]
    if preview:
        kwargs = ''.join(f", {k}={v!r}" for k, v in (('file_field', preview.get('file_field')),
                                                     ('user_field', preview.get('user_field')))
                         if v)
        lignes += [
            '        from wama.common.utils.preview_utils import register_app_preview',
            f"        register_app_preview('{app_id}', {item_model}{kwargs})",
        ]
    if spec:
        rendu = pprint.pformat(spec, width=88, sort_dicts=True).split('\n')
        lignes += [
            '        from wama.common.utils.detail_registry import register_app_detail_spec',
            f"        register_app_detail_spec('{app_id}', {item_model}, {rendu[0]}"
            + (')' if len(rendu) == 1 else ''),
        ]
        if len(rendu) > 1:
            pad = ' ' * len(f"        register_app_detail_spec('{app_id}', {item_model}, ")
            lignes += [pad + l for l in rendu[1:]]
            lignes[-1] += ')'
    lignes.append('')
    return '\n'.join(lignes), None
