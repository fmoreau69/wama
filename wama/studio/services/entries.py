"""
Studio — les ENTRÉES des cards d'entrée médias, et le LOT (décision de Fabien, 2026-10-20 —
`STUDIO_VISION.md §Entrées du Studio`).

Une card d'entrée du Studio reprend la card d'entrée v4 de l'app qu'elle alimente
(`CARD_DESIGN §11.10-11.11`) : ses ports, leurs modalités (importer · médiathèque · URL), plusieurs
fichiers de travail, le fichier de lot. Rien n'entre en file à la composition : la card DÉSIGNE.
Ce qu'elle retient vit dans son réglage `entry` :

    {'ports':  {'<port>': ['users/<id>/temp/a.wav', 'https://…'], …},   # card universelle
     'prompt': 'texte',                                                  # sa consigne
     'lot':    'users/<id>/temp/lot.csv',                                # un fichier de lot
     'files':  ['…'],                                                    # card simplifiée d'un port
     'output': 'intro.wav' }      # le `-o` d'une ligne de lot, posé sur l'élément au dépliage

Chaque chemin passe les gardes de la désignation (`media_paths.check_designation`) ; une URL est
téléchargée AU LANCEMENT, au mode que l'app destinataire déclare (`received_value`,
`WAMA_INGEST`), comme celle d'un port de la card v4 (« téléchargée au lancement — un fichier joint
prime »).

LE LOT, comme dans les apps : plusieurs fichiers de travail OU un fichier de lot donnent la même
chose, un lot (`CARD_DESIGN §11.11 G`) — et le pipeline tourne UNE FOIS PAR ÉLÉMENT (une card =
une instance de pipeline, `WAMA_APP_GENERATION_ROUTE §10.6`). `lot_graphs` déplie le graphe en un
graphe par élément ; l'exécuteur les joue comme des runs ordinaires, enfants du run lancé, puis
range les cards de chaque nœud d'app en un lot de sa file (`queue_manipulation.consolidate_arrival`,
la voie d'arrivée commune).

LE PORT « ENTRÉE DE CARD » : une card d'app reçoit ses entrées PAR PORT. La card universelle et le
fichier de lot remplissent une card ENTIÈRE — ce que porte une ligne de lot, et ce pourquoi l'onglet
du fichier de lot n'est jamais un port (`CARD_DESIGN §11.11`, 2026-09-29). Elles se branchent donc
sur un port DÉRIVÉ, que tout nœud d'app qui crée une card reçoit (`card_port`) ; leur valeur se
déplie en ports avant la création (`unfold`). Les cards simplifiées se branchent, elles, sur les
ports existants.
"""
from __future__ import annotations

import copy

#: Le port dérivé « entrée de card » d'un nœud d'app, et le type de ce qui y circule.
CARD_PORT_ID = 'card'
CARD_TYPE = 'card'

#: Le réglage (caché) où une card d'entrée retient ce qu'elle désigne.
ENTRY_PARAM = 'entry'


def card_port() -> dict:
    """Le port « entrée de card », sous la forme des ports d'un nœud (`studio_node_ports`)."""
    return {'id': CARD_PORT_ID, 'label': 'Entrée de card', 'group': CARD_PORT_ID,
            'types': [CARD_TYPE], 'multi': False,
            'description': "Une card ENTIÈRE — tous ses ports d'un coup : la card d'entrée "
                           "universelle, ou un fichier de lot (une ligne = une card)."}


def entry_of(params) -> dict:
    """Le contenu retenu par une card d'entrée — son réglage `entry`, objet ou texte JSON (le
    champ caché du rendu commun le relit en texte)."""
    raw = (params or {}).get(ENTRY_PARAM)
    if isinstance(raw, str):
        import json
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            raise ValueError("Card d'entrée : contenu illisible — recomposez-la.")
    return dict(raw or {})


def _refs(values) -> list:
    """Une liste de références (chemins, URL) sans vide."""
    if isinstance(values, str):
        values = [values]
    return [str(v).strip() for v in values or [] if str(v or '').strip()]


