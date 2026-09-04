"""
WAMA Common — Orchestration batch (côté serveur).

Le PARSING des fichiers batch vit dans ``batch_parsers.py`` ; l'UI de détection
et de prévisualisation dans ``static/common/js/batch-import.js`` +
``templates/common/batch_detect_bar.html``.

Ce module formalise la partie restante, jusqu'ici dupliquée/spécifique :
  - regrouper des fichiers par NATURE (image/vidéo/audio/document) — nécessaire
    quand les réglages de sortie sont communs au batch (ex. Converter) ;
  - créer/consolider un batch-of-N à partir d'items déjà créés, via des
    callbacks fournis par chaque app (chaque app conserve son modèle batch).

Conçu pour être branché progressivement dans TOUTES les apps génériques
(on commence par le Converter). Reader/Synthesizer peuvent y migrer ensuite
sans changement de comportement.
"""

from collections import OrderedDict
from typing import Callable, Iterable, List, Optional, Sequence


def group_paths_by_nature(paths: Sequence[str],
                          classifier: Callable[[str], Optional[str]]) -> "OrderedDict[str, List[str]]":
    """Regroupe des chemins par nature de média, en conservant l'ordre d'apparition.

    Args:
        paths:      chemins (ou noms) de fichiers.
        classifier: fonction ``path -> nature`` (ex. 'image'|'video'|'audio'|
                    'document'|'archive') ou ``None`` si non supporté.

    Returns:
        OrderedDict {nature: [paths…]} — les chemins non classables (classifier
        renvoie None) sont ignorés. Permet à l'appelant de créer UN batch par
        nature (réglages de sortie communs à chaque batch).
    """
    groups: "OrderedDict[str, List[str]]" = OrderedDict()
    for p in paths:
        nature = classifier(p)
        if not nature:
            continue
        groups.setdefault(nature, []).append(p)
    return groups


def consolidate_into_batch(items: Iterable,
                           *,
                           create_batch: Callable[[int], object],
                           link_item: Callable[[object, object, int], None],
                           unwrap_singletons: Optional[Callable[[List], None]] = None):
    """Crée UN batch-of-N reliant ``items`` (généralise la consolidation reader).

    Chaque app fournit les opérations propres à son modèle batch :

        create_batch(total)            -> instance batch (ex. BatchReadingItem)
        link_item(batch, item, index)  -> crée le lien batch↔item
        unwrap_singletons(item_ids)    -> (optionnel) supprime les batch-of-1
                                          créés au préalable pour ces items
                                          (cas reader : import wrappe en
                                          batch-of-1, puis on consolide).

    Returns:
        l'instance batch créée, ou ``None`` si aucun item.
    """
    items = list(items)
    if not items:
        return None
    if unwrap_singletons:
        unwrap_singletons([getattr(i, 'id', i) for i in items])
    batch = create_batch(len(items))
    for idx, item in enumerate(items):
        link_item(batch, item, idx)
    return batch


