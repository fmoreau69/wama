"""
Studio — ses nœuds INTÉGRÉS (cards d'entrée et de sortie), inscrits au registre commun.

ROUTE §10.6 point 3.3bis, marche R2 (2026-10-18). Le registre (`manifests/builtin/pipeline.py`,
`register_builtin_node`) est lu par la palette, l'inspecteur, le lancement et l'exécuteur ; ce
module y inscrit ce que le Studio apporte — le texte, les cards d'entrée médias et la sortie
médiathèque. Le monde Data inscrit les siens (`wama_data/functions/io/nodes.py`) : le jeu de
données (depuis le 2026-10-22), la base connectée et l'export.

Importé par le module déclarant du Studio (`studio/function_specs.py`, chargé par `load_all`).
Les exécuteurs et les réglages vivaient dans `studio/tasks.py` (`SOURCE_HANDLERS`, des branches par
nom de nœud) et `studio/services/node_params.py` (`_builtin_nodes`) : déplacés ici tels quels.
"""
from __future__ import annotations

from wama.common.manifests.builtin.pipeline import BuiltinNode, register_builtin_node
from wama.common.utils.param_schema import Param

from .entries import card_lot, files_lot

#: Un nœud intégré n'est pas un process : aucun réglage n'en périme un.
NO_STALE = ()


# ── Entrées ─────────────────────────────────────────────────────────────────────────────────
def _source_text(user, params):
    text = (params.get('text') or '').strip()
    if not text:
        raise ValueError("Nœud « Texte » : renseignez le texte dans les paramètres du nœud.")
    return 'prompt', text


def _emits_text(params):
    """Ce que fournira « Texte » : un prompt, et son texte s'il est saisi."""
    return {'types': ['prompt'], 'text': (params.get('text') or '').strip() or None}


# ── Les cards d'entrée MÉDIAS : la card d'entrée v4 des apps, dans le Studio (2026-10-20) ────
# `STUDIO_VISION §Entrées du Studio` : une card UNIVERSELLE (« Entrée ») qui prend la forme de la
# card v4 de l'app branchée, et ses cards SIMPLIFIÉES — un port de travail, un port de référence,
# un fichier de lot. Ce qu'elles désignent vit dans leur réglage caché `entry`, composé dans la
# modale du Studio (la card v4 de l'app, son volet à côté) ; le lot se déplie au lancement
# (`entries.lot_graphs`). « Texte » reste tel quel : prompts, textes libres, aperçus textuels.

def _entry_param():
    from .entries import ENTRY_PARAM
    return Param(name=ENTRY_PARAM, type='hidden', stales=NO_STALE,
                 help="Ce que la card désigne — composé dans sa modale.")


def _files_source(label):
    """Une card SIMPLIFIÉE d'un port : un ou plusieurs fichiers (plusieurs = un lot)."""
    def run(user, params):
        from .entries import entry_of, file_value, nature_of
        ref = file_value(user, entry_of(params), params, label)
        return nature_of(ref) or 'file', ref
    return run


def _emits_files(params):
    """Ce que fournira une card de fichiers : la nature de ses fichiers, s'ils sont choisis ; rien
    de décidé sinon (le fichier n'est pas exigé ici : on ne lance rien)."""
    from .entries import _refs, entry_of, nature_of
    try:
        refs = _refs(entry_of(params).get('files')) or _refs(params.get('asset_path'))
    except ValueError:
        return None
    natures = list(dict.fromkeys(n for n in map(nature_of, refs) if n))
    return {'types': natures} if natures else None


def _card_source(label):
    """Une card ENTIÈRE (universelle, fichier de lot) : `{port: valeur}` pour un élément."""
    def run(user, params):
        from .entries import CARD_TYPE, card_value, entry_of
        entry = entry_of(params)
        if entry.get('lot'):
            raise ValueError(f"Nœud « {label} » : son fichier de lot se déplie au lancement — "
                             f"relancez le pipeline depuis le Studio.")
        return CARD_TYPE, card_value(user, entry, label)
    return run


def _emits_card(params):
    """Ce que fournira une card entière : ses ports remplis, leur nature et sa consigne — ce que le
    nœud d'app alimenté montre « fourni » dans l'inspecteur (`graph_flow`)."""
    from .entries import CARD_TYPE, _refs, entry_of, nature_of
    try:
        entry = entry_of(params)
    except ValueError:
        return None
    ports = {}
    for port, refs in (entry.get('ports') or {}).items():
        natures = list(dict.fromkeys(n for n in map(nature_of, _refs(refs)) if n))
        if _refs(refs):
            ports[port] = {'types': natures, 'text': None}
    if (entry.get('prompt') or '').strip():
        ports['prompt'] = {'types': ['prompt'], 'text': entry['prompt'].strip()}
    return {'types': [CARD_TYPE], 'ports': ports}


