"""
Les docs DÉRIVÉES, construites par PLAN (ROADMAP.md §25.1 ③).

POURQUOI (Fabien, 2026-09-11)

    Les docs développeur et utilisateur DÉRIVENT de la doc de construction et y injectent les
    faits des registres. Un PLAN, déclaré dans `docs_catalog.py` à côté du doc qu'il produit, dit
    dans quel ordre on prend quoi : des EXTRAITS (sections de la doc de construction marquées pour
    ce public, `doc_sections.py`) et des FAITS (blocs calculés depuis les registres). Le `.md`
    produit est VERSIONNÉ — lisible depuis le dépôt comme depuis WAMA — et `doc_facts` le réécrit ;
    `doc_facts --check` échoue dès qu'il n'est plus ce que son plan produit.

LA CONFRONTATION DOC → DOC EST GRATUITE ICI (④)

    La dérivation est MÉCANIQUE : une source modifiée change le résultat, donc `--check` le voit.
    Une empreinte des sources ne servirait que si un humain ou un modèle réécrivait le texte.

LA PORTE REGISTRE — ce qui entre dans une doc UTILISATEUR (⑤, 2026-09-14)

    La doc de construction porte la vision ENTIÈRE ; l'utilisateur ne doit lire que ce qui existe.
    Une section destinée à l'utilisateur déclare donc sa porte (`porte=registre/clé`, ou
    `registre/clé/champ` pour un champ qui doit être vrai) : le fragment n'entre dans la doc
    utilisateur que si le registre confirme ce qu'il décrit — et jamais s'il est une INTENTION.
    Retenu n'est pas cassé : le fragment attend son implémentation, et le fichier produit le dit
    en commentaire (`WAMA:PORTE-FERMEE`), invisible à la lecture. Une porte INVÉRIFIABLE —
    registre inconnu, ou qui ne déclare pas ses fiches — est cassée, elle. Le développeur lit les
    intentions, annoncées comme telles : la porte ne filtre que la doc utilisateur.

CE QUI EST REFUSÉ — une doc dérivée ne se construit jamais « à peu près »

    Doc source inconnu, section introuvable ou ambiguë, section non marquée pour ce public,
    marquage invalide dans la source, générateur de faits introuvable, porte invérifiable :
    `PlanError`, que `doc_facts` compte comme CASSÉ.
"""
from __future__ import annotations

import importlib
import posixpath
import re
from typing import Callable, List, Optional

from .doc_sections import _TAG as _TAG_SECTION
from .doc_sections import STATES, sections

HEADER = ("<!-- WAMA:GENERE({key}) — généré par « python manage.py doc_facts » depuis le plan "
          "de wama/common/docs_catalog.py ; ne pas éditer -->")
#: Trace d'un fragment RETENU par la porte, laissée dans le fichier produit (invisible à la lecture).
GATE_CLOSED_MARK = "<!-- WAMA:PORTE-FERMEE({ou}) : {raison} -->"
#: = `docs_catalog.USER` — valeur de DONNÉE, écrite dans les balises des docs.
USER = 'utilisateur'

_LIEN = re.compile(r'(\]\()([^)\s#]+)((?:#[^)\s]*)?\))')
#: Le numéro d'une section de la doc de construction (« 9.1 », « 9quinquies.2 ») : un repère de
#: la SOURCE, qui ne numérote rien dans la doc dérivée.
_SECTION_NUMBER = re.compile(r'^\d+[a-z]*(?:\.\d+[a-z]*)*\.?\s+')
_SCHEME = re.compile(r'^[a-z][a-z0-9+.\-]*:', re.I)


class PlanError(ValueError):
    """Un plan qui ne se construit pas — cassé, jamais approximé."""


def gate_unverifiable(chemin: str) -> Optional[str]:
    """Pourquoi une porte ne peut pas être VÉRIFIÉE (registre inconnu, ou sans fiches) ; `None`
    sinon. Ne lit aucune fiche : `check_docs` l'appelle sur tout le corpus."""
    from .registries import REGISTRIES
    registre = chemin.split('/')[0]
    r = REGISTRIES.get(registre)
    if r is None:
        return f"porte « {chemin} » : registre « {registre} » inconnu"
    if r.entries is None:
        return (f"porte « {chemin} » : le registre « {registre} » ne déclare pas ses fiches "
                f"(`Registry.entries`) — il ne peut rien confirmer")
    return None


