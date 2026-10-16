"""
Le FOND en sections et sa FORME qui en garde les repères — la mise en forme AJUSTÉE d'un document
(2026-10-13, `ROADMAP §21.5`). Décision de Fabien : *« remise en forme par section si la section
est complètement modifiée, forme réutilisée si seulement un bout de phrase est modifié — la
quantité de modifications définit le process d'ajustement »*.

CE QUE FAIT CETTE BRIQUE, et ce qu'elle ne fait pas :
  • elle DÉCOUPE un fond Markdown en sections, par la règle de la brique de surface
    `text_sections` (un titre `#…` hors bloc de code commence une section ; rien ne se perd) — la
    même règle dans les deux langues, tenue par un test qui fait tourner le JS sous V8 ;
  • elle MESURE ce qui a changé section par section (`text_metrics.word_error_rate`, la mesure
    des signaux de qualité — jamais une seconde) et en tire un PLAN : rien, ajuster, ou tout
    refaire ;
  • elle AJUSTE le HTML précédent : un bout de phrase changé est remplacé dans le texte du HTML,
    sans modèle ; une section très modifiée est remise en forme SEULE, par le modèle que la glu
    lui passe (`ask`), en reprenant sa forme d'avant ;
  • elle ne choisit AUCUN modèle et n'écrit aucun fichier : c'est la glu du process de mise en
    forme qui appelle le modèle (`chat_with_catalog_model`) et rend son résultat au squelette.

LES REPÈRES. Le HTML garde la trace de ses sections : chaque section du fond est rendue dans un
élément `data-wama-section="<n>"` (n = rang dans le fond, 0 d'abord). Une mise en forme complète
les demande (`full_layout_messages`) ; sans eux, aucun ajustement n'est possible et le plan
dit de tout refaire. Ce sont aussi les ancres qu'attend le « clic dans l'aperçu → section ».

LA BASE DE COMPARAISON vient des fichiers de révision GARDÉS (`revisions.keep_outputs`,
`WAMA_COLLABORATION §7.2`) — le ▶ d'un process remplace sa sortie AVANT de lancer
(`AppPipeline.reset_outputs`) : l'ancien rendu n'existe plus qu'en copie de révision. Elle ne
vaut que si la FORME demandée n'a pas bougé depuis : la photo de ce que le process surveille
(`ctx.previous_snapshot` / `ctx.snapshot`, hors empreinte d'amont) le dit.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

#: L'attribut qui repère une section du fond dans le HTML rendu.
SECTION_ATTR = 'data-wama-section'
#: Au-delà de cette part de mots changés (WER contre la version d'avant), une section se remet en
#: forme ; en deçà, sa forme est réutilisée et seul son texte change. Défaut de départ, à régler.
PATCH_CEILING = 0.3

_HEADING = re.compile(r'^#{1,6}\s')
_FENCE = re.compile(r'^\s*(```|~~~)')


# ── Le fond en sections ─────────────────────────────────────────────────────────────────────

def split_sections(text: str) -> list:
    """Les sections d'un texte, sans rien perdre : leur concaténation EST le texte. Jumelle de
    `split` de `brick-text-sections.js` — mêmes cas, même résultat (`tests_document_sections`)."""
    lines = re.findall(r'[^\n]*\n|[^\n]+$', str(text or ''))
    out, cur, fenced = [], '', False
    for line in lines:
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced and _HEADING.match(line) and cur:
            out.append(cur)
            cur = ''
        cur += line
    if cur or not out:
        out.append(cur)
    return out


def plain_text(line: str) -> str:
    """Le texte LU d'une ligne Markdown, sans sa syntaxe : ce qu'un rendu HTML en affiche."""
    s = re.sub(r'^\s*#{1,6}\s+', '', line)
    s = re.sub(r'^\s*>\s?', '', s)
    s = re.sub(r'^\s*(?:[-*+]|\d+[.)])\s+', '', s)
    s = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', s)
    s = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', s)
    s = re.sub(r'(\*\*|__|\*|_|`)', '', s)
    return ' '.join(s.split())


def _content_lines(chunk: str) -> list:
    return [line.strip() for line in chunk.split('\n') if line.strip() and not _FENCE.match(line)]


# ── Le plan ─────────────────────────────────────────────────────────────────────────────────

@dataclass
class SectionChange:
    index: int
    kind: str                 # 'keep' | 'patch' | 'relayout'
    old: str
    new: str
    rate: float | None = None


@dataclass
class LayoutPlan:
    mode: str                 # 'none' (rien à refaire) | 'adjust' | 'full'
    reason: str = ''
    changes: list = field(default_factory=list)

    def counts(self) -> dict:
        out = {'keep': 0, 'patch': 0, 'relayout': 0}
        for change in self.changes:
            out[change.kind] += 1
        return out


def anchored_sections(soup) -> dict:
    """`{rang: élément}` des sections repérées d'un HTML déjà analysé (BeautifulSoup)."""
    found = {}
    for tag in soup.find_all(attrs={SECTION_ATTR: True}):
        try:
            found.setdefault(int(tag.get(SECTION_ATTR)), tag)
        except (TypeError, ValueError):
            continue
    return found


