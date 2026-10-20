"""
L'index des médias de la file par CONTENU — `WAMA_MEMORY.md §7sexies`.

Demande de Fabien (2026-10-19) : *« une image contenant une voiture devrait pouvoir se retrouver
par recherche sans que le nom voiture ne soit explicitement indiqué dans le nom du fichier […] en
tâche asynchrone différée, en priorité basse »*.

Trois gestes, tous sur des pièces existantes :
  • QUOI indexer — les images que porte un élément de file : `file_references.card_files` (ses
    champs fichier ET ses listes de chemins déclarées), filtrées par `category_of_path`, pour
    chaque surface de `DetailRegistry` (une surface = un modèle d'élément) ;
  • INDEXER — une tâche de la file GPU au palier le plus bas (`common.index_media`), qui
    vectorise dans l'espace `media` par le service de vectorisation, sous l'arbitrage du
    gouverneur, et installe le modèle par la route s'il manque ;
  • CHERCHER — la requête est vectorisée dans le même espace, comparée aux images des seules
    cards que la page montre et que le compte a le droit de lister.

⚠ DISCIPLINE GPU (`WAMA_MEMORY §5bis`) : pas de battement fréquent qui chargerait le modèle à
répétition. L'indexation part sur un GESTE (chercher dans une file met en tâche les éléments de
cette file qui ne sont pas encore indexés) et par le lot de nuit.

LA RÈGLE DE RÉPONSE — mesurée le 2026-10-19 sur 9 médias réels (`WAMA_MEMORY §7sexies`). Les
scores texte → image d'EmbeddingGemma-2 sont SERRÉS (0,57 à 0,75) et leur niveau dépend de la
requête : aucun seuil fixe ne tient. Ce qui sépare, c'est l'ÉCART à une requête NEUTRE (« une
image ») pour la même image — l'affinité générale de l'image à n'importe quel texte s'y annule.
Avec un écart minimal de +0,01 : « voiture » → la voiture et la navette ; « personne » → les trois
images qui en montrent ; « logo » → les deux logos ; « chien » → rien. Limites mesurées : « chat »
ne retrouve qu'un chat sur deux, « avion » ramène la navette — le Describer, qui DÉCRIT l'image en
texte, est la suite consignée pour la précision.
"""
from __future__ import annotations

import logging
import os

from . import service_client as vectors
from .spaces import MEDIA

logger = logging.getLogger(__name__)

#: Images par appel au service — un lot : Ollama rechargerait sinon le modèle à chaque requête.
BATCH = 16

#: Images retenues par élément. L'imager en génère quatre ; au-delà, un élément est un LOT
#: d'images, et ses premières suffisent à le retrouver.
MAX_IMAGES_PER_ELEMENT = 8

#: Les requêtes NEUTRES — la référence de chaque image (cf. en-tête). La meilleure des trois
#: compte : une image très « photo » ou très « image » est ramenée à elle-même.
NEUTRAL_QUERIES = ('une image', 'une photo', 'image')

#: Écart minimal à la référence pour qu'une image réponde (mesure du 2026-10-19, cf. en-tête).
MIN_OFFSET = 0.01

#: Cards qu'une recherche peut nommer — une file affichée, pas un balayage du parc.
MAX_CARDS = 2000

#: Résidence demandée au gouverneur pendant une passe ; refusée, chaque lot décharge.
RESIDENCE = '5m'

#: Délai d'un lot d'images : à froid, le chargement du modèle et de son projecteur s'y ajoute.
EMBED_TIMEOUT_S = 120.0


def surfaces() -> dict:
    """`{surface: modèle d'élément}` — les surfaces de détail déclarées (`DetailRegistry`)."""
    from wama.common.utils.detail_registry import DetailRegistry
    return {name: DetailRegistry.get(name)['model'] for name in DetailRegistry.registered_apps()}


def _abs(rel: str) -> str:
    from django.conf import settings
    return os.path.join(settings.MEDIA_ROOT, *rel.split('/'))


def _sig(path: str) -> str:
    """Signature `taille:date` du fichier — l'empreinte commune (`file_cache.file_stamp`), dans
    la forme écrite en base depuis la première passe."""
    from wama.common.file_cache import file_stamp
    mtime_ns, size = file_stamp(path) or (0, 0)
    return f'{size}:{mtime_ns}'


