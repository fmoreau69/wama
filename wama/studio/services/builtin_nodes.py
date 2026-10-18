"""
Studio — ses nœuds INTÉGRÉS (cards d'entrée et de sortie), inscrits au registre commun.

ROUTE §10.6 point 3.3bis, marche R2 (2026-10-18). Le registre (`manifests/builtin/pipeline.py`,
`register_builtin_node`) est lu par la palette, l'inspecteur, le lancement et l'exécuteur ; ce
module y inscrit ce que le Studio apporte — le texte, le média de la médiathèque, le jeu de données
et la sortie médiathèque. Le monde Data inscrit les siens (`wama_data/functions/io/nodes.py`).

Importé par le module déclarant du Studio (`studio/function_specs.py`, chargé par `load_all`).
Les exécuteurs et les réglages vivaient dans `studio/tasks.py` (`SOURCE_HANDLERS`, des branches par
nom de nœud) et `studio/services/node_params.py` (`_builtin_nodes`) : déplacés ici tels quels.
"""
from __future__ import annotations

from wama.common.manifests.builtin.pipeline import BuiltinNode, register_builtin_node
from wama.common.utils.param_schema import Param

#: Un nœud intégré n'est pas un process : aucun réglage n'en périme un.
NO_STALE = ()


def _media_rel(params, key, label) -> str:
    """Le chemin d'un média de la médiathèque (relatif à MEDIA_ROOT), qui doit exister."""
    import os
    from django.conf import settings
    rel = (params.get(key) or '').strip().lstrip('/')
    if rel.startswith('media/'):
        rel = rel[len('media/'):]
    if not rel:
        raise ValueError(f"Nœud « {label} » : choisissez un fichier dans les paramètres du nœud.")
    if not os.path.exists(os.path.join(settings.MEDIA_ROOT, rel)):
        raise ValueError(f"Nœud « {label} » : fichier introuvable ({rel}).")
    return rel


# ── Entrées ─────────────────────────────────────────────────────────────────────────────────
def _source_text(user, params):
    text = (params.get('text') or '').strip()
    if not text:
        raise ValueError("Nœud « Texte » : renseignez le texte dans les paramètres du nœud.")
    return 'prompt', text


def _source_media(user, params):
    from wama.common.app_registry import category_of_path
    rel = _media_rel(params, 'asset_path', 'Médias importés')
    return (params.get('asset_category') or category_of_path(rel)), rel


def _source_dataset(user, params):
    """Nœud « Jeu de données » : un fichier tabulaire (CSV) de la médiathèque → `TypedFrame`
    du `data_type` choisi. C'est la CARD D'ENTRÉE de `WAMA_DATA_FUNCTION_CARDS §5` (source +
    type déclaré → port typé), pas un contournement du pivot taxonomique (marche B) : le type
    est DIT par l'utilisateur, jamais deviné d'une extension."""
    import os
    from django.conf import settings
    from wama.common.catalog.data_types import DataType, TypedFrame, known_types, normalize_type
    rel = _media_rel(params, 'asset_path', 'Jeu de données')
    dtype = normalize_type((params.get('data_type') or DataType.TABLE).strip())
    if dtype not in known_types():
        raise ValueError(f"Nœud « Jeu de données » : type '{dtype}' inconnu de la taxonomie.")
    import pandas as pd
    try:
        df = pd.read_csv(os.path.join(settings.MEDIA_ROOT, rel), sep=None, engine='python')
    except Exception as exc:
        raise ValueError(f"Nœud « Jeu de données » : lecture impossible ({exc}).")
    return dtype, TypedFrame(df, dtype, meta={'source': rel})


def _media_categories() -> list:
    """Les catégories média, déclarées une fois (`app_registry.MEDIA_CATEGORIES`) — un média de la
    médiathèque en a une, et la sortie range n'importe laquelle. L'ancienne palette JS en
    recopiait une partie (ni `archive` ni `score`)."""
    from wama.common.app_registry import MEDIA_CATEGORIES
    return list(MEDIA_CATEGORIES)


