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
            self._enregistrer_registres()
        except Exception:
            log.warning('wama_data registres non déclarés', exc_info=True)

    # ──────────────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _enregistrer_registres():
        """Les deux CAPACITÉS AGRÉGATIVES du monde Data rejoignent le registre des registres.

        Doctrine : `WAMA_DATA_WORLD.md §9quinquies` — la MÉTHODE (importer, exporter) est
        universelle et s'écrit une fois ; les TYPES qu'elle sait traiter sont une capacité qui
        s'AGRÈGE, comme on ajoute un modèle IA. Une capacité qui s'agrège doit être visible et
        comptable, donc elle entre ici.
        """
        from wama.common.registries import REDECLARATION, Registre, Resultat, enregistrer

        # ── Lecteurs d'entrée (Importer + Connector : ils partagent le même registre) ─────────
        def _compter_lecteurs() -> int:
            from .sources import READERS
            return len(READERS)

        def _rafraichir_lecteurs() -> Resultat:
            """Re-déclare les lecteurs en RECHARGEANT les modules du paquet `sources`.

            ⚠ TROIS PIÈGES, tous déjà rencontrés par le rafraîchisseur de fonctions — on reprend
            sa séquence au lieu de la redécouvrir :

              ① `importlib.reload(sources)` NE SUFFIT PAS et vide même le registre. Le paquet
                 repeuple via `_register_builtins()`, qui fait `from . import trip, tabular` :
                 des modules DÉJÀ en cache, donc un import no-op. On rechargerait un `READERS`
                 neuf que personne ne remplirait.
              ② `register_reader()` LÈVE sur format dupliqué — recharger sans purger échouerait
                 au premier module.
              ③ Sans `invalidate_caches()`, un fichier CRÉÉ pendant que le serveur tourne reste
                 invisible : le chercheur de modules garde en cache le listing du répertoire.

            D'où : instantané → purge → rechargement → RESTAURATION si quoi que ce soit casse.
            Un registre à moitié rechargé serait pire que pas de rechargement.
            """
            import importlib

            from . import sources
            importlib.invalidate_caches()
            avant = dict(sources.READERS)
            # ⚠ La découverte a UN SEUL domicile : `sources.modules_lecteurs()`. Elle vivait ici
            # en copie, alors que le paquet lui-même en avait besoin pour son propre amorçage
            # (garde-fou G1). Deux énumérations du même ensemble finissent par diverger.
            noms = sources.modules_lecteurs()
            sources.READERS.clear()
            try:
                for nom in noms:
                    mod = importlib.import_module(f'{sources.__name__}.{nom}')
                    importlib.reload(mod)
            except Exception as e:
                sources.READERS.clear()
                sources.READERS.update(avant)          # restauration intégrale
                return Resultat(ok=False, total=len(avant),
                                messages=(f"rechargement abandonné, registre restauré : {e}",))
            apres = set(sources.READERS)
            return Resultat(ok=True, ajoutes=len(apres - set(avant)),
                            retires=len(set(avant) - apres), modifies=len(apres & set(avant)),
                            total=len(apres),
                            messages=(f"{len(noms)} module(s) de lecture rechargé(s)",))

        enregistrer(Registre(
            cle='lecteurs_data', nom="Formats d'entrée (WAMA Data)", nature=REDECLARATION,
            source="`wama_data/sources/` — un lecteur par format, inscrit à l'import",
            rafraichir=_rafraichir_lecteurs, compter=_compter_lecteurs,
            manifest_kind='dataset', doc='WAMA_DATA_WORLD.md §6.6, §9quinquies',
            description="Recharge les lecteurs de sources. Ajouter un format d'import ou de "
                        "connexion = déposer un lecteur, jamais éditer le moteur — l'Importer et "
                        "le Connector partagent ce registre.",
        ))

        # ── Formats de sortie (Exporter) ─────────────────────────────────────────────────────
        def _compter_formats() -> int:
            from .core.export import FORMATS
            return len(FORMATS)

        enregistrer(Registre(
            cle='formats_export_data', nom='Formats de sortie (WAMA Data)', nature=REDECLARATION,
            source="`wama_data/core/export.py` — `enregistrer_format()`, plus les écrivains "
                   "fournis par les adaptateurs",
            compter=_compter_formats,
            rafraichir=lambda: _rafraichir_formats(),
            doc='WAMA_DATA_WORLD.md §9ter.6 C, §9quinquies',
            description="Formats que l'Exporter sait NOMMER, et parmi eux ceux qu'il sait "
                        "ÉCRIRE — l'écart entre les deux est la dette, et elle est mesurée.",
        ))


def _rafraichir_formats():
    """Ré-importe l'adaptateur d'export : c'est lui qui peut FOURNIR les écrivains des formats
    déclarés sans écrivain (`xlsx`, `mat`).

    ⚠ On ne purge PAS `FORMATS` ici, contrairement aux lecteurs — et la différence n'est pas une
    inattention. `enregistrer_format()` est IDEMPOTENT par extension (le dernier inscrit gagne,
    précisément pour qu'un adaptateur puisse compléter un format déclaré sans écrivain), là où
    `register_reader()` lève sur doublon. La purge n'est nécessaire que quand le ré-enregistrement
    échouerait ; l'appliquer ici perdrait les formats natifs du cœur, que rien ne réenregistrerait.
    """
    import importlib

    from wama.common.registries import Resultat

    from .core.export import FORMATS, formats_ecrivables
    avant_total, avant_ecrivables = len(FORMATS), set(formats_ecrivables())
    importlib.invalidate_caches()
    try:
        from .functions.io import export as adaptateur
        importlib.reload(adaptateur)
    except Exception as e:
        return Resultat(ok=False, total=len(FORMATS),
                        messages=(f"adaptateur d'export non rechargé : {e}",))
    apres_ecrivables = set(formats_ecrivables())
    return Resultat(
        ok=True, ajoutes=len(FORMATS) - avant_total,
        retires=0, modifies=len(apres_ecrivables - avant_ecrivables), total=len(FORMATS),
        messages=(f"{len(apres_ecrivables)}/{len(FORMATS)} format(s) réellement écrivable(s)",))