def _media_categories() -> list:
    """Les catégories média, déclarées une fois (`app_registry.MEDIA_CATEGORIES`) — un média de la
    médiathèque en a une, et la sortie range n'importe laquelle. L'ancienne palette JS en
    recopiait une partie (ni `archive` ni `score`)."""
    from wama.common.app_registry import MEDIA_CATEGORIES
    return list(MEDIA_CATEGORIES)


def _known_types() -> list:
    from wama.common.catalog.data_types import known_types      # accesseur unique (2026-09-16)
    return sorted(known_types())


# ── Sortie médiathèque ──────────────────────────────────────────────────────────────────────
def _unique_asset_name(user, base, asset_type):
    from wama.media_library.models import UserAsset
    name, k = base, 2
    while UserAsset.objects.filter(user=user, name=name, asset_type=asset_type).exists():
        name = f"{base} ({k})"
        k += 1
    return name


def _asset_type_for(params, filename) -> str:
    """Le type d'asset d'un fichier rangé par le nœud Sortie — AUTOMATIQUE selon ce qu'il reçoit
    (2026-10-18, décision de Fabien : « ça dépend simplement de l'entrée »).

    Les usages ADMISSIBLES sont ceux du geste commun de la médiathèque
    (`media_library.services.candidate_asset_types` : sa politique d'acceptation par extension,
    « jamais une seconde table ») — ramené à la revérification : un premier jet jugeait par une
    comparaison de catégories écrite ici. Un usage choisi hors de ces admissibles est refusé en le
    disant (le défaut fixe `video` rangeait une image comme une vidéo). Vide, c'est le défaut
    DÉCLARÉ pour un puits du Studio — celui de la catégorie du fichier (`natures.CATEGORY_DEFAULT`,
    `category_of_path`) —, s'il est admissible, sinon le premier admissible."""
    from wama.common.app_registry import category_of_path
    from wama.media_library.natures import ASSET_NATURES, CATEGORY_DEFAULT, resolve_asset_type
    from wama.media_library.services import candidate_asset_types
    admissible = candidate_asset_types(filename)
    if not admissible:
        raise ValueError(f"Nœud « Sortie » : la médiathèque n'accepte pas ce fichier ({filename}).")
    chosen = (params.get('asset_type') or '').strip()
    if not chosen:
        preferred = CATEGORY_DEFAULT.get(category_of_path(filename))
        return preferred if preferred in admissible else admissible[0]
    asset_type = resolve_asset_type(chosen, filename)
    if asset_type not in admissible:
        raise ValueError(f"Nœud « Sortie » : le type « {ASSET_NATURES[asset_type].label} » ne "
                         f"convient pas à ce fichier ({filename}) — laissez « Automatique ».")
    return asset_type


def _sink_text_to_media_library(user, text, params, run_id):
    """Variante TEXTE du nœud Sortie : écrit un .txt et le range en médiathèque (document)."""
    from django.core.files.base import ContentFile
    from wama.media_library.models import UserAsset
    base = (params.get('asset_name') or '').strip() or f"studio-run-{run_id}"
    asset_type = _asset_type_for(params, f"{base}.txt")
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
    base = (params.get('asset_name') or '').strip() or f"studio-run-{run_id}-{frame.data_type}"
    asset_type = _asset_type_for(params, f"{base}.csv")
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
    from django.core.files import File
    from wama.common.utils.mime_utils import guess_mime_type
    from wama.media_library.models import UserAsset
    from .entries import checked_file
    # Le fichier DISQUE de ce qu'il reçoit : une sortie d'app, ou un fichier désigné en amont — un
    # dossier connecté compris (`MEDIA_ROOT/<valeur>` ne l'atteignait pas).
    src_abs = checked_file(user, value, 'Sortie')
    asset_type = _asset_type_for(params, os.path.basename(value))
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
    from wama.common.app_registry import MEDIA_CATEGORY_LABELS
    from wama.media_library.natures import ASSET_NATURES
    # Les NATURES déclarées une fois (`media_library.natures`, A′), jamais une liste ici : celle
    # qui vivait à cette place n'en offrait que six sur dix (2026-10-13). Groupées par CATÉGORIE,
    # derrière « Automatique » (2026-10-18) : le défaut fixe `video` faisait CLASSER à la main ce
    # que le fichier reçu dit déjà (`_asset_type_for`).
    auto = ('', 'Automatique (selon le fichier reçu)')
    groups = {}
    for key, nature in ASSET_NATURES.items():
        groups.setdefault(nature.category, []).append((key, nature.label))
    return [
        Param(name='asset_name', type='text', label='Nom dans la médiathèque', stales=NO_STALE,
              help='Vide : le nom du fichier produit.'),
        # `option_groups` pour le RENDU (il prime au select), `choices` à plat pour la PORTE
        # (`choice_values` ne lit qu'eux) : les mêmes valeurs, deux lectures.
        Param(name='asset_type', type='select', label="Type d'asset", stales=NO_STALE,
              choices=[auto] + [(k, n.label) for k, n in ASSET_NATURES.items()],
              option_groups=[('', [auto])]
              + [(MEDIA_CATEGORY_LABELS.get(category, category), options)
                 for category, options in groups.items()],
              default='',
              help='Automatique : la catégorie du fichier reçu (image, vidéo, audio…) et son '
                   'usage par défaut. Un usage choisi doit être de la même catégorie.'),
    ]


