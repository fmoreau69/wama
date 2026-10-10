"""
Les PUBLICATIONS des modèles d'une app — l'onglet « À propos » les tire du catalogue (2026-10-10).

Demande de Fabien : *« pointer les publications scientifiques associées aux modèles dans about,
comme on avait commencé à le faire »*. Ce qui avait été commencé : des liens « Publication » ÉCRITS
À LA MAIN dans le gabarit d'une app (`face_analyzer/base.html`) — et des listes de moteurs tout
aussi manuelles dans les À-propos des apps, qui vieillissent (le describer y cite encore des
modèles retirés). Ici, rien n'est écrit par app :
  • les MODÈLES d'une app sont ceux que proposent ses selects de catalogue — la même déclaration
    (`options_source='catalog'` + `options_query`) et la même lecture (`catalog_options`) que
    le select lui-même, donc zéro second lieu de vérité ;
  • leurs PUBLICATIONS sont celles que l'auteur rattache à son modèle sur sa carte Hugging Face
    (étiquettes `arxiv:<id>`), posées par la provenance (`provenance.arxiv_ids`, `set_identity`) et
    rangées dans `extra_info['publications']`.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

ARXIV_URL = 'https://arxiv.org/abs/{}'
HUB_PAPER_URL = 'https://huggingface.co/papers/{}'


DOI_URL = 'https://doi.org/{}'


def publication_links(model) -> list:
    """`[{id, kind, label, url, hub_url}]` des publications d'une ligne du catalogue, dans l'ordre
    déclaré. Un identifiant est arXiv (celui des cartes Hugging Face) ou un DOI (`10.…`, ce que
    citent les auteurs hors arXiv — DeepFace, revue, 2026-10-10)."""
    ids = (getattr(model, 'extra_info', None) or {}).get('publications') or []
    out = []
    for i in ids:
        if not isinstance(i, str) or not i:
            continue
        if i.startswith('10.'):
            out.append({'id': i, 'kind': 'doi', 'label': f'DOI {i}', 'url': DOI_URL.format(i),
                        'hub_url': ''})
        else:
            out.append({'id': i, 'kind': 'arxiv', 'label': f'arXiv {i}',
                        'url': ARXIV_URL.format(i), 'hub_url': HUB_PAPER_URL.format(i)})
    return out


def _model_rows(keys: list, seen: set) -> list:
    """Les lignes du catalogue de `keys`, dans leur ordre, sans celles déjà montrées."""
    from wama.model_manager.models import AIModel
    rows = {m.model_key: m for m in AIModel.objects.filter(model_key__in=keys)}
    out = []
    for key in keys:
        m = rows.get(key)
        if m is None or key in seen:
            continue
        seen.add(key)
        out.append({'key': key, 'name': m.name or key,
                    'description': m.description_short or m.description or '',
                    'platform_url': getattr(m, 'platform_url', '') or '',
                    'publications': publication_links(m)})
    return out


def app_models(app_id: str) -> list:
    """
    `[{label, models: [{key, name, description, platform_url, publications}]}]` — un groupe par
    select de catalogue de l'app, dans l'ordre du schéma. Un modèle déjà montré par un groupe
    précédent n'est pas répété.

    Aucune lecture recopiée (revérification du 2026-10-10) : un select se lit par
    `param_schema.catalog_options` (LA lecture côté serveur d'un select de catalogue), sa valeur
    devient une clé par `model_keys.catalog_key` ; une app SANS select de catalogue (Face
    Analyzer, monde Lab) montre les modèles qu'elle déclare, par la facette `models` de son
    manifeste (`manifests.builtin.app._models` : `AIModel.source == app`).
    """
    from wama.common.utils.auto_model import is_auto
    from wama.common.utils.model_keys import catalog_key
    from wama.common.utils.param_schema import catalog_options, schema_for_app

    groups, seen = [], set()
    for field in schema_for_app(app_id) or []:
        options = catalog_options(field)          # [] hors select de catalogue
        if not options:
            continue
        source = (field.get('options_query') or {}).get('source') or ''
        keys = [catalog_key(value, source) if source else value
                for value, _label in options if not is_auto(value)]
        models = _model_rows(keys, seen)
        if models:
            groups.append({'label': field.get('label') or field.get('name') or '', 'models': models})
    if not groups:
        from wama.common.manifests.builtin.app import _models
        models = _model_rows(((_models(app_id) or {}).get('catalog_keys') or []), seen)
        if models:
            groups.append({'label': 'Modèles', 'models': models})
    return groups
