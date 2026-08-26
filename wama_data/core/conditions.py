"""
Chaîne conditionnelle — conditions DÉCLARÉES et assemblage logique en ARBRE.

Sa spécification est `WAMA_DATA_WORLD.md §9ter.6 B`. Ce module fournit la couche qui manquait
AU-DESSUS du moteur : `core/segmentation.py::conditionnelle()` prend déjà un masque booléen en
entrée — ce qu'on ne savait pas faire, c'est **déclarer** ce masque autrement qu'en code.

CE QUE LA LECTURE DU CODE D'ORIGINE A CHANGÉ (`BIND_GUI.mlapp`, extrait le 2026-08-23). Les trois
points ci-dessous ne sont pas des critiques gratuites : chacun justifie une décision d'ici.

  ① L'assemblage y est du TEXTE PASSÉ À `eval()` :

         ET = @and;  OU = @or;  NON = @not;  XOR = @xor;
         master_mask = eval(strrep(operations, 'C', 'masks.C'));

     Conséquences mesurables, toutes évitées par l'arbre : une référence à un `C4` inexistant, une
     arité fausse ou une parenthèse manquante ne se voient qu'À L'EXÉCUTION, et le rattrapage est
     un `uialert` unique — « Probleme avec les connecteurs, Impossible de segmenter » — qui ne dit
     NI lequel, NI où. Ici la même faute est refusée à la DÉCLARATION, en nommant le fautif.

  ② L'exemple affiché par l'interface d'origine n'est pas dans la syntaxe qu'elle accepte.
     Elle montre `NON(C1 ET C2 OU(C4 XOR (C5 ET C6)))` — de l'infixe — alors que son propre
     constructeur (`fusion_connecteur`) n'émet que du PRÉFIXE binaire imbriqué, `ET (C1 , C2)`,
     seule forme que `eval()` accepte vraiment (`ET` est une poignée de fonction, pas un opérateur).
     L'exemple est donc un contre-exemple. C'est le symptôme habituel d'un texte qui sert à la fois
     de modèle et d'affichage : les deux divergent sans que rien ne le signale.

  ③ Le filtrage des opérateurs existe, mais sur le MAUVAIS AXE. L'interface d'origine restreint la
     liste selon ce qu'on CRÉE (une situation n'a droit qu'aux 6 comparaisons numériques, un
     événement aux 16), jamais selon le TYPE DE LA COLONNE TESTÉE. On peut donc y appliquer `<` à
     une colonne de texte : MATLAB compare alors les codes des caractères et rend un masque
     plausible. Ici la sorte de la colonne commande, et l'axe « quoi créer » ne restreint rien —
     il n'a aucune raison de le faire (point 4 de §9ter.6 B : la sortie est un PORT, pas un mode).

⚠ CE MODULE EST PUR — aucune dépendance à pandas ni à Django, comme `segmentation.py` et
`calculation.py`. La sorte d'une colonne (numérique / texte / booléen) est une DONNÉE D'ENTRÉE : la
déduire d'un `dtype` pandas est le travail de l'adaptateur, pas du cœur.

⚠ `data_types.py` NE TYPE PAS LES COLONNES — il type le CADRE (`TypedFrame.data_type`), et
`TypedFrame` n'expose que `.fields`, une liste de noms. La phrase de §9ter.6 B3 (« WAMA a déjà
`data_types.py` pour savoir de quel type est une colonne : la vérification est gratuite ») est donc
fausse, et c'est pour cela que la notion de SORTE est introduite ici au lieu d'être empruntée.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple, Union

from .values import missing

# ══════════════════════════════════════════════════════════════════════════════════════════════
# 1. SORTES de colonne — le vocabulaire minimal qui suffit à filtrer les opérateurs
# ══════════════════════════════════════════════════════════════════════════════════════════════

#: Trois sortes, pas plus. Ce n'est pas un système de types : c'est la seule distinction dont le
#: filtrage des opérateurs a besoin. En ajouter (« entier », « date ») demanderait de justifier
#: quel opérateur s'y comporte différemment — aucun aujourd'hui.
NUMERIC = 'numerique'
TEXT = 'texte'
BOOLEAN = 'booleen'

KINDS: Tuple[str, ...] = (NUMERIC, TEXT, BOOLEAN)

_TOUTES = frozenset(KINDS)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2. Registre des OPÉRATEURS — même geste que `STATISTIQUES` du Calculator
# ══════════════════════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Operator:
    """Un opérateur de comparaison DÉCLARÉ.

    `kinds` est ce qui rend l'UI dérivable : une colonne de texte ne se voit pas proposer `>=`.
    `operande=False` marque les opérateurs qui ne prennent PAS de valeur de référence (`vide`) —
    sans ce champ, l'interface afficherait une case de saisie inutile et la validation ne pourrait
    pas distinguer « valeur oubliée » de « valeur sans objet ».
    """
    test: Callable[[Any, Any], bool]
    kinds: FrozenSet[str]
    label: str
    operand: bool = True


def _texte(v: Any) -> str:
    """Vue TEXTE d'une valeur, pour les opérateurs de chaîne. `None`/NaN → chaîne vide.

    Comparer `str(None)` donnerait `'None'`, qui « contient » un `o` : une absence de donnée se
    mettrait à satisfaire des conditions. C'est le genre de faux positif qu'on ne voit jamais dans
    un tableau de résultats.
    """
    return '' if missing(v) else str(v)


def _num(op: Callable[[Any, Any], bool]) -> Callable[[Any, Any], bool]:
    """Comparaison numérique STRICTE : une valeur absente ou non numérique rend `False`.

    Refuser plutôt que convertir. `float('12')` marcherait, mais alors la même colonne se
    comparerait tantôt comme du texte tantôt comme un nombre selon les lignes — et le masque
    dépendrait du contenu, pas de la déclaration.
    """
    def _test(value: Any, reference: Any) -> bool:
        if missing(value) or isinstance(value, bool):
            return False
        if not isinstance(value, (int, float)):
            return False
        try:
            return bool(op(value, reference))
        except TypeError:
            return False
    return _test


#: Vocabulaire COMMUN des comparaisons : nom → `Operator`. Ajouter une entrée ici la rend
#: disponible à la déclaration, à la validation ET à l'UI — il n'y a pas d'autre endroit à toucher.
#:
#: ⚠ 14 entrées là où l'outil d'origine en a 16 : ses `=` / `≠` (numériques) et ses
#: « est égal à » / « n'est pas égal à » (texte) sont FUSIONNÉS en `==` / `!=`. Le dédoublement
#: n'existait chez lui que par contrainte du langage — en MATLAB, `==` sur deux chaînes compare les
#: caractères un à un et rend un vecteur, pas un booléen, d'où un second opérateur pour `strcmp`.
#: Python n'a pas ce défaut : garder deux noms pour une seule question créerait exactement la
#: juxtaposition de vocabulaires que WAMA s'interdit.
OPERATORS: Dict[str, Operator] = {
    # ── Comparaisons d'ORDRE — numériques seules : « plus grand » n'a pas de sens sur du texte
    #    (l'ordre lexicographique en a un, mais ce n'est pas ce que l'utilisateur demande).
    '<':  Operator(_num(lambda v, r: v < r),  frozenset({NUMERIC}), 'est inférieur à'),
    '<=': Operator(_num(lambda v, r: v <= r), frozenset({NUMERIC}), 'est inférieur ou égal à'),
    '>':  Operator(_num(lambda v, r: v > r),  frozenset({NUMERIC}), 'est supérieur à'),
    '>=': Operator(_num(lambda v, r: v >= r), frozenset({NUMERIC}), 'est supérieur ou égal à'),

    # ── ÉGALITÉ — toutes sortes (voir la note de fusion ci-dessus).
    '==': Operator(lambda v, r: (not missing(v)) and v == r, _TOUTES, 'est égal à'),
    '!=': Operator(lambda v, r: (not missing(v)) and v != r, _TOUTES, "n'est pas égal à"),

    # ── TEXTE.
    'contains': Operator(
        lambda v, r: _texte(r) in _texte(v), frozenset({TEXT}), 'contient'),
    'not_contains': Operator(
        lambda v, r: _texte(r) not in _texte(v), frozenset({TEXT}), 'ne contient pas'),
    'startswith': Operator(
        lambda v, r: _texte(v).startswith(_texte(r)), frozenset({TEXT}), 'commence par'),
    'not_startswith': Operator(
        lambda v, r: not _texte(v).startswith(_texte(r)), frozenset({TEXT}),
        'ne commence pas par'),
    'endswith': Operator(
        lambda v, r: _texte(v).endswith(_texte(r)), frozenset({TEXT}), 'finit par'),
    'not_endswith': Operator(
        lambda v, r: not _texte(v).endswith(_texte(r)), frozenset({TEXT}), 'ne finit pas par'),

    # ── PRÉSENCE — sans opérande, et applicables à toutes les sortes. Ce sont les seuls
    #    opérateurs qui interrogent l'ABSENCE ; tous les autres la traitent comme un `False`.
    'empty': Operator(
        lambda v, r=None: missing(v) or _texte(v) == '', _TOUTES, 'est vide', operand=False),
    'not_empty': Operator(
        lambda v, r=None: (not missing(v)) and _texte(v) != '', _TOUTES, "n'est pas vide",
        operand=False),
}


def operators_for(kind: str) -> List[str]:
    """Opérateurs applicables à une sorte de colonne, dans l'ordre du registre.

    C'EST LA FONCTION QUI DÉRIVE L'UI. Le menu d'une condition ne s'écrit pas : il s'obtient d'ici.
    Sans elle, chaque interface recopierait la liste — et divergerait, exactement comme les six
    graphies du bouton ⚙ avant qu'une brique ne les rende inutiles à discuter.
    """
    if kind not in _TOUTES:
        raise ValueError(f"sorte '{kind}' inconnue (attendu : {', '.join(KINDS)})")
    return [name for name, op in OPERATORS.items() if kind in op.kinds]


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3. La CONDITION — une déclaration, pas une ligne d'interface
# ══════════════════════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Condition:
    """Une condition atomique, SÉRIALISABLE — donc entrant dans un manifeste, donc rejouable.

    Chez l'outil d'origine elle vit dans une struct d'application (`app.structCondition`, sauvée
    par `save_env_*`) : elle appartient à une SESSION. Ici elle appartient à la DÉCLARATION, ce qui
    est toute la différence entre « j'ai refait la même analyse » et « j'ai rejoué la même analyse ».

    `key` est l'étiquette (`C1`, `C2`…) par laquelle l'arbre logique la désigne. `stream` nomme la
    table d'où vient la colonne — deux conditions peuvent porter le même nom de champ dans deux
    tables différentes, et sans `stream` l'arbre serait ambigu.

    ⚠ `stream` et non `source` (renommé le 2026-08-23, §9sexies) : dans ce monde, **`source`
    désigne déjà un fichier/format à lire** (`SourceReader`, `SourceInfo`, `sources/`).
    """
    key: str
    field: str
    operator: str
    value: Any = None
    stream: str = ''
    kind: str = NUMERIC

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("une condition doit porter une clé (« C1 », « C2 »…)")
        op = OPERATORS.get(self.operator)
        if op is None:
            raise ValueError(
                f"{self.key} : opérateur '{self.operator}' inconnu "
                f"(disponibles : {', '.join(OPERATORS)})")
        if self.kind not in _TOUTES:
            raise ValueError(f"{self.key} : sorte '{self.kind}' inconnue "
                             f"(attendu : {', '.join(KINDS)})")
        # LE contrôle qui n'existe pas dans l'outil d'origine : l'opérateur doit convenir à la
        # sorte de la colonne. Sans lui, `<` sur du texte rend un masque plausible et faux.
        if self.kind not in op.kinds:
            raise ValueError(
                f"{self.key} : l'opérateur '{self.operator}' ne s'applique pas à une colonne "
                f"{self.kind} (admis : {', '.join(sorted(op.kinds))}) — "
                f"pour cette colonne : {', '.join(operators_for(self.kind))}")
        # Une valeur fournie à un opérateur qui n'en prend pas est une faute de déclaration, pas
        # un détail à ignorer : elle signale que l'auteur croyait comparer à quelque chose.
        if not op.operand and self.value is not None:
            raise ValueError(
                f"{self.key} : l'opérateur '{self.operator}' ne prend pas de valeur de référence")
        if op.operand and self.value is None:
            raise ValueError(
                f"{self.key} : l'opérateur '{self.operator}' exige une valeur de référence")

    def evaluate(self, values: Sequence[Any]) -> List[bool]:
        """Masque booléen de la condition sur une colonne, ligne à ligne."""
        test = OPERATORS[self.operator].test
        return [bool(test(v, self.value)) for v in values]

    def render(self) -> str:
        """Phrase lisible — `vitesse contient « FIN »`. Sert aux libellés et aux messages."""
        op = OPERATORS[self.operator]
        cible = f"{self.stream}.{self.field}" if self.stream else self.field
        return f"{cible} {op.label}" + (f" « {self.value} »" if op.operand else "")

    def to_dict(self) -> Dict[str, Any]:
        """Forme sérialisée — §9ter.6 B1 affirmait cette propriété, elle n'existait pas (§9sexies).

        ⚠ `kind` N'Y FIGURE PAS, délibérément : elle est **lue dans la donnée** par l'adaptateur,
        jamais déclarée. La sérialiser inviterait à la relire, donc à laisser une déclaration
        contredire la colonne qu'elle décrit — le défaut même que le filtrage par sorte corrige.
        """
        return {'key': self.key, 'stream': self.stream, 'field': self.field,
                'operator': self.operator, 'value': self.value}


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 4. L'ARBRE logique — le modèle ; le texte n'en est que le rendu
# ══════════════════════════════════════════════════════════════════════════════════════════════

#: Un nœud : soit une clé de condition (`'C1'`), soit `{'op': 'ET', 'args': [...]}`.
Tree = Union[str, Dict[str, Any]]


@dataclass(frozen=True)
class Connector:
    """Un connecteur logique déclaré. `arity` vaut `None` pour « deux ou plus »."""
    calcul: Callable[[List[bool]], bool]
    arity: Optional[int]
    label: str


def _xor(bits: List[bool]) -> bool:
    return bits[0] != bits[1]


#: ⚠ `ET` et `OU` sont N-AIRES ici alors qu'ils sont binaires dans l'outil d'origine (`@and`,
#: `@or`). Ce n'est pas un enrichissement gratuit : c'est ce qui supprime l'imbrication à gauche
#: que son constructeur de texte devait fabriquer par concaténation — `ET ( ET (C1 , C2) , C3 )`
#: pour dire « les trois ». L'arbre n-aire dit la même chose sans profondeur artificielle, et deux
#: déclarations équivalentes s'y comparent.
#:
#: ⚠ `XOR` reste BINAIRE, délibérément. À trois arguments, « ou exclusif » a deux lectures
#: courantes et incompatibles — parité (un nombre impair de vrais) ou exclusivité (exactement un
#: vrai) — qui divergent dès `(V, V, V)`. Aucune n'est « la » bonne : on refuse la question plutôt
#: que d'en trancher une au hasard dans un moteur d'analyse scientifique.
CONNECTEURS: Dict[str, Connector] = {
    'ET':  Connector(all, None, 'et'),
    'OU':  Connector(any, None, 'ou'),
    'XOR': Connector(_xor, 2, 'ou exclusif'),
    'NON': Connector(lambda bits: not bits[0], 1, 'non'),
}


def validate(arbre: Tree, cles: Sequence[str], _chemin: str = 'racine') -> None:
    """Refuse un arbre mal formé À LA DÉCLARATION, en NOMMANT le fautif et son emplacement.

    C'est la contrepartie directe du `try/catch` unique de l'outil d'origine, qui ne pouvait dire
    que « Probleme avec les connecteurs ». Quatre fautes sont distinguées ici, et chacune a son
    message : clé inconnue, connecteur inconnu, arité fausse, nœud malformé.
    """
    if isinstance(arbre, str):
        if arbre not in cles:
            connues = ', '.join(cles) if cles else '— aucune condition déclarée'
            raise ValueError(f"{_chemin} : condition '{arbre}' jamais déclarée (connues : {connues})")
        return

    if not isinstance(arbre, dict) or 'op' not in arbre:
        raise ValueError(
            f"{_chemin} : nœud attendu sous la forme {{'op': …, 'args': [...]}}, reçu {arbre!r}")

    op = arbre['op']
    connecteur = CONNECTEURS.get(op)
    if connecteur is None:
        raise ValueError(
            f"{_chemin} : connecteur '{op}' inconnu (disponibles : {', '.join(CONNECTEURS)})")

    args = arbre.get('args')
    if not isinstance(args, (list, tuple)) or not args:
        raise ValueError(f"{_chemin} : le connecteur '{op}' attend une liste d'arguments non vide")

    attendue = connecteur.arity
    if attendue is not None and len(args) != attendue:
        raise ValueError(
            f"{_chemin} : '{op}' prend {attendue} argument(s), {len(args)} fourni(s)")
    if attendue is None and len(args) < 2:
        raise ValueError(
            f"{_chemin} : '{op}' prend au moins 2 arguments, {len(args)} fourni(s)")

    for i, sous in enumerate(args):
        validate(sous, cles, f"{_chemin} › {op}[{i + 1}]")


def evaluate(arbre: Tree, masques: Mapping[str, Sequence[bool]]) -> List[bool]:
    """Combine les masques des conditions selon l'arbre. Toutes de MÊME longueur.

    L'égalité des longueurs est vérifiée : des masques dépareillés viendraient de colonnes de
    tables différentes, et les combiner produirait un masque tronqué à la plus courte — donc des
    segments qui s'arrêtent sans raison visible.
    """
    validate(arbre, list(masques))
    longueurs = {len(m) for m in masques.values()}
    if len(longueurs) > 1:
        detail = ', '.join(f"{k}={len(v)}" for k, v in masques.items())
        raise ValueError(f"masques de longueurs différentes ({detail}) — les conditions doivent "
                         "porter sur des colonnes du même échantillonnage")
    return _evaluer(arbre, masques, longueurs.pop() if longueurs else 0)


def _evaluer(arbre: Tree, masques: Mapping[str, Sequence[bool]], n: int) -> List[bool]:
    if isinstance(arbre, str):
        return [bool(x) for x in masques[arbre]]
    calcul = CONNECTEURS[arbre['op']].calcul
    sous = [_evaluer(a, masques, n) for a in arbre['args']]
    return [calcul([m[i] for m in sous]) for i in range(n)]


def render(arbre: Tree) -> str:
    """Rendu textuel canonique de l'arbre — `ET(C1, OU(C2, NON(C3)))`.

    Une seule forme, préfixe et parenthésée, pour l'affichage comme pour la relecture. L'outil
    d'origine en avait deux (celle qu'il construit et celle qu'il montre en exemple) et elles
    n'étaient pas la même : voir ② en tête de module.
    """
    if isinstance(arbre, str):
        return arbre
    return f"{arbre['op']}({', '.join(render(a) for a in arbre['args'])})"


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 5. SAISIE textuelle — acceptée, immédiatement convertie en arbre
# ══════════════════════════════════════════════════════════════════════════════════════════════

def parse(text: str, cles: Sequence[str]) -> Tree:
    """Convertit une saisie `ET(C1, OU(C2, NON(C3)))` en arbre validé.

    Accepte la forme de l'outil d'origine — préfixe, séparateurs virgule OU espace, espaces libres
    autour des parenthèses (`ET (C1 , C2)`). N'accepte PAS l'infixe (`C1 ET C2`) : la seule
    interface qui l'ait jamais affiché ne savait pas non plus l'exécuter (② en tête).

    Le résultat est un arbre — le texte n'est pas conservé. C'est le point : deux saisies
    différemment espacées donnent le même modèle, donc se comparent.
    """
    jetons = _decouper(text)
    if not jetons:
        raise ValueError("chaîne de connecteurs vide — déclarer au moins une condition")
    arbre, reste = _lire(jetons, 0)
    if reste != len(jetons):
        raise ValueError(f"texte en trop après l'expression : « {' '.join(jetons[reste:])} »")
    validate(arbre, cles)
    return arbre


def _decouper(text: str) -> List[str]:
    jetons: List[str] = []
    courant = ''
    for c in text:
        if c in '(),' or c.isspace():
            if courant:
                jetons.append(courant)
                courant = ''
            if c in '(),':
                jetons.append(c)
        else:
            courant += c
    if courant:
        jetons.append(courant)
    return jetons


def _lire(jetons: List[str], i: int) -> Tuple[Tree, int]:
    if i >= len(jetons):
        raise ValueError("expression incomplète — il manque un opérande")
    jeton = jetons[i]
    if jeton in '(),':
        raise ValueError(f"« {jeton} » inattendu à la position {i + 1}")

    # Un nom suivi d'une parenthèse est un connecteur ; seul, c'est une clé de condition.
    if i + 1 < len(jetons) and jetons[i + 1] == '(':
        if jeton not in CONNECTEURS:
            raise ValueError(
                f"connecteur '{jeton}' inconnu (disponibles : {', '.join(CONNECTEURS)})")
        args: List[Tree] = []
        j = i + 2
        while j < len(jetons) and jetons[j] != ')':
            if jetons[j] == ',':
                j += 1
                continue
            sous, j = _lire(jetons, j)
            args.append(sous)
        if j >= len(jetons):
            raise ValueError(f"parenthèse jamais refermée après '{jeton}'")
        return {'op': jeton, 'args': args}, j + 1

    if jeton in CONNECTEURS:
        raise ValueError(f"le connecteur '{jeton}' doit être suivi de ses arguments entre "
                         f"parenthèses — par exemple {jeton}(C1, C2)")
    return jeton, i + 1


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 6. SÉRIALISATION d'une condition
# ══════════════════════════════════════════════════════════════════════════════════════════════

def condition_from_dict(brut: Mapping[str, Any], kind: str = NUMERIC) -> Condition:
    """Reconstruit une condition depuis sa forme sérialisée, en LUI IMPOSANT une sorte.

    La sorte est un paramètre d'appel et non une clé du dict : c'est l'appelant qui la connaît
    (l'adaptateur la lit dans le cadre), et une déclaration ne doit pas pouvoir la dicter.
    """
    if not isinstance(brut, Mapping):
        raise ValueError(f"condition attendue sous forme d'objet, reçu {type(brut).__name__}")
    return Condition(key=brut.get('key', ''), field=brut.get('field', ''),
                     operator=brut.get('operator', ''), value=brut.get('value'),
                     stream=brut.get('stream', ''), kind=kind)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 7. Nom DÉRIVÉ — délégué à la brique unique `core/noms.py` (audit A, §9sexies)
# ══════════════════════════════════════════════════════════════════════════════════════════════

#: Réexports : `join_name` vivait ici alors qu'elle nomme une JONCTION, pas une condition.
#: Elle a rejoint la brique ; on la garde importable d'ici pour ne pas casser les appelants.
from .naming import join_name, normalize  # noqa: E402,F401


def chain_name(arbre: Tree) -> str:
    """Nom dérivé d'une chaîne conditionnelle — `et_c1_ou_c2_c3`, en minuscules et sans ponctuation.

    Dérivé de l'ARBRE et non du texte saisi : c'est ce qui rend deux saisies équivalentes (espaces,
    virgules) porteuses du même nom.
    """
    return normalize(render(arbre))
