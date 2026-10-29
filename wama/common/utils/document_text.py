"""La COUCHE TEXTE d'un document — lire ses passages, puis les réécrire SUR PLACE en conservant tout
le reste (2026-10-28, ROADMAP §16.4bis, vision §5.4).

    read_segments(path, unit='')                              → [texte du segment 0, …]
    write_replacements(path, out_path, replacements, unit='') → out_path

`replacements` = `{segment: [(start, end, nouveau_texte), …]}`, en index de caractères du texte
que `read_segments` a rendu pour ce segment. Deux consommateurs, une brique : l'Anonymizer (domaine
document : le nouveau texte est le libellé `[PERSONNE]`) et le Translator (le nouveau texte est la
traduction — à brancher). Anonymiser, c'est conserver EXACTEMENT la forme d'origine : on ne fait
qu'occulter dans le fichier même (décision de Fabien, 2026-10-28) — la mise en forme revue, elle,
est le geste du Writer, par chaînage.

FORMATS (v1) — un segment est :
  • `.txt`, `.md` : le fichier entier ;
  • `.docx` : un paragraphe `w:p` — du corps (tableaux, zones de texte, liens, champs compris),
    des en-têtes et pieds, des commentaires et des notes de bas de page et de fin. Le texte d'un
    paragraphe est éclaté en morceaux de même mise en forme : le nouveau texte prend la place du
    passage dans le PREMIER morceau touché, les suivants sont rognés — la mise en forme du début du
    passage est gardée. Les SUPPRESSIONS du suivi des modifications (`w:del`, texte encore présent
    dans le fichier) sont retirées, les métadonnées d'auteur vidées ;
  • `.pdf` (texte natif) : une page. Le passage est retrouvé à sa place (`search_for`), le texte
    dessous est SUPPRIMÉ (`apply_redactions` — un rectangle posé par-dessus le laisserait
    extractible : une fuite) et le nouveau texte écrit dans la zone ; métadonnées effacées
    (`scrub`), fichier réécrit en entier (`garbage=4`, jamais en incrémental : les anciens objets
    resteraient dans le fichier). Un PDF scanné n'a pas de texte : c'est l'Anonymizer image (OCR,
    boîtes) qui le traite.

UNITÉ `block` (le Translator, 2026-10-28) : un segment PDF est alors un BLOC de texte (un
paragraphe de la page, ses lignes réunies), réécrit EN ENTIER dans son cadre — le texte dessous
supprimé sans toucher au fond ni aux images, le nouveau texte posé dans le même cadre (`insert_htmlbox`,
toutes écritures) avec le STYLE DOMINANT du bloc — famille générique de sa police (avec ou sans
empattement, chasse fixe), gras, italique, taille, couleur, interlignage (2026-10-29 : tout était
réécrit en sans-serif, sans gras, réduit sans limite). Le texte garde sa taille ; s'il ne tient
pas, le cadre descend dans la place libre dessous, et il ne se réduit qu'ensuite. Un bloc fait
de polices mathématiques (une formule) n'est pas un segment ; un bloc inchangé n'est pas réécrit.
Un bloc de TABLEAU (PyMuPDF y range tout le tableau, chaque cellule étant une ligne) donne un
segment par cellule, réécrit dans sa colonne — les chiffres, sans lettre, ne sont jamais touchés.
Remplacer un passage dans une page entière ne vaut que pour un passage court ; une traduction
remplace tout.
Les autres formats ont déjà le grain d'un paragraphe : l'unité ne les change pas.
Un texte brut garde son encodage d'origine, sauf s'il ne peut pas porter le nouveau texte (une
traduction en polonais dans un fichier cp1252) : il passe alors en UTF-8.
"""
from __future__ import annotations

import os
from pathlib import Path

TEXT_EXTS = ('.txt', '.md')
SUPPORTED_EXTS = TEXT_EXTS + ('.docx', '.pdf')


def _ext(path) -> str:
    ext = Path(str(path)).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"format non pris en charge par la couche texte : {ext or '(aucun)'} "
                         f"— {', '.join(SUPPORTED_EXTS)}")
    return ext