def group_into_batches_by_nature(items,
                                 *,
                                 nature_of: Callable[[object], str],
                                 create_batch: Callable[[str, int], object],
                                 link_item: Callable[[object, object, int], None],
                                 unwrap_singletons: Optional[Callable[[List], None]] = None):
    """Crée UN batch PAR NATURE — **règle générale** de regroupement batch (conventions §9).

    Règle unifiée pour TOUTES les apps :
      - app mono-nature → ``nature_of`` renvoie une constante → un seul batch
        (comportement identique à une consolidation simple) ;
      - app multi-natures (image/vidéo/audio/document…) → un batch par nature
        (réglages cohérents par groupe, UI plus lisible).

    Callbacks fournis par l'app (chaque app garde son modèle batch) :
        nature_of(item)              -> str (nature)
        create_batch(nature, total)  -> instance batch (la nature peut être ignorée
                                        si l'app ne la stocke pas sur le batch)
        link_item(batch, item, idx)  -> lien batch↔item
        unwrap_singletons(item_ids)  -> (optionnel) supprime les batch-of-1 préalables

    Returns: liste des batchs créés (un par nature, dans l'ordre d'apparition).

    ⚠⚠ `nature_of` A UN JUMEAU, ET IL EST OBLIGATOIRE (2026-09-04, remarque de Fabien pendant
    le chantier drag&drop). Cette fonction décide de ce qui peut cohabiter dans un lot **à
    l'import**. Le drag&drop pose exactement la même question **après coup** — « ces deux cards
    peuvent-elles fusionner ? » — et la réponse doit venir de la MÊME déclaration, sinon les
    deux chemins divergent : l'import refuserait de mélanger image et vidéo pendant que le
    glisser-déposer le permettrait, dans la même app, le même jour.

    Donc : toute app qui passe `nature_of` ICI passe la MÊME fonction en `group_key=` à
    `make_queue_manipulation_views[_direct]`. Ce n'est pas une recommandation — c'est vérifié
    par `wama/common/tests_queue_dnd.py::…nature_a_son_jumeau_group_key`, précisément pour que
    la règle ne repose pas sur la mémoire du prochain (leçon « une garde se pose avec ses
    JUMEAUX »). Nommer la fonction plutôt que l'écrire en lambda est ce qui rend le partage
    possible ET lisible.
    """
    items = list(items)
    if not items:
        return []
    if unwrap_singletons:
        unwrap_singletons([getattr(i, 'id', i) for i in items])
    by_nature: "OrderedDict[str, List]" = OrderedDict()
    for it in items:
        by_nature.setdefault(nature_of(it), []).append(it)
    batches = []
    for nature, group in by_nature.items():
        batch = create_batch(nature, len(group))
        for idx, it in enumerate(group):
            link_item(batch, it, idx)
        batches.append(batch)
    return batches


# ---------------------------------------------------------------------------
# Batch UNIFIÉ — « tout est batch » (le batch-of-1 est rendu comme card simple).
# Généralise les helpers jusqu'ici dupliqués transcriber/composer/describer
# (audit empirique PROJECT_STATUS §20bis, 2026-07-06).
# ---------------------------------------------------------------------------

def wrap_in_batch(item, *, batch_model, item_model, fk_name, item_extra=None,
                  batch_extra=None):
    """Enveloppe UN item métier dans un batch-of-1 (règle « tout est batch »).

    Args:
        item        : objet métier (Transcript, ComposerGeneration, Description…) ; porte ``.user``.
        batch_model : modèle batch de l'app (ex. BatchTranscript).
        item_model  : modèle de liaison (ex. BatchTranscriptItem).
        fk_name     : nom de la FK métier sur le modèle de liaison (ex. 'transcript').
        item_extra  : dict OU callable(item)->dict de champs supplémentaires du LIEN
                      (ex. composer : output_filename).
        batch_extra : dict OU callable(item)->dict de champs supplémentaires du BATCH
                      (ex. imager : ``{'domain': 'video'}`` — sa file est scopée par onglet).
                      Sans ça, un batch-of-1 créé ici retombait sur le défaut du modèle et
                      une vidéo isolée de son batch atterrissait dans l'onglet Images.
                      Même nom que dans ``make_queue_manipulation_views_direct`` — vocabulaire
                      déjà en place, l'asymétrie entre les deux variantes était le défaut.
    """
    bkw = {'user': item.user, 'total': 1}
    if batch_extra:
        bkw.update(batch_extra(item) if callable(batch_extra) else dict(batch_extra))
    batch = batch_model.objects.create(**bkw)
    kwargs = {'batch': batch, 'row_index': 0, fk_name: item}
    if item_extra:
        kwargs.update(item_extra(item) if callable(item_extra) else dict(item_extra))
    item_model.objects.create(**kwargs)
    return batch