def checked_ref(user, ref, label) -> str:
    """Une référence retenue : une URL telle quelle (téléchargée au lancement), un chemin s'il
    passe les gardes de la désignation — refusé tout de suite, en le nommant, sinon."""
    from wama.common.utils.media_paths import InputRefused, check_designation
    from wama.common.utils.source_ingest import is_remote
    ref = str(ref).strip()
    if is_remote(ref):
        return ref
    rel = ref[len('media/'):] if ref.startswith('media/') else ref
    try:
        return check_designation(rel, user)
    except InputRefused as exc:
        raise ValueError(f"Nœud « {label} » : {exc}")


def received_value(user, upstream, mode='media'):
    """La valeur qu'un nœud reçoit de l'amont, prête pour lui : une URL DÉSIGNÉE est téléchargée
    dans l'espace du compte, au mode que l'app destinataire DÉCLARE (`source_ingest.declared_mode`,
    `media` hors d'une app) ; un texte, une consigne, une donnée passent tels quels — même un texte
    qui commence par une adresse. LA règle, lue par le nœud d'app, la fonction et la sortie."""
    from wama.common.utils.source_ingest import download_to_user, is_remote
    value = upstream.get('value')
    if (upstream.get('is_text') or upstream.get('is_frame') or upstream.get('is_lots')
            or upstream.get('type') == 'prompt' or not isinstance(value, str)
            or not is_remote(value)):
        return value
    return download_to_user(user, value, mode)


def app_ingest_mode(app_id) -> str:
    """Le mode d'une URL destinée à l'app `app_id` : celui que son modèle d'élément déclare."""
    from wama.common.utils.detail_registry import DetailRegistry
    from wama.common.utils.source_ingest import declared_mode
    return declared_mode((DetailRegistry.get(app_id) or {}).get('model'))


def nature_of(ref) -> str:
    """La catégorie d'un fichier désigné ('' pour une URL sans extension connue)."""
    from wama.common.app_registry import category_of_path
    return category_of_path(str(ref).split('?')[0]) or ''


# ── Ce qu'une card d'entrée fournit à UN élément ────────────────────────────────────────────

def card_value(user, entry, label) -> dict:
    """La valeur d'une card ENTIÈRE pour un élément : `{port: référence | texte}`. Un port n'y porte
    qu'une valeur — plusieurs fichiers forment un lot, déplié AVANT (`lot_graphs`)."""
    value = {}
    for port, refs in (entry.get('ports') or {}).items():
        refs = _refs(refs)
        if len(refs) > 1:
            raise ValueError(f"Nœud « {label} » : plusieurs fichiers sur « {port} » — un lot se "
                             f"déplie au lancement ; relancez depuis le Studio.")
        if refs:
            value[port] = checked_ref(user, refs[0], label)
    prompt = str(entry.get('prompt') or '').strip()
    if prompt:
        value['prompt'] = prompt
    return value


def file_value(user, entry, params, label) -> str:
    """La valeur d'une card simplifiée d'un port pour un élément : UNE référence. L'ancien
    réglage `asset_path` (« Médias importés », avant le 2026-10-20) en est une."""
    refs = _refs(entry.get('files')) or _refs((params or {}).get('asset_path'))
    if not refs:
        raise ValueError(f"Nœud « {label} » : choisissez un fichier (composez l'entrée).")
    if len(refs) > 1:
        raise ValueError(f"Nœud « {label} » : plusieurs fichiers — un lot se déplie au lancement.")
    return checked_ref(user, refs[0], label)


# ── Le LOT : un graphe par élément ──────────────────────────────────────────────────────────

def _target_node(graph, node_id, port=None):
    """Le nœud que la card `node_id` alimente (par `port` si donné) — le premier lien sortant."""
    nodes = {n['id']: n for n in graph.get('nodes', [])}
    for link in graph.get('links', []):
        if link.get('from') == node_id and (port is None or link.get('to_port') == port):
            return nodes.get(link.get('to')), link.get('to_port')
    return None, None