# ── Texte brut ────────────────────────────────────────────────────────────────────────────────
def _read_plain(path) -> tuple:
    raw = Path(path).read_bytes()
    for encoding in ('utf-8', 'cp1252'):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1'), 'latin-1'


def _splice(text: str, changes) -> str:
    """Le texte, chaque passage remplacé — de la fin vers le début, pour que les index tiennent."""
    for start, end, new in sorted(changes, key=lambda c: c[0], reverse=True):
        text = text[:start] + new + text[end:]
    return text


# ── DOCX ──────────────────────────────────────────────────────────────────────────────────────
# Au niveau du XML, pas des objets de python-docx : `paragraph.runs` ne voit ni le texte d'un lien,
# ni celui d'une zone de texte, d'un champ ou d'un contrôle de contenu ; et python-docx charge les
# NOTES de bas de page et de fin comme des octets opaques. Un segment = un paragraphe `w:p` de
# chaque partie qui porte du texte, son texte = ses PROPRES nœuds `w:t` (pas ceux d'un paragraphe
# imbriqué, qui est son propre segment).
_DOCX_TEXT_PARTS = ('header', 'footer', 'comments', 'footnotes', 'endnotes')


def _open_docx(path):
    """Le document, ses notes chargées comme parties XML (relues et réécrites par python-docx)."""
    import docx
    from docx.opc.constants import CONTENT_TYPE as CT
    from docx.opc.part import PartFactory, XmlPart
    for content_type in (CT.WML_FOOTNOTES, CT.WML_ENDNOTES):
        PartFactory.part_type_for.setdefault(content_type, XmlPart)
    return docx.Document(str(path))


def _docx_parts(document) -> list:
    """Les parties à texte, dans un ordre STABLE : le corps, puis les autres par identifiant."""
    rels = sorted((rel for rel in document.part.rels.values() if not rel.is_external),
                  key=lambda rel: rel.rId)
    others = [rel.target_part for rel in rels
              if rel.reltype.rsplit('/', 1)[-1] in _DOCX_TEXT_PARTS
              and getattr(rel.target_part, 'element', None) is not None]
    return [document.part] + others


def _docx_paragraphs(document) -> list:
    from docx.oxml.ns import qn
    return [p for part in _docx_parts(document) for p in part.element.iter(qn('w:p'))]


def _own_texts(paragraph) -> list:
    """Les nœuds `w:t` dont le paragraphe le plus proche est `paragraph`."""
    from docx.oxml.ns import qn
    tag_p = qn('w:p')
    own = []
    for node in paragraph.iter(qn('w:t')):
        parent = node.getparent()
        while parent is not None and parent.tag != tag_p:
            parent = parent.getparent()
        if parent is paragraph:
            own.append(node)
    return own


def _paragraph_text(paragraph) -> str:
    return ''.join(node.text or '' for node in _own_texts(paragraph))


def _rewrite_paragraph(paragraph, changes) -> None:
    """Remplace des passages d'un paragraphe à travers ses nœuds de texte (de la fin vers le
    début) : le nouveau texte prend la place dans le PREMIER nœud touché, les suivants sont rognés."""
    space = '{http://www.w3.org/XML/1998/namespace}space'
    nodes = _own_texts(paragraph)
    for start, end, new in sorted(changes, key=lambda c: c[0], reverse=True):
        position, first = 0, True
        for node in nodes:
            text = node.text or ''
            node_start = position
            position += len(text)
            if position <= start or node_start >= end:
                continue
            local_start, local_end = max(start - node_start, 0), min(end - node_start, len(text))
            node.text = text[:local_start] + (new if first else '') + text[local_end:]
            node.set(space, 'preserve')
            first = False


def _scrub_docx(document) -> None:
    """Retire ce qui garde le texte d'origine HORS de la page : les suppressions du suivi des
    modifications (`w:del`, leur texte reste dans le fichier) et l'auteur des propriétés."""
    from docx.oxml.ns import qn
    for part in _docx_parts(document):
        for deleted in list(part.element.iter(qn('w:del'))):
            deleted.getparent().remove(deleted)
    props = document.core_properties
    props.author = ''
    props.last_modified_by = ''


