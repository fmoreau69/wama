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

import ast
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

#: Saveurs de sortie déclarées par `backends/__init__.RESULT` (marche B1) — ce que le
#: backend PRODUIT, donc ce que la tâche composée en fait. Défaut historique : 'file'.
FLAVORS = {
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
    flavor: str = 'file'
    #: 'route' (déclaré dans ROUTES) ou 'classe' (sous-contrat BaseModelBackend).
    kind: str = 'route'
    packages: List[str] = field(default_factory=list)
    vram_gb: Optional[float] = None
    description: str = ''
    #: Modèles du catalogue servis par ce backend (clés AIModel).
    models: List[str] = field(default_factory=list)
    #: MOTEUR déclaré par le backend lui-même (`ENGINE`) — la librairie qu'il pilote.
    engine: str = ''
    #: Ses paquets requis sont-ils présents dans CE venv ? (`find_spec`, sans import)
    #: ⚠ Toujours vrai pour un backend ISOLÉ : la question ne se pose pas ici (cf. `isolation`).
    engine_installed: bool = True
    #: ENVIRONNEMENT d'exécution déclaré par le backend (`ISOLATION`) — vide = venv principal.
    #: `venv:<chemin>` ou `service:<url>`. C'est la MOITIÉ MANQUANTE du verdict de grisage :
    #: sans elle, « paquet absent » et « backend qui vit ailleurs » se confondent.
    isolation: str = ''
    #: MOTEURS (librairies d'exécution) que ce backend appelle — DÉRIVÉS des modèles servis
    #: (`composition.runtime.engine`). ⚠ Backend ≠ moteur (recadrage Fabien 2026-09-03) : le
    #: backend est l'adaptateur WAMA (contrat load/unload/process), le moteur est la
    #: librairie qui exécute réellement le modèle (faster-whisper, coqui, audio-cpp…).
    engines: List[str] = field(default_factory=list)
    #: Moteurs déclarés mais ABSENTS de l'inventaire d'exécutables (`known_engines`).
    missing_engines: List[str] = field(default_factory=list)
    #: Comment le lien modèle↔backend a été établi : 'backend_ref' (déclaré) ou 'app' (déduit
    #: du fait que le modèle appartient à l'app). La PROVENANCE du lien se dit — un lien
    #: déduit n'a pas la valeur d'un lien déclaré.
    link: str = ''

    @property
    def signature(self) -> str:
        """Empreinte de voisinage — ce sur quoi le LLM peut trier « le plus approchant »."""
        n = '+'.join(self.natures) or '—'
        return f"{n} → {self.flavor}"


@dataclass
class AppBackends:
    app: str
    #: Jumelle de bac à sable : porte le nom de sa source (jamais comptée comme une app de plus).
    generated_from: str = ''
    routes: dict = field(default_factory=dict)
    flavor: str = 'file'
    #: Colonne de nature DÉCLARÉE (`NATURE_FIELD`) — vide si l'app s'en remet au défaut.
    nature_field: str = ''
    #: Colonne EFFECTIVEMENT lue par le corps composé : la déclarée, ou le défaut historique
    #: `media_type` (pilote converter). La page montre celle-ci — afficher un blanc là où le
    #: générateur lit `media_type` laisserait croire à un trou (relevé par un test, 03/09).
    effective_nature: str = 'media_type'
    #: La nature vient-elle d'une déclaration explicite ? (déclaré ≠ hérité du défaut)
    declared_nature: bool = False
    entries: List[BackendEntry] = field(default_factory=list)
    #: Ce qui manque pour que la chaîne de génération compose le corps de tâche de cette app.
    missing: str = ''
    #: Sous-modules du paquet qu'on n'a pas pu lire (dépendance absente) — DIT, jamais avalé.
    unreadable: List[str] = field(default_factory=list)
    #: Classes de backend RÉSOLUES (nom, cls) — sert la dérivation d'inventaire de moteurs ;
    #: la page, elle, n'affiche que les champs déclaratifs des entrées.

    #: Modèles rattachés à l'APP (lien non déclaré) et moteurs qu'ils nomment. ⚠ Ils vivent
    #: ICI et non sur chaque backend : l'attribution par app ÉTALAIT les modèles sur toutes
    #: les entrées (BarkBackend annoncé appelant coqui/higgs/kokoro — mesuré le 03/09). Une
    #: page qui étale une attribution inconnue ment plus qu'elle n'informe.
    models_app: List[str] = field(default_factory=list)
    app_engines: List[str] = field(default_factory=list)


def _init_declarations(chemin) -> dict:
    """Déclarations LITTÉRALES du `backends/__init__.py` (ROUTES/RESULT/NATURE_FIELD),
    lues sans import — même raison que `_classe_backends` : lire ne doit rien exécuter."""
    out = {}
    try:
        arbre = ast.parse(chemin.read_text(encoding='utf-8'))
    except (OSError, SyntaxError):
        return out
    for n in arbre.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            nom = n.targets[0].id
            if nom in ('ROUTES', 'RESULT', 'NATURE_FIELD'):
                out[nom] = _literal_value(n.value)
    return out


_CONTRAT_CACHE: Optional[tuple] = None


def _contract_abstract_methods() -> tuple:
    """Méthodes `@abstractmethod` de `BaseModelBackend`, lues par AST (source unique)."""
    global _CONTRAT_CACHE
    if _CONTRAT_CACHE is None:
        noms = set()
        try:
            base = Path(__file__).resolve().parents[1] / 'backends' / 'base.py'
            for n in ast.walk(ast.parse(base.read_text(encoding='utf-8'))):
                if isinstance(n, ast.ClassDef) and n.name == 'BaseModelBackend':
                    for s in n.body:
                        if (isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))
                                and any(getattr(d, 'id', getattr(d, 'attr', '')) == 'abstractmethod'
                                        for d in s.decorator_list)):
                            noms.add(s.name)
        except (OSError, SyntaxError) as e:
            logger.warning('[backends] contrat commun illisible : %s', e)
        _CONTRAT_CACHE = tuple(sorted(noms))
    return _CONTRAT_CACHE