def target_ports(graph, node_id) -> tuple:
    """`(app, ports d'entrée)` du nœud d'app que la card `node_id` alimente par le port « entrée
    de card » — `(None, [])` si elle n'en alimente aucun."""
    from wama.common.app_registry import studio_node_ports
    from wama.common.manifests.builtin.pipeline import node_kind
    target, _port = _target_node(graph, node_id, CARD_PORT_ID)
    if target is None or node_kind(target) != 'app':
        return None, []
    return target, list((studio_node_ports(target.get('app') or '') or {}).get('inputs') or [])


def lot_lines(user, ref, ports, label) -> list:
    """Les lignes d'un fichier de lot désigné, rangées dans les PORTS du nœud alimenté —
    `[({port: valeur}, réglages, nom de sortie)]` (`batch_parsers.parse_batch_lines` /
    `line_to_ports` ; le nom de sortie est le `-o` de la ligne, `''` sans lui). Une ligne sans
    fichier ni consigne se lit dans la famille de l'app : une consigne par ligne quand sa consigne
    suffit à créer l'élément (`principal_entry`), un fichier par ligne sinon."""
    import os

    from django.conf import settings

    from wama.common.app_registry import principal_entry
    from wama.common.utils.batch_parsers import (extract_batch_file_text, line_to_ports,
                                                 parse_batch_lines)
    rel = checked_ref(user, ref, label)
    path = os.path.join(settings.MEDIA_ROOT, rel)
    plain_as = 'prompt' if principal_entry(ports).get('primary_input') == 'prompt' else 'input'
    try:
        lines, warnings = parse_batch_lines(extract_batch_file_text(path), plain_as=plain_as)
    except (ValueError, RuntimeError) as exc:
        raise ValueError(f"Nœud « {label} » : fichier de lot illisible — {exc}")
    if not lines:
        raise ValueError(f"Nœud « {label} » : " + ('; '.join(warnings) or 'fichier de lot vide'))
    out = []
    for line in lines:
        try:
            out.append((*line_to_ports(line, ports), output_name(line.get('output'))))
        except ValueError as exc:
            raise ValueError(f"Nœud « {label} » : {exc}")
    return out


def output_name(value) -> str:
    """Le NOM de sortie d'une ligne de lot (`-o`), sans dossier : le Studio honore le nom, comme
    les apps, pas encore la destination (`BATCH_FORMAT.md` § `-o`). Le dossier est retiré — il
    deviendrait un chemin dans le ZIP du run, `..` compris."""
    import posixpath
    return posixpath.basename(str(value or '').replace('\\', '/').strip())


def element_output(graph) -> str:
    """Le nom de sortie d'un ÉLÉMENT de lot (le graphe d'un run enfant) : celui que sa ligne a
    posé dans la card d'entrée (`entry['output']`, `card_lot`), `''` sans lui."""
    for node in (graph or {}).get('nodes') or []:
        name = entry_of(node.get('params')).get('output')
        if name:
            return output_name(name)
    return ''


def node_elements(user, graph, node) -> list:
    """Les éléments qu'une card d'entrée fournit : `[(réglage entry d'un élément, réglages de
    l'app alimentée)]` — un seul pour une card sans lot. Rien pour un nœud qui n'est pas une
    card d'entrée médias."""
    from wama.common.manifests.builtin.pipeline import builtin_node
    builtin = builtin_node(node.get('app'))
    if builtin is None or builtin.lot is None:
        return []
    return builtin.lot(user, graph, node)


