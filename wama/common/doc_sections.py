"""
Marquage des SECTIONS de la doc de construction — à qui elles parlent, quel genre de texte
elles sont, et si elles CONSTATENT ou VISENT (ROADMAP.md §25.1 ②).

POURQUOI (Fabien, 2026-09-11 — AGENTS.md §Trois docs, trois publics)

    Les docs développeur et utilisateur DÉRIVENT de la doc de construction. Pour les en extraire
    mécaniquement, chaque section de fond doit dire à qui elle s'adresse. Le marquage est par
    SECTION, pas par paragraphe : marquer finement est le coût connu de DITA, qui rend la source
    illisible — et la doc de construction doit rester lisible par ceux qui la lisent aujourd'hui.

SYNTAXE — sur la ligne qui suit un titre (lignes vides admises), invisible sur GitHub comme dans
le lecteur de doc :

    ## Ajouter un modèle
    <!-- WAMA:SECTION(audience=developpeur; type=guide; nature=constat; etat=✅) -->

    audience : developpeur, utilisateur — une ou plusieurs, séparées par des virgules. La doc de
               construction est la SOURCE : elle n'a pas à se déclarer.
    type     : tutoriel · guide · reference · explication (cadre Diátaxis). Le public ne suffit
               pas : une explication filtrée « utilisateur » reste une explication, pas un guide.
    nature   : constat · intention (AGENTS.md, règle CONSTAT / INTENTION).
    etat     : ✅ · 🔄 · ⏳.

    Les quatre clés sont obligatoires. Une sous-section sans balise HÉRITE de celle de son parent.

LA DOUBLE VÉRIFICATION (proposition de Fabien, 2026-09-11)

    `nature` et `etat` se contrôlent l'un l'autre. Un CONSTAT est ✅ : un « constat ⏳ » affirme
    l'état présent de ce qui n'existe pas encore. Une INTENTION est 🔄 ou ⏳ : une « intention ✅ »
    est réalisée, à requalifier en constat. `check_docs` refuse les deux incohérences.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

TAG_PREFIX = '<!-- WAMA:SECTION('
_TAG = re.compile(r'^\s*<!-- WAMA:SECTION\((.*)\) -->\s*$')
_HEADING = re.compile(r'^(#{1,6})\s+(.+?)\s*#*\s*$')
_FENCE = re.compile(r'^\s*(```|~~~)')

#: ⚠ Les VALEURS sont un vocabulaire de DONNÉE, écrit dans les docs : elles ne se renomment pas
#: avec les identifiants (AGENTS.md §nommage, règle 3). `audience` reprend celui du catalogue.
AUDIENCES = ('developpeur', 'utilisateur')
TYPES = {
    'tutoriel': "apprendre en faisant",
    'guide': "accomplir une tâche précise",
    'reference': "décrire exactement ce qui existe",
    'explication': "faire comprendre le pourquoi",
}
NATURES = {'constat': "affirme l'état présent", 'intention': "vise une implémentation future"}
ETATS = {'✅': 'livré', '🔄': 'en cours', '⏳': 'en attente'}
#: La double vérification : ce que chaque nature admet comme état.
ETATS_PAR_NATURE = {'constat': {'✅'}, 'intention': {'🔄', '⏳'}}
CLES = ('audience', 'type', 'nature', 'etat')


@dataclass
class Section:
    title: str
    level: int
    #: Ligne du TITRE (1-indexée).
    line: int
    attrs: Dict[str, object] = field(default_factory=dict)
    #: Vrai si les attributs viennent d'un parent, faux si la section porte sa propre balise.
    inherited: bool = False
    #: Le texte PROPRE de la section, jusqu'au titre suivant (quel que soit son niveau).
    body: str = ''


def parse_attrs(raw: str) -> Tuple[Dict[str, object], List[str]]:
    """`audience=…; type=…` → attributs + erreurs (vocabulaire ET double vérification)."""
    attrs: Dict[str, object] = {}
    erreurs: List[str] = []
    for morceau in raw.split(';'):
        morceau = morceau.strip()
        if not morceau:
            continue
        cle, sep, valeur = morceau.partition('=')
        cle, valeur = cle.strip(), valeur.strip()
        if not sep or not valeur:
            erreurs.append(f"« {morceau} » : attendu clé=valeur")
        elif cle not in CLES:
            erreurs.append(f"clé « {cle} » inconnue (attendu : {', '.join(CLES)})")
        elif cle in attrs:
            erreurs.append(f"clé « {cle} » en double")
        else:
            attrs[cle] = valeur

    if 'audience' in attrs:
        publics = tuple(a.strip() for a in str(attrs['audience']).split(',') if a.strip())
        inconnus = [a for a in publics if a not in AUDIENCES]
        if inconnus or not publics:
            erreurs.append(f"audience {', '.join(inconnus) or '(vide)'} : attendu "
                           f"{', '.join(AUDIENCES)}")
        attrs['audience'] = publics
    for cle, vocabulaire in (('type', TYPES), ('nature', NATURES), ('etat', ETATS)):
        if cle in attrs and attrs[cle] not in vocabulaire:
            erreurs.append(f"{cle} « {attrs[cle]} » : attendu {' · '.join(vocabulaire)}")
    manquantes = [c for c in CLES if c not in attrs]
    if manquantes:
        erreurs.append(f"clé(s) manquante(s) : {', '.join(manquantes)}")

    nature, etat = attrs.get('nature'), attrs.get('etat')
    if nature in ETATS_PAR_NATURE and etat in ETATS and etat not in ETATS_PAR_NATURE[nature]:
        if nature == 'constat':
            erreurs.append(f"constat {etat} : un constat affirme l'état PRÉSENT — il est ✅, "
                           f"ou c'est une intention")
        else:
            erreurs.append("intention ✅ : elle est réalisée — à requalifier en constat")
    return attrs, erreurs


def sections(texte: str) -> Tuple[List[Section], List[Tuple[int, str]]]:
    """Les sections d'un `.md` avec leurs attributs (propres ou hérités) + les erreurs de
    marquage `(ligne, message)`. Les blocs de code sont ignorés : on y CITE la syntaxe."""
    out: List[Section] = []
    erreurs: List[Tuple[int, str]] = []
    pile: List[Tuple[int, Dict[str, object]]] = []   # (niveau, attributs) des ancêtres
    courante: Optional[Section] = None
    corps: List[str] = []
    dans_code = False
    balise_admise = False     # vrai jusqu'à la 1ʳᵉ ligne non vide qui suit un titre

    def _clore():
        if courante is not None:
            courante.body = '\n'.join(corps).strip('\n')

    for i, ligne in enumerate(texte.splitlines(), 1):
        if _FENCE.match(ligne):
            dans_code = not dans_code
            balise_admise = False
            corps.append(ligne)
            continue
        if dans_code:
            corps.append(ligne)
            continue

        titre = _HEADING.match(ligne)
        if titre:
            _clore()
            niveau = len(titre.group(1))
            while pile and pile[-1][0] >= niveau:
                pile.pop()
            parent = pile[-1][1] if pile else {}
            courante = Section(title=titre.group(2).strip(), level=niveau, line=i,
                               attrs=dict(parent), inherited=bool(parent))
            out.append(courante)
            pile.append((niveau, courante.attrs))
            corps = []
            balise_admise = True
            continue

        balise = _TAG.match(ligne)
        if balise:
            if balise_admise and courante is not None:
                attrs, errs = parse_attrs(balise.group(1))
                erreurs += [(i, e) for e in errs]
                courante.attrs, courante.inherited = attrs, False
                pile[-1] = (courante.level, attrs)
            else:
                erreurs.append((i, "balise WAMA:SECTION hors de la ligne qui suit un titre"))
            balise_admise = False
            continue
        if TAG_PREFIX in ligne and '`' not in ligne:
            # Une balise écrite à côté de texte, ou non fermée, serait IGNORÉE en silence.
            erreurs.append((i, "balise WAMA:SECTION mal formée (seule sur sa ligne, fermée par -->)"))

        if ligne.strip():
            balise_admise = False
        corps.append(ligne)
    _clore()
    return out, erreurs


def extract(texte: str, audience: str, type_: Optional[str] = None) -> List[Section]:
    """Les sections destinées à un public (et à un type, si précisé), dans l'ordre du texte."""
    return [s for s in sections(texte)[0]
            if audience in s.attrs.get('audience', ())
            and (type_ is None or s.attrs.get('type') == type_)]