def gate_closed(chemin: str) -> Optional[str]:
    """Pourquoi le registre ne confirme PAS ce que la porte désigne ; `None` si elle est ouverte.
    Lève `PlanError` si la porte est invérifiable."""
    from .fact_tags import FactError, entries
    invalide = gate_unverifiable(chemin)
    if invalide:
        raise PlanError(invalide)
    registre, cle, *champ = chemin.split('/')
    try:
        fiches = entries(registre)
    except FactError as e:
        raise PlanError(f"porte « {chemin} » : {e}")
    if cle not in fiches:
        return f"« {cle} » absent du registre « {registre} »"
    if champ:
        fiche = fiches[cle]
        if champ[0] not in fiche:
            raise PlanError(f"porte « {chemin} » : champ « {champ[0]} » absent de la fiche")
        if not fiche[champ[0]]:
            return f"{chemin} est faux"
    return None


def _relink(ligne: str, source_path: str, target_path: str) -> str:
    """Un lien relatif écrit pour la SOURCE, réécrit pour le fichier CIBLE — sinon un extrait
    copié dans `docs/dev/` pointerait dans le vide, sur GitHub comme dans le lecteur."""
    def _sub(m):
        cible = m.group(2)
        if cible.startswith('/') or _SCHEME.match(cible):
            return m.group(0)
        absolu = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), cible))
        rel = posixpath.relpath(absolu, posixpath.dirname(target_path) or '.')
        return f"{m.group(1)}{rel}{m.group(3)}"
    return _LIEN.sub(_sub, ligne)


def excerpt_markdown(texte: str, section: str, audience: str, source_path: str,
                     target_path: str, title: str = '',
                     gate: Optional[Callable[[str], Optional[str]]] = None) -> List[str]:
    """Les lignes markdown d'UN extrait : la section (et ses sous-sections destinées au même
    public), titres ramenés au niveau 2, balises retirées, liens recalés, source citée en pied.

    `gate` : `chemin → raison de fermeture ou None` (`gate_closed` en vrai, une fonction de
    test sinon). Requise dès que l'extrait est destiné à l'utilisateur."""
    secs, erreurs = sections(texte)
    if erreurs:
        raise PlanError(f"{source_path} : marquage invalide ligne {erreurs[0][0]} — "
                        f"{erreurs[0][1]}")
    trouvees = [s for s in secs if s.title == section]
    if not trouvees:
        raise PlanError(f"section « {section} » introuvable dans {source_path}")
    if len(trouvees) > 1:
        raise PlanError(f"section « {section} » ambiguë dans {source_path} "
                        f"({len(trouvees)} titres identiques)")
    s = trouvees[0]
    if audience not in s.attrs.get('audience', ()):
        raise PlanError(f"section « {section} » ({source_path}) non marquée pour « {audience} »")

    def _withheld(attrs) -> Optional[str]:
        """Pourquoi un fragment n'entre PAS dans la doc utilisateur ; `None` s'il y entre."""
        if audience != USER:
            return None
        if attrs.get('nature') == 'intention':
            return (f"intention {attrs.get('etat', '')} — n'arrive chez l'utilisateur qu'une "
                    f"fois implémentée")
        if gate is None:
            raise PlanError("extrait pour l'utilisateur sans résolveur de porte")
        for chemin in attrs.get('porte', ()):
            raison = gate(chemin)
            if raison:
                return f"porte {chemin} fermée — {raison}"
        return None

    raison = _withheld(s.attrs)
    if raison:
        return [GATE_CLOSED_MARK.format(ou=f"{source_path} — {s.title}", raison=raison), ""]

    lignes = texte.splitlines()
    idx = secs.index(s)
    fin = next((t.line for t in secs[idx + 1:] if t.level <= s.level), len(lignes) + 1)
    enfants = [t for t in secs[idx + 1:] if t.line < fin]
    exclues, retenues = set(), {}
    for k, t in enumerate(enfants):
        if t.line in exclues:
            continue                                   # déjà sortie avec un parent
        if audience in t.attrs.get('audience', ()):
            # Une sous-section qui HÉRITE partage le verdict de son parent, déjà rendu.
            raison = None if t.inherited else _withheld(t.attrs)
            if raison is None:
                continue
            retenues[t.line] = GATE_CLOSED_MARK.format(ou=f"{source_path} — {t.title}", raison=raison)
        # Sortie de l'extrait, avec ses propres sous-sections : marquée pour un AUTRE public, ou
        # retenue par la porte.
        fin_t = next((u.line for u in enfants[k + 1:] if u.level <= t.level), fin)
        exclues.update(range(t.line, fin_t))
    decalage = 2 - s.level
    titres = {t.line: t for t in enfants}

    out = [f"## {title or s.title}", ""]
    if s.attrs.get('nature') == 'intention':
        etat = s.attrs.get('etat', '')
        out += [f"> {etat} **Intention** ({STATES.get(etat, '')}) — ce que décrit cette section "
                f"n'est pas encore implémenté.", ""]
    corps = []
    dans_note = False
    for n in range(s.line + 1, fin):
        if n in exclues:
            if n in retenues:
                corps.append(retenues[n])
            continue
        ligne = lignes[n - 1]
        if _TAG_SECTION.match(ligne):
            continue
        # Un commentaire HTML de la source est une NOTE DE CONSTRUCTION (vérifié quand, contre
        # quel fichier) : invisible partout, il ne concerne pas les publics. Les balises `WAMA:`
        # (faits, blocs générés) passent, elles portent du contenu.
        nue = ligne.lstrip()
        if dans_note or (nue.startswith('<!--') and not nue.startswith('<!-- WAMA:')):
            dans_note = '-->' not in ligne
            continue
        if n in titres:
            t = titres[n]
            ligne = ('#' * max(2, min(6, t.level + decalage)) + ' '
                     + (_SECTION_NUMBER.sub('', t.title) or t.title))
        corps.append(_relink(ligne, source_path, target_path))
    out += ['\n'.join(corps).strip('\n'), ""]

    from .docs_catalog import _slug
    lien = posixpath.relpath(source_path, posixpath.dirname(target_path) or '.')
    out += [f"*Source : [{source_path} — {s.title}]({lien}#{_slug(s.title, {})})*", ""]
    return out