def _soup(html: str):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html or '', 'html.parser')


def plan_layout_update(previous_text: str, text: str, previous_html: str, *,
                       ceiling: float = PATCH_CEILING, language: str | None = None) -> LayoutPlan:
    """Ce que demande le passage de `previous_text` à `text`, quand `previous_html` est la forme
    rendue de `previous_text` : rien, AJUSTER section par section, ou tout refaire.

    Tout refaire quand il manque une base (pas de fond ou de rendu d'avant), quand des sections
    sont ajoutées ou retirées (la structure du document change), ou quand le rendu ne porte pas
    les repères de toutes ses sections. Sinon, par section : inchangée → gardée ; une part de
    mots changés ≤ `ceiling` → texte remplacé dans la forme ; au-delà → remise en forme seule."""
    from wama.common.services.text_metrics import word_error_rate
    if not previous_text or not previous_html:
        return LayoutPlan('full', 'pas de version précédente gardée')
    old, new = split_sections(previous_text), split_sections(text)
    if len(old) != len(new):
        return LayoutPlan('full', f'{len(old)} → {len(new)} sections')
    anchors = anchored_sections(_soup(previous_html))
    if set(anchors) != set(range(len(old))):
        return LayoutPlan('full', 'le rendu précédent ne repère pas toutes ses sections')
    changes = []
    for index, (before, after) in enumerate(zip(old, new)):
        if before == after:
            changes.append(SectionChange(index, 'keep', before, after, 0.0))
            continue
        rate = word_error_rate(before, after, language).rate
        kind = 'patch' if rate is not None and rate <= ceiling else 'relayout'
        changes.append(SectionChange(index, kind, before, after, rate))
    if all(c.kind == 'keep' for c in changes):
        return LayoutPlan('none', 'fond inchangé', changes)
    return LayoutPlan('adjust', '', changes)


# ── L'ajustement ────────────────────────────────────────────────────────────────────────────

def _words_pattern(text: str):
    words = text.split()
    return re.compile(r'\s+'.join(re.escape(w) for w in words)) if words else None


def _replace_once(tag, old: str, new: str) -> bool:
    """Remplace `old` par `new` dans UN nœud de texte de `tag`, où `old` figure une seule fois
    (espaces souples). Faux si `old` est absent, ambigu, ou à cheval sur deux nœuds."""
    pattern = _words_pattern(old)
    if pattern is None:
        return False
    hits = [(node, m) for node in tag.find_all(string=True) for m in pattern.finditer(str(node))]
    if len(hits) != 1:
        return False
    node, m = hits[0]
    value = str(node)
    node.replace_with(value[:m.start()] + new + value[m.end():])
    return True


def _patch_line(tag, old_line: str, new_line: str) -> bool:
    """Une ligne du fond a changé : on remplace la ligne LUE entière si elle tient dans un nœud,
    sinon le seul passage changé, avec ce qu'il faut de contexte pour être unique."""
    old_plain, new_plain = plain_text(old_line), plain_text(new_line)
    if old_plain == new_plain:
        return False            # seule la syntaxe a changé (gras, lien) : c'est de la forme
    if _replace_once(tag, old_plain, new_plain):
        return True
    a, b = old_plain.split(), new_plain.split()
    head = 0
    while head < min(len(a), len(b)) and a[head] == b[head]:
        head += 1
    tail = 0
    while tail < min(len(a), len(b)) - head and a[-1 - tail] == b[-1 - tail]:
        tail += 1
    for context in (3, 2, 1, 0):
        lo = max(0, head - context)
        hi_a, hi_b = len(a) - max(0, tail - context), len(b) - max(0, tail - context)
        old_part, new_part = ' '.join(a[lo:hi_a]), ' '.join(b[lo:hi_b])
        if old_part and _replace_once(tag, old_part, new_part):
            return True
    return False