# ── PDF ───────────────────────────────────────────────────────────────────────────────────────
def _read_pdf(path) -> list:
    import fitz
    with fitz.open(str(path)) as pdf:
        return [page.get_text('text') for page in pdf]


def _rewrite_pdf(path, out_path, replacements, segments) -> None:
    import fitz
    with fitz.open(str(path)) as pdf:
        for index, changes in replacements.items():
            page = pdf[int(index)]
            for start, end, new in changes:
                passage = segments[int(index)][start:end].strip()
                if not passage:
                    continue
                for quad in page.search_for(passage, quads=True):
                    rect = quad.rect
                    page.add_redact_annot(quad, text=new, fill=(1, 1, 1), text_color=(0, 0, 0),
                                          fontsize=max(min(rect.height * 0.75, 11), 4))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        pdf.scrub()
        pdf.save(str(out_path), garbage=4, deflate=True)


#: Polices de MATHÉMATIQUES (TeX : italique math, symboles, extensions ; AMS ; « …Math ») — un bloc
#: qui en est fait pour l'essentiel est une formule, pas un texte : il n'est pas un segment.
_MATH_FONTS = ('CMMI', 'CMSY', 'CMEX', 'MSAM', 'MSBM', 'MATH')


def _span_style(span) -> tuple:
    """Le style d'un morceau de texte du PDF : `(famille, gras, italique, taille, couleur)`. La
    famille est GÉNÉRIQUE (empattement, chasse fixe, sinon sans) : la police embarquée n'est qu'un
    sous-ensemble des glyphes du texte d'origine — elle n'écrirait pas les lettres d'une traduction."""
    flags, font = span['flags'], span['font'].lower()
    family = 'monospace' if flags & 8 else 'serif' if flags & 4 else 'sans-serif'
    bold = bool(flags & 16) or 'bold' in font
    italic = bool(flags & 2) or 'italic' in font or 'oblique' in font
    return family, bold, italic, round(span['size'], 1), span['color']


def _css(style, leading=None, align='') -> str:
    family, bold, italic, size, color = style
    return (f'font-family: {family}; font-size: {size:.1f}pt; color: #{color:06x}; '
            f'font-weight: {"bold" if bold else "normal"}; '
            f'font-style: {"italic" if italic else "normal"};'
            + (f' line-height: {leading:.2f};' if leading else '')
            + (f' text-align: {align};' if align and align != 'left' else ''))


def _pdf_unit(lines, page_width=0) -> dict | None:
    """Un passage du PDF fait de `lines` (lignes de `get_text('dict')`) : son cadre, son texte (les
    lignes réunies par une espace — elles ne sont que le retour à la ligne du cadre), son style
    DOMINANT (celui du plus grand nombre de caractères) et son interlignage. None : pas de texte,
    ou une formule."""
    import fitz
    spans = [span for line in lines for span in line['spans'] if span['text'].strip()]
    text = ' '.join(''.join(span['text'] for span in line['spans']).strip()
                    for line in lines).strip()
    if not text or not spans:
        return None
    weights, math = {}, 0
    for span in spans:
        style, count = _span_style(span), len(span['text'].strip())
        weights[style] = weights.get(style, 0) + count
        math += count if any(m in span['font'].upper() for m in _MATH_FONTS) else 0
    if math * 2 > sum(weights.values()):
        return None
    style = max(weights, key=weights.get)
    pitches = sorted(b['spans'][0]['origin'][1] - a['spans'][0]['origin'][1]
                     for a, b in zip(lines, lines[1:]) if a['spans'] and b['spans'])
    pitches = [p for p in pitches if p > 0]
    leading = pitches[len(pitches) // 2] / style[3] if pitches and style[3] else None
    rect = fitz.Rect(lines[0]['bbox'])
    for line in lines[1:]:
        rect |= fitz.Rect(line['bbox'])
    # Le sens d'écriture (le tampon vertical d'une marge, l'axe d'une figure) : un quart de tour
    # se réécrit tourné, un autre angle n'est pas un segment.
    dx, dy = lines[0].get('dir', (1, 0))
    rotate = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}.get((round(dx), round(dy)))
    if rotate is None or abs(abs(dx) + abs(dy) - 1) > 0.01:
        return None
    return {'rect': rect, 'text': text, 'style': style, 'rotate': rotate, 'lines': len(lines),
            'align': _alignment(lines, rect, page_width),
            'leading': min(max(leading, 1.0), 1.6) if leading else None}