def _packages_present(paquets, isolation: str = '') -> bool:
    """Les paquets requis sont-ils importables ? — `find_spec`, donc SANS import réel.

    ⚠ Ne PAS appeler `known_engines()` d'ici : `inventory()` alimente l'inventaire des
    moteurs, donc le consulter ici crée un CYCLE. Mesuré le 03/09 en l'écrivant :
    47 s d'empilement récursif avant qu'une exception ne l'arrête, contre 0,2 s sans.
    *Un producteur ne consulte jamais le registre qu'il alimente.*

    ⚠ Un backend ISOLÉ n'est pas mesurable d'ici (ses paquets vivent dans un autre venv,
    ou derrière un service) : on ne le condamne pas sur une absence qui est ATTENDUE —
    même permissivité que `backend_missing`, et même raison que dans le contrat commun.
    """
    if isolation:
        return True
    from importlib.util import find_spec
    for nom in (paquets or []):
        try:
            if find_spec(nom.split('.')[0]) is None:
                return False
        except (ImportError, ValueError):
            return False
    return True


def _literal_value(noeud):
    """Valeur d'une affectation de classe si elle est LITTÉRALE, sinon None."""
    try:
        return ast.literal_eval(noeud)
    except (ValueError, SyntaxError):
        return None


def _class_backends(paquet_dir, prefixe: str) -> tuple:
    """(classes, illisibles) — backends du paquet, lus par AST : AUCUN IMPORT.

    ⚠ POURQUOI STATIQUE (mesuré le 2026-09-03, après une 1ʳᵉ version qui importait) :
      • la page coûtait **9,07 s au premier affichage** par worker (import de tout le socle
        modèles — diffusers, torch…), 0,10 s ensuite : un registre qui fait payer le socle
        à son premier visiteur n'est pas un registre, c'est un chargement ;
      • surtout, IMPORTER a des EFFETS : deux backends imager ont muté `HF_HUB_CACHE` au
        niveau module (règle CLAUDE.md). Le chantier HF est en cours de re-correction — une
        page de lecture ne doit dépendre d'aucun état de ce chantier. *Lire une déclaration
        ne doit jamais exécuter le code qui la porte.*

    Classification SANS import : fermeture transitive des bases (`BaseModelBackend` →
    bases métier → backends concrets). ABSTRAITE = il reste une méthode abstraite NON
    implémentée, en remontant la chaîne — ⚠ pas seulement « déclare un `@abstractmethod` » :
    mesuré le 03/09, `DetectionBackend` et `TTSBackend` sont abstraites parce qu'elles
    n'implémentent pas le contrat commun, sans rien déclarer elles-mêmes. La 1ʳᵉ règle les
    laissait passer pour des backends exécutables — un inventaire qui annonce un moteur
    inexécutable est aussi faux qu'un inventaire qui en rate un.
    """
    abstraites_du_contrat = _contract_abstract_methods()
    fichiers = sorted(paquet_dir.glob('*.py')) if paquet_dir.is_dir() else []
    classes_par_nom, unreadable = {}, []
    for f in fichiers:
        try:
            arbre = ast.parse(f.read_text(encoding='utf-8'))
        except (OSError, SyntaxError) as e:
            unreadable.append(f'{f.stem} ({type(e).__name__})')
            continue
        for n in arbre.body:
            if not isinstance(n, ast.ClassDef):
                continue
            bases = {b.id if isinstance(b, ast.Name) else getattr(b, 'attr', '')
                     for b in n.bases}
            attrs, propres_abstraites, definies = {}, set(), set()
            for s in n.body:
                if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
                    attrs[s.targets[0].id] = _literal_value(s.value)
                elif isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name) and s.value is not None:
                    attrs[s.target.id] = _literal_value(s.value)
                elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if any(getattr(d, 'id', getattr(d, 'attr', '')) == 'abstractmethod'
                           for d in s.decorator_list):
                        propres_abstraites.add(s.name)
                    else:
                        definies.add(s.name)
                elif isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
                    definies.add(s.targets[0].id)     # alias de méthode (load_model = load)
            classes_par_nom[n.name] = {
                'nom': n.name, 'bases': bases, 'module': f'{prefixe}.{f.stem}',
                'fichier': f.stem, 'attrs': attrs,
                'propres_abstraites': propres_abstraites, 'definies': definies}

    # Fermeture transitive depuis le contrat commun (les bases métier sont dans le paquet).
    backends, bougé = {'BaseModelBackend'}, True
    while bougé:
        bougé = False
        for nom, info in classes_par_nom.items():
            if nom not in backends and (info['bases'] & backends):
                backends.add(nom)
                bougé = True

    def _still_abstract(nom, vus=None):
        """Méthodes abstraites NON implémentées, en remontant la chaîne d'héritage."""
        vus = vus or set()
        if nom in vus:
            return set()
        vus.add(nom)
        info = classes_par_nom.get(nom)
        if info is None:                      # base hors paquet = le contrat commun
            return set(abstraites_du_contrat) if nom == 'BaseModelBackend' else set()
        heritees = set()
        for b in info['bases']:
            heritees |= _still_abstract(b, vus)
        return (heritees | info['propres_abstraites']) - info['definies']

    def _inherited_attrs(nom, vus=None) -> dict:
        """Attributs déclaratifs vus par la classe — les SIENS priment, le reste remonte.

        C'est ce que fait Python : une sous-classe qui ne redéclare pas `ISOLATION` hérite
        celle de sa base. Le lire à plat ratait donc toute famille qui déclare une fois sur
        sa base métier — précisément la façon dont un paquet isolé s'écrira (une base
        `venv:…`, N moteurs concrets en dessous). Idem pour `ENGINE`/`REQUIRED_PACKAGES`.
        """
        vus = vus or set()
        if nom in vus or nom not in classes_par_nom:
            return {}
        vus.add(nom)
        hérités = {}
        for b in classes_par_nom[nom]['bases']:
            hérités.update(_inherited_attrs(b, vus))
        hérités.update({k: v for k, v in classes_par_nom[nom]['attrs'].items() if v is not None})
        return hérités

    trouvees = [(nom, dict(info, attrs=_inherited_attrs(nom)))
                for nom, info in classes_par_nom.items()
                if nom in backends and not _still_abstract(nom)]
    return sorted(trouvees, key=lambda t: t[0]), unreadable