def patch_section(tag, old: str, new: str) -> bool:
    """Reporte dans l'élément `tag` (une section rendue) les changements de TEXTE de `old` à `new`,
    ligne à ligne. Faux — et rien n'est garanti de `tag`, qu'on jette — dès qu'une ligne est
    ajoutée, retirée ou introuvable dans la forme : la section se remet alors en forme."""
    old_lines, new_lines = _content_lines(old), _content_lines(new)
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == 'equal':
            continue
        if op != 'replace' or (i2 - i1) != (j2 - j1):
            return False
        for old_line, new_line in zip(old_lines[i1:i2], new_lines[j1:j2]):
            if not _patch_line(tag, old_line, new_line):
                return False
    return True


def _form_hints(*, style: str = '', language: str = '', kind: str = '') -> str:
    """Ce que le modèle doit savoir de la FORME demandée, en fin de consigne — dit une fois pour
    les deux mises en forme (une section, le document entier)."""
    return ((f" Nature du document : {kind}." if kind else '')
            + (f" Langue du document : {language}." if language else '')
            + (f" Consigne de forme : {style}" if style else ''))


def section_relayout_messages(index: int, new_text: str, current_html: str, *,
                              style: str = '', language: str = '') -> list:
    """Les messages qui demandent au modèle de remettre en forme UNE section, en reprenant la
    forme qu'elle avait (structure, classes, style) — le reste du document ne bouge pas."""
    system = (
        "Tu mets à jour UNE section d'un document HTML déjà mis en forme. Rends UNIQUEMENT le "
        f"fragment HTML de cette section : un seul élément racine portant l'attribut "
        f'{SECTION_ATTR}="{index}", avec la même structure, les mêmes classes et le même style '
        "que le fragment actuel. Reprends le texte fourni sans le modifier, le résumer ni le "
        "compléter. Pas de <html>, de <head>, de <style>, de commentaire ni de bloc de code."
        + _form_hints(style=style, language=language))
    user = (f"Fragment actuel de la section :\n{current_html}\n\n"
            f"Nouveau texte de la section (Markdown) :\n{new_text}")
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]


def _fragment(reply: str, index: int):
    """L'élément de section rendu par le modèle, repéré ; None s'il n'y en a pas un et un seul."""
    soup = _soup(extract_document(reply))
    tagged = anchored_sections(soup).get(index)
    if tagged is not None:
        return tagged
    roots = [el for el in soup.contents if getattr(el, 'name', None)]
    if len(roots) == 1:
        roots[0][SECTION_ATTR] = str(index)
        return roots[0]
    return None


def apply_plan(previous_html: str, plan: LayoutPlan, ask, *, style: str = '',
               language: str = '', console=None) -> str | None:
    """Le HTML ajusté selon `plan` (mode `adjust`), à partir de `previous_html`.

    `ask(messages) -> texte` : l'appel au modèle que la glu a choisi (`chat_with_catalog_model`),
    pour les seules sections à remettre en forme ; une section dont le texte n'a pu être reporté
    dans la forme est remise en forme aussi. Rend None quand l'ajustement est impossible (une
    réponse du modèle sans section reconnaissable) : la glu fait alors la mise en forme
    complète. `console` dit ce qui a été fait."""
    soup = _soup(previous_html)
    anchors = anchored_sections(soup)
    patched, relaid = [], []
    for change in plan.changes:
        if change.kind == 'keep':
            continue
        tag = anchors.get(change.index)
        if tag is None:
            return None
        if change.kind == 'patch':
            trial = _soup(str(tag))
            trial_tag = anchored_sections(trial).get(change.index)
            if trial_tag is not None and patch_section(trial_tag, change.old, change.new):
                tag.replace_with(trial_tag)
                anchors[change.index] = trial_tag
                patched.append(change.index)
                continue
        reply = ask(section_relayout_messages(change.index, change.new, str(tag),
                                              style=style, language=language))
        fresh = _fragment(reply or '', change.index)
        if fresh is None:
            return None
        tag.replace_with(fresh)
        anchors[change.index] = fresh
        relaid.append(change.index)
    if console:
        console(f"Mise en forme ajustée : {len(patched)} section(s) au texte remplacé, "
                f"{len(relaid)} remise(s) en forme, le reste gardé.")
    return with_charset(str(soup))


