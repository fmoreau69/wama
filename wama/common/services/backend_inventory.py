"""
Registre des BACKENDS — vue DÉRIVÉE du vivier de moteurs de WAMA (demande Fabien 2026-09-03).

POURQUOI (deux besoins, une seule source)

  1. **Le LLM de la marche B** doit « piocher dans le vivier pour s'inspirer du plus
     approchant » : sans inventaire, il faut lire dix paquets `backends/` pour trouver le
     backend le plus proche de celui qu'on veut écrire. Ici, une entrée porte tout ce qui
     rend un voisinage calculable — nature d'entrée routée, SAVEUR de sortie
     (fichier/texte), paquets requis, VRAM, modèles servis.
  2. **La vision d'ensemble** depuis WAMA : une page au registre des registres, avec le
     lien modèle ↔ backend.

CE QUE CE MODULE N'EST PAS : un registre de plus. Il ne stocke RIEN et n'a pas de
rafraîchisseur (nature `DERIVED` de `registries.py`) — il LIT les déclarations qui existent
déjà, à chaque affichage :

    wama/<app>/backends/__init__.py   ROUTES / RESULT / NATURE_FIELD   (routage, marche B1)
    classes BaseModelBackend           REQUIRED_PACKAGES, recommended_vram_gb, description
    catalogue AIModel                  source=<app> + backend_ref      (modèles servis)

*Une page qui DÉRIVE ne peut pas diverger de ses sources* — c'est l'argument qui a écarté
un 5ᵉ registre pour les licences (`license_audit`), il vaut ici mot pour mot.

⚠ Le module ne cite AUCUNE app : il parcourt les apps installées et regarde si elles
portent un paquet `backends` (même règle que le registre de fonctions — « le registre ne
connaît jamais ses producteurs »). Une app ajoutée demain y apparaît sans toucher ce
fichier ; les jumelles de bac à sable sont marquées, jamais confondues avec leur source.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

#: Saveurs de sortie déclarées par `backends/__init__.RESULT` (marche B1) — ce que le
#: backend PRODUIT, donc ce que la tâche composée en fait. Défaut historique : 'file'.
SAVEURS = {
    'file': "écrit un fichier de sortie (la tâche range le chemin)",
    'text': "rend du texte (la tâche le persiste dans la colonne déclarée)",
}


@dataclass
class BackendEntry:
    """UN backend exécutable — la maille que le LLM compare pour trouver « le plus approchant »."""
    app: str
    #: Nom du callable ou de la classe tel qu'il est routé/enregistré.
    name: str
    #: Chemin d'import relatif au paquet de l'app (`backends.image_backend.describe_image`).
    path: str
    #: Nature(s) d'entrée qui mènent ici (clés de ROUTES) — vide si le backend n'est pas routé.
    natures: List[str] = field(default_factory=list)
    saveur: str = 'file'
    #: 'route' (déclaré dans ROUTES) ou 'classe' (sous-contrat BaseModelBackend).
    kind: str = 'route'
    packages: List[str] = field(default_factory=list)
    vram_gb: Optional[float] = None
    description: str = ''
    #: Modèles du catalogue servis par ce backend (clés AIModel).
    models: List[str] = field(default_factory=list)
    #: Comment le lien modèle↔backend a été établi : 'backend_ref' (déclaré) ou 'app' (déduit
    #: du fait que le modèle appartient à l'app). La PROVENANCE du lien se dit — un lien
    #: déduit n'a pas la valeur d'un lien déclaré.
    lien: str = ''

    @property
    def signature(self) -> str:
        """Empreinte de voisinage — ce sur quoi le LLM peut trier « le plus approchant »."""
        n = '+'.join(self.natures) or '—'
        return f"{n} → {self.saveur}"


@dataclass
class AppBackends:
    app: str
    #: Jumelle de bac à sable : porte le nom de sa source (jamais comptée comme une app de plus).
    generated_from: str = ''
    routes: dict = field(default_factory=dict)
    saveur: str = 'file'
    #: Colonne de nature DÉCLARÉE (`NATURE_FIELD`) — vide si l'app s'en remet au défaut.
    nature_field: str = ''
    #: Colonne EFFECTIVEMENT lue par le corps composé : la déclarée, ou le défaut historique
    #: `media_type` (pilote converter). La page montre celle-ci — afficher un blanc là où le
    #: générateur lit `media_type` laisserait croire à un trou (relevé par un test, 03/09).
    nature_effective: str = 'media_type'
    #: La nature vient-elle d'une déclaration explicite ? (déclaré ≠ hérité du défaut)
    nature_declaree: bool = False
    entries: List[BackendEntry] = field(default_factory=list)
    #: Ce qui manque pour que la chaîne de génération compose le corps de tâche de cette app.
    manque: str = ''
    #: Sous-modules du paquet qu'on n'a pas pu lire (dépendance absente) — DIT, jamais avalé.
    illisibles: List[str] = field(default_factory=list)


def _classe_backends(paquet) -> tuple:
    """(classes, illisibles) — sous-classes de `BaseModelBackend` de TOUT le paquet.

    ⚠ Balayer le seul `__init__` ne suffit pas (mesuré à l'écriture, 03/09) : 4 apps sur 9
    n'y ré-exportent pas leurs classes — elles seraient sorties du vivier en silence, et un
    inventaire qui rate des entrées est pire qu'aucun inventaire. On parcourt donc les
    SOUS-MODULES, en ne gardant que les classes qui y sont DÉFINIES (`__module__`), sinon un
    import partagé compterait deux fois.

    Un sous-module illisible (dépendance absente) est REMONTÉ, jamais avalé : c'est
    précisément l'information qu'un vivier doit donner.
    """
    import pkgutil
    from importlib import import_module

    try:
        from wama.common.backends.base import BaseModelBackend
    except Exception:
        return [], []

    modules = [paquet]
    illisibles = []
    for info in pkgutil.iter_modules(getattr(paquet, '__path__', []) or []):
        try:
            modules.append(import_module(f'{paquet.__name__}.{info.name}'))
        except Exception as e:
            illisibles.append(f'{info.name} ({type(e).__name__})')

    trouvees, vues = [], set()
    for mod in modules:
        for nom, obj in vars(mod).items():
            if (inspect.isclass(obj) and issubclass(obj, BaseModelBackend)
                    and obj is not BaseModelBackend
                    and obj.__module__.startswith(paquet.__name__)
                    and (obj.__module__, nom) not in vues):
                vues.add((obj.__module__, nom))
                trouvees.append((nom, obj))
    return trouvees, illisibles


def _modeles_par_app() -> dict:
    """{app: [(clé, backend_ref)]} depuis le CATALOGUE — jamais depuis les fichiers d'app.

    Le catalogue est la source unique de lecture des méta-modèles (règle du dépôt) ; on lit
    donc `AIModel.source` (le lien app↔modèles, 91/91 mesuré le 02/08) et `backend_ref`
    quand un modèle nomme SON backend.
    """
    out = {}
    try:
        from wama.model_manager.models import AIModel
        # ⚠ Le champ d'identité est `model_key`, PAS `key` — écrit de mémoire à la première
        # version, l'exception était avalée et la page annonçait « 0 modèle lié » sans rien
        # dire. *Vérifier un nom de champ, ne jamais le deviner.*
        for m in AIModel.objects.all().only('model_key', 'source', 'backend_ref'):
            out.setdefault(m.source or '', []).append(
                (m.model_key, getattr(m, 'backend_ref', '') or ''))
    except Exception as e:      # hors Django/base absente : l'inventaire reste utile sans
        logger.warning('[backends] catalogue illisible : %s', e)
    return out


def inventory() -> List[AppBackends]:
    """Le vivier, DÉRIVÉ à l'appel. Une app = une entrée ; jamais de nom d'app en dur ici."""
    from importlib import import_module

    from django.apps import apps as django_apps

    modeles = _modeles_par_app()
    resultat: List[AppBackends] = []

    for config in django_apps.get_app_configs():
        app = config.label
        try:
            paquet = import_module(f'{config.name}.backends')
        except Exception:
            continue                      # pas de paquet backends : ce n'est pas un défaut

        marque = ''
        try:
            from wama.common.app_registry import APP_CATALOG
            marque = (APP_CATALOG.get(app) or {}).get('generated_from') or ''
        except Exception:
            pass

        routes = dict(getattr(paquet, 'ROUTES', {}) or {})
        result = getattr(paquet, 'RESULT', None) or {}
        saveur = (result.get('kind') if isinstance(result, dict) else '') or 'file'
        nature_field = getattr(paquet, 'NATURE_FIELD', '') or ''

        # Modèles servis. ⚠ FAIT MESURÉ le 2026-09-03 : `AIModel.backend_ref` porte
        # aujourd'hui un nom d'APP (`sam3` → 'anonymizer'), pas un nom de backend — son sens
        # actuel est « cette app assume le moteur » (cf. `backends/manager.backend_missing`).
        # On ne fabrique donc PAS un lien fin qui n'existe pas : un `backend_ref` qui nomme
        # une entrée du vivier vaut lien DÉCLARÉ ; sinon le modèle est rattaché à l'app et la
        # page le dit « déduit ». C'est exactement le chantier ouvert (rendre `backend_ref`
        # déclaratif au manifeste modèle) — le laisser visible vaut mieux que le maquiller.
        par_ref, niveau_app = {}, []
        noms_connus = set()
        for chemin in routes.values():
            noms_connus.add(chemin.rsplit('.', 1)[-1])
        for cle, ref in modeles.get(app, []):
            if ref and ref != app:
                par_ref.setdefault(ref, []).append(cle)
            else:
                niveau_app.append(cle)

        entries: List[BackendEntry] = []

        #: ① Les callables ROUTÉS — la maille de la marche B1.
        chemins = {}
        for nature, chemin in routes.items():
            chemins.setdefault(chemin, []).append(nature)
        for chemin, natures in chemins.items():
            nom = chemin.rsplit('.', 1)[-1]
            entries.append(BackendEntry(
                app=app, name=nom, path=chemin, natures=sorted(natures), saveur=saveur,
                kind='route', models=sorted(par_ref.get(nom, [])),
                lien='backend_ref' if par_ref.get(nom) else ''))

        #: ② Les CLASSES au contrat commun (modèles chargés, VRAM comptée).
        classes, illisibles = _classe_backends(paquet)
        for nom, cls in classes:
            servis = sorted(par_ref.get(nom, []))
            entries.append(BackendEntry(
                app=app, name=nom,
                path=f'{cls.__module__.split(".", 2)[-1]}.{nom}',
                natures=[], saveur=saveur, kind='classe',
                packages=list(getattr(cls, 'REQUIRED_PACKAGES', []) or []),
                vram_gb=getattr(cls, 'recommended_vram_gb', None),
                description=(getattr(cls, 'description', '') or '').strip(),
                models=servis or sorted(niveau_app),
                lien='backend_ref' if servis else ('app' if niveau_app else '')))

        if not entries and not illisibles:
            continue

        # Ce qui manque pour COMPOSER (dit ici parce que c'est la seule page qui voit les
        # trois déclarations ensemble ; la grille le mesure app par app, cf. backend_routes).
        manque = ''
        if not routes:
            manque = "pas de ROUTES — le corps de tâche généré reste un trou marqué"
        elif saveur == 'text' and not (result.get('field') if isinstance(result, dict) else ''):
            manque = "RESULT.kind='text' sans `field` — la tâche ne saurait où persister"
        elif not nature_field and 'media_type' not in routes:
            manque = ''      # défaut historique media_type : légitime, rien à signaler

        resultat.append(AppBackends(
            app=app, generated_from=marque, routes=routes, saveur=saveur,
            nature_field=nature_field,
            nature_effective=nature_field or 'media_type',
            nature_declaree=bool(nature_field),
            entries=entries, manque=manque, illisibles=illisibles))

    return sorted(resultat, key=lambda a: (bool(a.generated_from), a.app))


def summary() -> dict:
    """Chiffres de tête de page + le vivier. Aucun compteur recopié ailleurs (un chiffre vit
    à UN endroit) : tout est dérivé de `inventory()`."""
    apps = inventory()
    reels = [a for a in apps if not a.generated_from]
    entrees = [e for a in reels for e in a.entries]
    # ⚠ Un modèle servi par plusieurs entrées d'une même app (rattachement de NIVEAU APP)
    # ne compte qu'UNE fois : un total qui additionne les cartes annoncerait plus de modèles
    # liés que le catalogue n'en a — *un chiffre qui gonfle tout seul ne mesure plus rien*.
    lies = {(e.app, m) for e in entrees for m in e.models}
    declares = {(e.app, m) for e in entrees if e.lien == 'backend_ref' for m in e.models}
    return {
        'apps': apps,
        'apps_count': len(reels),
        'backends_count': len(entrees),
        'routes_count': sum(len(a.routes) for a in reels),
        'saveurs': {s: sum(1 for e in entrees if e.saveur == s) for s in SAVEURS},
        'sans_routage': sorted(a.app for a in reels if not a.routes),
        'modeles_lies': len(lies),
        #: Part du lien FIN (backend_ref nommant un backend) — 0 aujourd'hui : `backend_ref`
        #: porte un nom d'app. Le chiffre EST le chantier, la page ne le cache pas.
        'modeles_lien_declare': len(declares),
    }


def count() -> int:
    """Total de backends du vivier (apps réelles) — pour le registre des registres."""
    return summary()['backends_count']