def element_images(instance, limit: int = MAX_IMAGES_PER_ELEMENT) -> list:
    """`[(champ, chemin relatif)]` des images que l'élément porte et qui existent sur le disque —
    entrée comme résultat, sans doublon, au plus `limit`."""
    from wama.common.app_registry import category_of_path
    from wama.common.utils.file_references import card_files
    out, seen = [], set()
    for field, rel in card_files(instance):
        if rel in seen or category_of_path(rel) != 'image' or not os.path.isfile(_abs(rel)):
            continue
        seen.add(rel)
        out.append((field, rel))
        if len(out) >= limit:
            break
    return out


def _grouped(addresses) -> dict:
    """`{surface: {pk…}}` des adresses `(surface, pk)` valides (surface déclarée, pk entier)."""
    known = surfaces()
    out = {}
    for surface, pk in addresses or ():
        try:
            pk = int(pk)
        except (TypeError, ValueError):
            continue
        if surface in known and pk > 0:
            out.setdefault(surface, set()).add(pk)
    return out


def pending(addresses=None, limit: int = None) -> list:
    """Les images à (re)vectoriser : absentes de l'index, vectorisées par un autre modèle, ou
    dont le fichier a changé. `addresses` borne aux éléments nommés, sinon tout le parc.

    Rend `[{'surface', 'object_id', 'field', 'path', 'sig'}]`. Une surface illisible (table
    d'une jumelle de bac à sable qui ne suit pas son modèle) est sautée, jamais bloquante."""
    from wama.common.models import MediaVector
    wanted = _grouped(addresses) if addresses is not None else None
    out = []
    for surface, model in surfaces().items():
        if wanted is not None and surface not in wanted:
            continue
        try:
            qs = model.objects.all()
            rows = MediaVector.objects.filter(surface=surface, space=MEDIA.key,
                                              embedding_model=MEDIA.model)
            if wanted is not None:
                qs = qs.filter(pk__in=wanted[surface])
                rows = rows.filter(object_id__in=wanted[surface])
            known = {(r[0], r[1]): r[2] for r in rows.values_list('object_id', 'path', 'content_sig')}
            for obj in qs.order_by('pk').iterator():
                for field, rel in element_images(obj):
                    sig = _sig(_abs(rel))
                    if known.get((obj.pk, rel)) != sig:
                        out.append({'surface': surface, 'object_id': obj.pk, 'field': field,
                                    'path': rel, 'sig': sig})
                        if limit is not None and len(out) >= limit:
                            return out
        except Exception:
            logger.warning('[media_index] surface %s illisible — sautée', surface, exc_info=True)
    return out


def index(addresses=None, *, limit: int = 512) -> dict:
    """Vectorise ce qui attend (`pending`), par lots. Rend un résumé.

    Appelé par la tâche `common.index_media` — jamais dans une requête. La résidence du modèle
    pendant la passe est DEMANDÉE au gouverneur ; le point final décharge et libère, toujours
    ensemble (`memory/store.reindex`, même règle)."""
    from wama.common.models import MediaVector
    todo = pending(addresses, limit=limit)
    summary = {'pending': len(todo), 'indexed': 0, 'failed': 0}
    if addresses is None:
        summary['purged'] = purge()
    if not todo:
        return summary
    if not vectors.available(MEDIA.key):
        summary['unavailable'] = True
        logger.warning('[media_index] %s absent chez Ollama — rien de vectorisé', MEDIA.model)
        return summary
    allowed, why = vectors.residency_allowed(MEDIA.key)
    summary['residence'] = f"{'accordée' if allowed else 'refusée'} ({why})"
    if allowed:
        vectors.reserve(MEDIA.key)
    try:
        for start in range(0, len(todo), BATCH):
            chunk = todo[start:start + BATCH]
            vecs = vectors.embed(MEDIA.key, [{'image': _abs(e['path'])} for e in chunk],
                                 keep_alive=RESIDENCE if allowed else '0',
                                 timeout=EMBED_TIMEOUT_S)
            if not vecs:
                # Lot perdu : on ARRÊTE au lieu de boucler à vide ; il sera repris au prochain geste.
                summary['failed'] += len(chunk)
                break
            for entry, vec in zip(chunk, vecs):
                MediaVector.objects.update_or_create(
                    surface=entry['surface'], object_id=entry['object_id'], path=entry['path'],
                    space=MEDIA.key,
                    defaults={'field': entry['field'], 'content_sig': entry['sig'],
                              'embedding_model': MEDIA.model, 'embedding': vec})
            summary['indexed'] += len(chunk)
    finally:
        if summary['indexed']:
            vectors.unload(MEDIA.key)
        if allowed:
            vectors.release(MEDIA.key)
    return summary


