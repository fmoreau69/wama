"""
Codage — le 5ᵉ mode de segmentation : un **protocole déclaré** + une **exécution**.

C'est le mode qui produit des segments à partir d'une observation, humaine ou automatique. Sa
spécification est `WAMA_DATA_WORLD.md §9ter.4`, tirée d'un mécanisme réel de 2019 dont le découpage
est tout l'intérêt :

    le protocole (un fichier à part, édité par une AUTRE application)
    l'interface de codage — GÉNÉRIQUE, pilotée par le protocole, jamais écrite par projet
    la session — qui exige la vidéo et le transport, synchronisés

Autrement dit : le schéma-driven appliqué au codage, sept ans avant qu'on le nomme ainsi ici. La
conséquence qui compte pour WAMA est celle-ci — **une IA de vision n'est qu'un producteur de plus
des mêmes segments**. Même sortie, même type, origine tracée. Il n'y a donc PAS de « module de
codage IA » à écrire à côté : il y a un `codeur` qui change.

CE QUI VIENT DE CHAQUE MONDE (aucun de ces points ne s'invente) :
  • l'outil MATLAB → protocole SÉPARÉ de l'outil d'analyse, interface générique, session qui refuse
    de démarrer sans média ;
  • le logiciel d'éthologie → le vocabulaire (éthogramme, sujet, modificateurs typés, comportements
    mutuellement exclusifs) et surtout l'**état ouvert** : un comportement commencé et pas encore
    refermé. Sans lui, on ne peut pas coder EN COURS de flux — or c'est le cas normal.

CE QUE CE MODULE NE FAIT PAS, délibérément :
  • aucune UI. Le protocole DÉCRIT ce qui est codable ; l'interface s'en génère (métadonnée-driven).
  • aucun accès média. La session porte la référence du média et refuse de coder sans, mais c'est le
    transport (`WamaShuttle`) qui joue, pas ce module.

VOCABULAIRE : `segment` est le MODÈLE ; l'utilisateur lit « situation » ou « état ».
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .segmentation import OUVERT, Segment, _tracer, _tri

#: Les deux natures d'un comportement. La distinction est structurante, pas cosmétique : un
#: PONCTUEL n'a pas de durée (il ne se referme jamais), un ÉTAT en a une et peut rester OUVERT.
PONCTUEL = 'point'
ETAT = 'state'
NATURES = (PONCTUEL, ETAT)

#: Types de modificateur. `libre` accepte tout ; les autres CONTRAIGNENT — et cette contrainte est
#: la moitié de l'intérêt d'un protocole : elle rend deux codages comparables.
MOD_UN_PARMI = 'one'
MOD_PLUSIEURS_PARMI = 'many'
MOD_NOMBRE = 'number'
MOD_LIBRE = 'free'
TYPES_MODIFICATEUR = (MOD_UN_PARMI, MOD_PLUSIEURS_PARMI, MOD_NOMBRE, MOD_LIBRE)


class ProtocoleInvalide(ValueError):
    """Le protocole lui-même est incohérent — détecté à la déclaration, jamais en cours de codage."""


class CodageRefuse(ValueError):
    """Un geste de codage viole le protocole. Refusé À LA SOURCE.

    Un codage qu'on laisse partir faux se découvre à l'analyse, quand la campagne est finie et que
    la vidéo n'est plus regardée par personne. C'est la raison d'être de la validation immédiate.
    """


# ──────────────────────────────────────────────────────────────────────────────────────────────
# 1. LE PROTOCOLE — ce qui est codable. Déclaratif, donc sérialisable, donc un manifeste.
# ──────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Modificateur:
    """Une précision attachée à un comportement (gravité, direction, nombre d'occupants…).

    TYPÉ, et c'est le point : un modificateur libre partout redonne un champ texte, donc des
    variantes d'orthographe, donc des données inexploitables au regroupement.
    """
    cle: str
    label: str = ''
    type: str = MOD_UN_PARMI
    valeurs: Tuple[Any, ...] = ()
    requis: bool = False

    def valider(self, valeur: Any) -> Any:
        """Renvoie la valeur normalisée, ou lève `CodageRefuse`."""
        if valeur is None or valeur == '' or valeur == []:
            if self.requis:
                raise CodageRefuse(f"modificateur '{self.cle}' requis")
            return None
        if self.type == MOD_NOMBRE:
            try:
                return float(valeur)
            except (TypeError, ValueError):
                raise CodageRefuse(f"modificateur '{self.cle}' : nombre attendu, reçu {valeur!r}")
        if self.type == MOD_LIBRE:
            return valeur
        if self.type == MOD_UN_PARMI:
            if self.valeurs and valeur not in self.valeurs:
                raise CodageRefuse(
                    f"modificateur '{self.cle}' : {valeur!r} hors des valeurs déclarées "
                    f"({', '.join(map(str, self.valeurs))})")
            return valeur
        # MOD_PLUSIEURS_PARMI
        recu = list(valeur) if isinstance(valeur, (list, tuple, set)) else [valeur]
        if self.valeurs:
            hors = [v for v in recu if v not in self.valeurs]
            if hors:
                raise CodageRefuse(f"modificateur '{self.cle}' : {hors!r} hors des valeurs déclarées")
        return recu


@dataclass(frozen=True)
class Comportement:
    """Une entrée de l'éthogramme : ce qu'on peut coder, et sous quelle forme."""
    code: str
    label: str = ''
    nature: str = ETAT
    #: Groupe d'exclusion mutuelle. Deux comportements du même groupe ne peuvent pas être ouverts
    #: ensemble : ouvrir l'un FERME l'autre. C'est ce qui modélise un mode de conduite, une phase,
    #: une posture — tout ce dont il n'existe qu'une valeur à la fois.
    exclusif: str = ''
    modificateurs: Tuple[Modificateur, ...] = ()
    #: Touche de l'interface générée. Déclarée ici parce que c'est une propriété du PROTOCOLE
    #: (le codeur l'apprend par cœur pour la campagne), pas un réglage d'écran.
    touche: str = ''
    couleur: str = ''
    description: str = ''

    @property
    def est_etat(self) -> bool:
        return self.nature == ETAT


@dataclass(frozen=True)
class Protocole:
    """L'éthogramme : la liste de ce qui est codable, plus les sujets observés.

    Sérialisable dans les deux sens (`en_dict` / `depuis_dict`) — c'est la forme qu'un manifeste
    prendra. Un protocole est le SEUL endroit où l'on décrit un codage : l'interface s'en génère et
    l'exécution s'y contraint, donc changer le protocole change les deux d'un coup.
    """
    nom: str
    comportements: Tuple[Comportement, ...] = ()
    #: Sujets observés (conducteur, piéton, véhicule…). Vide = un seul sujet implicite. Un codage
    #: multi-sujets suit les états SÉPARÉMENT par sujet : deux personnes peuvent tenir le même état.
    sujets: Tuple[str, ...] = ()
    version: str = '1'
    description: str = ''

    def __post_init__(self):
        vus = set()
        for c in self.comportements:
            if not c.code:
                raise ProtocoleInvalide("un comportement sans code")
            if c.code in vus:
                raise ProtocoleInvalide(f"code de comportement en double : '{c.code}'")
            vus.add(c.code)
            if c.nature not in NATURES:
                raise ProtocoleInvalide(
                    f"'{c.code}' : nature '{c.nature}' inconnue (attendu {' ou '.join(NATURES)})")
            if c.exclusif and not c.est_etat:
                raise ProtocoleInvalide(
                    f"'{c.code}' : un comportement PONCTUEL ne peut pas être exclusif — il n'a pas "
                    f"de durée, donc rien à fermer")
            for m in c.modificateurs:
                if m.type not in TYPES_MODIFICATEUR:
                    raise ProtocoleInvalide(f"'{c.code}.{m.cle}' : type '{m.type}' inconnu")

    def get(self, code: str) -> Comportement:
        for c in self.comportements:
            if c.code == code:
                return c
        raise CodageRefuse(
            f"comportement '{code}' absent du protocole '{self.nom}' "
            f"(déclarés : {', '.join(c.code for c in self.comportements) or '—'})")

    def groupe(self, code: str) -> str:
        return self.get(code).exclusif

    def en_dict(self) -> dict:
        return {
            'name': self.nom, 'version': self.version, 'description': self.description,
            'subjects': list(self.sujets),
            'behaviors': [
                {'code': c.code, 'label': c.label, 'nature': c.nature, 'exclusive': c.exclusif,
                 'key': c.touche, 'color': c.couleur, 'description': c.description,
                 'modifiers': [{'key': m.cle, 'label': m.label, 'type': m.type,
                                'values': list(m.valeurs), 'required': m.requis}
                               for m in c.modificateurs]}
                for c in self.comportements],
        }

    @classmethod
    def depuis_dict(cls, d: dict) -> "Protocole":
        return cls(
            nom=d.get('name', ''), version=str(d.get('version', '1')),
            description=d.get('description', ''),
            sujets=tuple(d.get('subjects') or ()),
            comportements=tuple(
                Comportement(
                    code=b['code'], label=b.get('label', ''), nature=b.get('nature', ETAT),
                    exclusif=b.get('exclusive', ''), touche=b.get('key', ''),
                    couleur=b.get('color', ''), description=b.get('description', ''),
                    modificateurs=tuple(
                        Modificateur(cle=m['key'], label=m.get('label', ''),
                                     type=m.get('type', MOD_UN_PARMI),
                                     valeurs=tuple(m.get('values') or ()),
                                     requis=bool(m.get('required')))
                        for m in (b.get('modifiers') or ())))
                for b in (d.get('behaviors') or ())))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# 2. L'EXÉCUTION — une session de codage. Produit des segments, comme tout autre mode.
# ──────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionCodage:
    """Un codage en cours. Chaque geste est validé contre le protocole AU MOMENT du geste.

    ⚠ La session refuse de démarrer sans média (`media`), et ce n'est pas une formalité recopiée
    du modèle : coder sans support, c'est produire des bornes temporelles que plus personne ne peut
    vérifier. Le mécanisme d'origine posait déjà la règle en 2019.

    Le `codeur` est libre — « fabien », « qwen3-vl », « detector:locate-anything ». C'est ce champ,
    et lui seul, qui distingue un codage humain d'un codage automatique : le reste du chemin est
    identique, ce qui est exactement le but.
    """
    protocole: Protocole
    media: str
    codeur: str = ''
    #: États ouverts, indexés par (sujet, code). Un état par sujet : deux sujets peuvent tenir le
    #: même comportement simultanément sans se fermer l'un l'autre.
    _ouverts: Dict[Tuple[str, str], Segment] = field(default_factory=dict, repr=False)
    _clos: List[Segment] = field(default_factory=list, repr=False)
    _ponctuels: List[Segment] = field(default_factory=list, repr=False)
    _dernier_t: Optional[float] = field(default=None, repr=False)

    def __post_init__(self):
        if not self.media:
            raise CodageRefuse(
                "codage sans média : une session exige le support qu'elle décrit (règle héritée du "
                "mécanisme d'origine — sans vidéo, les bornes ne sont plus vérifiables)")

    # ── gestes ────────────────────────────────────────────────────────────────────────────────

    def marquer(self, t: float, code: str, *, sujet: str = '', modificateurs: Optional[dict] = None,
                commentaire: str = '') -> Segment:
        """LE geste unique du codage. Ponctuel → un segment de durée nulle. État → il OUVRE, ou il
        FERME s'il est déjà ouvert (bascule), en fermant au passage l'état exclusif concurrent.

        Une seule fonction plutôt que `ouvrir`/`fermer`/`evenement` : c'est ce que fait le codeur —
        il appuie sur une touche. La nature du comportement est déclarée dans le protocole, donc
        l'exécution n'a pas à être commandée deux fois.
        """
        comp = self.protocole.get(code)
        sujet = self._sujet(sujet)
        mods = self._valider_modificateurs(comp, modificateurs)
        self._verifier_monotone(t)

        if not comp.est_etat:
            seg = _tracer({'start': t, 'end': t, 'value': code, 'label': comp.label or code,
                           'subject': sujet or None, 'nature': PONCTUEL},
                          'codage', coder=self.codeur or None, protocol=self.protocole.nom,
                          media=self.media, comment=commentaire or None)
            seg.update(mods)
            self._ponctuels.append(seg)
            return seg

        cle = (sujet, code)
        if cle in self._ouverts:                       # bascule : le même geste referme
            return self._fermer_cle(cle, t)

        if comp.exclusif:                              # ouvrir ferme le concurrent du groupe
            for (s, c) in list(self._ouverts):
                if s == sujet and self.protocole.groupe(c) == comp.exclusif:
                    self._fermer_cle((s, c), t, cause='exclusive')

        seg = _tracer({'start': t, 'end': OUVERT, 'value': code, 'label': comp.label or code,
                       'subject': sujet or None, 'nature': ETAT, 'open': True},
                      'codage', coder=self.codeur or None, protocol=self.protocole.nom,
                      media=self.media, comment=commentaire or None)
        seg.update(mods)
        self._ouverts[cle] = seg
        return seg

    def ouvrir(self, t: float, code: str, **kw) -> Segment:
        """Ouverture EXPLICITE — refuse si l'état est déjà ouvert, là où `marquer` basculerait.

        Utile au codage automatique, où un modèle propose des ouvertures sans savoir ce qui court
        déjà : la bascule silencieuse y refermerait un état au lieu de signaler l'incohérence.
        """
        comp = self.protocole.get(code)
        if not comp.est_etat:
            raise CodageRefuse(f"'{code}' est PONCTUEL — il n'a pas d'ouverture, utiliser `marquer`")
        if (self._sujet(kw.get('sujet', '')), code) in self._ouverts:
            raise CodageRefuse(f"'{code}' est déjà ouvert pour ce sujet")
        return self.marquer(t, code, **kw)

    def fermer(self, t: float, code: str, *, sujet: str = '') -> Segment:
        """Fermeture EXPLICITE — refuse si rien n'est ouvert, plutôt que d'ouvrir par surprise."""
        cle = (self._sujet(sujet), code)
        self.protocole.get(code)
        if cle not in self._ouverts:
            raise CodageRefuse(f"'{code}' n'est pas ouvert pour ce sujet — rien à fermer")
        self._verifier_monotone(t)
        return self._fermer_cle(cle, t)

    def annuler_dernier(self) -> Optional[Segment]:
        """Retire la dernière production. Le codage en temps réel produit des erreurs de doigt : ne
        pas offrir le retour arrière, c'est obliger à reprendre la passation."""
        candidats: List[Tuple[float, str, Any]] = []
        if self._ponctuels:
            candidats.append((self._ponctuels[-1]['start'], 'ponctuel', None))
        if self._clos:
            candidats.append((self._clos[-1]['end'], 'clos', None))
        for cle, seg in self._ouverts.items():
            candidats.append((seg['start'], 'ouvert', cle))
        if not candidats:
            return None
        t, quoi, cle = max(candidats, key=lambda x: x[0])
        if quoi == 'ponctuel':
            return self._ponctuels.pop()
        if quoi == 'clos':                             # un segment refermé redevient OUVERT
            seg = self._clos.pop()
            seg['end'] = OUVERT
            seg['open'] = True
            seg.pop('closed_by', None)
            self._ouverts[(seg.get('subject') or '', seg['value'])] = seg
            return seg
        return self._ouverts.pop(cle)

    # ── sorties ───────────────────────────────────────────────────────────────────────────────

    def segments(self, *, fin_de_session: Optional[float] = None) -> List[Segment]:
        """Tous les états, y compris ceux restés OUVERTS.

        `fin_de_session` ferme d'office les états en cours et TRACE cette fermeture (`closed_at`) :
        une durée refermée par la fin de l'enregistrement n'a pas le statut d'une durée observée, et
        confondre les deux fausse toute statistique de durée.
        """
        out = list(self._clos) + list(self._ouverts.values())
        if fin_de_session is not None:
            from .segmentation import fermer as _fermer_seg
            out = _fermer_seg(out, fin_de_session)
        return _tri(out)

    def evenements(self) -> List[Segment]:
        """Les comportements ponctuels — même forme, durée nulle. Ils rejoignent le flux `events`."""
        return sorted(self._ponctuels, key=lambda s: s['start'])

    def ouverts(self) -> List[Segment]:
        return sorted(self._ouverts.values(), key=lambda s: s['start'])

    def resume(self) -> dict:
        """De quoi alimenter un bandeau d'interface sans que celle-ci connaisse le modèle."""
        return {'protocol': self.protocole.nom, 'media': self.media, 'coder': self.codeur,
                'states': len(self._clos) + len(self._ouverts), 'open': len(self._ouverts),
                'events': len(self._ponctuels), 'last_time': self._dernier_t}

    # ── interne ───────────────────────────────────────────────────────────────────────────────

    def _sujet(self, sujet: str) -> str:
        if self.protocole.sujets:
            if not sujet:
                if len(self.protocole.sujets) == 1:
                    return self.protocole.sujets[0]
                raise CodageRefuse(
                    f"sujet requis (déclarés : {', '.join(self.protocole.sujets)})")
            if sujet not in self.protocole.sujets:
                raise CodageRefuse(f"sujet '{sujet}' absent du protocole")
        return sujet

    def _valider_modificateurs(self, comp: Comportement, recus: Optional[dict]) -> dict:
        recus = dict(recus or {})
        connus = {m.cle for m in comp.modificateurs}
        inconnus = set(recus) - connus
        if inconnus:
            raise CodageRefuse(
                f"'{comp.code}' : modificateur(s) non déclaré(s) {sorted(inconnus)}")
        out = {}
        for m in comp.modificateurs:
            v = m.valider(recus.get(m.cle))
            if v is not None:
                out[m.cle] = v
        return out

    def _verifier_monotone(self, t: float) -> None:
        """Le codage suit le temps du média. Un geste antérieur au précédent signale un transport
        qui a sauté en arrière sans que la session le sache — mieux vaut le dire que produire un
        segment à durée négative."""
        if self._dernier_t is not None and t < self._dernier_t:
            raise CodageRefuse(
                f"geste à t={t:g} antérieur au précédent (t={self._dernier_t:g}) — reprendre le "
                f"codage après un retour arrière du transport exige de rouvrir la session")
        self._dernier_t = t

    def _fermer_cle(self, cle: Tuple[str, str], t: float, *, cause: str = '') -> Segment:
        seg = self._ouverts.pop(cle)
        seg['end'] = t
        seg.pop('open', None)
        if cause:
            seg['closed_by'] = cause
        self._clos.append(seg)
        return seg


# ──────────────────────────────────────────────────────────────────────────────────────────────
# 3. REJOUER un codage — la même session, alimentée par une liste de gestes
# ──────────────────────────────────────────────────────────────────────────────────────────────

def rejouer(protocole: Protocole, media: str, gestes: Iterable[dict], *, codeur: str = '',
            fin_de_session: Optional[float] = None) -> Tuple[List[Segment], List[Segment]]:
    """Rejoue une liste de gestes `{t, code, sujet?, modificateurs?, commentaire?}`.

    C'est le point d'entrée du codage AUTOMATIQUE : un modèle de vision produit une liste de gestes,
    on la rejoue, et l'on obtient exactement la même sortie qu'un codage humain — validée par le
    même protocole. Rien d'autre à écrire côté IA que la production des gestes.

    Renvoie `(segments, événements)`.
    """
    s = SessionCodage(protocole=protocole, media=media, codeur=codeur)
    for g in gestes:
        s.marquer(g['t'], g['code'], sujet=g.get('sujet', ''),
                  modificateurs=g.get('modificateurs'), commentaire=g.get('commentaire', ''))
    return s.segments(fin_de_session=fin_de_session), s.evenements()


def accord(a: Sequence[Segment], b: Sequence[Segment], *, tolerance: float = 1.0) -> dict:
    """Compare DEUX codages du même média (deux humains, ou un humain et un modèle).

    Mesure volontairement simple — appariement par code et par proximité des débuts, dans une
    tolérance. Ce n'est pas un kappa : c'est ce qu'il faut pour dire « ce que la machine a proposé
    correspond-il à ce que l'humain a codé », qui est la question posée quand on valide un codage
    assisté. Le calcul d'indicateurs d'accord plus fins est du ressort du module Calculator.
    """
    restants = list(b)
    apparies: List[Tuple[Segment, Segment]] = []
    for sa in sorted(a, key=lambda s: s['start']):
        proche, ecart = None, None
        for sb in restants:
            if sb.get('value') != sa.get('value') or sb.get('subject') != sa.get('subject'):
                continue
            d = abs(sb['start'] - sa['start'])
            if d <= tolerance and (ecart is None or d < ecart):
                proche, ecart = sb, d
        if proche is not None:
            restants.remove(proche)
            apparies.append((sa, proche))
    return {'matched': len(apparies), 'only_a': len(a) - len(apparies), 'only_b': len(restants),
            'mean_offset': (sum(abs(y['start'] - x['start']) for x, y in apparies) / len(apparies)
                            if apparies else None)}
