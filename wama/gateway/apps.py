from django.apps import AppConfig


class GatewayConfig(AppConfig):
    """
    Passerelle de canaux conversationnels (Tchap/Matrix, Discord) — `ROADMAP.md` §19.

    App TECHNIQUE, délibérément HORS `APP_CATALOG` : le catalogue décrit les applications
    média (entrées/sorties typées, file d'attente, batch), et la grille de conformité ne
    note QUE ses entrées (`check_app_conformity` → `non_sandbox_apps(APP_CATALOG)`). Y
    inscrire la passerelle la ferait apparaître à 0/72 sur 72 critères dont aucun ne la
    concerne. Sa place, si une entrée de menu devient utile, est
    `APP_CATEGORIES['platform']['extra_links']` — là où vivent déjà Studio, la Médiathèque
    et la Gestion des modèles.

    ⚠ NOM DE L'APP. Le nom naturel était « channels » ; il est ÉCARTÉ parce qu'il est aussi
    celui de Django Channels — le label par défaut aurait rendu ce paquet impossible à
    installer plus tard. `gateway` est libre (aucun paquet homonyme dans requirements.txt).
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.gateway'
    verbose_name = 'Passerelle de canaux'