def _known_types() -> list:
    from wama.common.catalog.data_types import known_types      # accesseur unique (2026-09-16)
    return sorted(known_types())


def _dataset_params():
    from wama.common.catalog.data_types import DataType
    return [
        Param(name='asset_path', type='media_picker', label='Fichier tabulaire (médiathèque)',
              stales=NO_STALE),
        Param(name='data_type', type='select', label='Type de donnée', stales=NO_STALE,
              help='Le type est DIT, jamais deviné de l’extension — la taxonomie des types de '
                   'donnée.',
              choices=[(t, t) for t in _known_types()], default=DataType.TABLE),
    ]


# ── Sortie médiathèque ──────────────────────────────────────────────────────────────────────
def _unique_asset_name(user, base, asset_type):
    from wama.media_library.models import UserAsset
    name, k = base, 2
    while UserAsset.objects.filter(user=user, name=name, asset_type=asset_type).exists():
        name = f"{base} ({k})"
        k += 1
    return name


def _sink_text_to_media_library(user, text, params, run_id):
    """Variante TEXTE du nœud Sortie : écrit un .txt et le range en médiathèque (document)."""
    from django.core.files.base import ContentFile
    from wama.media_library.models import UserAsset
    # Une CATÉGORIE (`'audio'`) devient sa nature par défaut ; un alias n'entre plus en base
    # (A′, `natures.resolve_asset_type` — le puits écrivait la valeur telle quelle jusqu'au 13/09).
    from wama.media_library.natures import resolve_asset_type
    base = (params.get('asset_name') or '').strip() or f"studio-run-{run_id}"
    asset_type = resolve_asset_type(params.get('asset_type') or 'document', f"{base}.txt")
    name = _unique_asset_name(user, base, asset_type)
    asset = UserAsset(user=user, name=name, asset_type=asset_type, mime_type='text/plain')
    asset.file.save(f"{base}.txt", ContentFile(text.encode('utf-8')), save=False)
    try:
        asset.file_size = asset.file.size
    except Exception:
        pass
    asset.save()
    return f"médiathèque : « {name} » (texte, {len(text)} car.)"


def _sink_frame_to_media_library(user, frame, params, run_id):
    """Variante DONNÉES du nœud Sortie : un `TypedFrame` (sortie d'un nœud fonction) écrit
    en CSV et rangé en médiathèque (`document`) — la même porte que le texte."""
    from django.core.files.base import ContentFile
    from wama.media_library.models import UserAsset
    from wama.media_library.natures import resolve_asset_type
    base = (params.get('asset_name') or '').strip() or f"studio-run-{run_id}-{frame.data_type}"
    asset_type = resolve_asset_type(params.get('asset_type') or 'document', f"{base}.csv")
    name = _unique_asset_name(user, base, asset_type)
    asset = UserAsset(user=user, name=name, asset_type=asset_type, mime_type='text/csv')
    asset.file.save(f"{base}.csv", ContentFile(frame.df.to_csv(index=False).encode('utf-8')),
                    save=False)
    try:
        asset.file_size = asset.file.size
    except Exception:
        pass
    asset.save()
    return f"médiathèque : « {name} » ({frame.data_type}, {len(frame.df)} ligne(s))"


def _sink_file_to_media_library(user, value, params):
    """Copie la sortie dans la MÉDIATHÈQUE (UserAsset) — fichier DUPLIQUÉ (la sortie
    d'app reste dans sa file ; l'asset est autonome, supprimable indépendamment)."""
    import os
    from django.conf import settings
    from django.core.files import File
    from wama.common.utils.mime_utils import guess_mime_type
    from wama.media_library.models import UserAsset
    src_abs = os.path.join(settings.MEDIA_ROOT, value)
    if not os.path.exists(src_abs):
        raise ValueError(f"Nœud « Sortie » : fichier à ranger introuvable ({value}).")
    # Catégorie → nature (A′) ; l'extension du fichier rangé départage dans la catégorie.
    from wama.media_library.natures import resolve_asset_type
    asset_type = resolve_asset_type(params.get('asset_type') or 'video', os.path.basename(value))
    base = (params.get('asset_name') or '').strip() or os.path.splitext(os.path.basename(value))[0]
    name = _unique_asset_name(user, base, asset_type)
    asset = UserAsset(user=user, name=name, asset_type=asset_type,
                      mime_type=guess_mime_type(value) or '')
    with open(src_abs, 'rb') as fh:
        asset.file.save(os.path.basename(value), File(fh), save=False)
    try:
        asset.file_size = asset.file.size
    except Exception:
        pass
    asset.save()
    return f"médiathèque : « {name} » ({asset_type})"