def card_lot(user, graph, node) -> list:
    """Les éléments d'une card ENTIÈRE (universelle, fichier de lot) : un par ligne de son fichier
    de lot, sinon un par fichier de son port de travail principal, sinon un seul. Les autres ports
    gardent leur valeur pour chaque élément ; une ligne la remplace."""
    from wama.common.app_registry import entry_form
    from wama.studio.services.node_params import node_label
    label = node_label(node.get('app'))
    entry = entry_of(node.get('params'))
    ports = {p: _refs(refs) for p, refs in (entry.get('ports') or {}).items() if _refs(refs)}
    prompt = entry.get('prompt') or ''
    _target, target_inputs = target_ports(graph, node['id'])
    if entry.get('lot'):
        if not target_inputs:
            raise ValueError(f"Nœud « {label} » : reliez-le au port « Entrée de card » d'une app "
                             f"— ses lignes se rangent dans les ports de cette app.")
        elements = []
        for line_ports, line_settings, line_output in lot_lines(user, entry['lot'],
                                                                target_inputs, label):
            fixed = {p: refs[:1] for p, refs in ports.items()}
            fixed.update({p: [v] for p, v in line_ports.items() if p != 'prompt'})
            element = {'ports': fixed, 'prompt': line_ports.get('prompt') or prompt}
            # Le `-o` de la ligne nomme le résultat de CET élément dans le ZIP du run
            # (`run_results.run_archive`), comme il nomme l'entrée du ZIP d'un lot d'app.
            if line_output:
                element['output'] = line_output
            elements.append((element, line_settings))
        return elements
    work = entry_form(target_inputs)['work'] if target_inputs else ''
    work = work or next((p for p, refs in ports.items() if len(refs) > 1), '')
    for port, refs in ports.items():
        if port != work and len(refs) > 1:
            raise ValueError(f"Nœud « {label} » : plusieurs fichiers sur « {port} » — seul le port "
                             f"de travail principal en porte plusieurs (un lot).")
    many = ports.get(work) or [None]
    return [({'ports': {**{p: refs[:1] for p, refs in ports.items()},
                        **({work: [ref]} if ref else {})},
              'prompt': prompt}, {}) for ref in many]


def files_lot(user, graph, node) -> list:
    """Les éléments d'une card simplifiée d'un port : un par fichier (plusieurs = un lot)."""
    entry = entry_of(node.get('params'))
    refs = _refs(entry.get('files')) or _refs((node.get('params') or {}).get('asset_path'))
    return [({'files': [ref]}, {}) for ref in refs] or [({'files': []}, {})]


def lot_graphs(user, graph) -> list:
    """Le graphe déplié en UN graphe par élément du lot, ou `[]` s'il n'y a rien à déplier (un
    seul élément partout, aucun fichier de lot). Un fichier de lot d'UNE ligne se déplie aussi —
    en un seul graphe : c'est sa ligne qui remplit la card. Un seul nœud peut multiplier : deux
    lots dans un pipeline ne disent pas lequel parcourir. Les réglages d'une ligne de lot
    s'ajoutent à ceux du nœud d'app alimenté, pour cet élément seulement — ceux que son schéma ne
    connaît pas sont refusés en le disant."""
    from wama.studio.services.node_params import node_label, node_schema
    plural = []
    for node in graph.get('nodes', []):
        elements = node_elements(user, graph, node)
        if len(elements) > 1 or (elements and entry_of(node.get('params')).get('lot')):
            plural.append((node, elements))
    if not plural:
        return []
    if len(plural) > 1:
        raise ValueError("Deux lots dans un même pipeline ("
                         + ', '.join(f"« {node_label(n.get('app'))} »" for n, _e in plural)
                         + ") : un seul nœud peut porter plusieurs éléments.")
    node, elements = plural[0]
    target, _ports = target_ports(graph, node['id'])
    known = {p['name'] for p in ((node_schema(target['app']) or {}).get('params') or [])} \
        if target is not None else set()
    graphs = []
    for index, (entry, settings) in enumerate(elements, start=1):
        unknown = sorted(set(settings) - known)
        if unknown:
            raise ValueError(f"Élément {index} du lot : réglage(s) inconnu(s) de "
                             f"« {node_label(target['app']) if target else '?'} » — "
                             f"{', '.join(unknown)}.")
        child = copy.deepcopy(graph)
        for n in child.get('nodes', []):
            if n['id'] == node['id']:
                n['params'] = {**(n.get('params') or {}), ENTRY_PARAM: entry}
                n['params'].pop('asset_path', None)
            elif target is not None and n['id'] == target['id'] and settings:
                n['params'] = {**(n.get('params') or {}), **settings}
        graphs.append(child)
    return graphs


