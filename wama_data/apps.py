from django.apps import AppConfig


class WamaDataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama_data'
    verbose_name = 'WAMA Data'

    def ready(self):
        """Déclare au substrat ce que le monde Data apporte : ses fonctions et ses REGISTRES.

        C'est le monde qui se déclare, jamais le registre qui va chercher ses producteurs : avant
        ce déport, `common/apps.py` importait les fonctions Data et `load_all()` citait
        `wama_lab.cam_analyzer` en dur — le substrat connaissait deux mondes par leur nom. Même
        geste que `cam_analyzer/apps.py`, qui faisait déjà les choses correctement.

        ⚠ LA MÊME RAISON COMMANDE L'ENREGISTREMENT DES REGISTRES CI-DESSOUS. Les inscrire dans
        `common/registries_builtin.py` aurait été plus court, et aurait fait importer `wama_data`
        par le substrat — exactement le défaut qu'on vient de corriger, réintroduit par la porte
        d'à côté. Un monde POUSSE ses capacités vers le substrat ; le substrat ne tire jamais.
        """
        import logging
        log = logging.getLogger(__name__)
        try:
            from . import functions  # noqa: F401  (l'import enregistre les FunctionSpec)
        except Exception:
            log.warning('wama_data functions non enregistrées', exc_info=True)
        try:
            self._register_registries()
        except Exception:
            log.warning('wama_data registres non déclarés', exc_info=True)

    # ──────────────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _register_registries():
        """Les deux CAPACITÉS AGRÉGATIVES du monde Data rejoignent le registre des registres.

        Doctrine : `WAMA_DATA_WORLD.md §9quinquies` — la MÉTHODE (importer, exporter) est
        universelle et s'écrit une fois ; les TYPES qu'elle sait traiter sont une capacité qui
        s'AGRÈGE, comme on ajoute un modèle IA. Une capacité qui s'agrège doit être visible et
        comptable, donc elle entre ici.
        """
        from wama.common.registries import REDECLARATION, RefreshResult, Registry, register

        # ── Lecteurs d'entrée (Importer + Connector : ils partagent le même registre) ─────────
        def _count_readers() -> int:
            from .sources import READERS
            return len(READERS)

        def _refresh_readers() -> RefreshResult:
            from . import sources
            return _recharger_greffons(sources, sources.READERS, sources.reader_modules(),
                                       'lecture')

        register(Registry(
            key='lecteurs_data', label="Formats d'entrée (WAMA Data)", nature=REDECLARATION,
            source="`wama_data/sources/` — un lecteur par format, inscrit à l'import",
            refresh=_refresh_readers, count=_count_readers,
            manifest_kind='dataset', doc='WAMA_DATA_WORLD.md §6.6, §9quinquies',
            description="Recharge les lecteurs de sources. Ajouter un format d'import ou de "
                        "connexion = déposer un lecteur, jamais éditer le moteur — l'Importer et "
                        "le Connector partagent ce registre.",
        ))

        # ── Formats de sortie (Exporter) ─────────────────────────────────────────────────────
        def _count_formats() -> int:
            from .core.export import FORMATS
            return len(FORMATS)

        register(Registry(
            key='formats_export_data', label='Formats de sortie (WAMA Data)', nature=REDECLARATION,
            source="`wama_data/core/export.py` — `register_format()`, plus les écrivains "
                   "fournis par les adaptateurs",
            count=_count_formats,
            refresh=lambda: _refresh_formats(),
            doc='WAMA_DATA_WORLD.md §9ter.6 C, §9quinquies',
            description="Formats que l'Exporter sait NOMMER, et parmi eux ceux qu'il sait "
                        "ÉCRIRE — l'écart entre les deux est la dette, et elle est mesurée.",
        ))

        # ── Schémas de CONTENEUR (l'écrivain) ────────────────────────────────────────────────
        def _count_containers() -> int:
            from .containers import SCHEMAS
            return len(SCHEMAS)

        def _refresh_containers() -> RefreshResult:
            from . import containers
            return _recharger_greffons(containers, containers.SCHEMAS,
                                       containers.schema_modules(), 'schéma')

        register(Registry(
            key='conteneurs_data', label='Schémas de conteneur (WAMA Data)', nature=REDECLARATION,
            source="`wama_data/containers/` — un schéma par format de sortie, inscrit à l'import",
            refresh=_refresh_containers, count=_count_containers,
            doc='WAMA_DATA_WORLD.md §9quater.2 (D3), §9quinquies',
            description="Conteneurs que WAMA Data sait ÉCRIRE : `.wdat` natif et `.trip` pour la "
                        "compatibilité BIND. Un moteur, N schémas — ajouter un format = déposer "
                        "un module, jamais éditer le moteur (G1).",
        ))


