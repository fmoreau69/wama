"""
Les PUBLICATIONS des modèles d'une app — l'onglet « À propos » les tire du catalogue (2026-10-10).

Demande de Fabien : *« pointer les publications scientifiques associées aux modèles dans about,
comme on avait commencé à le faire »*. Ce qui avait été commencé : des liens « Publication » ÉCRITS
À LA MAIN dans le gabarit d'une app (`face_analyzer/base.html`) — et des listes de moteurs tout
aussi manuelles dans les À-propos des apps, qui vieillissent (le describer y cite encore des
modèles retirés). Ici, rien n'est écrit par app :
  • les MODÈLES d'une app sont ceux que proposent ses selects de catalogue — la même déclaration
    (`options_source='catalog'` + `options_query`) et la même lecture (`get_registry_models`) que
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


def publication_links(model) -> list:
    """`[{id, url, hub_url}]` des publications d'une ligne du catalogue, dans l'ordre de la carte."""
    ids = (getattr(model, 'extra_info', None) or {}).get('publications') or []
    return [{'id': i, 'url': ARXIV_URL.format(i), 'hub_url': HUB_PAPER_URL.format(i)}
            for i in ids if isinstance(i, str) and i]


def app_models(app_id: str) -> list:
    """
    `[{label, models: [{key, name, description, platform_url, publications}]}]` — un groupe par
    select de catalogue de l'app, dans l'ordre du schéma. Un modèle déjà montré par un groupe
    précédent n'est pas répété. [] pour une app sans select de catalogue, ou catalogue illisible.
    """
    from wama.common.utils.param_schema import schema_for_app
    from wama.model_manager.models import AIModel
    from wama.model_manager.services import get_registry_models

    groups, seen = [], set()
    for field in schema_for_app(app_id) or []:
        if field.get('options_source') != 'catalog':
            continue
        query = dict(field.get('options_query') or {})
        source = query.pop('source', None)
        try:
            choices, _info = get_registry_models(source, **query)
        except Exception:
            logger.warning("[model_publications] select %s de %s illisible",
                           field.get('name'), app_id, exc_info=True)
            continue
        # Même espace de clés que le select : sans source, l'id EST la clé du catalogue.
        keys = [f'{source}:{cid}' if source else cid for cid, _label in choices]
        rows = {m.model_key: m for m in AIModel.objects.filter(model_key__in=keys)}
        models = []
        for key in keys:
            m = rows.get(key)
            if m is None or key in seen:
                continue
            seen.add(key)
            models.append({'key': key, 'name': m.name or key,
                           'description': m.description_short or '',
                           'platform_url': getattr(m, 'platform_url', '') or '',
                           'publications': publication_links(m)})
        if models:
            groups.append({'label': field.get('label') or field.get('name') or '', 'models': models})
    return groups