def _alignment(lines, rect, page_width) -> str:
    """L'alignement LU sur la position des lignes : centré (toutes les lignes centrées sur le
    cadre — sur la page pour une ligne seule), justifié (toutes sauf la dernière vont d'un bord à
    l'autre), sinon à gauche."""
    edges = [(line['bbox'][0], line['bbox'][2]) for line in lines]
    middle = (rect.x0 + rect.x1) / 2
    if len(edges) == 1:
        x0, x1 = edges[0]
        return 'center' if page_width and abs((x0 + x1) / 2 - page_width / 2) < 2 else 'left'
    if all(abs((x0 + x1) / 2 - middle) < 2 for x0, x1 in edges) \
            and max(x1 - x0 for x0, x1 in edges) - min(x1 - x0 for x0, x1 in edges) > 4:
        return 'center'
    if len(edges) > 2 and all(abs(x0 - rect.x0) < 1.5 and abs(x1 - rect.x1) < 1.5
                              for x0, x1 in edges[:-1]):
        return 'justify'
    return 'left'


def _same_band(a, b) -> bool:
    """Deux lignes côte à côte : leurs hauteurs se recouvrent de plus de la moitié."""
    top, bottom = max(a['bbox'][1], b['bbox'][1]), min(a['bbox'][3], b['bbox'][3])
    smaller = min(a['bbox'][3] - a['bbox'][1], b['bbox'][3] - b['bbox'][1])
    return smaller > 0 and bottom - top > smaller / 2


def _split_tabular(lines) -> list:
    """Les passages d'un bloc. Un bloc de TABLEAU (au moins deux rangées portant plusieurs lignes
    côte à côte — PyMuPDF garde chaque cellule comme une ligne à part, mais range tout le tableau
    dans un bloc) donne une cellule par passage, et ses lignes empilées seules dans leur rangée (la
    légende dessous, un intertitre de groupe) un passage par suite. Sinon, le bloc entier : un
    paragraphe que coupe une formule n'a qu'une rangée double."""
    rows = []
    for line in lines:
        row = next((row for row in rows if _same_band(row[0], line)), None)
        if row is None:
            rows.append([line])
        else:
            row.append(line)
    if sum(1 for row in rows if len(row) > 1) < 2:
        return [lines]
    cells = {id(line) for row in rows if len(row) > 1 for line in row}
    parts, run = [], []
    for line in lines:
        if id(line) in cells:
            if run:
                parts.append(run)
                run = []
            parts.append([line])
        else:
            run.append(line)
    return parts + ([run] if run else [])


def _pdf_blocks(page) -> list:
    """Les passages de texte d'une page, dans l'ordre du fichier (voir `_pdf_unit`) — un bloc de
    tableau donne un passage par cellule (`_split_tabular`)."""
    units = []
    for block in page.get_text('dict')['blocks']:
        if block.get('type') == 0:
            for lines in _split_tabular(block['lines']):
                unit = _pdf_unit(lines, page.rect.width)
                if unit:
                    units.append(unit)
    return units


def _read_pdf_blocks(path) -> list:
    import fitz
    with fitz.open(str(path)) as pdf:
        return [unit['text'] for page in pdf for unit in _pdf_blocks(page)]