def _recharger_greffons(paquet, registre: dict, naming, quoi: str):
    """Re-déclare les greffons d'un paquet en RECHARGEANT ses modules. Purge, ou restauration.

    ⚠ TROIS PIÈGES, tous rencontrés d'abord par le rafraîchisseur de fonctions — on reprend sa
    séquence au lieu de la redécouvrir :

      ① `importlib.reload(paquet)` NE SUFFIT PAS et vide même le registre : l'amorçage du paquet
         ré-importe des modules DÉJÀ en cache, donc un no-op. On rechargerait un registre neuf que
         personne ne remplirait.
      ② `register_reader()` / `register_schema()` LÈVENT sur doublon — recharger sans purger
         échouerait au premier module.
      ③ Sans `invalidate_caches()`, un fichier CRÉÉ pendant que le serveur tourne reste invisible :
         le chercheur de modules garde en cache le listing du répertoire.

    D'où : instantané → purge → rechargement → RESTAURATION intégrale si quoi que ce soit casse.
    Un registre à moitié rechargé serait pire que pas de rechargement.

    ⚠ FACTORISÉ LE 2026-08-24, à l'arrivée du registre des conteneurs. Le corps était écrit pour
    les lecteurs ; le second usage l'aurait recopié à l'identique, à trois identifiants près. La
    liste des modules est passée en paramètre plutôt que devinée : sa découverte a **un seul
    domicile**, dans le paquet concerné (garde-fou G1), et ce serait la redécouvrir ici que de la
    recalculer.
    """
    import importlib

    from wama.common.registries import RefreshResult as Result

    importlib.invalidate_caches()
    before = dict(registre)
    registre.clear()
    try:
        for name in naming:
            importlib.reload(importlib.import_module(f'{paquet.__name__}.{name}'))
    except Exception as e:
        registre.clear()
        registre.update(before)
        return Result(ok=False, total=len(before),
                        messages=(f"rechargement abandonné, registre restauré : {e}",))
    after = set(registre)
    return Result(ok=True, added=len(after - set(before)),
                    removed=len(set(before) - after), updated=len(after & set(before)),
                    total=len(after), messages=(f"{len(naming)} module(s) de {quoi} rechargé(s)",))


def _refresh_formats():
    """Ré-importe l'adaptateur d'export : c'est lui qui peut FOURNIR les écrivains des formats
    déclarés sans écrivain (`xlsx`, `mat`).

    ⚠ On ne purge PAS `FORMATS` ici, contrairement aux lecteurs — et la différence n'est pas une
    inattention. `register_format()` est IDEMPOTENT par extension (le dernier inscrit gagne,
    précisément pour qu'un adaptateur puisse compléter un format déclaré sans écrivain), là où
    `register_reader()` lève sur doublon. La purge n'est nécessaire que quand le ré-enregistrement
    échouerait ; l'appliquer ici perdrait les formats natifs du cœur, que rien ne réenregistrerait.
    """
    import importlib

    from wama.common.registries import RefreshResult as Result

    from .core.export import FORMATS, writable_formats
    avant_total, avant_ecrivables = len(FORMATS), set(writable_formats())
    importlib.invalidate_caches()
    try:
        from .functions.io import export as adaptateur
        importlib.reload(adaptateur)
    except Exception as e:
        return Result(ok=False, total=len(FORMATS),
                        messages=(f"adaptateur d'export non rechargé : {e}",))
    apres_ecrivables = set(writable_formats())
    return Result(
        ok=True, added=len(FORMATS) - avant_total,
        removed=0, updated=len(apres_ecrivables - avant_ecrivables), total=len(FORMATS),
        messages=(f"{len(apres_ecrivables)}/{len(FORMATS)} format(s) réellement écrivable(s)",))
