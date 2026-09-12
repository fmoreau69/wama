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

CE QUI EST REFUSÉ — une doc dérivée ne se construit jamais « à peu près »

    Doc source inconnu, section introuvable ou ambiguë, section non marquée pour ce public,
    marquage invalide dans la source, générateur de faits introuvable : `PlanError`, que
    `doc_facts` compte comme CASSÉ.
"""
from __future__ import annotations

import importlib
import posixpath
import re
from typing import List

from .doc_sections import _TAG as _TAG_SECTION
from .doc_sections import ETATS, sections

HEADER = ("<!-- WAMA:GENERE({key}) — généré par « python manage.py doc_facts » depuis le plan "
          "de wama/common/docs_catalog.py ; ne pas éditer -->")

_LIEN = re.compile(r'(\]\()([^)\s#]+)((?:#[^)\s]*)?\))')
_SCHEME = re.compile(r'^[a-z][a-z0-9+.\-]*:', re.I)


class PlanError(ValueError):
    """Un plan qui ne se construit pas — cassé, jamais approximé."""


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
                     target_path: str, title: str = '') -> List[str]:
    """Les lignes markdown d'UN extrait : la section (et ses sous-sections destinées au même
    public), titres ramenés au niveau 2, balises retirées, liens recalés, source citée en pied."""
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

    lignes = texte.splitlines()
    idx = secs.index(s)
    fin = next((t.line for t in secs[idx + 1:] if t.level <= s.level), len(lignes) + 1)
    enfants = [t for t in secs[idx + 1:] if t.line < fin]
    exclues = set()
    for k, t in enumerate(enfants):
        if audience not in t.attrs.get('audience', ()):
            # Une sous-section marquée pour un AUTRE public sort de l'extrait, avec les siennes.
            fin_t = next((u.line for u in enfants[k + 1:] if u.level <= t.level), fin)
            exclues.update(range(t.line, fin_t))
    decalage = 2 - s.level
    titres = {t.line: t for t in enfants}

    out = [f"## {title or s.title}", ""]
    if s.attrs.get('nature') == 'intention':
        etat = s.attrs.get('etat', '')
        out += [f"> {etat} **Intention** ({ETATS.get(etat, '')}) — ce que décrit cette section "
                f"n'est pas encore implémenté.", ""]
    corps = []
    for n in range(s.line + 1, fin):
        if n in exclues:
            continue
        ligne = lignes[n - 1]
        if _TAG_SECTION.match(ligne):
            continue
        if n in titres:
            t = titres[n]
            ligne = '#' * max(2, min(6, t.level + decalage)) + ' ' + t.title
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
                                    etape.title)
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
