"""IDENTITÉ D'UN LOT — ce que la card mère, le volet, le menu « Ajouter à un lot », le calendrier
et la page des partages disent d'un lot (2026-10-19, demande de Fabien : « seul le numéro identifie
un batch, pas son contenu »).

RIEN N'EST DÉCLARÉ ICI, TOUT SE LIT :
  • l'ENTRÉE de chaque élément — celle que sa fiche Infos montre (`DetailRegistry`, spec
    `source_file` / `source_text` / `source_type`) ; son vrai nom, la provenance
    (`InputProvenance.original_name`) quand l'import l'a gardé (la copie de travail peut porter un
    suffixe) ;
  • l'ORIGINE du lot — son fichier de lot (`batch_file`), sinon le DOSSIER commun des sources que
    la provenance a enregistrées (`InputProvenance.ref`) ;
  • ce qui VARIE — les réglages `chip=True` du schéma de l'élément, lus comme la fiche Infos
    (`spec_schema` + porteur `extra_from_params`) et mis en forme comme les pastilles des cards
    (`card_chips.varying_chips_for_items`) ;
  • le NOM donné à la main (`BatchLabel`, adressé comme `BatchSettings`), qui prime.

LE TITRE, dans cet ordre : le nom donné ; l'entrée si TOUS les éléments partagent la même (un même
fichier traité par plusieurs modèles) ; le fichier de lot ; le dossier d'origine ; sinon la plage
des entrées (« interview_01 … interview_12 », ou « a + 3 autres »). Le numéro du lot reste affiché
à côté : il identifie, le titre décrit.

⚠ APPELÉ À CHAQUE RENDU DE FILE : deux requêtes par page (noms, provenances), aucune par lot ; un
échec de lecture rend un titre dérivé sans nom ni origine, jamais une page en erreur.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: Au-delà, un texte d'entrée (prompt, texte à dire) s'abrège dans un titre.
TEXT_CHARS = 60

#: Le nombre de valeurs d'un réglage qui varie dites en clair ; au-delà, seulement leur nombre.
VALUES_SHOWN = 3

#: Longueur minimale du début commun de deux noms pour les dire en PLAGE (« a … b »).
RANGE_PREFIX = 4

#: Profondeur de la RACINE de chaque nature de source (`provenance.kind_of`) : un dossier commun
#: qui n'est que cette racine (`users/<u>/temp`, `mounts/<id>`) ne nomme rien.
SOURCE_ROOT_DEPTH = {'temp': 3, 'asset': 3, 'mount': 2}

#: Longueur maximale d'un nom donné à la main (colonne `BatchLabel.label`).
LABEL_MAX = 120


# ── L'entrée d'un élément ────────────────────────────────────────────────────────────────────

def _spec_of(element_model):
    from wama.common.utils.detail_registry import DetailRegistry
    surface = DetailRegistry.surface_of(element_model)
    return surface, ((DetailRegistry.get(surface) or {}).get('spec') or {}) if surface else {}


def _source_field(element, form):
    """Le champ fichier que la spec désigne comme entrée — un nom, ou le premier non vide d'une
    liste (la forme « premier champ non vide » de `spec_value`)."""
    if isinstance(form, str):
        return form
    if isinstance(form, (list, tuple)):
        return next((n for n in form if getattr(element, n, None)), None)
    return None


def _file_name(value) -> str:
    name = getattr(value, 'name', None) if not isinstance(value, str) else value
    return Path(str(name)).name if name else ''


def element_entry(element, origins=None) -> dict:
    """L'entrée DÉCLARÉE d'un élément : `{'name', 'text', 'nature', 'origin'}` (`''` / None quand
    rien n'est déclaré). `origins` : les provenances déjà lues (`_origins_for`)."""
    from wama.common.app_registry import category_of_path
    from wama.common.utils.detail_registry import spec_value
    _, spec = _spec_of(type(element))
    field = _source_field(element, spec.get('source_file'))
    origin = (origins or {}).get((element._meta.app_label, type(element).__name__, element.pk,
                                  field)) if field else None
    name = (origin.original_name if origin is not None and origin.original_name
            else _file_name(getattr(element, field, None) if field else None))
    text = ' '.join(str(spec_value(element, spec.get('source_text')) or '').split())
    nature = spec_value(element, spec.get('source_type'))
    if not isinstance(nature, str) or not nature:
        nature = category_of_path(name) if name else ''
    return {'name': name, 'text': text, 'nature': nature, 'origin': origin}


def entry_label(entry) -> str:
    """Ce qu'on DIT d'une entrée : son texte (le prompt, le texte à dire) s'il y en a un — c'est
    lui que l'utilisateur a écrit, le fichier qui l'accompagne (image de référence, voix) est
    secondaire —, sinon le nom du fichier."""
    text = entry.get('text') or ''
    if text:
        return text if len(text) <= TEXT_CHARS else text[:TEXT_CHARS - 1].rstrip() + '…'
    return entry.get('name') or ''


# ── Lectures groupées (une requête chacune, quelle que soit la page) ─────────────────────────

def _key(batch):
    from wama.common.services.batch_settings import address
    a = address(batch)
    return (a['app'], a['batch_type'], a['batch_id'])


def _labels_for(batches) -> dict:
    from django.db.models import Q
    from wama.common.models import BatchLabel
    groups = {}
    for b in batches:
        app, kind, pk = _key(b)
        groups.setdefault((app, kind), []).append(pk)
    if not groups:
        return {}
    q = Q()
    for (app, kind), ids in groups.items():
        q |= Q(app=app, batch_type=kind, batch_id__in=ids)
    try:
        return {(r.app, r.batch_type, r.batch_id): r.label for r in BatchLabel.objects.filter(q)}
    except Exception:
        logger.warning('[batch_identity] noms de lot illisibles', exc_info=True)
        return {}


def _origins_for(elements) -> dict:
    from django.db.models import Q
    from wama.common.models import InputProvenance
    groups = {}
    for e in elements:
        groups.setdefault((e._meta.app_label, type(e).__name__), []).append(e.pk)
    if not groups:
        return {}
    q = Q()
    for (app, kind), ids in groups.items():
        q |= Q(app=app, object_type=kind, object_id__in=ids)
    try:
        return {(p.app, p.object_type, p.object_id, p.field): p
                for p in InputProvenance.objects.filter(q)}
    except Exception:
        logger.warning('[batch_identity] provenances illisibles', exc_info=True)
        return {}


# ── Ce que le titre et ses détails disent ────────────────────────────────────────────────────

def _distinct(values):
    out = []
    for v in values:
        if v and v not in out:
            out.append(v)
    return out


def _folder_of(entries):
    """Le dossier d'où viennent TOUS les éléments (leur provenance), ou ''. Un élément sans
    provenance, une source qui n'est pas un dossier (la sortie d'une autre card), ou des dossiers
    différents : pas d'origine commune à dire."""
    from wama.common.utils.provenance import kind_of
    parents = set()
    for e in entries:
        origin = e.get('origin')
        ref = getattr(origin, 'ref', '') if origin is not None else ''
        depth = SOURCE_ROOT_DEPTH.get(kind_of(ref)) if ref else None
        parent = Path(ref).parent if ref else None
        if depth is None or parent is None or len(parent.parts) <= depth:
            return ''
        parents.add(parent.as_posix())
    return Path(parents.pop()).name if len(parents) == 1 else ''


def _range(labels, count, noun) -> str:
    """Plusieurs entrées distinctes : leur DÉBUT COMMUN (« Bonneuil_plateforme_… ») — des noms qui
    ne diffèrent qu'à la fin se lisent mieux ainsi que bout à bout —, sinon la première et le
    compte des autres (« un chat roux… + 1 autre »). Le nombre d'entrées n'est dit que s'il
    diffère du nombre de cards (`count`), que l'en-tête affiche déjà : « (2 fichiers) »."""
    if len(labels) == 1:
        return labels[0]
    import os
    common = os.path.commonprefix(labels)
    if len(common) >= RANGE_PREFIX:
        return f'{common}…' + (f' ({len(labels)} {noun})' if len(labels) != count else '')
    others = len(labels) - 1
    return f"{labels[0]} + {others} autre{'s' if others > 1 else ''}"


def _varying(works) -> list:
    """« Modèle : whisper, voxtral » pour chaque réglage `chip=True` qui diffère."""
    from wama.common.utils.card_chips import varying_chips_for_items
    from wama.common.utils.detail_registry import spec_schema
    surface, spec = _spec_of(type(works[0]))
    if not surface:
        return []
    schema = [p if isinstance(p, dict) else p.to_dict()
              for p in (spec_schema(works[0], spec, surface) or [])]
    carrier = spec.get('extra_from_params')
    values_of = ((lambda w: getattr(w, carrier, None) or {}) if isinstance(carrier, str) else None)
    out = []
    for v in varying_chips_for_items(works, schema, values_of):
        shown = v['values']
        out.append(f"{v['title']} : {', '.join(shown)}" if len(shown) <= VALUES_SHOWN
                   else f"{v['title']} ({len(shown)} valeurs)")
    return out


def _natures(entries) -> str:
    """« 8 audio · 4 vidéos » quand le lot MÊLE des natures (une seule : le total la dit déjà)."""
    from wama.common.app_registry import MEDIA_CATEGORY_LABELS
    counts = {}
    for e in entries:
        if e.get('nature'):
            counts[e['nature']] = counts.get(e['nature'], 0) + 1
    if len(counts) < 2:
        return ''
    return ' · '.join(f"{n} {MEDIA_CATEGORY_LABELS.get(k, k).lower()}" for k, n in counts.items())


def _identity(batch, works, name, origins) -> dict:
    entries = [element_entry(w, origins) for w in works]
    labels = _distinct(entry_label(e) for e in entries)
    batch_file = _file_name(getattr(batch, 'batch_file', None))
    details = []
    if name:
        title, kind = name, 'manual'
    elif len(works) > 1 and len(labels) == 1 and all(entry_label(e) for e in entries):
        title, kind = labels[0], 'shared_input'
    elif batch_file:
        title, kind = batch_file, 'batch_file'
    else:
        folder = _folder_of(entries) if entries else ''
        if folder:
            title, kind = folder, 'folder'
        elif labels:
            noun = 'textes' if any(e.get('text') for e in entries) else 'fichiers'
            title, kind = _range(labels, len(works), noun), 'inputs'
        else:
            title, kind = '', ''
    if works:
        try:
            details.extend(_varying(works))
        except Exception:
            logger.warning('[batch_identity] réglages du lot illisibles', exc_info=True)
    natures = _natures(entries) if kind != 'shared_input' else ''
    if natures:
        details.append(natures)
    return {'title': title, 'kind': kind, 'manual': name or '', 'details': details,
            'number': batch.pk}


# ── Lectures publiques ───────────────────────────────────────────────────────────────────────

def identify(pairs) -> list:
    """L'identité de chaque lot de `pairs` — `[(lot, [éléments]), …]`, éléments dans l'ordre des
    lignes (`batch_elements`, ou le cache de `build_batches_list`). Lots de modèles différents
    admis (le calendrier mêle les apps). Deux requêtes en tout."""
    pairs = [(b, list(ws or [])) for b, ws in pairs]
    names = _labels_for([b for b, _ in pairs])
    origins = _origins_for([w for _, ws in pairs for w in ws])
    return [_identity(b, ws, names.get(_key(b)), origins) for b, ws in pairs]


def identity_of(batch) -> dict:
    """L'identité d'UN lot, ses éléments lus par `batch_elements` (pour qui ne tient que le lot)."""
    from wama.common.utils.batch_common import batch_elements, surface_for_batch_model
    from wama.common.utils.preview_registry import PreviewRegistry
    surface = surface_for_batch_model(type(batch))
    elements = batch_elements(batch, PreviewRegistry.get_model(surface)) if surface else []
    return identify([(batch, elements)])[0]


def display_title(identity) -> str:
    """Le titre à afficher : le titre de l'identité, sinon le numéro (« Lot #12 »)."""
    return identity.get('title') or f"Lot #{identity.get('number')}"


def label_of(batch) -> str:
    """Le nom donné à la main à ce lot, ou ''."""
    return _labels_for([batch]).get(_key(batch), '')


def rename(batch, label: str) -> str:
    """Donne (ou efface, `label` vide) le nom d'un lot. Rend le nom retenu ('' = effacé)."""
    from wama.common.models import BatchLabel
    app, kind, pk = _key(batch)
    label = ' '.join(str(label or '').split())[:LABEL_MAX]
    if not label:
        BatchLabel.objects.filter(app=app, batch_type=kind, batch_id=pk).delete()
        return ''
    BatchLabel.objects.update_or_create(app=app, batch_type=kind, batch_id=pk,
                                        defaults={'label': label})
    return label


def forget(batch) -> int:
    """Le nom part avec le lot (appelé par la suppression du lot, comme `batch_settings.forget`)."""
    from wama.common.models import BatchLabel
    app, kind, pk = _key(batch)
    return BatchLabel.objects.filter(app=app, batch_type=kind, batch_id=pk).delete()[0]