def build(doc) -> str:
    """Le `.md` complet d'une doc dérivée, tel que son plan le produit AUJOURD'HUI."""
    from .docs_catalog import AUDIENCE_BADGES, BY_KEY, Excerpt, Facts, file_of

    if not doc.plan or not doc.path:
        raise PlanError(f"« {doc.key} » : un plan exige un chemin et au moins une étape")
    badge = AUDIENCE_BADGES.get(doc.audience, doc.audience)
    out = [HEADER.format(key=doc.key), f"# {doc.label}", "",
           f"> {badge[:1].upper()}{badge[1:]} **générée** : chaque section vient de la doc de "
           f"construction (source citée en pied) ou des registres eux-mêmes. Pour la corriger, "
           f"corriger la SOURCE — ce fichier est réécrit par `python manage.py doc_facts`.", ""]
    for etape in doc.plan:
        if isinstance(etape, Excerpt):
            source = BY_KEY.get(etape.doc)
            if source is None or not source.path:
                raise PlanError(f"doc source « {etape.doc} » inconnu du catalogue (ou sans fichier)")
            try:
                texte = file_of(source).read_text(encoding='utf-8')
            except OSError as e:
                raise PlanError(f"{source.path} illisible : {e}")
            out += excerpt_markdown(texte, etape.section, doc.audience, source.path, doc.path,
                                    etape.title, gate=gate_closed)
        elif isinstance(etape, Facts):
            module, _, fonction = etape.generator.partition(':')
            try:
                produire = getattr(importlib.import_module(module), fonction)
            except (ImportError, AttributeError):
                raise PlanError(f"générateur de faits « {etape.generator} » introuvable")
            # Un générateur écrit ses liens depuis la RACINE : on les recale sur la cible.
            faits = produire().strip().splitlines()
            out += [_relink(l, '', doc.path) for l in faits] + [""]
        else:
            raise PlanError(f"étape de plan inconnue : {type(etape).__name__}")
    return '\n'.join(out).rstrip() + '\n'