def lot_progress(run):
    """Ce que le canvas montre d'un run de LOT, ou `None` pour un run ordinaire :
    `{'node_states': {nœud: {status, done, total}}, 'lot': {total, done, failed, current}}`.
    L'état de chaque nœud résume celui de ses N éléments par la règle d'un lot d'app
    (`batch_views.lot_overview`) — un lot du Studio se lit comme une card mère."""
    from wama.common.utils.batch_views import lot_overview
    elements = list(run.elements.order_by('pk'))
    if not elements:
        return None
    node_states = {}
    for node in (run.graph or {}).get('nodes', []):
        statuses = [((e.node_states or {}).get(node['id']) or {}).get('status') or 'PENDING'
                    for e in elements]
        counts, overall = lot_overview(statuses)
        node_states[node['id']] = {'status': overall, 'done': counts['success'],
                                   'total': len(elements)}
    counts, _overall = lot_overview([e.status for e in elements])
    current = next((i for i, e in enumerate(elements, start=1) if e.status == 'RUNNING'), None)
    return {'node_states': node_states,
            'lot': {'total': len(elements), 'done': counts['success'],
                    'failed': counts['failure'], 'current': current}}


# ── Côté nœud d'app : la valeur reçue dépliée en ports ──────────────────────────────────────

def _fill(inputs, app_id, port, value) -> None:
    """Pose la valeur d'un PORT — refusée, en le disant, si un autre lien l'a déjà remplie d'une
    autre valeur (une card entière ET un lien direct sur le même port) : la seconde écraserait
    la première en silence."""
    if port in inputs and inputs[port] != value:
        raise ValueError(f"Nœud {app_id} : le port « {port} » est alimenté deux fois (par la card "
                         f"d'entrée et par un lien) — gardez l'un des deux.")
    inputs[port] = value


def unfold(user, app_id, port, upstream, inputs) -> None:
    """Range dans `inputs` (par port, et par nature pour l'entrée principale) ce qu'un lien
    apporte au nœud d'app `app_id` : une card ENTIÈRE se déplie sur ses ports, une valeur seule
    va au port du lien. Une URL est téléchargée ici, au mode que l'app déclare
    (`received_value`). Un port déjà rempli d'une autre valeur se refuse (`_fill`)."""
    from wama.common.app_registry import studio_node_ports
    from wama.studio.services.generic_runner import primary_ports
    declared = {p['id']: p for p in (studio_node_ports(app_id) or {}).get('inputs') or []}
    mode = app_ingest_mode(app_id)
    if not upstream.get('is_card'):
        # Une valeur seule : rangée sous le port du lien ET sous sa nature — la lecture d'avant
        # (l'entrée principale se cherche par nature, `generic_runner.create`).
        key = port or upstream.get('type')
        value = received_value(user, upstream, mode)
        _fill(inputs, app_id, key, value)
        downloaded = value != upstream.get('value')
        kind = nature_of(value) if downloaded else upstream.get('type')
        if kind:
            inputs[kind] = value
        return
    received = dict(upstream['value'] or {})
    unknown = sorted(p for p in received if p not in declared and p != 'prompt')
    if unknown:
        raise ValueError(f"Nœud {app_id} : la card d'entrée remplit « {', '.join(unknown)} », "
                         f"que cette app n'a pas — recomposez l'entrée sur ce nœud.")
    principal = primary_ports(app_id)
    for pid, value in received.items():
        value = received_value(user, {'value': value, 'type': 'prompt' if pid == 'prompt' else ''},
                               mode)
        _fill(inputs, app_id, pid, value)
        if pid in principal and pid != 'prompt' and nature_of(value):
            inputs[nature_of(value)] = value