def load_in_import_order(model, ids, user):
    """Charge les objets d'un lot d'ids DANS L'ORDRE des ids (= ordre d'arrivée d'un import)."""
    items = list(model.objects.filter(id__in=ids, user=user))
    pos = {oid: p for p, oid in enumerate(ids)}
    items.sort(key=lambda o: pos.get(o.id, 0))
    return items


def delete_singleton_batches(batch_model, fk_name, user, item_ids):
    """Supprime les batch-of-1 qui enveloppent ces items (cascade sur les LIENS seulement —
    les objets métier survivent). C'est le `unwrap_singletons` standard des consolidations."""
    batch_model.objects.filter(
        user=user, total=1, **{f'items__{fk_name}_id__in': item_ids}
    ).distinct().delete()


def auto_wrap_orphans(user, *, work_model, batch_model, item_model, fk_name,
                      item_extra=None, batch_extra=None, wrap_group=None, order_by='id'):
    """Rattache paresseusement (au chargement de page) les items hors batch.

    Les orphelins proviennent des imports serveur (« Envoyer vers » du filemanager…) —
    l'upload JS, lui, enveloppe déjà à la création.

    Stratégie de regroupement :
      - défaut : chaque orphelin → SON batch-of-1 — **la règle depuis 2026-08-14** (10 apps).
        Le regroupement (par nature / of-N) se fait AU MOMENT d'un import groupé
        (`api_import_to_app` → helper `consolidate_*_into_batches` de l'app), jamais ici :
        indexé sur l'ACCUMULATION, ce wrap fusionnait des envois individuels espacés dans
        le temps dès que la page n'avait pas été chargée entre deux (constat Fabien 14/08,
        anonymizer — la même dérive existait sur enhancer/describer/transcriber).
      - ``wrap_group(orphans)`` : stratégie d'app qui crée les batchs elle-même. ⚠ Ne s'en
        servir QUE si le groupe a un sens indépendant du moment d'arrivée — pas pour
        regrouper « ce qui traîne ».
      - ``batch_extra`` : champs du BATCH créé (ex. imager ``domain``). À préférer à un
        ``wrap_group`` écrit uniquement pour poser un champ : la stratégie par défaut suffit
        alors, et l'app ne réimplémente pas la boucle.

    Silencieux par item (un orphelin cassé ne bloque pas la page — comportement historique).
    Returns: liste des batchs créés (vide si aucun orphelin).
    """
    existing_ids = set(
        item_model.objects.filter(batch__user=user).values_list(f'{fk_name}_id', flat=True)
    )
    orphans = list(
        work_model.objects.filter(user=user).exclude(id__in=existing_ids).order_by(order_by)
    )
    if not orphans:
        return []
    if wrap_group is not None:
        return wrap_group(orphans) or []
    wrapped = []
    for orphan in orphans:
        try:
            wrapped.append(wrap_in_batch(orphan, batch_model=batch_model,
                                         item_model=item_model, fk_name=fk_name,
                                         item_extra=item_extra, batch_extra=batch_extra))
        except Exception:
            pass
    return wrapped