def adjust_layout(basis, text: str, ask, *, style: str = '', language: str = '',
                  console=None) -> str | None:
    """LE geste d'une glu de mise en forme : le HTML de `text`, AJUSTÉ depuis la dernière mise
    en forme (`basis`, rendu par `adjustment_basis`) — le rendu d'avant tel quel si le fond n'a
    pas changé, des sections retouchées sinon. None quand il faut TOUT refaire (pas de base, une
    structure qui change, des repères qui manquent, une réponse du modèle inutilisable) : la glu
    fait alors sa mise en forme complète (`full_layout_messages`, `finish_document`).

    `ask(messages) -> texte` : l'appel au modèle choisi par la glu, pour les seules sections à
    remettre en forme. Rien d'autre n'est appelé : un bout de phrase changé se remplace sans
    modèle. (L'API étroite est voulue : la 1ʳᵉ glu générée sur les briques détaillées lisait des
    attributs qui n'existaient pas — 2026-10-13.)"""
    if basis is None:
        return None
    plan = plan_layout_update(basis.previous_text, text, basis.previous_html, language=language or None)
    if plan.mode == 'full':
        if console:
            console(f"Mise en forme complète : {plan.reason}.")
        return None
    if plan.mode == 'none':
        if console:
            console("Fond inchangé : le rendu précédent est repris tel quel.")
        return with_charset(basis.previous_html)
    return apply_plan(basis.previous_html, plan, ask, style=style, language=language,
                      console=console)


# ── La mise en forme complète ───────────────────────────────────────────────────────────────

def full_layout_instruction(text: str) -> str:
    """La règle à ajouter à la consigne d'une mise en forme COMPLÈTE : les repères de sections
    (sans eux, aucune correction suivante ne pourra être ajustée) et le jeu de caractères."""
    count = len(split_sections(text))
    # Le texte RECOPIÉ tel quel n'est pas une préférence de style : c'est ce qui permet à la
    # correction suivante d'un bout de phrase de se reporter dans la forme sans modèle (la 2ᵉ glu
    # générée, le 2026-10-13, l'avait perdu de sa consigne) — la règle vit donc ICI.
    return (f"Mets en forme le fond fourni en un document HTML complet et autonome. Reprends son "
            f"texte TEL QUEL — sans le reformuler, le résumer ni le compléter : seule la "
            f"présentation t'appartient. "
            f"Le fond compte {count} section(s), chacune commence à un titre Markdown (la "
            f"première peut être le texte qui précède le premier titre). Rends chaque section "
            f'dans UN élément portant l\'attribut {SECTION_ATTR}="k", k allant de 0 à {count - 1} '
            f"dans l'ordre du fond ; ne fusionne ni ne coupe aucune section. Le document commence "
            f'par <!DOCTYPE html> et déclare <meta charset="utf-8">.')


def full_layout_messages(text: str, *, style: str = '', language: str = '',
                         kind: str = '') -> list:
    """Les messages d'une mise en forme COMPLÈTE — le jumeau de `section_relayout_messages` :
    la règle (`full_layout_instruction`), la nature du document, sa langue, la consigne de forme,
    et le FOND lui-même dans le message utilisateur.

    Les deux glus générées sur la seule règle, le 2026-10-13, n'envoyaient pas le fond au modèle :
    le nom faisait croire qu'elle le contenait (elle n'en lit que le nombre de sections). Une glu
    passe donc par cette brique, puis par `finish_document`."""
    system = full_layout_instruction(text) + _form_hints(style=style, language=language, kind=kind)
    return [{'role': 'system', 'content': system},
            {'role': 'user', 'content': f"Fond à mettre en forme (Markdown) :\n{text}"}]