def _models_by_app() -> dict:
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
        for m in AIModel.objects.all().only('model_key', 'source', 'backend_ref',
                                            'composition'):
            engine = ((m.composition or {}).get('runtime') or {}).get('engine') or ''
            out.setdefault(m.source or '', []).append(
                (m.model_key, getattr(m, 'backend_ref', '') or '', engine))
    except Exception as e:      # hors Django/base absente : l'inventaire reste utile sans
        logger.warning('[backends] catalogue illisible : %s', e)
    return out


def inventory() -> List[AppBackends]:
    """Le vivier, DÉRIVÉ à l'appel. Une app = une entrée ; jamais de nom d'app en dur ici."""
    from django.apps import apps as django_apps

    modeles = _models_by_app()
    resultat: List[AppBackends] = []

    for config in django_apps.get_app_configs():
        app = config.label
        paquet_dir = Path(config.path) / 'backends'
        if not (paquet_dir / '__init__.py').is_file():
            continue                      # pas de paquet backends : ce n'est pas un défaut
        # ROUTES/RESULT/NATURE_FIELD : lus au LITTÉRAL du `__init__.py`, sans import.
        decl = _init_declarations(paquet_dir / '__init__.py')

        marque = ''
        try:
            from wama.common.app_registry import APP_CATALOG
            marque = (APP_CATALOG.get(app) or {}).get('generated_from') or ''
        except Exception:
            pass

        routes = dict(decl.get('ROUTES') or {})
        result = decl.get('RESULT') or {}
        flavor = (result.get('kind') if isinstance(result, dict) else '') or 'file'
        nature_field = decl.get('NATURE_FIELD') or ''

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
        engine_of = {}
        for cle, ref, engine in modeles.get(app, []):
            if engine:
                engine_of[cle] = engine
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
            servis_r = sorted(par_ref.get(nom, []))
            mot_r = sorted({engine_of[c] for c in servis_r if c in engine_of})
            entries.append(BackendEntry(
                app=app, name=nom, path=chemin, natures=sorted(natures), flavor=flavor,
                kind='route', models=servis_r, engines=mot_r,
                missing_engines=[],
                link='backend_ref' if servis_r else ''))

        #: ② Les CLASSES au contrat commun (modèles chargés, VRAM comptée).
        classes, unreadable = _class_backends(paquet_dir, f'{config.name}.backends')
        for nom, info in classes:
            servis = sorted(par_ref.get(nom, []))
            isolation = (info['attrs'].get('ISOLATION') or '').strip()
            entries.append(BackendEntry(
                app=app, name=nom,
                path=f"backends.{info['fichier']}.{nom}",
                natures=[], flavor=flavor, kind='classe',
                packages=list(info['attrs'].get('REQUIRED_PACKAGES') or []),
                vram_gb=info['attrs'].get('recommended_vram_gb'),
                description=(info['attrs'].get('description') or '').strip(),
                engine=(info['attrs'].get('ENGINE') or '').strip(),
                isolation=isolation,
                engine_installed=_packages_present(
                    info['attrs'].get('REQUIRED_PACKAGES'), isolation),
                models=servis,
                engines=sorted({engine_of[c] for c in servis if c in engine_of}),
                missing_engines=[],
                link='backend_ref' if servis else ''))

        if not entries and not unreadable and not routes:
            # ⚠ Une app à paquet `backends/` mais SANS backend exécutable reste inventoriée
            # (anonymizer, mesuré le 03/09 : sa seule classe est une base métier abstraite).
            # La faire disparaître dirait « pas de paquet » là où il faut dire « aucun
            # backend exécutable » — un vide non expliqué se lit comme un oubli.
            resultat.append(AppBackends(app=app, generated_from=marque, routes={},
                                        missing="aucun backend EXÉCUTABLE (bases métier "
                                               "abstraites seules) — et pas de ROUTES : le "
                                               "corps de tâche généré reste un trou marqué"))
            continue

        # Ce qui manque pour COMPOSER (dit ici parce que c'est la seule page qui voit les
        # trois déclarations ensemble ; la grille le mesure app par app, cf. backend_routes).
        missing = ''
        if not routes:
            missing = "pas de ROUTES — le corps de tâche généré reste un trou marqué"
        elif flavor == 'text' and not (result.get('field') if isinstance(result, dict) else ''):
            missing = "RESULT.kind='text' sans `field` — la tâche ne saurait où persister"
        elif not nature_field and 'media_type' not in routes:
            missing = ''      # défaut historique media_type : légitime, rien à signaler

        resultat.append(AppBackends(
            app=app, generated_from=marque, routes=routes, flavor=flavor,
            nature_field=nature_field,
            effective_nature=nature_field or 'media_type',
            declared_nature=bool(nature_field),
            entries=entries, missing=missing, unreadable=unreadable,
            models_app=sorted(niveau_app),
            app_engines=sorted({engine_of[c] for c in niveau_app if c in engine_of})))

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
    lies = ({(e.app, m) for e in entrees for m in e.models}
            | {(a.app, m) for a in reels for m in a.models_app})
    declares = {(e.app, m) for e in entrees if e.link == 'backend_ref' for m in e.models}
    return {
        'apps': apps,
        'apps_count': len(reels),
        'backends_count': len(entrees),
        'routes_count': sum(len(a.routes) for a in reels),
        'saveurs': {s: sum(1 for e in entrees if e.flavor == s) for s in FLAVORS},
        'without_routes': sorted(a.app for a in reels if not a.routes),
        'linked_models': len(lies),
        #: Part du lien FIN (backend_ref nommant un backend) — 0 aujourd'hui : `backend_ref`
        #: porte un nom d'app. Le chiffre EST le chantier, la page ne le cache pas.
        'declared_link_models': len(declares),
        #: MOTEURS distincts appelés par les backends (≠ nombre de backends : plusieurs
        #: backends peuvent appeler le même moteur, et un backend peut n'en déclarer aucun).
        'engines': sorted({m for e in entrees for m in e.engines}
                          | {m for a in reels for m in a.app_engines}),
        'missing_engines': sorted({m for e in entrees for m in e.missing_engines}),
        'runnable_engines': sorted({e.engine for a in reels for e in a.entries
                                       if e.engine and e.engine_installed}),
        #: Backends qui tournent HORS du venv principal, par environnement déclaré
        #: (`ISOLATION`). Le défaut VOULU est zéro : un venv unique, l'isolement étant
        #: l'exception déclarée. Ce compteur EST la garde — s'il enfle, on a multiplié les
        #: venvs sans le décider (chaque processus isolé est un détenteur de VRAM que le
        #: gouverneur de ressources ne voit pas).
        'isolations': {env: sorted(n for n, e in
                                   ((f'{a.app}:{e.name}', e) for a in reels for e in a.entries)
                                   if e.isolation == env)
                       for env in sorted({e.isolation for a in reels for e in a.entries
                                          if e.isolation})},
    }


