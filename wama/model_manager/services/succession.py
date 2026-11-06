"""
SUCCESSION d'un modèle — quand une nouvelle version s'installe, elle REMPLACE l'ancienne partout
où l'ancienne était choisie (2026-10-29, demande de Fabien : « quand on a une montée de version,
il faudrait que le remplacement se fasse le plus naturellement possible à tous les endroits où le
modèle plus ancien était »).

Le LIEN existait déjà : une proposition de mise à jour porte la ligne qu'elle vise
(`extra_info['prospect']['origin_key']`, écrit par `prospect_ollama` et `seed_hf_successors`).
Seule la branche Ollama d'`install_candidate` en tirait une conséquence — le retrait de l'ancien,
au catalogue seulement ; un successeur du Hub s'installait à côté, et les cards, les réglages
mémorisés, le tirage continuaient de nommer l'ancien. Vécu avec olmOCR v1 → olmOCR-2.

Les ENDROITS qui nomment un modèle ne se listent pas ici : ils se DÉRIVENT des déclarations.
  • les colonnes de card — les réglages « catalogue » (`options_source='catalog'`) de TOUS les
    schémas de l'app (`auto_model.catalog_fields`) qui sont des colonnes du modèle
    d'élément déclaré (`DetailRegistry`) ;
  • les réglages MÉMORISÉS des utilisateurs (`common.UserAppSetting`) — une valeur qui EST la clé
    de l'ancien, ou son identifiant nu sous le nom d'un de ces réglages ;
  • les réglages de LOT (`common.BatchSettings`), par les mêmes noms.
Une colonne d'HISTOIRE (le moteur EMPLOYÉ, `used_backend`) n'est pas un réglage : elle dit ce qui a
tourné, elle ne change pas. L'ancien sort des choix comme une ligne désinstallée
(`model_installer.withdraw_from_choices`, origine `superseded`), ses poids RESTENT — revenir en
arrière reste possible, et le désinstaller est un clic du model manager.

Le cas voisin, le MÊME modèle sous une autre clé (un poids renommé, 2026-11-06), est `rekey` : les
mêmes choix suivent, et avec eux ce qui était mesuré de ces poids ; l'ancienne ligne, sans fichier,
quitte le catalogue.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def model_reference_fields() -> list:
    """`[(surface, modèle, champ, source)]` : chaque colonne de card qui NOMME un modèle du
    catalogue — dérivée des schémas et des modèles d'élément DÉCLARÉS, jamais listée. `source` est
    l'espace d'un identifiant nu (la source que le réglage borne, sinon l'app qui l'écrit)."""
    from wama.common.utils.detail_registry import DetailRegistry
    out = []
    for surface in DetailRegistry.registered_apps():
        model = (DetailRegistry.get(surface) or {}).get('model')
        if model is None:
            continue
        app = model._meta.app_label
        concrete = {f.name for f in model._meta.concrete_fields}
        for name, source in sorted(catalog_settings(app).items()):
            if name in concrete:
                out.append((surface, model, name, source))
    return out


def catalog_settings(app: str) -> dict:
    """`{nom du réglage: source de ses identifiants nus}` des réglages d'une app qui CHOISISSENT un
    modèle du catalogue, tous schémas confondus — la lecture commune `auto_model.catalog_fields`.
    Un réglage mémorisé se range sous son NOM ou sous l'identifiant de son champ au volet
    (`panel_dom_id`, la clé par défaut de `user_settings.read_panel_settings`) : les deux y sont."""
    from wama.common.utils.auto_model import catalog_fields
    from wama.common.utils.param_schema import panel_dom_id
    out = {}
    for field in catalog_fields(app):
        source = (field.get('options_query') or {}).get('source') or app
        for name in (field.get('name'), panel_dom_id(field)):
            if name:
                out[name] = source
    return out


def _names_the_model(value, old_key: str, source: str) -> bool:
    """La valeur stockée désigne-t-elle `old_key` (clé entière, ou identifiant nu dans `source`) ?"""
    from wama.common.utils.model_keys import catalog_key
    return isinstance(value, str) and bool(value) and catalog_key(value, source) == old_key


def _stored_form(new_key: str, source: str, value: str) -> str:
    """La valeur à écrire à la place : la forme que le réglage stocke déjà — un identifiant nu
    quand l'ancienne valeur l'était et que le successeur vit dans la même source, sinon la clé."""
    from wama.common.utils.model_keys import split_key
    new_source, new_id = split_key(new_key)
    bare_before = not split_key(value)[0]
    return new_id if (bare_before and new_source == source) else new_key


def _setting_name_matches(stored_name: str, names) -> bool:
    """Un réglage mémorisé se range sous le nom du param, ou `<domaine>.<nom>` (`domain_key`)."""
    return any(stored_name == n or stored_name.endswith('.' + n) for n in names)


def _two_rows(old_key: str, new_key: str):
    """`(ancienne, nouvelle)` lignes du catalogue, ou `(None, None)` si l'une manque ou si ce sont
    la même."""
    from ..models import AIModel
    old = AIModel.objects.filter(model_key=old_key, is_proposed=False).first()
    new = AIModel.objects.filter(model_key=new_key, is_proposed=False).first()
    if old is None or new is None or old.pk == new.pk:
        return None, None
    return old, new


def _follow_choices(old_key: str, new_key: str, apply: bool) -> tuple:
    """Les CHOIX qui nommaient `old_key` nomment `new_key` : colonnes de card, réglages mémorisés,
    réglages de lot (les endroits DÉRIVÉS, cf. l'en-tête). Rend `(cards, réglages, lots)` comptés ;
    n'écrit qu'avec `apply`. Corps commun de la succession et du changement de clé (`rekey`)."""
    from wama.common.models import BatchSettings, UserAppSetting

    cards, settings_n, batches_n = {}, 0, 0
    for surface, model, field, source in model_reference_fields():
        rows = [(pk, value) for pk, value in model.objects.values_list('pk', field)
                if _names_the_model(value, old_key, source)]
        if not rows:
            continue
        cards[f'{surface}.{field}'] = len(rows)
        if apply:
            for pk, value in rows:
                model.objects.filter(pk=pk).update(**{field: _stored_form(new_key, source, value)})

    names_by_app = {}
    for setting in UserAppSetting.objects.all().only('pk', 'app', 'name', 'value'):
        names = names_by_app.setdefault(setting.app, catalog_settings(setting.app))
        value = setting.value
        if value == old_key:
            source = setting.app
        else:
            matched = [n for n in names if _setting_name_matches(setting.name, [n])]
            if not matched or not _names_the_model(value, old_key, names[matched[0]]):
                continue
            source = names[matched[0]]
        settings_n += 1
        if apply:
            UserAppSetting.objects.filter(pk=setting.pk).update(
                value=_stored_form(new_key, source, value))

    for lot in BatchSettings.objects.all().only('pk', 'app', 'settings'):
        names = names_by_app.setdefault(lot.app, catalog_settings(lot.app))
        values = dict(lot.settings or {})
        changed = {n: _stored_form(new_key, names[n], values[n]) for n in names
                   if n in values and _names_the_model(values[n], old_key, names[n])}
        if changed:
            batches_n += 1
            if apply:
                BatchSettings.objects.filter(pk=lot.pk).update(settings={**values, **changed})
    return cards, settings_n, batches_n


def _weights_file(row):
    """Le fichier (ou dossier) de poids que la ligne désigne — `extra_info['path']`, sinon
    `local_path` (la lecture de `_drop_rows_superseded_by_location`) — ou None."""
    from pathlib import Path
    value = (row.extra_info or {}).get('path') or row.local_path
    return Path(value) if value else None


def rekey(old_key: str, new_key: str, *, apply: bool = True) -> dict:
    """Le MÊME modèle — les mêmes poids — change de CLÉ : tout ce qui le désignait suit, puis
    l'ancienne ligne sort du catalogue.

    Vécu le 2026-11-06 (Fabien : « renomme le fichier yolo11l pour l'aligner sur le dépôt ») : un
    poids YOLO renommé à la main avant la chaîne d'installation (`yolo11l_face_plate_signs.pt`, que
    le dépôt Panoramax publie `yolo11l_panoramax.pt`, même sha256). Le balayage dérive la clé du NOM
    du fichier : le renommer fait naître une ligne, et laisse l'ancienne « installée » sur un
    fichier absent. Ce n'est PAS une succession (`supersede`) : l'ancien n'a plus de poids, il n'y a
    pas de retour arrière à garder, et ce que l'on avait MESURÉ de ces poids vaut pour la nouvelle
    clé. Ce qui suit, chacun par la voie qui l'écrit déjà :
      * les CHOIX — cards, réglages mémorisés, lots (`_follow_choices`, le corps de `supersede`) ;
      * les faits DÉCLARÉS de la ligne — licence, auteur, contrat de prompt, publications… : la
        fiche de l'ancienne superposée à celle de la nouvelle, les VIDES seuls comblés
        (`proposals.fill_empty`), projetée par `write_back_model` — une anatomie ou une capacité
        que la découverte vient d'écrire n'est jamais remplacée ;
      * les MESURES des poids — la vitesse apprise (`ModelRuntimeStat`, par matériel ; une mesure
        déjà présente sous la nouvelle clé pour le même matériel est gardée, l'ancienne est
        signalée, jamais fusionnée), les évaluations de résultats (`ResultEvaluation`) ;
      * le CORPUS — la fiche de l'ancienne en part, celle de la nouvelle s'écrit (`corpus.follow`).
    L'HISTOIRE ne bouge pas (colonnes `used_backend`, conversations, journal des installations).

    Gardes, lues sur les lignes : l'ancienne ne désigne plus aucun fichier présent (sinon ce sont
    deux copies — une succession), la provenance est la même (`platform_ref`, ou absente d'un côté)
    et la taille aussi quand les deux la portent. `apply=False` compte et n'écrit rien."""
    from django.db import transaction

    from wama.common.models import ResultEvaluation

    from ..models import AIModel, ModelRuntimeStat
    old, new = _two_rows(old_key, new_key)
    if old is None:
        return {'error': f"changement de clé impossible : {old_key!r} → {new_key!r} "
                         "(deux lignes distinctes du catalogue attendues)"}
    weights = _weights_file(old)
    if weights is not None and weights.exists():
        return {'error': f"{old_key} désigne encore des poids présents ({weights}) : deux copies, "
                         "pas un changement de clé — `supersede` fait la succession"}
    if old.platform_ref and new.platform_ref and old.platform_ref != new.platform_ref:
        return {'error': f"provenances différentes ({old.platform_ref} ≠ {new.platform_ref}) : "
                         "pas le même modèle"}
    sizes = [(r.extra_info or {}).get('size_bytes') for r in (old, new)]
    if all(sizes) and sizes[0] != sizes[1]:
        return {'error': f"tailles différentes ({sizes[0]} ≠ {sizes[1]} octets) : pas les mêmes poids"}

    from wama.common.manifests.builtin.model import extract_model, write_back_model
    from wama.common.manifests.proposals import fill_empty
    old_sheet, new_sheet = extract_model(old_key), extract_model(new_key)
    body, filled, _ = fill_empty(new_sheet.get('body') or {}, old_sheet.get('body') or {}, 'body')

    stats = ModelRuntimeStat.objects.filter(model_key=old_key)
    taken = set(ModelRuntimeStat.objects.filter(model_key=new_key)
                .values_list('hardware_fingerprint', flat=True))
    moving = [s.pk for s in stats if s.hardware_fingerprint not in taken]
    kept_apart = [s.hardware_fingerprint for s in stats if s.hardware_fingerprint in taken]
    evaluations = ResultEvaluation.objects.filter(model_key=old_key)

    result = {'old': old_key, 'new': new_key, 'applied': apply, 'filled': filled,
              'runtime_stats': len(moving), 'runtime_stats_kept_apart': kept_apart,
              'evaluations': evaluations.count()}
    with transaction.atomic():
        cards, settings_n, batches_n = _follow_choices(old_key, new_key, apply)
        result.update(cards=cards, user_settings=settings_n, batch_settings=batches_n)
        if apply:
            write_back_model({**new_sheet, 'body': body}, apply=True)
            ModelRuntimeStat.objects.filter(pk__in=moving).update(model_key=new_key)
            evaluations.update(model_key=new_key)
            AIModel.objects.filter(pk=old.pk).delete()
    if apply:
        # Le corpus SUIT les deux clés, par sa porte commune (`forget_in_corpus` → `corpus.follow`,
        # celle de la désinstallation) : la fiche d'une clé disparue part, l'autre s'écrit.
        from .model_installer import forget_in_corpus
        forget_in_corpus([old_key, new_key])
    logger.info("[succession] clé %s → %s : %s", old_key, new_key, result)
    return result


def supersede(old_key: str, new_key: str, *, apply: bool = True) -> dict:
    """Fait de `new_key` le successeur de `old_key` partout où l'ancien était CHOISI, puis retire
    l'ancien des choix. `apply=False` compte sans rien écrire (le relevé à lire avant).

    Rend {'cards': {surface.champ: n}, 'user_settings': n, 'batch_settings': n,
    'withdrawn': [...]} ; {'error': …} si une des deux lignes manque ou si elles sont la même."""
    from django.db import transaction

    old, _ = _two_rows(old_key, new_key)
    if old is None:
        return {'error': f"succession impossible : {old_key!r} → {new_key!r} "
                         "(deux lignes distinctes du catalogue attendues)"}

    with transaction.atomic():
        cards, settings_n, batches_n = _follow_choices(old_key, new_key, apply)
        withdrawn = []
        if apply:
            from django.utils import timezone

            from .model_installer import withdraw_from_choices
            from ..models import WITHDRAWN_SUPERSEDED
            withdrawn = withdraw_from_choices([old], timezone.now().isoformat(),
                                              by=WITHDRAWN_SUPERSEDED, superseded_by=new_key)
            # Le corpus SUIT (2026-11-02) : la fiche de l'ancien porte son exclusion, et les apps
            # qui le proposaient ne le proposent plus — la porte commune, que la désinstallation
            # emprunte aussi (`forget_in_corpus`).
            from .model_installer import forget_in_corpus
            forget_in_corpus(withdrawn)
    result = {'old': old_key, 'new': new_key, 'applied': apply, 'cards': cards,
              'user_settings': settings_n, 'batch_settings': batches_n, 'withdrawn': withdrawn}
    logger.info("[succession] %s → %s : %s", old_key, new_key, result)
    return result


def supersede_after_install(cand, installed_keys) -> dict | None:
    """La succession d'une proposition de MISE À JOUR qu'on vient d'installer, ou None : elle ne
    joue que pour un candidat `update` qui nomme la ligne visée (`origin_key`) et dont
    l'installation a fait naître UNE ligne — plusieurs, on ne devine pas laquelle succède.
    Best-effort : une succession manquée ne défait jamais une installation réussie."""
    prospect = (cand.extra_info or {}).get('prospect') or {}
    origin = prospect.get('origin_key')
    keys = [k for k in dict.fromkeys(installed_keys or ()) if k and k != origin]
    if cand.proposal_kind != 'update' or not origin or len(keys) != 1:
        return None
    try:
        return supersede(origin, keys[0])
    except Exception as e:
        logger.warning("[succession] %s → %s non appliquée : %s", origin, keys[0], e,
                       exc_info=True)
        return {'error': f"{type(e).__name__}: {e}"}


def installed_keys(res: dict) -> list:
    """Les clés que l'installation a atteintes : celles qui ont reçu leur identité
    (`record_provenance` → `provenance.models`)."""
    models = ((res or {}).get('provenance') or {}).get('models') or []
    return [m.get('model') for m in models if isinstance(m, dict) and m.get('model')]
