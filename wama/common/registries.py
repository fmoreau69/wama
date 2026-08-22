"""
Registre des REGISTRES — l'actualisation devient un mécanisme, pas une page.

POURQUOI CE FICHIER EXISTE (demande de Fabien, 2026-08-22)

    WAMA construit une page catalogue par capacité (modèles, apps, fonctions, librairies, licences,
    RAG, skills). Chacune a besoin d'être actualisée, et **deux seulement l'étaient** — les modèles
    (`api/sync/`) et la grille de conformité (`api/conformity/refresh/`), chacune avec son endpoint,
    son bouton et son script inline recopiés. Écrire le huitième à la main garantissait la dérive :
    des libellés différents, des permissions différentes, des pages sans bouton du tout.

    D'où le geste habituel de WAMA : **un registre keyé et déclaratif**, comme `MANIFEST_KINDS`,
    `FUNCTION_CATALOG`, `mecanismes.py` ou `wama_data/modules.py`. Une page catalogue déclare la
    CLÉ de son registre et hérite du bouton, de l'endpoint, de la permission, du chronométrage et
    du compte-rendu. Un nouveau catalogue = une entrée ici, zéro ligne d'UI.

⚠ POURQUOI LA CLÉ N'EST PAS LE `manifest_kind` (question posée, tranchée par la mesure)

    L'intuition était de keyer sur le kind de manifeste, puisque les kinds sont auto-descriptifs.
    Le relevé du 2026-08-22 dit non : sur 7 surfaces catalogues, **4 seulement** correspondent à un
    kind (`app`, `function`, `library`, `model`) ; **3 kinds n'ont aucune page** (`dataset`,
    `pipeline`, `project`) ; et **3 pages ne sont pas des kinds** (licences, RAG, skills). Keyer sur
    le kind aurait couvert 4/7 en traînant 3 entrées mortes. On garde donc `manifest_kind` comme
    LIEN facultatif — l'information est vraie et utile, elle n'est simplement pas la clé.

⚠ QUATRE NATURES D'ACTUALISATION, et les confondre produit des boutons qui mentent

    Un bouton « Actualiser » sur une page qui recalcule déjà à chaque requête est un mensonge :
    il ne fait rien et laisse croire que le reste est périmé. La nature est donc DÉCLARÉE, et l'UI
    s'en sert pour montrer un bouton ou une mention « toujours à jour ».
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Un scanner externe alimente un registre PERSISTANT (disque, `importlib`, LDAP → BDD).
#: Coûteux, potentiellement destructif (une entrée disparue du disque disparaît du registre).
SCAN = 'scan'
#: Un calcul dérive un rapport ÉCRIT (grille de conformité, redondances, faits de doc).
MESURE = 'mesure'
#: Un registre en MÉMOIRE peuplé par import au démarrage. Actualiser = re-déclarer.
REDECLARATION = 'redeclaration'
#: Rien n'est stocké : la page recalcule à chaque requête. **Il n'y a rien à actualiser**, et c'est
#: une qualité — « une page qui DÉRIVE ne peut pas diverger de ses sources » (`licenses_catalog_view`).
DERIVE = 'derive'

NATURES = {
    SCAN: "Scan d'une source externe vers un registre persistant",
    MESURE: "Calcul qui produit un rapport écrit",
    REDECLARATION: "Registre en mémoire, peuplé par import",
    DERIVE: "Dérivé à chaque affichage — toujours à jour",
}


@dataclass
class Resultat:
    """Compte-rendu UNIFORME d'une actualisation, quelle que soit sa nature.

    Chaque rafraîchisseur natif rend ce qu'il veut (`SyncResult`, un dict de scores, un entier) ;
    l'adaptateur traduit ici. Sans ce contrat, l'UI devrait connaître sept formats.
    """
    ok: bool = True
    ajoutes: int = 0
    modifies: int = 0
    retires: int = 0
    total: int = 0
    messages: Tuple[str, ...] = ()
    duree_s: float = 0.0

    def resume(self) -> str:
        """Phrase courte pour un toast. Le cas « rien n'a bougé » est DIT, pas laissé vide :
        un compte-rendu muet se lit comme un échec."""
        bouts = []
        if self.ajoutes:
            bouts.append(f"{self.ajoutes} ajouté{'s' if self.ajoutes > 1 else ''}")
        if self.modifies:
            bouts.append(f"{self.modifies} mis à jour")
        if self.retires:
            bouts.append(f"{self.retires} retiré{'s' if self.retires > 1 else ''}")
        if not bouts:
            bouts.append("aucun changement")
        if self.total:
            bouts.append(f"{self.total} au total")
        return ' · '.join(bouts)

    def en_dict(self) -> dict:
        return {'ok': self.ok, 'ajoutes': self.ajoutes, 'modifies': self.modifies,
                'retires': self.retires, 'total': self.total, 'messages': list(self.messages),
                'duree_s': round(self.duree_s, 3), 'resume': self.resume()}


@dataclass(frozen=True)
class Registre:
    """Ce qu'une page catalogue déclare pour hériter de l'actualisation."""
    cle: str
    nom: str
    nature: str
    #: D'où vient l'état — phrase courte affichée à l'utilisateur, qui répond à « actualiser quoi ? »
    source: str
    #: Le rafraîchisseur. `None` pour un registre DÉRIVÉ : il n'y a rien à actualiser.
    rafraichir: Optional[Callable[[], Resultat]] = None
    #: Comptage courant, pour afficher un total sans lancer d'actualisation.
    compter: Optional[Callable[[], int]] = None
    url_name: str = ''
    #: 'staff' (une actualisation qui ÉCRIT) ou 'auth' (sans effet de bord partagé).
    permission: str = 'staff'
    #: Passé au démarrage du serveur. RÉSERVÉ aux rafraîchisseurs en mémoire et bon marché :
    #: un scan disque à chaque boot de worker gunicorn se paie ×4 et court après lui-même.
    au_demarrage: bool = False
    #: Nom de la tâche Celery Beat qui l'actualise périodiquement, s'il y en a une. Déclaratif :
    #: sert à MONTRER dans l'UI qu'un catalogue se tient à jour tout seul.
    periodique: str = ''
    #: Lien FACULTATIF vers le kind de manifeste correspondant (4 des 7 en ont un).
    manifest_kind: str = ''
    doc: str = ''
    description: str = ''


REGISTRES: Dict[str, Registre] = {}


def enregistrer(r: Registre) -> Registre:
    if r.cle in REGISTRES:
        raise ValueError(f"registre '{r.cle}' déjà enregistré")
    if r.nature not in NATURES:
        raise ValueError(f"nature '{r.nature}' inconnue (attendu : {', '.join(NATURES)})")
    if r.nature == DERIVE and r.rafraichir is not None:
        raise ValueError(
            f"'{r.cle}' : un registre DÉRIVÉ ne peut pas avoir de rafraîchisseur — s'il en a un, "
            f"c'est qu'il stocke quelque chose, donc sa nature est mal déclarée")
    if r.nature != DERIVE and r.rafraichir is None:
        raise ValueError(
            f"'{r.cle}' : nature '{r.nature}' sans rafraîchisseur — déclarer DERIVE si la page "
            f"recalcule à chaque affichage")
    REGISTRES[r.cle] = r
    return r


def get(cle: str) -> Registre:
    try:
        return REGISTRES[cle]
    except KeyError:
        raise KeyError(
            f"registre '{cle}' inconnu (enregistrés : {', '.join(sorted(REGISTRES)) or '—'})")


def autorise(r: Registre, user) -> bool:
    if r.permission == 'staff':
        return bool(user and user.is_authenticated and user.is_staff)
    return bool(user and user.is_authenticated)


def rafraichir(cle: str, *, user=None) -> Resultat:
    """LE point d'entrée unique. Vérifie la permission, chronomètre, uniformise le compte-rendu.

    Une exception du rafraîchisseur devient un `Resultat` en échec plutôt qu'une 500 : une
    actualisation qui plante ne doit pas emporter la page qu'elle sert.
    """
    r = get(cle)
    if user is not None and not autorise(r, user):
        return Resultat(ok=False, messages=(f"réservé au {r.permission}",))
    if r.nature == DERIVE:
        return Resultat(ok=True, total=_compter(r),
                        messages=("dérivé à chaque affichage — rien à actualiser",))
    t0 = time.monotonic()
    try:
        res = r.rafraichir()
    except Exception as e:                       # noqa: BLE001 — on RAPPORTE, on ne propage pas
        logger.warning("actualisation de '%s' en échec", cle, exc_info=True)
        return Resultat(ok=False, duree_s=time.monotonic() - t0, messages=(str(e)[:300],))
    if not isinstance(res, Resultat):
        res = Resultat(ok=True, messages=(str(res)[:300],) if res else ())
    res.duree_s = time.monotonic() - t0
    if not res.total:
        res.total = _compter(r)
    return res


def _compter(r: Registre) -> int:
    if not r.compter:
        return 0
    try:
        return int(r.compter())
    except Exception:
        return 0


def etat() -> List[dict]:
    """Photo de tous les registres, pour l'UI et pour la documentation générée."""
    out = []
    for r in sorted(REGISTRES.values(), key=lambda x: x.nom):
        out.append({
            'cle': r.cle, 'nom': r.nom, 'nature': r.nature,
            'nature_label': NATURES[r.nature], 'source': r.source,
            'actualisable': r.nature != DERIVE, 'permission': r.permission,
            'url_name': r.url_name, 'au_demarrage': r.au_demarrage,
            'periodique': r.periodique, 'manifest_kind': r.manifest_kind,
            'total': _compter(r), 'doc': r.doc, 'description': r.description,
        })
    return out


def au_demarrage() -> Dict[str, Resultat]:
    """Passe les registres marqués `au_demarrage`. Appelé une fois par processus.

    ⚠ N'y mettre QUE des rafraîchisseurs en mémoire. Gunicorn lance plusieurs workers : un scan
    disque ici se paierait autant de fois, et deux scans concurrents sur le même registre
    persistant se marchent dessus. Le bon domicile d'un SCAN périodique est Celery Beat, déclaré
    dans le champ `periodique` — pas le démarrage.
    """
    out = {}
    for r in REGISTRES.values():
        if not r.au_demarrage or r.nature == DERIVE:
            continue
        if r.nature == SCAN:
            logger.warning(
                "registre '%s' : au_demarrage ignoré — un SCAN ne se lance pas au boot "
                "(voir `periodique`)", r.cle)
            continue
        out[r.cle] = rafraichir(r.cle)
    return out
