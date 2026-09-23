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
    attach_to_batch(item, batch, 0, item_model=item_model, fk_name=fk_name, item_extra=item_extra)
    return batch


def attach_to_batch(element, batch, row_index, *, item_model=None, fk_name=None,
                    item_extra=None, batch_attr='batch', row_field='batch_row_index'):
    """Rattache UN élément à un lot EXISTANT, à la ligne `row_index` — les deux formes du dépôt.

      • par LIAISON (`item_model` donné) : crée la ligne `item_model(batch=…, <fk_name>=élément,
        row_index=…)` — l'idiome des 9 apps, que `wrap_in_batch`, les fabriques de manipulation
        et les vues GÉNÉRÉES écrivaient chacun de leur côté (2026-09-22 : trois copies du même
        `objects.create`, plus une quatrième dans le code généré) ;
      • à FK DIRECTE (`item_model` absent, converter) : pose `<batch_attr>` et `<row_field>` sur
        l'élément et le sauve.

    Rend la ligne de liaison créée, ou l'élément lui-même en forme directe.
    `item_extra` : dict ou callable(élément)->dict — champs supplémentaires de la LIAISON
    (composer : `output_filename`), comme dans `wrap_in_batch`.
    """
    if item_model is not None:
        kwargs = {batch_attr: batch, 'row_index': row_index, fk_name: element}
        if item_extra:
            kwargs.update(item_extra(element) if callable(item_extra) else dict(item_extra))
        return item_model.objects.create(**kwargs)
    setattr(element, batch_attr, batch)
    setattr(element, row_field, row_index)
    element.save(update_fields=[batch_attr, row_field])
    return element


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


#: ⚠ La table d'alias vit au DOMICILE DU VOCABULAIRE depuis le 2026-09-17 (marche P2) :
#: `common/models.JOB_STATUS_ALIASES`. Celle qui était écrite ici en dupliquait une autre, à deux
#: entrées près — et aucune des deux ne connaissait `stale` (monde Lab). Nom conservé comme ALIAS
#: de transition : il a des lecteurs hors de ce module.
from wama.common.models import JOB_STATUS_ALIASES as STATUS_ALIASES  # noqa: F401  (ré-export)


def normalized_statuses(works):
    """Statuts des éléments ramenés au vocabulaire commun (SUCCESS/RUNNING/FAILURE/STALE…).

    Commodité OBJET ; pour un état isolé (JSON de nœud, littéral), appeler directement
    `common.models.normalize_job_status`.
    """
    from wama.common.models import normalize_job_status
    return [normalize_job_status(w.status) for w in works]


def status_counts(works):
    """Compteurs d'un lot tels que les affiche sa card mère (`_batch_card.html`).

    Sortis de `build_batches_list` le 2026-09-15 : la suppression d'une card de lot sans
    rechargement de la page doit rendre à la brique JS les MÊMES compteurs que le rendu de la
    file — deux calculs auraient fini par diverger.
    """
    statuses = normalized_statuses(works)
    counts = {
        'success_count': statuses.count('SUCCESS'),
        'running_count': statuses.count('RUNNING'),
        'failure_count': statuses.count('FAILURE'),
        # AWAITING_RESOURCES (02/09) : compté À PART de l'attente ordinaire — le filtre
        # de file « En attente de ressources » repose dessus, et le ranger dans le
        # brouillon rendrait l'état invisible (c'est un état qui appelle un GESTE :
        # baisser le curseur de qualité, ou attendre — cf. common/models.py).
        'awaiting_count': statuses.count('AWAITING_RESOURCES'),
        # STALE (2026-09-17, marche P2) : compté À PART de SUCCESS — le process a réussi, mais
        # son résultat n'est plus à jour. Le ranger avec les terminés dirait « tout est à jour »,
        # ce qui est faux, et ferait disparaître le seul geste qui reste à poser : relancer.
        'stale_count': statuses.count('STALE'),
    }
    counts['has_success'] = counts['success_count'] > 0
    return counts


def _batch_evaluation(works):
    """Comparaison des modèles du lot contre leur référence (`result_evaluation`), ou None.

    Posée ICI, pour toutes les apps d'un coup : une app qui DÉCLARE son évaluation voit la ligne
    de comparaison apparaître sur sa card mère sans une ligne de gabarit ; les autres ne paient
    rien (aucune requête : la surface n'est pas évaluable).
    """
    if not works:
        return None
    from wama.common.services.result_evaluation import batch_evaluation, evaluable_surface_of
    surface = evaluable_surface_of(type(works[0]))
    return batch_evaluation(surface, works) if surface else None


