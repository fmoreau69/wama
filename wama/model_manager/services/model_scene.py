"""La SCÈNE des modèles (WAMA_SCENES_3D §3.2, C2) — le parc entier en une constellation : ce qui
fait la même tâche se rapproche, une sphère par TYPE (et, en couche, par SOURCE), la taille dit la
VRAM, la couleur le type, l'hébergement, la famille de licence ou l'état d'installation.

RIEN N'EST RECOPIÉ : les modèles sont ceux que le catalogue montre au demandeur
(`AIModel.objects.catalogue_visible_to`, propositions exclues — elles ont leur file à valider) ;
le nom d'une source est `source_identity`, l'hébergement `AIModel.hosting` et ses libellés
`external_sources`, la famille de licence `license_audit.qualifier`.

Les modèles DISTANTS (des centaines de modèles d'OpenRouter) sont une COUCHE éteinte au départ :
la scène s'ouvre sur ce que WAMA fait tourner lui-même, et les distants s'y ajoutent d'un clic.
"""


def _declared_task_and_modalities(caps):
    """La tâche (`task`, une chaîne — la clé que lisent `model_selector` et le prospecteur) et les
    modalités déclarées par les capacités d'un modèle, en listes pour le facteur `jaccard`."""
    if not isinstance(caps, dict):
        return [], []
    task = caps.get('task')
    mods = caps.get('modalities')
    return ([task] if isinstance(task, str) and task else [],
            [m for m in mods if isinstance(m, str)] if isinstance(mods, list) else [])


def model_scene(user=None) -> dict:
    from django.urls import reverse

    from wama.common import external_sources as xs
    from wama.common.services.license_audit import FAMILLES, qualifier

    from ..models import AIModel, ModelType, source_identity

    type_label = dict(ModelType.choices)
    hosting_label = {xs.LOCAL_ORIGIN_KEY: xs.LOCAL_ORIGIN_LABEL, **xs.CLOUD_ORIGIN_LABELS}
    rows = list(AIModel.objects.catalogue_visible_to(user).filter(is_proposed=False)
                .order_by('model_type', 'source', 'model_key'))
    catalog_url = reverse('model_manager:index')
    nodes, sources = [], {}
    for m in rows:
        q = qualifier(m.license)
        tasks, mods = _declared_task_and_modalities(m.capabilities)
        src = source_identity(m.source)
        sources.setdefault(m.source, src['label'])
        local = m.hosting == xs.LOCAL_ORIGIN_KEY
        state = ('installed' if (m.is_downloaded and local) else 'available' if (not local and m.is_available)
                 else 'absent')
        state_label = {'installed': 'Installé', 'available': 'Disponible (distant)', 'absent': 'Non installé'}[state]
        vram = m.vram_gb or 0
        nodes.append({
            'id': m.model_key, 'kind': 'model', 'name': m.name, 'handle': m.model_key,
            'sub': f"{type_label.get(m.model_type, m.model_type)} · {src['label']}",
            'size': vram if local else 0, 'layer': None if local else 'cloud',
            'groups': [f'type:{m.model_type}', f'src:{m.source}'],
            'attrs': {'engine': m.backend_ref or None, 'vram': vram if local else None,
                      'license': q['rang'] if q['id'] else None},
            'attr_labels': {'engine': f'moteur {m.backend_ref}' if m.backend_ref else '',
                            'license': q['famille']},
            'sets': {'tasks': tasks, 'modalities': mods},
            'cats': {'type': m.model_type, 'hosting': m.hosting or 'third_party',
                     'license': str(q['rang']), 'state': state},
            'tip': [f"{type_label.get(m.model_type, m.model_type)} · {src['label']}",
                    hosting_label.get(m.hosting, m.hosting or 'distant')
                    + (f' · {vram:g} Go de VRAM' if local and vram else ''),
                    f"Licence : {q['id'] or 'inconnue'} ({q['famille']})"],
            'detail': {
                'badges': [{'text': type_label.get(m.model_type, m.model_type), 'color': f'--wc-type-{m.model_type}'},
                           {'text': hosting_label.get(m.hosting, m.hosting or 'distant')},
                           {'text': state_label}],
                'text': m.description_short or m.description[:240],
                'url': m.platform_url or catalog_url,
                'url_label': m.platform_label or 'Gestion des modèles',
                'sections': [
                    {'title': 'Fiche', 'type': 'kv', 'rows': [r for r in (
                        ['Source', src['label']],
                        ['Moteur', m.backend_ref] if m.backend_ref else None,
                        ['Tâche', ', '.join(tasks)] if tasks else None,
                        ['Modalités', ', '.join(mods)] if mods else None,
                        ['VRAM', f'{vram:g} Go'] if local and vram else None,
                        ['Disque', f'{m.disk_gb:g} Go'] if m.disk_gb else None,
                        ['Licence', f"{q['id'] or 'inconnue'} — {q['famille']}"],
                        ['Auteur', m.author] if m.author else None,
                        ['Indice de qualité', f'{m.quality_index:.2f}'] if m.quality_index is not None else None,
                    ) if r]},
                ],
            },
        })
    groups = ([{'id': f'type:{t}', 'kind': 'type', 'name': type_label.get(t, t), 'sub': 'Type de modèle',
                'color': f'--wc-type-{t}'} for t in dict.fromkeys(m.model_type for m in rows)]
              + [{'id': f'src:{s}', 'kind': 'source', 'name': label, 'sub': 'Source',
                  'color': '--wc-ink-soft', 'legend': 'Source (app ou fournisseur)'}
                 for s, label in sources.items()])
    return {
        'nodes': nodes, 'groups': groups, 'links': [], 'beams': [],
        'colorings': {
            'type': {'palette': {t: f'--wc-type-{t}' for t in type_label},
                     'legend': [[label, t] for t, label in type_label.items()]},
            'hosting': {'palette': {h: f'--wc-hosting-{h}' for h in hosting_label},
                        'legend': [[label, h] for h, label in hosting_label.items()]},
            'license': {'palette': {str(r): f'--wc-rank-{r}' for r in FAMILLES},
                        'legend': [[label, str(r)] for r, (label, _) in FAMILLES.items()]},
            'state': {'palette': {'installed': '--wc-state-installed', 'available': '--wc-state-available',
                                  'absent': '--wc-state-absent'},
                      'legend': [['Installé', 'installed'], ['Disponible (distant)', 'available'],
                                 ['Non installé', 'absent']]},
        },
    }