class _DeclaredEngine:
    """Ce qu'un inventaire de moteurs doit exposer, sans importer le backend.

    `register_engine_inventory` accepte un mapping {moteur: porteur} et `known_engines()`
    ne retient que les porteurs dont `missing_packages()` est vide. On rend donc un objet
    minimal qui répond à ce contrat en STATIQUE (`find_spec` sur les paquets déclarés) :
    importer la classe coûterait le socle modèles entier et rouvrirait la porte aux effets
    de bord d'import que ce chantier vient de fermer.
    """

    __slots__ = ('engine', 'packages', 'isolation')

    def __init__(self, engine: str, packages, isolation: str = ''):
        self.engine, self.packages = engine, list(packages or [])
        self.isolation = isolation

    def missing_packages(self):
        """Même règle que le contrat commun : un backend ISOLÉ n'a rien à installer ICI."""
        if self.isolation:
            return []
        return [p for p in self.packages if not _packages_present([p])]

    def __repr__(self):
        return f'<moteur {self.engine}>'


_ENGINES_CACHE: Optional[dict] = None


def declared_engines() -> dict:
    """{moteur: classe de backend} DÉRIVÉ des déclarations `ENGINE` des backends.

    C'est l'autre moitié du lien modèle↔moteur (2026-09-03) : le modèle déclare le moteur
    qu'il EXIGE (`composition.runtime.engine`), le backend déclare celui qu'il SAIT piloter,
    et l'inventaire des exécutables se DÉRIVE — plus de liste tenue à la main (avant ce
    jour : 2 apps sur 9 en enregistraient une, donc `known_engines()` était structurellement
    incomplet et un modèle pouvait être grisé faute d'inventaire, pas faute de moteur).

    Rendu au format MAPPING attendu par `register_engine_inventory` (il seul permet de
    remonter au contrat du backend : PIP_PACKAGES, missing_packages).

    ⚠ Appelé PARESSEUSEMENT (jamais au démarrage) et mis en cache : le balayage importe les
    sous-modules de backends. Mesuré le 03/09 : 0,13 s et — depuis le correctif HF cache de
    l'instance parallèle — AUCUNE mutation de `HF_HUB_CACHE` (c'était le risque : deux
    backends imager mutaient l'environnement au niveau module).
    """
    global _ENGINES_CACHE
    if _ENGINES_CACHE is None:
        carte = {}
        for a in inventory():
            if a.generated_from:
                continue                    # une jumelle n'ajoute aucun moteur au parc
            for e in a.entries:
                if e.engine:
                    carte.setdefault(e.engine,
                                     _DeclaredEngine(e.engine, e.packages, e.isolation))
        _ENGINES_CACHE = carte
    return dict(_ENGINES_CACHE)


def count() -> int:
    """Total de backends du vivier (apps réelles) — pour le registre des registres."""
    return summary()['backends_count']