def build_batches_list(user, *, batch_model, work_attr, items_related='items',
                       order_by='-id', has_output=None, extra=None):
    """Agrégats de file pour le template — contrat de la toolbar commune (``queue_view.py``).

    Returns:
        [{'obj', 'items', 'success_count', 'running_count', 'failure_count',
          'awaiting_count', 'stale_count', 'has_success', 'evaluation'
          [, **extra(batch, items, works)]}, …]   # `evaluation` : None hors surface évaluable

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
        statuses = normalized_statuses(works)
        row = {'obj': batch, 'items': items, **status_counts(works),
               'evaluation': _batch_evaluation(works)}
        if has_output is not None:
            row['has_success'] = any(s == 'SUCCESS' and has_output(w)
                                     for s, w in zip(statuses, works))
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


def batch_of(element):
    """Le LOT (instance) auquel cet élément appartient, ou None s'il n'en a pas.

    Jumeau d'INSTANCE de `batch_model_for`, et même dérivation : les deux formes de
    rattachement du dépôt, dans le même ordre.
      • FK DIRECTE  : `element.batch` (converter, converter_01) ;
      • par LIAISON : `element.<liaison>.batch` — le reverse est un OneToOne nommé
        `batch_item` sur les 10 apps qui l'utilisent (`queue_manipulation` s'appuie déjà
        dessus), mais on ne le NOMME pas en dur : on cherche le reverse one-to-one dont le
        modèle porte une FK `batch`. Une 13ᵉ app qui nommerait autrement son reverse est
        couverte sans geste.

    ⚠ Écrit le 2026-09-08 pour le PARTAGE. `PROFILES_PERMISSIONS §7.4bis` l'exige noir sur
    blanc : « une card partagée sans son batch **n'apparaît pas** » — la file est construite à
    partir des LOTS. Partager une card sans propager au lot produirait donc un partage
    silencieusement inopérant : le destinataire ne verrait rien, et rien ne le dirait.
    """
    if element is None:
        return None
    direct = getattr(element, 'batch', None)
    if direct is not None:
        return direct
    for f in element._meta.related_objects:
        if not getattr(f, 'one_to_one', False):
            continue
        modele = f.related_model
        if not any(getattr(x, 'many_to_one', False) and x.name == 'batch'
                   for x in modele._meta.get_fields()):
            continue
        liaison = getattr(element, f.get_accessor_name(), None)
        if liaison is not None:
            return getattr(liaison, 'batch', None)
    return None


def batch_elements(lot, element_model):
    """Les ÉLÉMENTS d'un lot, DANS L'ORDRE DES LIGNES — le pendant DESCENDANT de `batch_of`.

    `lot.items` est uniforme sur les deux formes du dépôt (mesuré : le converter, seule app à FK
    directe, nomme AUSSI son `related_name='items'`). Ce que `items` CONTIENT diffère :
      • FK DIRECTE  : les éléments eux-mêmes, ordonnés par `batch_row_index` ;
      • par LIAISON : des objets de liaison ordonnés par `row_index`, qui portent l'élément sur
        une autre relation (chargée en une requête : `select_related`).
    L'ordre est GARANTI ici (2026-09-22) : jusque-là la fonction rendait l'ordre par défaut du
    modèle, et les vues GÉNÉRÉES avaient réécrit leur propre lecture ordonnée du lot
    (`_batch_elements`) — un chemin parallèle, retiré au profit de celle-ci. Les vues des apps
    réelles écrivent encore `batch.items.select_related(fk).order_by('row_index')` à la main :
    même geste, à porter dessus au fil des passes.

    ⚠ `element_model` est EXIGÉ, et ce n'est pas de la paresse. Ma première version le devinait
    en suivant « la première relation sortante qui n'est pas `batch` » : sur la forme à FK
    directe, `ConversionJob` porte aussi `user` — elle rendait donc l'UTILISATEUR comme élément.
    Le modèle attendu est une donnée que l'appelant POSSÈDE (il l'a résolu par
    `PreviewRegistry`), la deviner était un choix arbitraire déguisé en dérivation.
    *Quand une dérivation doit trancher entre deux relations plausibles, c'est qu'il manque une
    donnée à l'entrée.*

    ⚠ Écrit le 2026-09-08 pour le PARTAGE D'UN LOT (question de Fabien : « est-ce que le partage
    fonctionne pour les batch ? »). La symétrie est une EXIGENCE, pas une élégance : un lot
    partagé dont les éléments restent privés se montre au destinataire… VIDE. C'est le miroir
    exact du défaut que `batch_of` évite dans l'autre sens.
    (Nommée `elements_du_lot` jusqu'au 2026-09-22 — un identifiant de code se nomme en anglais.)
    """
    if lot is None or element_model is None:
        return []
    manager = getattr(lot, 'items', None)
    if manager is None:
        return []
    member_model = manager.model
    member_fields = {f.name for f in member_model._meta.get_fields()}
    direct = issubclass(member_model, element_model)      # les membres SONT les éléments
    row_field = ('batch_row_index' if direct and 'batch_row_index' in member_fields
                 else 'row_index' if not direct and 'row_index' in member_fields else None)
    # Forme par LIAISON : la relation (many_to_one ou one_to_one, non auto-créée) qui vise
    # exactement le modèle d'élément.
    element_field = None if direct else next(
        (f.name for f in member_model._meta.get_fields()
         if (getattr(f, 'many_to_one', False) or getattr(f, 'one_to_one', False))
         and not getattr(f, 'auto_created', False) and f.related_model is element_model), None)
    if not direct and element_field is None:
        return []
    # Un lot PRÉCHARGÉ (`prefetch_related('items__<élément>')`, idiome des vues de liste et de
    # `build_batches_list`) se lit dans son cache : aucune requête de plus — sinon une liste de
    # N lots coûterait N requêtes. Même tri que la requête (sur le cache, comme la file).
    prefetched = (getattr(lot, '_prefetched_objects_cache', None) or {}).get('items')
    if prefetched is not None:
        members = sorted(prefetched, key=lambda m: getattr(m, row_field, 0) or 0) if row_field \
            else list(prefetched)
    else:
        qs = manager.all() if direct else manager.select_related(element_field)
        members = list(qs.order_by(row_field) if row_field else qs)
    # Chaque élément rendu porte `batch_link` : la LIGNE du lot qui le porte — la ligne de
    # liaison (qui a ses propres champs : `output_filename` du synthesizer et du composer,
    # `row_index`), ou l'élément lui-même en FK directe. C'est ce qui permet à une vue de lot
    # commune de nommer un fichier d'après la ligne sans connaître la forme du rattachement
    # (2026-09-23 : jusque-là, composer et synthesizer gardaient leur `batch_download` local
    # pour cette seule raison).
    if direct:
        for m in members:
            m.batch_link = m
        return members
    elements = []
    for m in members:
        e = getattr(m, element_field, None)
        if e is not None:
            e.batch_link = m
            elements.append(e)
    return elements


# ─────────────────────────────────────────────────────────────────────────────
# Position d'un élément dans la file — pour les rendus HORS de la page d'index
# ─────────────────────────────────────────────────────────────────────────────

def is_batch_child(element):
    """L'élément s'affiche-t-il comme FILLE d'un lot (lot de plusieurs cards) ?

    C'est la valeur `in_batch` que reçoivent les cards d'app. Au rendu de la file,
    `common/_queue_entry.html` la pose d'après `is_unitary` — c'est une propriété de la
    POSITION dans la file, pas de l'app. Mais les vues `card_html`, qui rendent une card
    SEULE (rafraîchissement, suppression sans rechargement de la page), la recalculaient
    chacune à la main. Mesuré le 2026-09-15 sur les 11 vues : cinq variantes, dont une
    fausse (`.exists()` de l'enhancer — un lot unitaire rendait une card de fille) et quatre
    absentes (converter, synthesizer, avatarizer, imager — la fille rafraîchie perdait son
    apparence de fille). Même décision que le gabarit : un lot existe et n'est pas unitaire.
    """
    batch = batch_of(element)
    return bool(batch is not None and not batch.is_unitary)


def batch_snapshot(element):
    """Référence `(modèle de lot, id)` du lot de l'élément, ou None — à relever AVANT sa suppression.

    Après, la liaison est partie avec l'élément (cascade) et `batch_of` ne trouverait plus
    rien. On garde une RÉFÉRENCE et non l'instance : sur la forme à FK directe, l'instance est
    celle-là même que le signal `batch_sync` supprime quand le lot se vide — sa clé primaire
    passe alors à None et elle ne désigne plus rien.
    """
    batch = batch_of(element)
    return None if batch is None else (type(batch), batch.pk)


def batch_state(snapshot, element_model):
    """État du lot APRÈS le retrait d'un élément — ce que la brique `queue-actions.js` affiche.

    Rend None si l'élément n'était dans aucun lot, sinon ``{'id', 'total', **status_counts}``.
    ``total == 0`` : le lot a disparu (`batch_sync` supprime un lot vidé) ; ``1`` : il
    redevient une card simple ; au-delà, la card mère change ses compteurs.

    Remplace le drapeau `batch_changed` (2026-09-15) : il ne disait que « il y avait un lot »,
    et la brique ne savait qu'en faire une chose — recharger la page, ce qui ramène
    l'utilisateur en haut de la file. Le serveur dit maintenant CE QUE DEVIENT le lot, et la
    brique met la file à jour sans rechargement de la page.
    """
    if snapshot is None:
        return None
    batch_model, batch_id = snapshot
    batch = batch_model.objects.filter(pk=batch_id).first()
    if batch is None:
        return {'id': batch_id, 'total': 0}
    return {'id': batch_id, 'total': batch.total,
            **status_counts(batch_elements(batch, element_model))}


def batch_model_for_app(app_name):
    """Idem depuis un nom de SURFACE (`'enhancer'`, `'audio_enhancer'`…).

    Passe par `PreviewRegistry`, déjà l'annuaire surface → modèle d'élément du dépôt
    (manifestes, grille de conformité, scénarios nocturnes le lisent). ⚠ La clé est la
    SURFACE et non l'app Django : l'enhancer en expose deux (`enhancer` et
    `audio_enhancer`), avec deux modèles d'élément et deux modèles de lot distincts.
    """
    from wama.common.utils.preview_registry import PreviewRegistry
    return batch_model_for(PreviewRegistry.get_model(app_name))
