"""
Indexation RAG — découpe en `RagChunk` le texte QUE WAMA A DÉJÀ PRODUIT. Doc : `WAMA_MEMORY.md`.

PRINCIPE : ON N'EXTRAIT RIEN. WAMA possède déjà ses couches d'extraction — le Transcriber rend un
texte, le Reader une OCR, le Describer une description. Ré-extraire ici doublonnerait ces chaînes
et produirait un second texte, différent de celui que l'utilisateur voit dans l'app. On indexe donc
la SORTIE existante, jamais le fichier source.

Mesuré le 2026-08-21 sur la base : transcriber `text` (18) + `summary` (15), describer
`result_text` (10) + `summary` (3), reader `result_text` (8) — ~592 k caractères. Les neuf autres
apps ne portent aucun champ texte : elles produisent des médias, et n'ont donc rien à indexer.

DÉRIVATION, PAS DÉCLARATION. Les sources viennent de `detail_registry` (comme le journal) et le
champ texte est DÉTECTÉ parmi des candidats — même mécanisme que la détection du champ de date
dans `services/journal.py`. Une app qui gagnera une sortie texte entrera donc au RAG sans qu'on
touche à ce module.

⚠ ZÉRO APPEL DE MODÈLE ICI. Le découpage est mécanique ; les vecteurs se calculent après coup et
par lot via `store.reindex()`. Même règle que la projection (`project.py`) et pour la même raison :
écrire ne doit jamais dépendre de la disponibilité du GPU.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Champs texte candidats, par ordre de préférence. Détecter plutôt que déclarer évite une table
#: à tenir à jour — et une app qui n'en a aucun est simplement sans objet pour le RAG.
CHAMPS_TEXTE = ('result_text', 'text', 'extracted_text', 'transcription', 'summary')

#: Taille de découpe, en caractères. ~800 tient largement dans la fenêtre de `bge-m3` tout en
#: gardant un fragment ASSEZ GRAND pour être compréhensible seul — un fragment trop court se
#: retrouve bien mais ne veut plus rien dire une fois sorti de son contexte.
TAILLE_CHUNK = 800

#: Recouvrement entre fragments consécutifs. Sans lui, une phrase coupée en deux devient
#: introuvable : ni l'un ni l'autre des deux fragments ne la contient en entier.
RECOUVREMENT = 120


def sources_texte():
    """
    Rend `[(app, model, [champs texte])]` — dérivé de `detail_registry`.

    Une app sans champ texte est écartée en silence : ce n'est pas un trou, c'est une app qui
    produit des médias.
    """
    from django.db.models import CharField, TextField

    from ..utils.detail_registry import DetailRegistry

    trouvees = []
    for app, entree in sorted(DetailRegistry._registry.items()):
        model = entree.get('model')
        if model is None:
            continue
        noms = {f.name for f in model._meta.get_fields()
                if isinstance(f, (TextField, CharField))}
        champs = [c for c in CHAMPS_TEXTE if c in noms]
        if champs:
            trouvees.append((app, model, champs))
    return trouvees


def decouper(texte, taille=TAILLE_CHUNK, recouvrement=RECOUVREMENT):
    """
    Découpe en fragments qui se recouvrent, en préférant une frontière NATURELLE.

    On cherche la dernière fin de phrase (ou à défaut le dernier espace) avant la limite, plutôt
    que de couper au caractère près : un fragment qui commence au milieu d'un mot pollue son
    propre vecteur, et se relit mal quand on le cite à l'utilisateur.
    """
    texte = (texte or '').strip()
    if not texte:
        return []
    if len(texte) <= taille:
        return [texte]

    fragments, debut = [], 0
    while debut < len(texte):
        fin = min(debut + taille, len(texte))
        if fin < len(texte):
            fenetre = texte[debut:fin]
            coupe = max(fenetre.rfind('. '), fenetre.rfind('.\n'),
                        fenetre.rfind('!\n'), fenetre.rfind('?\n'), fenetre.rfind('\n\n'))
            if coupe < taille // 2:              # frontière trop tôt : on n'ampute pas le fragment
                coupe = fenetre.rfind(' ')
            if coupe > taille // 2:
                fin = debut + coupe + 1
        fragment = texte[debut:fin].strip()
        if fragment:
            fragments.append(fragment)
        if fin >= len(texte):
            break
        debut = max(fin - recouvrement, debut + 1)
    return fragments


def indexer(*, user=None, apps=None, limite=None, dry_run=False):
    """
    Indexe les sorties texte en `RagChunk`. Rend un résumé `{...}`.

    IDEMPOTENTE, et par un moyen que `MemoryItem` ne s'autorise pas : les fragments d'un objet
    sont SUPPRIMÉS puis réécrits quand son texte a changé. C'est légitime ici précisément parce
    qu'un `RagChunk` est re-dérivable — la source fait foi (cf. `WAMA_MEMORY.md §3`). Appliquer
    ce geste à un souvenir serait une faute.
    """
    from ..models import RagChunk, ScopedVisibility
    from .store import content_hash

    resume = {'objets': 0, 'indexes': 0, 'inchanges': 0, 'fragments': 0, 'sans_texte': 0,
              'dry_run': dry_run}

    for app, model, champs in sources_texte():
        if apps and app not in apps:
            continue
        qs = model.objects.all()
        if user is not None:
            qs = qs.filter(user=user)

        for obj in qs.iterator():
            if limite is not None and resume['objets'] >= limite:
                break
            resume['objets'] += 1

            # Les champs sont concaténés dans l'ordre de `CHAMPS_TEXTE` : le corps d'abord, le
            # résumé ensuite. Les indexer séparément ferait deux sources concurrentes pour un
            # seul objet, et le résumé — plus dense — écraserait le corps au classement.
            morceaux = [str(getattr(obj, c, '') or '').strip() for c in champs]
            texte = '\n\n'.join(m for m in morceaux if m)
            if not texte:
                resume['sans_texte'] += 1
                continue

            source_id = f'{app}:{obj.pk}'
            fragments = decouper(texte)
            empreintes = [content_hash(f) for f in fragments]

            existants = list(RagChunk.objects.filter(source_kind='doc', source_id=source_id)
                             .order_by('ordinal').values_list('content_hash', flat=True))
            if existants == empreintes:
                resume['inchanges'] += 1
                continue

            resume['indexes'] += 1
            resume['fragments'] += len(fragments)
            if dry_run:
                continue

            # Réécriture COMPLÈTE : un texte modifié redécoupe différemment, donc apparier
            # fragment par fragment n'aurait pas de sens.
            RagChunk.objects.filter(source_kind='doc', source_id=source_id).delete()
            RagChunk.objects.bulk_create([
                RagChunk(
                    content=frag,
                    content_hash=emp,
                    # ⚠ Aucun vecteur ici : `store.reindex()` les calcule par lot, quand la
                    # machine est libre. Voir l'incident GPU du 2026-08-20 (§5bis).
                    embedding=None,
                    embedding_model='',
                    source_kind='doc',
                    source_id=source_id,
                    source_ref=f'{app}#{obj.pk}',
                    ordinal=i,
                    user=getattr(obj, 'user', None),
                    # ⚠ PRIVÉ, toujours. Ces modèles n'ont PAS de champ `visibility` : leur seule
                    # vérité est leur propriétaire. Le piège de la visibilité dénormalisée
                    # (`WAMA_MEMORY.md §4`) ne concerne donc PAS cette famille de sources — il
                    # s'ouvrira le jour où l'on indexera la médiathèque (`UserAsset`), qui, elle,
                    # hérite de `ScopedVisibility`.
                    visibility=ScopedVisibility.VIS_PRIVATE,
                )
                for i, (frag, emp) in enumerate(zip(fragments, empreintes))
            ])

    if not dry_run:
        logger.info('[memory.index] %s objets → %s indexés (%s fragments), %s inchangés',
                    resume['objets'], resume['indexes'], resume['fragments'],
                    resume['inchanges'])
    return resume