def build_batches_list(user, *, batch_model, work_attr, items_related='items',
                       order_by='-id', has_output=None, extra=None):
    """Agrégats de file pour le template — contrat de la toolbar commune (``queue_view.py``).

    Returns:
        [{'obj', 'items', 'success_count', 'running_count', 'failure_count',
          'awaiting_count', 'has_success' [, **extra(batch, items, works)]}, …]

    Args:
        work_attr  : nom de la FK métier sur le modèle de liaison ('transcript', 'generation'…).
        has_output : callable(work)->bool optionnel — 'has_success' exige alors au moins un
                     SUCCESS avec sortie exploitable (ex. composer : audio_output non vide) ;
                     sinon 'has_success' = success_count > 0.
        extra      : callable(batch, items, works)->dict — enrichissements d'app
                     (ex. transcriber : success_pct + méta communes aux filles).
    """
    # Visibilité : un modèle de batch ayant adopté `ScopedVisibility` fait remonter aussi ce qui
    # est PARTAGÉ avec l'utilisateur (unité / projet / public) ; les autres gardent exactement le
    # comportement d'avant. Opt-in par modèle, donc aucun risque pour les apps non portées.
    #
    # Pourquoi ici et pas dans chaque app : la file est construite à UN seul endroit pour les
    # 10 apps (contrat de la toolbar commune, cf. queue_view.py). Et pourquoi le BATCH est la
    # bonne unité de partage : une card isolée est déjà auto-enveloppée dans son propre batch
    # (cf. `_auto_wrap_orphans`), donc partager ce batch revient à partager la card — sans avoir
    # à faire remonter des works dont le contenant, lui, ne serait pas partagé.
    _mgr = batch_model.objects
    base = _mgr.visible_to(user) if hasattr(_mgr, 'visible_to') else _mgr.filter(user=user)
    batches = (base
               .prefetch_related(f'{items_related}__{work_attr}')
               .order_by(order_by))
    result = []
    for batch in batches:
        # sorted() sur le cache prefetch (pas de .order_by() ici : re-requêterait par batch)
        items = sorted(getattr(batch, items_related).all(),
                       key=lambda it: getattr(it, 'row_index', 0) or 0)
        # ── Alias NORMALISÉ `elem` (2026-08-24) ───────────────────────────────
        # Chaque app nomme son élément métier autrement sur la liaison — `media`,
        # `generation`, `transcript`, `reading`, `synthesis`, `enhancement`… — et le
        # gabarit devait donc connaître ce nom pour l'atteindre. Résultat : SIX graphies
        # d'`{% include %}` pour un seul geste, ce qui interdisait tout partial commun
        # (mesuré le 2026-08-24 sur les 10 gabarits).
        # Le nom, le commun le CONNAÎT DÉJÀ : c'est `work_attr`, que l'app déclare ici même.
        # On l'expose donc sous un nom unique, et les gabarits cessent de le deviner.
        # ⚠ `elem` et non `work` : côté serveur `work` dit ce qu'on EXÉCUTE (`work_model`,
        # `work_attr`) — mais une FILE affiche un ÉLÉMENT, elle ne l'exécute pas (arbitrage
        # Fabien 2026-08-24). C'est aussi le mot de la doc et des scénarios (« le ⚙ d'un
        # élément », « élément vs lot »). ⚠ Ni `item`, déjà pris par la LIAISON dans
        # `{% for item in batch_info.items %}` — l'écraser est l'ambiguïté que reader avait
        # introduite. Abrégé : il sera écrit ~500 fois dans les gabarits.
        # Posé sur l'instance (pas en base) : aucun champ, aucune migration, aucune requête —
        # la valeur vient du `prefetch_related` juste au-dessus.
        for _it in items:
            _it.elem = getattr(_it, work_attr, None)
        works = [it.elem for it in items if it.elem]
        # Vocabulaires de statut variables selon les apps (reader : DONE/ERROR…) —
        # même tolérance que _cycle_button.html / wama-cycle-button.js stateFor().
        _ALIAS = {'DONE': 'SUCCESS', 'COMPLETED': 'SUCCESS', 'ERROR': 'FAILURE',
                  'FAILED': 'FAILURE', 'PROCESSING': 'RUNNING', 'STARTED': 'RUNNING'}
        statuses = [_ALIAS.get((w.status or '').upper(), (w.status or '').upper()) for w in works]
        row = {
            'obj': batch,
            'items': items,
            'success_count': statuses.count('SUCCESS'),
            'running_count': statuses.count('RUNNING'),
            'failure_count': statuses.count('FAILURE'),
            # AWAITING_RESOURCES (02/09) : compté À PART de l'attente ordinaire — le filtre
            # de file « En attente de ressources » repose dessus, et le ranger dans le
            # brouillon rendrait l'état invisible (c'est un état qui appelle un GESTE :
            # baisser le curseur de qualité, ou attendre — cf. common/models.py).
            'awaiting_count': statuses.count('AWAITING_RESOURCES'),
        }
        if has_output is not None:
            row['has_success'] = any(s == 'SUCCESS' and has_output(w)
                                     for s, w in zip(statuses, works))
        else:
            row['has_success'] = row['success_count'] > 0
        if extra is not None:
            row.update(extra(batch, items, works) or {})
        result.append(row)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Modèle de LOT d'une app — DÉRIVÉ, jamais déclaré