def register_scene():
    """Déclare la scène `models` (appelé par `ModelManagerConfig.ready`)."""
    from wama.common.scenes import Scene, register_scene as register
    register(Scene(
        key='models', page_title='Constellation des modèles', kicker='Modèles · WAMA',
        description="Le parc des modèles : ce qui fait la même tâche se rapproche ; taille = VRAM.",
        data='wama.model_manager.services.model_scene:model_scene', registry='models',
        back_url_name='model_manager:index', back_label='Gestion des modèles',
        loading='Chargement du catalogue…', search_placeholder='Trouver un modèle…',
        layers=(
            {'key': 'types', 'role': 'groups', 'label': 'Types', 'dot': 'type-vision', 'on': True},
            {'key': 'sources', 'role': 'groups', 'label': 'Sources', 'dot': 'ink-soft', 'on': False},
            {'key': 'cloud', 'role': 'nodes', 'label': 'Modèles distants', 'dot': 'hosting-sovereign',
             'on': False},
        ),
        colorings=({'key': 'type', 'label': 'Type'}, {'key': 'hosting', 'label': 'Hébergement'},
                   {'key': 'license', 'label': 'Licence'}, {'key': 'state', 'label': 'Installation'}),
        forces_hint="La distance entre deux modèles se calcule de ces facteurs ; changez leur "
                    "poids, la constellation se réarrange.",
        factors=(
            {'key': 'task', 'kind': 'jaccard', 'set': 'tasks', 'label': 'Même tâche', 'value': 2.5,
             'max': 6, 'one': 'tâche commune', 'many': 'tâches communes',
             'help': 'Part des tâches déclarées en commun (capacités du modèle).'},
            {'key': 'type', 'kind': 'groups', 'group': 'type', 'label': 'Même type', 'value': 2,
             'max': 6, 'help': 'LLM, vision, diffusion, parole…'},
            {'key': 'source', 'kind': 'groups', 'group': 'source', 'label': 'Même source',
             'value': 1.2, 'max': 6, 'help': "L'app qui le déclare, ou le fournisseur distant."},
            {'key': 'engine', 'kind': 'same', 'attr': 'engine', 'label': 'Même moteur', 'value': 1.2,
             'max': 4, 'why': '{v}', 'help': 'Le moteur qui le charge (`backend_ref`).'},
            {'key': 'modalities', 'kind': 'jaccard', 'set': 'modalities', 'label': 'Mêmes modalités',
             'value': 0.8, 'max': 4, 'one': 'modalité commune', 'many': 'modalités communes',
             'help': 'Image, vidéo, audio, texte…'},
            {'key': 'vram', 'kind': 'closeness', 'attr': 'vram', 'range': 24, 'label': 'VRAM voisine',
             'value': 0.6, 'max': 4, 'why': 'VRAM voisine',
             'help': 'Deux modèles locaux de coût mémoire voisin (sur 24 Go).'},
            {'key': 'license', 'kind': 'same', 'attr': 'license', 'label': 'Même famille de licence',
             'value': 0.5, 'max': 4, 'why': '{v}', 'help': 'Permissive, non commerciale, à qualifier…'},
        ),
        group_kinds={
            'type': {'layer': 'types', 'label': 'Type', 'base': 0.025, 'rim': 0.45, 'margin': 1.4,
                     'pull': {'weight': 'type', 'k': 0.006}},
            'source': {'layer': 'sources', 'label': 'Source', 'base': 0.015, 'rim': 0.35,
                       'wire': True, 'margin': 1.0, 'pull': {'weight': 'source', 'k': 0.004}},
        },
        stats=({'count': 'nodes', 'one': 'modèle', 'many': 'modèles'},
               {'count': 'groups', 'kind': 'type', 'one': 'type', 'many': 'types'},
               {'count': 'groups', 'kind': 'source', 'one': 'source', 'many': 'sources'}),
        legend={
            'intro': "Chaque étoile est un modèle du catalogue : sa taille dit sa VRAM, sa place ce "
                     "qu'il partage avec ses voisins — tâche, type, source, moteur.",
            'nodes_note': "Taille = VRAM (modèles locaux). Les modèles distants s'ajoutent par leur couche.",
            'groups_note': "Une sphère enveloppe les modèles d'un même type ; la couche « Sources » "
                           "ajoute celles des apps et des fournisseurs.",
        },
        # Un parc de centaines de modèles : des ressorts plus souples et plus longs, une répulsion
        # plus forte, une vue plus reculée — et seules les plus grosses étoiles étiquetées.
        label_limit=18,
        layout={'spread': 2.5, 'home': 72, 'repulsion': 40, 'spring': 0.015, 'rest': 22,
                'gravity': 0.006, 'warmup': 400},
        nearest_empty="Rien ne relie encore ce modèle aux autres.",
    ))