def purge() -> int:
    """Retire les vecteurs dont l'élément n'existe plus, ou dont le fichier a disparu. Rend le
    nombre de lignes retirées. L'index se re-dérive du disque : rien n'y est irrécupérable."""
    from wama.common.models import MediaVector
    removed = 0
    known = surfaces()
    for surface in MediaVector.objects.values_list('surface', flat=True).distinct():
        model = known.get(surface)
        rows = MediaVector.objects.filter(surface=surface)
        try:
            stale = rows if model is None else rows.exclude(
                object_id__in=model.objects.values_list('pk', flat=True))
            removed += stale.delete()[0]
        except Exception:
            logger.warning('[media_index] purge de %s impossible', surface, exc_info=True)
    gone = [pk for pk, rel in MediaVector.objects.values_list('pk', 'path')
            if not os.path.isfile(_abs(rel))]
    if gone:
        removed += MediaVector.objects.filter(pk__in=gone).delete()[0]
    return removed


def search(user, query: str, addresses) -> dict:
    """Les éléments, parmi `addresses` (les cards que la page montre), dont une image répond à
    `query`. Seuls comptent ceux que `user` a le droit de LISTER (`scoping.listable_by`).

    Rend `{'hits': [{'surface', 'pk', 'score'}], 'pending': [(surface, pk)…], 'indexed': n}` —
    `pending` = les éléments listables qui portent une image et n'ont encore aucun vecteur
    (l'appelant met leur indexation en tâche). `hits` triés par score décroissant ; `score` = l'écart à la
    référence neutre (cf. en-tête). Fournisseur indisponible : `hits` vide, `unavailable`."""
    import numpy as np

    from wama.common.models import MediaVector
    from wama.common.utils.scoping import listable_by

    query = (query or '').strip()
    grouped = _grouped(list(addresses or ())[:MAX_CARDS])
    known = surfaces()
    allowed = {}
    for surface, pks in grouped.items():
        try:
            allowed[surface] = set(listable_by(known[surface].objects.filter(pk__in=pks), user)
                                   .values_list('pk', flat=True))
        except Exception:
            logger.warning('[media_index] droits de %s illisibles', surface, exc_info=True)
    result = {'hits': [], 'pending': [], 'indexed': 0}
    rows = []
    for surface, pks in allowed.items():
        rows += list(MediaVector.objects.filter(surface=surface, object_id__in=pks,
                                                space=MEDIA.key, embedding_model=MEDIA.model)
                     .values_list('surface', 'object_id', 'embedding'))
    indexed = {(r[0], r[1]) for r in rows}
    result['indexed'] = len(indexed)
    # À indexer : les éléments SANS aucun vecteur qui portent une image. Pas `pending()` : il
    # relit la date de chaque fichier (un fichier changé au même chemin), trop lent à chaque
    # frappe sur /mnt/d — le lot de nuit s'en charge.
    for surface, pks in allowed.items():
        missing = [pk for pk in pks if (surface, pk) not in indexed]
        if missing:
            for obj in known[surface].objects.filter(pk__in=missing):
                if element_images(obj, limit=1):
                    result['pending'].append((surface, obj.pk))
    result['pending'].sort()
    if not rows or len(query) < 2:
        return result
    qvecs = vectors.embed(MEDIA.key, [query, *NEUTRAL_QUERIES], query=True)
    if len(qvecs) != 1 + len(NEUTRAL_QUERIES):
        result['unavailable'] = True
        return result

    def unit(m):
        m = np.asarray(m, dtype=np.float32)
        return m / np.maximum(np.linalg.norm(m, axis=-1, keepdims=True), 1e-12)

    images = unit([r[2] for r in rows])
    q = unit(qvecs)
    sims = images @ q.T                      # (images × (requête + neutres))
    offsets = sims[:, 0] - sims[:, 1:].max(axis=1)
    best = {}
    for (surface, pk, _vec), offset in zip(rows, offsets.tolist()):
        best[(surface, pk)] = max(best.get((surface, pk), -1.0), offset)
    result['hits'] = [{'surface': s, 'pk': pk, 'score': round(score, 4)}
                      for (s, pk), score in sorted(best.items(), key=lambda kv: -kv[1])
                      if score >= MIN_OFFSET]
    return result