def _room(page, unit, obstacles):
    """Le cadre agrandi dans la place LIBRE : vers le bas jusqu'au premier obstacle (texte, image,
    trait) placé dessous et en vis-à-vis, sinon la marge du bas ; et, pour un passage d'UNE ligne
    (un titre, une cellule), vers la droite jusqu'au premier obstacle sur sa hauteur. Un texte
    tourné garde son cadre."""
    import fitz
    rect = unit['rect']
    if unit['rotate']:
        return rect
    others = [o for o in obstacles if o != rect]
    bottom, right = page.rect.y1 - 36, rect.x1
    for other in others:
        if other.y0 >= rect.y1 - 1 and other.x0 < rect.x1 - 1 and other.x1 > rect.x0 + 1:
            bottom = min(bottom, other.y0 - 2)
    if unit['lines'] == 1 and unit['align'] == 'left':
        right = page.rect.x1 - 36
        for other in others:
            if other.x0 >= rect.x1 - 1 and other.y0 < rect.y1 - 1 and other.y1 > rect.y0 + 1:
                right = min(right, other.x0 - 2)
    return fitz.Rect(rect.x0, rect.y0, max(right, rect.x1), max(bottom, rect.y1))


def _place(page, unit, html_text, css, grown) -> None:
    """Le texte dans son cadre à sa TAILLE d'origine ; s'il ne tient pas, dans le cadre agrandi
    (`_room`) ; et seulement ensuite, réduit pour tenir."""
    rect = unit['rect']
    attempts = [(rect, 1)] + ([(grown, 1)] if grown != rect else []) + [(grown, 0)]
    for box, low in attempts:
        if page.insert_htmlbox(box, html_text, css=css, scale_low=low,
                               rotate=unit['rotate'])[0] >= 0:
            return


def _rewrite_pdf_blocks(path, out_path, replacements) -> None:
    import html

    import fitz
    with fitz.open(str(path)) as pdf:
        index = 0
        for page in pdf:
            units, todo = _pdf_blocks(page), []
            for unit in units:
                if index in replacements:
                    new = _splice(unit['text'], replacements[index])
                    if new != unit['text']:
                        todo.append((unit, new))
                index += 1
            if not todo:
                continue
            obstacles = ([unit['rect'] for unit in units]
                         + [fitz.Rect(b['bbox']) for b in page.get_text('dict')['blocks']
                            if b.get('type') == 1]
                         + [d['rect'] for d in page.get_drawings()])
            for unit, _ in todo:
                page.add_redact_annot(unit['rect'], fill=False)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                  graphics=fitz.PDF_REDACT_LINE_ART_NONE)
            for unit, new in todo:
                _place(page, unit, html.escape(new),
                       '* {' + _css(unit['style'], unit['leading'], unit['align']) + '}',
                       _room(page, unit, obstacles))
        pdf.save(str(out_path), garbage=4, deflate=True)


# ── Les deux gestes ───────────────────────────────────────────────────────────────────────────
def read_segments(path, unit: str = '') -> list:
    """Le texte de chaque segment du document (voir l'en-tête pour ce qu'est un segment ;
    `unit='block'` : un PDF par blocs)."""
    ext = _ext(path)
    if ext in TEXT_EXTS:
        return [_read_plain(path)[0]]
    if ext == '.docx':
        return [_paragraph_text(p) for p in _docx_paragraphs(_open_docx(path))]
    return _read_pdf_blocks(path) if unit == 'block' else _read_pdf(path)


def write_replacements(path, out_path, replacements: dict, unit: str = '') -> str:
    """Le document `path` réécrit dans `out_path`, chaque passage remplacé SUR PLACE — les index
    sont ceux de `read_segments(path, unit)`."""
    ext = _ext(path)
    os.makedirs(os.path.dirname(os.path.abspath(str(out_path))), exist_ok=True)
    changes = {int(k): list(v) for k, v in (replacements or {}).items() if v}
    if ext in TEXT_EXTS:
        text, encoding = _read_plain(path)
        new = _splice(text, changes.get(0, []))
        try:
            data = new.encode(encoding)
        except UnicodeEncodeError:
            data = new.encode('utf-8')
        Path(out_path).write_bytes(data)
    elif ext == '.pdf' and unit == 'block':
        _rewrite_pdf_blocks(path, out_path, changes)
    elif ext == '.docx':
        document = _open_docx(path)
        paragraphs = _docx_paragraphs(document)
        for index, items in changes.items():
            _rewrite_paragraph(paragraphs[index], items)
        _scrub_docx(document)
        document.save(str(out_path))
    else:
        _rewrite_pdf(path, out_path, changes, _read_pdf(path))
    return str(out_path)