# ─────────────────────────────────────────────────────────────────────────────
def batch_model_for(element_model):
    """Modèle de LOT associé à un modèle d'ÉLÉMENT, ou None si indécidable.

    DÉRIVÉ des métadonnées Django, pas déclaré : rien à maintenir, rien qu'une app puisse
    oublier d'inscrire, toute app future couverte sans geste. C'est aussi la doctrine du
    dépôt — le substrat ne cite jamais ses producteurs.

    LA CONVENTION SUR LAQUELLE ON S'APPUIE EST LUE, PAS INVENTÉE : le rattachement à un lot
    est une FK nommée `batch`, de `related_name='items'`. Uniforme sur les 9 modèles du
    dépôt, et surtout **déjà consommée par le commun** — `build_batches_list(items_related=
    'items')` en fait son défaut. S'appuyer dessus, c'est lire une règle existante.
    ⚠ Ce qu'il ne FAUT PAS faire, et qui était ma première version : deviner sur le NOM DE
    CLASSE. `ComposerBatch`, `BatchAnonymizer`, `GenerationBatch`, `BatchReadingItemLink` ne
    suivent pas la même graphie — une règle sur le nom de classe serait fausse dès la 4ᵉ app.
    ⚠ Ni se contenter de « une FK vers un modèle de la même app » : `ConversionJob` en a DEUX
    (`profile` → ConversionProfile, `batch` → ConversionBatch), et l'accesseur rendait None.

    Deux formes coexistent, mesurées sur les 12 surfaces enregistrées (2026-08-24) — c'est la
    seule raison pour laquelle cette fonction n'est pas une ligne :
      • FK DIRECTE (converter, converter_01) : Élément.batch → Lot ;
      • via un modèle de LIAISON (10/12)     : Élément ← BatchXItem.batch → Lot.

    AMBIGU ou introuvable = None, jamais un choix arbitraire : un appelant qui reçoit None
    sait qu'il ne sait pas, là où un mauvais modèle ferait supprimer les mauvaises lignes.
    """
    if element_model is None:
        return None

    def _fk_batch(modele):
        """Cible de la FK de rattachement (`batch`) de ce modèle, ou None."""
        for f in modele._meta.get_fields():
            if getattr(f, 'many_to_one', False) and f.name == 'batch':
                return f.related_model
        return None

    # Forme B — l'élément porte lui-même son rattachement.
    direct = _fk_batch(element_model)
    if direct is not None:
        return direct

    # Forme A — un modèle de LIAISON référence l'élément et porte le rattachement.
    candidats = set()
    for rel in element_model._meta.related_objects:
        cible = _fk_batch(rel.related_model)
        if cible is not None and cible is not element_model:
            candidats.add(cible)
    return next(iter(candidats)) if len(candidats) == 1 else None


def batch_model_for_app(app_name):
    """Idem depuis un nom de SURFACE (`'enhancer'`, `'audio_enhancer'`…).

    Passe par `PreviewRegistry`, déjà l'annuaire surface → modèle d'élément du dépôt
    (manifestes, grille de conformité, scénarios nocturnes le lisent). ⚠ La clé est la
    SURFACE et non l'app Django : l'enhancer en expose deux (`enhancer` et
    `audio_enhancer`), avec deux modèles d'élément et deux modèles de lot distincts.
    """
    from wama.common.utils.preview_registry import PreviewRegistry
    return batch_model_for(PreviewRegistry.get_model(app_name))
