"""Les SCÈNES DE PROXIMITÉ (constellations 3D) — déclarées par leur domaine, montées par UNE brique.

Demande de Fabien (2026-10-21) : *« une brique commune réutilisable pour différents registres »*,
après la constellation des utilisateurs. Une scène DÉCLARE ce qu'elle montre — ses couches, ses
facteurs de distance, ses sortes de groupes, ses mesures, ses textes — et la page commune
(`common/constellation.html`) la monte avec la brique JS (`common/js/wama-constellation.js`).
Grammaire et cartographie : `docs/construction/ui/WAMA_SCENES_3D.md`.

POURQUOI UN REGISTRE À PART, ET PAS UN CHAMP DE `Registry` (WAMA_SCENES_3D §7, question 2).
Les scènes ne projettent pas toutes un registre : la constellation des utilisateurs n'en a pas, les
mécanismes, la file des cards ou le journal non plus. Une scène NOMME le registre qu'elle projette
(`registry`) quand elle en projette un — c'est ce qui allume son bouton dans l'en-tête de la page
du registre (`wama_catalog.scene_button`) —, sans que `Registry` ait à connaître la 3D.

LE REGISTRE NE CONNAÎT JAMAIS SES PRODUCTEURS : chaque domaine déclare sa scène dans le `ready()` de
son app (`accounts`, `model_manager`, `common` pour les licences). Les DONNÉES se lisent d'une
fonction nommée par chemin (`data`, importée à la demande) : déclarer ne coûte rien au démarrage.

Le contrat des données (rendu par `data(user)`, ou mis en forme côté page par un adaptateur
`module` quand la source rend des faits) : `{nodes, groups, links, beams, colorings}` — détaillé en
tête de la brique JS.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from importlib import import_module
from typing import Dict, Optional, Tuple

#: Rôles d'une couche : ce que la puce montre ou cache.
#:   `groups`     — les sphères d'une sorte (`kind`) et leurs filets ;
#:   `links`      — les arcs et les faisceaux ;
#:   `satellites` — ce que chaque nœud porte ;
#:   `nodes`      — les nœuds qui déclarent cette couche (`node.layer`), cachés quand elle est éteinte ;
#:   `names`      — les noms en clair (éteinte : initiales seules, pour projeter devant un public).
LAYER_ROLES = ('groups', 'links', 'satellites', 'nodes', 'names')

#: Familles de facteurs de distance (WAMA_SCENES_3D §2) — calculés à l'écran, poids en curseur.
FACTOR_KINDS = ('relation', 'groups', 'hierarchy', 'jaccard', 'same', 'closeness')

#: Qui peut ouvrir une scène : tout compte connecté, ou l'administration seule.
PERMISSIONS = ('auth', 'admin')


@dataclass(frozen=True)
class Scene:
    key: str
    #: Titre de l'onglet du navigateur, et du HUD (`kicker` au-dessus, `heading` en grand).
    page_title: str
    kicker: str
    heading: str = 'Constellation'
    description: str = ''
    #: `'module:fonction'` — `fonction(user)` rend le contrat. Vide : la scène a sa propre route
    #: de données (`data_url_name`), qui rend des FAITS mis en forme par l'adaptateur `module`.
    data: str = ''
    permission: str = 'auth'
    #: La clé du registre que la scène projette (`registries.REGISTRIES`), s'il y en a un.
    registry: str = ''
    #: Adaptateur JS (chemin statique) : il met les faits au contrat et peut rendre son volet.
    module: str = ''
    #: Une scène peut garder ses propres adresses (celle des utilisateurs, ouverte depuis « Users »).
    page_url_name: str = ''
    data_url_name: str = ''
    back_url_name: str = ''
    back_label: str = ''
    loading: str = 'Chargement…'
    search_placeholder: str = 'Trouver…'
    layers: Tuple[dict, ...] = ()
    colorings: Tuple[dict, ...] = ()
    colorings_title: str = 'Couleur des étoiles'
    forces_title: str = 'Ce qui rapproche'
    forces_hint: str = ''
    factors: Tuple[dict, ...] = ()
    group_kinds: Dict[str, dict] = field(default_factory=dict)
    stats: Tuple[dict, ...] = ()
    legend: Dict[str, object] = field(default_factory=dict)
    #: Constantes de la mise en espace qu'une scène plus peuplée ajuste (défauts : la brique).
    layout: Dict[str, float] = field(default_factory=dict)
    #: Au-delà, seules les étiquettes des plus gros nœuds (et du choisi, de ses voisins) s'affichent.
    label_limit: int = 0
    nearest_title: str = 'Les plus proches'
    nearest_empty: str = 'Rien ne relie encore cet élément aux autres.'


SCENES: Dict[str, Scene] = {}


def register_scene(scene: Scene) -> Scene:
    """Déclare une scène. Les incohérences se voient À LA DÉCLARATION, pas dans le navigateur."""
    if scene.permission not in PERMISSIONS:
        raise ValueError(f"scène {scene.key} : permission {scene.permission!r} inconnue")
    keys = {l['key'] for l in scene.layers}
    for l in scene.layers:
        if l.get('role') not in LAYER_ROLES:
            raise ValueError(f"scène {scene.key} : couche {l['key']} au rôle {l.get('role')!r} inconnu")
    for f in scene.factors:
        if f.get('kind') not in FACTOR_KINDS:
            raise ValueError(f"scène {scene.key} : facteur {f['key']} de famille {f.get('kind')!r} inconnue")
    for k, kd in scene.group_kinds.items():
        if kd.get('layer') and kd['layer'] not in keys:
            raise ValueError(f"scène {scene.key} : la sorte {k} cite la couche {kd['layer']} absente")
    if not (scene.data or scene.data_url_name):
        raise ValueError(f"scène {scene.key} : ni `data`, ni route de données")
    SCENES[scene.key] = scene
    return scene


def get_scene(key: str) -> Optional[Scene]:
    return SCENES.get(key)


def scene_for_registry(registry_key: str) -> Optional[Scene]:
    """La scène qui projette ce registre, s'il y en a une (bouton de l'en-tête de sa page)."""
    return next((s for s in SCENES.values() if s.registry == registry_key), None)


def can_view(scene: Scene, user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    if scene.permission == 'admin':
        from wama.accounts.permissions import is_admin_tier
        return is_admin_tier(user)
    return True


def page_url(scene: Scene) -> str:
    from django.urls import reverse
    if scene.page_url_name:
        return reverse(scene.page_url_name)
    return reverse('common:scene', args=[scene.key])


def data_url(scene: Scene) -> str:
    from django.urls import reverse
    if scene.data_url_name:
        return reverse(scene.data_url_name)
    return reverse('common:scene_data', args=[scene.key])


def scene_data(scene: Scene, user) -> dict:
    """Le contrat de la scène, lu de sa source (`data`)."""
    module, _, name = scene.data.partition(':')
    return getattr(import_module(module), name)(user)


def scene_spec(scene: Scene) -> dict:
    """La déclaration, telle que la page la sert à la brique (`<script type="application/json">`)."""
    spec = asdict(scene)
    for private in ('data', 'page_url_name', 'data_url_name', 'back_url_name', 'permission'):
        spec.pop(private)
    return spec


def page_context(scene: Scene, embed: bool) -> dict:
    """Le contexte du gabarit commun : la déclaration, et l'état de départ de chaque puce.

    La couche des NOMS s'éteint d'office quand une présentation intègre la page (`embed_on`) :
    elle se projette devant d'autres personnes. Le détail « Ce qui rapproche » s'y replie aussi."""
    from django.templatetags.static import static
    from django.urls import reverse

    from .hand_gestures import TASKS_VISION_VENDOR
    layers = [dict(l, on_now=(l['embed_on'] if embed and 'embed_on' in l else l.get('on', False)))
              for l in scene.layers]
    return {
        # Les MAINS (`common/js/wama-hands.js`) : les moteurs WebAssembly vendorisés, le modèle des
        # gestes servi par la route de la page, et la page où l'installer s'il manque.
        'hands': {'wasm': static(f'{TASKS_VISION_VENDOR}/wasm'), 'model': reverse('common:hand_model'),
                  'manage': reverse('model_manager:index')},
        'scene': scene,
        'scene_spec': scene_spec(scene),
        'scene_spec_id': f'wc-{scene.key}-spec',
        'scene_layers': layers,
        'scene_data_url': data_url(scene),
        'scene_back_url': reverse(scene.back_url_name) if scene.back_url_name and not embed else '',
        'embed': embed,
    }