def finish_document(reply: str, text: str, console=None) -> str:
    """Le document rendu par le modèle, prêt à écrire : sans le raisonnement ni la clôture de code
    qui l'entourent parfois (« ```html » vu dans l'aperçu, constat de Fabien le 2026-10-13), avec
    son jeu de caractères. Dit à la console quand des repères de sections manquent."""
    html = with_charset(extract_document(reply))
    expected = set(range(len(split_sections(text))))
    found = set(anchored_sections(_soup(html)))
    if console and found != expected:
        console(f"Avertissement : le rendu repère {len(found & expected)} section(s) sur "
                f"{len(expected)} — la prochaine correction refera tout le document.",
                level='warning')
    return html


def extract_document(reply: str) -> str:
    """Le document d'une réponse de modèle : sans bloc de raisonnement (`<think>`), et sans la
    clôture de code qui l'entoure quand le modèle en met une — de l'ouvrante à la DERNIÈRE
    clôture (la règle d'`extract_code` du rôle codegen : un document peut contenir des clôtures)."""
    text = re.sub(r'<think>.*?</think>', '', str(reply or ''), flags=re.S).strip()
    opening = re.search(r'```[\w-]*[ \t]*\n', text)
    if opening and '<' not in text[:opening.start()]:
        closing = text.rfind('```')
        if closing > opening.end():
            return text[opening.end():closing].strip()
    return text


def with_charset(html: str) -> str:
    """`html` déclarant `<meta charset="utf-8">` : un document servi sans jeu de caractères
    affiche ses accents cassés (relevé au smoke du 2026-10-13 — Apache sert `text/html` nu)."""
    if re.search(r'<meta[^>]+charset', html or '', re.I):
        return html
    meta = '<meta charset="utf-8">'
    head = re.search(r'<head[^>]*>', html or '', re.I)
    if head:
        return html[:head.end()] + meta + html[head.end():]
    root = re.search(r'<html[^>]*>', html or '', re.I)
    if root:
        return html[:root.end()] + f'<head>{meta}</head>' + html[root.end():]
    return meta + (html or '')


# ── La base de comparaison ──────────────────────────────────────────────────────────────────

@dataclass
class LayoutBasis:
    previous_text: str
    previous_html: str


def adjustment_basis(app_id: str, item, ctx, *, source_field: str,
                     output_field: str) -> LayoutBasis | None:
    """Le fond et le rendu de la DERNIÈRE mise en forme, pris dans les fichiers de révision gardés
    — ou None quand il faut tout refaire : le process n'avait jamais rendu, la forme demandée a
    changé depuis (réglages ou fichiers surveillés, hors empreinte d'amont), ou les copies
    manquent (app qui ne garde pas, fichier purgé).

    `source_field` : le champ du fond (l'entrée de la mise en forme) ; `output_field` : le champ
    du rendu. La révision qui porte le dernier rendu donne le rendu ; le fond est celui qu'elle
    avait — la dernière copie du fond gardée à cette révision ou avant."""
    import os

    from django.conf import settings

    from wama.common.services.process_pipeline import UPSTREAM_KEY
    from wama.common.services.revisions import kept_file, revisions_of
    before = getattr(ctx, 'previous_snapshot', None)
    now = getattr(ctx, 'snapshot', None)
    if before is None or now is None:
        return None

    def form(snapshot):
        return {k: v for k, v in (snapshot or {}).items() if k != UPSTREAM_KEY}
    if form(before) != form(now):
        return None

    def read(rel):
        try:
            with open(os.path.join(settings.MEDIA_ROOT, rel), encoding='utf-8') as source:
                return source.read()
        except (OSError, ValueError):
            return ''
    rendered_at = None
    for revision in revisions_of(app_id, item):
        if kept_file(app_id, item, revision.number, output_field):
            rendered_at = revision.number
            break
    if rendered_at is None:
        return None
    html = read(kept_file(app_id, item, rendered_at, output_field))
    text = ''
    for revision in revisions_of(app_id, item).filter(number__lte=rendered_at):
        rel = kept_file(app_id, item, revision.number, source_field)
        if rel:
            text = read(rel)
            break
    if not html or not text:
        return None
    return LayoutBasis(text, html)
