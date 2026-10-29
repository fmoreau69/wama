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


def supersede(old_key: str, new_key: str, *, apply: bool = True) -> dict:
    """Fait de `new_key` le successeur de `old_key` partout où l'ancien était CHOISI, puis retire
    l'ancien des choix. `apply=False` compte sans rien écrire (le relevé à lire avant).

    Rend {'cards': {surface.champ: n}, 'user_settings': n, 'batch_settings': n,
    'withdrawn': [...]} ; {'error': …} si une des deux lignes manque ou si elles sont la même."""
    from django.db import transaction

    from wama.common.models import BatchSettings, UserAppSetting

    from ..models import AIModel
    old = AIModel.objects.filter(model_key=old_key, is_proposed=False).first()
    new = AIModel.objects.filter(model_key=new_key, is_proposed=False).first()
    if old is None or new is None or old.pk == new.pk:
        return {'error': f"succession impossible : {old_key!r} → {new_key!r} "
                         "(deux lignes distinctes du catalogue attendues)"}

    cards, settings_n, batches_n = {}, 0, 0
    with transaction.atomic():
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

        withdrawn = []
        if apply:
            from django.utils import timezone

            from .model_installer import withdraw_from_choices
            from ..models import WITHDRAWN_SUPERSEDED
            withdrawn = withdraw_from_choices([old], timezone.now().isoformat(),
                                              by=WITHDRAWN_SUPERSEDED, superseded_by=new_key)
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