def _sink_media_library(user, incoming, params, run_id):
    """Nœud « Sortie » : range la valeur reçue de l'amont — un fichier, un texte ou une donnée
    typée. Une base connectée ne se range pas : elle passe par l'export du monde Data."""
    if not incoming:
        raise ValueError("Nœud « Sortie » : aucune entrée reçue (connectez un nœud amont).")
    first = incoming[0]
    if first.get('is_lots'):
        raise ValueError("Nœud « Sortie » : une base connectée ne se range pas en médiathèque — "
                         "passez par un nœud « Export de données ».")
    if first.get('is_frame'):
        return _sink_frame_to_media_library(user, first['value'], params, run_id)
    if first.get('is_text'):
        return _sink_text_to_media_library(user, first['value'], params, run_id)
    return _sink_file_to_media_library(user, first['value'], params)


def _output_params():
    from wama.media_library.models import ASSET_TYPES
    return [
        Param(name='asset_name', type='text', label='Nom dans la médiathèque', stales=NO_STALE,
              help='Vide : le nom du fichier produit.'),
        # Les NATURES déclarées une fois (`media_library.natures`, A′), jamais une liste ici :
        # celle qui vivait à cette place n'en offrait que six sur dix (2026-10-13).
        Param(name='asset_type', type='select', label="Type d'asset", stales=NO_STALE,
              choices=list(ASSET_TYPES), default='video'),
    ]


register_builtin_node(BuiltinNode(
    key='text_input', role='source', label='Texte', icon='fas fa-keyboard', color='#f7c46c',
    description='Source : un texte / prompt saisi dans les paramètres du nœud (inspecteur).',
    run=_source_text, port_label='Texte', port_types=lambda: ['prompt'],
    params=lambda: [Param(name='text', type='textarea', label='Texte', stales=NO_STALE,
                          help='Texte ou prompt envoyé au nœud aval.')]))

register_builtin_node(BuiltinNode(
    key='media_import', role='source', label='Médias importés', icon='fas fa-photo-film',
    color='#6ee7a8',
    description='Source : vos médias existants (image, vidéo, audio, document…) injectés dans le '
                'pipeline.',
    run=_source_media, port_label='Médias', port_types=_media_categories,
    params=lambda: [Param(name='asset_path', type='media_picker', label='Média (médiathèque)',
                          stales=NO_STALE)]))

register_builtin_node(BuiltinNode(
    key='dataset_input', role='source', label='Jeu de données', icon='fas fa-table',
    color='#9ad0ec',
    description="Source : un fichier tabulaire (CSV) de la médiathèque lu comme donnée TYPÉE "
                "(type choisi dans l'inspecteur) → entrée d'un nœud fonction.",
    run=_source_dataset, port_label='Données', port_types=_known_types, params=_dataset_params))

register_builtin_node(BuiltinNode(
    key='studio_output', role='sink', label='Sortie', icon='fas fa-flag-checkered',
    color='#e78fb3',
    description="Range le résultat final dans la MÉDIATHÈQUE (nom + type configurables dans "
                "l'inspecteur).",
    run=_sink_media_library, port_label='Média final',
    # Une donnée typée se range aussi (écrite en CSV, rangée en document).
    port_types=lambda: list(dict.fromkeys(_media_categories() + _known_types())),
    params=_output_params))