register_builtin_node(BuiltinNode(
    key='text_input', role='source', label='Texte', icon='fas fa-keyboard', color='#f7c46c',
    world='media',
    description='Source : un texte / prompt saisi dans les paramètres du nœud (inspecteur).',
    run=_source_text, port_label='Texte', port_types=lambda: ['prompt'], emits=_emits_text,
    params=lambda: [Param(name='text', type='textarea', label='Texte', stales=NO_STALE,
                          help='Texte ou prompt envoyé au nœud aval.')]))

register_builtin_node(BuiltinNode(
    key='card_input', role='source', label='Entrée', icon='fas fa-plus-circle', color='#6ee7a8',
    world='media',
    description="Source : la card d'entrée de l'app branchée, avec tous ses ports — prompt, "
                "fichier(s) de travail, référence(s), fichier de lot. À brancher sur le port "
                "« Entrée de card » d'une app.",
    run=_card_source('Entrée'), port_label='Card', port_types=lambda: ['card'],
    emits=_emits_card, params=lambda: [_entry_param()],
    lot=card_lot, compose='card'))

# La clé `media_import` reste (une DONNÉE des graphes enregistrés) : « Médias importés » devient
# la card simplifiée du port de travail — la médiathèque est l'une de ses modalités, à côté du
# poste et de l'URL ; son ancien réglage `asset_path` est encore lu (`entries.file_value`).
register_builtin_node(BuiltinNode(
    key='media_import', role='source', label='Fichier(s) de travail', icon='fas fa-photo-film',
    color='#6ee7a8', world='media',
    description="Source : le ou les fichiers que l'app TRAITE — depuis le poste, la médiathèque "
                "ou une URL. Plusieurs fichiers forment un lot : le pipeline tourne une fois par "
                "fichier.",
    run=_files_source('Fichier(s) de travail'), port_label='Fichier(s)',
    port_types=_media_categories, emits=_emits_files,
    # `asset_path` garde son sélecteur : vers une FONCTION ou la Sortie, il n'y a pas de card d'app
    # à rendre dans la modale — c'est alors le geste de la card (un média de la médiathèque).
    params=lambda: [_entry_param(),
                    Param(name='asset_path', type='media_picker', label='Média (médiathèque)',
                          stales=NO_STALE,
                          help="Vers une fonction ou une sortie. Vers une app : « Composer "
                               "l'entrée » (poste, médiathèque, URL, plusieurs fichiers).")],
    lot=files_lot, compose='files'))

register_builtin_node(BuiltinNode(
    key='reference_input', role='source', label='Fichier(s) de référence', icon='fas fa-paperclip',
    color='#6ee7a8', world='media',
    description="Source : le ou les fichiers qui GUIDENT l'app (style, mélodie, voix…) — depuis le "
                "poste, la médiathèque ou une URL. Plusieurs fichiers forment un lot.",
    run=_files_source('Fichier(s) de référence'), port_label='Référence',
    port_types=_media_categories, emits=_emits_files, params=lambda: [_entry_param()],
    lot=files_lot, compose='files'))

register_builtin_node(BuiltinNode(
    key='batch_input', role='source', label='Fichier de lot', icon='fas fa-file-lines',
    color='#6ee7a8', world='media',
    description="Source : un fichier de lot (TXT, MD, CSV, PDF, DOCX — une ligne = une card) : le "
                "pipeline tourne une fois par ligne. À brancher sur le port « Entrée de card » "
                "d'une app.",
    run=_card_source('Fichier de lot'), port_label='Lot', port_types=lambda: ['card'],
    emits=_emits_card, params=lambda: [_entry_param()],
    lot=card_lot, compose='lot'))

register_builtin_node(BuiltinNode(
    key='studio_output', role='sink', label='Sortie', icon='fas fa-flag-checkered',
    color='#e78fb3',
    description="Range le résultat final dans la MÉDIATHÈQUE (nom + type configurables dans "
                "l'inspecteur).",
    run=_sink_media_library, port_label='Média final',
    # Une donnée typée se range aussi (écrite en CSV, rangée en document).
    port_types=lambda: list(dict.fromkeys(_media_categories() + _known_types())),
    params=_output_params))
