"""
Context processors for the accounts app.
"""
import json as _json


def user_role(request):
    """Add user role and preferences to template context."""
    from .views import is_admin, is_dev, get_user_role

    user = request.user

    # Preferred language + UI mode (defaults for unauthenticated users)
    preferred_language = 'fr'
    ui_mode = 'advanced'
    card_layout = 'list'
    card_stacked = False
    card_design = 'v3'
    inspector_autoplay = False
    if user.is_authenticated:
        try:
            preferred_language = user.profile.preferred_language
            ui_mode = user.profile.ui_mode
            card_layout = user.profile.card_layout
            card_stacked = user.profile.card_stacked
            card_design = user.profile.card_design
            inspector_autoplay = user.profile.inspector_autoplay
        except Exception:
            pass

    # App catalog JSON — injected into base.html for FileManager JS
    # Computed once per request; small enough that caching isn't necessary
    try:
        from wama.common.app_registry import get_app_extensions_for_filemanager, APP_CATALOG
        _ext = get_app_extensions_for_filemanager()
        _catalog_for_js = {
            name: {
                'label': spec['label'],
                'icon':  spec['icon'],
                'color': spec.get('color', ''),
                'input_extensions': _ext[name],
                'has_batch':      spec['has_batch'],
                'has_url_import': spec['has_url_import'],
                # Catégorie + couleur d'identité dérivée (APP_CATEGORIES / CARD_DESIGN §9) :
                # la nav, le studio et le filemanager peuvent grouper/teinter (2026-07-05).
                'category':       spec.get('category', ''),
                'color':          spec.get('color', ''),
            }
            for name, spec in APP_CATALOG.items()
        }
        app_catalog_json = _json.dumps(_catalog_for_js)
    except Exception:
        app_catalog_json = '{}'

    try:
        from wama.converter.utils.format_router import CONVERTER_OUTPUT_FORMATS
        converter_output_formats_json = _json.dumps(CONVERTER_OUTPUT_FORMATS)
    except Exception:
        converter_output_formats_json = '{}'

    # Accès par profil/rôles (axe A tier + axe B rôles métier) — exposé pour filtrer la nav.
    # Non bloquant ici : c'est la nav/les vues qui décideront d'utiliser `accessible_apps`.
    try:
        from wama.accounts.permissions import user_tier, user_roles as _roles, accessible, all_gated_apps
        account_tier = user_tier(user)
        roles_set = sorted(_roles(user))
        accessible_apps = {a for a in all_gated_apps() if accessible(user, 'app', a)}
    except Exception:
        account_tier, roles_set, accessible_apps = 'utilisateur', [], set()

    # ABONNEMENT (PROFILES_PERMISSIONS §8) — la PRÉFÉRENCE, appliquée APRÈS le droit et
    # seulement à l'affichage. Elle ne peut qu'enlever : `masques` est un ensemble d'apps que
    # l'utilisateur a lui-même masquées parmi celles auxquelles il a DÉJÀ droit. Le menu montre
    # « mes applications » ; le catalogue `/apps/` continue de montrer TOUT, avec la bascule.
    try:
        from wama.common.services.subscriptions import masques as _masques
        apps_masquees = _masques(user, 'app') & accessible_apps
    except Exception:
        apps_masquees = set()

    # Menu « Applications » GROUPÉ par catégorie (APP_CATEGORIES) — GÉNÉRÉ du catalogue,
    # filtré par accessible_apps ; les extra_links portent gate/nav_hide (décision 2026-07-05).
    try:
        from django.urls import reverse as _reverse
        from wama.common.app_registry import get_apps_by_category
        nav_apps_grouped = []
        _sandbox_entries = []
        for _cid, _meta, _apps in get_apps_by_category():
            _entries = []
            for _name, _spec in _apps:
                if _name not in accessible_apps or _name in apps_masquees:
                    continue
                try:
                    _entry = {'name': _name, 'label': _spec['label'], 'icon': _spec['icon'],
                              'color': _spec.get('color', ''), 'url': _reverse(_spec['url_name']),
                              'description': _spec.get('description', '')}
                except Exception:
                    continue
                # Jumelles de bac à sable → groupe DÉDIÉ en queue de menu (demande Fabien
                # 03/09 : à un bac à sable par app portée, les catégories deviendraient
                # illisibles). Libellé = source + identifiant (le badge « ⚠ BAC À SABLE »
                # du catalogue serait redondant sous cet en-tête de groupe).
                if _spec.get('sandbox'):
                    _base = _spec['label'].replace(' ⚠ BAC À SABLE', '').strip()
                    _entry['label'] = f"{_base} ({_name})"
                    _sandbox_entries.append(_entry)
                    continue
                _entries.append(_entry)
            _links = []
            for _link in _meta.get('extra_links', []):
                if _link.get('nav_hide'):
                    continue
                _gate = _link.get('gate')
                if _gate and _gate not in accessible_apps:
                    continue
                # …puis la PRÉFÉRENCE, dans le même ordre que pour les cards : une surface
                # transversale (studio, médiathèque) ou Lab se masque comme une app, par la même
                # clé `gate`. Elle reste retrouvable au catalogue, avec sa bascule.
                if _gate and _gate in apps_masquees:
                    continue
                try:
                    _links.append({**_link, 'url': _reverse(_link['url_name'])})
                except Exception:
                    # JAMAIS d'omission silencieuse (leçon WAMA Lab disparu, 2026-07-05) :
                    # un lien déclaré qui ne résout pas = un warning visible dans les logs.
                    import logging
                    logging.getLogger('wama.nav').warning(
                        "Menu : lien '%s' (%s) omis — URL irrésolvable",
                        _link.get('label'), _link.get('url_name'))
                    continue
            if _entries or _links:
                nav_apps_grouped.append({'id': _cid, 'meta': _meta, 'apps': _entries, 'links': _links})
        if _sandbox_entries:
            nav_apps_grouped.append({'id': 'sandbox',
                                     'meta': {'label': 'Bac à sable', 'icon': '🧪'},
                                     'apps': _sandbox_entries, 'links': []})
    except Exception:
        nav_apps_grouped = []

    # Couleur d'IDENTITÉ de l'app courante (liseré des cards — CARD_DESIGN §9) : dérivée du
    # 1er segment du path si c'est une app du catalogue. Identité ≠ état (jamais sur les barres).
    # `current_app` : l'ID d'app était DÉJÀ dérivé ici pour la couleur, mais jeté après usage —
    # chaque app le re-codait en dur dans son JS (listener wama:fileimported ×7). On l'expose.
    current_app_color, current_app, current_app_spec = '', '', None
    try:
        from wama.common.app_registry import APP_CATALOG as _AC
        _seg = (request.path.split('/') + [''])[1]
        if _seg in _AC:
            current_app = _seg
            current_app_color = _AC[_seg].get('color', '')
            # Spec CATALOGUE de l'app courante — nourrit les blocs par défaut du gabarit
            # commun (onglets À-propos/Aide auto-générés des métadonnées, brique 2026-08-11).
            current_app_spec = _AC[_seg]
    except Exception:
        pass

    return {
        'is_admin': is_admin(user),
        'is_dev': is_dev(user),
        'user_role': get_user_role(user),
        'preferred_language': preferred_language,
        'ui_mode': ui_mode,
        'card_layout': card_layout,
        'card_stacked': card_stacked,
        'card_design': card_design,
        'inspector_autoplay': inspector_autoplay,
        'app_catalog_json': app_catalog_json,
        'nav_apps_grouped': nav_apps_grouped,
        'current_app': current_app,
        'current_app_color': current_app_color,
        'current_app_spec': current_app_spec,
        'converter_output_formats_json': converter_output_formats_json,
        'account_tier': account_tier,
        'user_roles_set': roles_set,
        'accessible_apps': accessible_apps,
        # Nombre d'apps que l'utilisateur s'est lui-même masquées : le menu l'affiche pour que
        # « il en manque » ne devienne jamais « c'est cassé » — un filtrage silencieux serait
        # exactement la panne muette que le dépôt traque.
        'apps_masquees_count': len(apps_masquees),
    }
