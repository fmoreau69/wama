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
    passage est gardée (avec `markup=True`, chaque passage balisé retrouve la sienne — « Balises
    de mise en forme »). Les SUPPRESSIONS du suivi des modifications (`w:del`, texte encore présent
    dans le fichier) sont retirées, les métadonnées d'auteur vidées ;
  • `.pdf` (texte natif) : une page. Le passage est retrouvé à sa place (`search_for`), le texte
    dessous est SUPPRIMÉ (`apply_redactions` — un rectangle posé par-dessus le laisserait
    extractible : une fuite) et le nouveau texte écrit dans la zone ; métadonnées effacées
    (`scrub`), fichier réécrit en entier (`garbage=4`, jamais en incrémental : les anciens objets
    resteraient dans le fichier). Un PDF scanné n'a pas de texte : ⏳ c'est le domaine document
    de l'Anonymizer qui le traitera (OCR, boîtes ; décision du 2026-10-28, ROADMAP §16.4bis — en
    construction, en pause le temps du chantier de Portage Apps), en gardant sa forme. Il lui
    faut l'OCR À POSITIONS, le même maillon que l'étape préalable du Translator et la forme d'un
    scan au Reader (ROADMAP §10.B).

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
import re
from pathlib import Path

TEXT_EXTS = ('.txt', '.md')
SUPPORTED_EXTS = TEXT_EXTS + ('.docx', '.pdf')


def _ext(path) -> str:
    ext = Path(str(path)).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"format non pris en charge par la couche texte : {ext or '(aucun)'} "
                         f"— {', '.join(SUPPORTED_EXTS)}")
    return ext


# ── Balises de mise en forme ──────────────────────────────────────────────────────────────────
# `markup=True` : le texte d'un segment porte `<tN>…</tN>` autour de chaque passage dont la mise
# en forme n'est pas celle qui DOMINE le segment (le texte nu). Un traducteur garde les balises
# autour des mots qui leur correspondent, et la réécriture rend à chacun sa mise en forme.
_TAG = re.compile(r'</?t(\d+)>', re.IGNORECASE)


def strip_markup(text: str) -> str:
    """Le texte sans ses balises de mise en forme."""
    return _TAG.sub('', text or '')


def _mark(pieces) -> tuple:
    """`(texte balisé, {numéro: clé}, clé dominante)` de morceaux `(clé de mise en forme, texte)`,
    dans l'ordre. La clé dominante est celle du plus grand nombre de caractères ; un morceau
    blanc suit le passage où il se trouve (une espace ne coupe pas un passage en gras)."""
    weights = {}
    for key, text in pieces:
        if text.strip():
            weights[key] = weights.get(key, 0) + len(text.strip())
    if not weights:
        return ''.join(text for _, text in pieces), {}, None
    dominant = max(weights, key=weights.get)
    numbers, out, current = {}, [], dominant
    for key, text in pieces:
        if text.strip() and key != current:
            if current != dominant:
                out.append(f'</t{numbers[current]}>')
            if key != dominant:
                numbers.setdefault(key, len(numbers) + 1)
                out.append(f'<t{numbers[key]}>')
            current = key
        out.append(text)
    if current != dominant:
        out.append(f'</t{numbers[current]}>')
    return ''.join(out), {n: key for key, n in numbers.items()}, dominant


def _parse_markup(text: str, tags) -> list | None:
    """`[(numéro ou None, texte), …]` d'un texte balisé ; None si ses balises sont illisibles
    (inconnues, imbriquées, mal fermées)."""
    pieces, current, position = [], None, 0
    for match in _TAG.finditer(text):
        if match.start() > position:
            pieces.append((current, text[position:match.start()]))
        position = match.end()
        number = int(match.group(1))
        if number not in tags:
            return None
        if match.group(0)[1] == '/':
            if current != number:
                return None
            current = None
        elif current is not None:
            return None
        else:
            current = number
    if current is not None:
        return None
    if position < len(text):
        pieces.append((None, text[position:]))
    return pieces


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


def _docx_groups(paragraph):
    """`(nœuds, clé de chaque nœud, texte balisé, {numéro de balise: clé}, clé dominante)` : la clé
    d'un nœud est la mise en forme de son morceau (`w:rPr` sérialisé)."""
    from lxml import etree

    from docx.oxml.ns import qn
    nodes = _own_texts(paragraph)
    keys = []
    for node in nodes:
        run = node.getparent()
        rpr = run.find(qn('w:rPr')) if run is not None else None
        keys.append(etree.tostring(rpr) if rpr is not None else b'')
    pieces = [(key, node.text or '') for key, node in zip(keys, nodes)]
    marked, tags, dominant = _mark(pieces)
    return nodes, keys, marked, tags, dominant


def _rewrite_paragraph_marked(paragraph, changes) -> None:
    """Le paragraphe réécrit d'après son texte BALISÉ : chaque morceau du nouveau texte va dans le
    prochain nœud de SA mise en forme (le texte nu, dans celle qui domine), les nœuds restants
    sont vidés. Un morceau dont la mise en forme ne revient plus (la traduction a inversé l'ordre)
    rejoint le nœud précédent : sa mise en forme se perd, jamais son texte. Des balises illisibles :
    tout le texte, nu, dans la mise en forme dominante."""
    space = '{http://www.w3.org/XML/1998/namespace}space'
    nodes, keys, marked, tags, dominant = _docx_groups(paragraph)
    if not nodes:
        return
    new = _splice(marked, changes)
    pieces = _parse_markup(new, tags) or [(None, strip_markup(new))]
    texts, cursor = {}, None
    for tag, text in pieces:
        key = tags[tag] if tag is not None else dominant
        start = 0 if cursor is None else cursor
        target = next((j for j in range(start, len(nodes)) if keys[j] == key), None)
        if target is None:
            target = cursor if cursor is not None else 0
        texts[target] = texts.get(target, '') + text
        cursor = target
    for j, node in enumerate(nodes):
        node.text = texts.get(j, '')
        node.set(space, 'preserve')


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


#: Fragments de NOMS de polices → famille de base de MuPDF, dans cet ordre (« sans » avant
#: « serif » : `NimbusSans`, `PTSans` ; une police TeX se nomme `CMR`, `CMSS`, `CMTT`).
_FAMILY_BY_NAME = (
    ('Courier', ('courier', 'mono', 'consol', 'menlo', 'cmtt', 'typewriter')),
    ('Helvetica', ('sans', 'arial', 'helvet', 'verdana', 'roboto', 'calibri', 'tahoma', 'segoe',
                   'lato', 'inter-', 'futura', 'gill', 'gothic', 'univers', 'frutiger', 'cmss')),
    ('Times', ('times', 'roman', 'serif', 'georgia', 'cambria', 'garamond', 'palatino',
               'bookman', 'minion', 'charis', 'nimbusrom', 'cmr', 'lmroman')),
)


def _family_by_name(font: str) -> str:
    """La famille de base de MuPDF que désigne le nom d'une police, '' s'il ne la dit pas."""
    name = font.split('+')[-1].lower()             # « ABCDEF+Roboto-Regular » : sous-ensemble
    for family, fragments in _FAMILY_BY_NAME:
        if any(fragment in name for fragment in fragments):
            return family
    return ''


def _span_style(span) -> tuple:
    """Le style d'un morceau de texte du PDF : `(famille, gras, italique, taille, couleur,
    exposant)`. La famille est GÉNÉRIQUE (empattement, chasse fixe, sinon sans) : la police
    embarquée n'est qu'un sous-ensemble des glyphes du texte d'origine — elle n'écrirait pas les
    lettres d'une traduction. Elle se nomme par les polices de base de MuPDF (Nimbus : Times,
    Helvetica, Courier — les métriques des polices les plus courantes des documents) ; « serif »
    y donnait Charis SIL, aux minuscules visiblement plus hautes que celles d'un Times (mesuré le
    2026-10-29). Un glyphe qu'elles n'ont pas est pris par le repli de MuPDF (Noto). La famille se
    lit d'abord sur le NOM de la police, les drapeaux du PDF ensuite : une figure en Roboto ou en
    Verdana se déclarait « à empattement » et ressortait en Times (mesuré le même jour)."""
    flags, font = span['flags'], span['font'].lower()
    family = _family_by_name(font) or ('Courier' if flags & 8 else 'Times' if flags & 4
                                       else 'Helvetica')
    bold = bool(flags & 16) or 'bold' in font
    italic = bool(flags & 2) or 'italic' in font or 'oblique' in font
    return family, bold, italic, round(span['size'], 1), span['color'], bool(flags & 1)


def _css(style, leading=None, align='') -> str:
    family, bold, italic, size, color, superscript = style
    return (f'font-family: {family}; font-size: {size:.1f}pt; color: #{color:06x}; '
            f'font-weight: {"bold" if bold else "normal"}; '
            f'font-style: {"italic" if italic else "normal"};'
            + (' vertical-align: super;' if superscript else '')
            + (f' line-height: {leading:.2f};' if leading else '')
            + (f' text-align: {align};' if align and align != 'left' else ''))


def _line_pieces(line) -> list:
    """`[(style, texte)]` d'une ligne, ses blancs de bord retirés."""
    pieces = [(_span_style(span), span['text']) for span in line['spans'] if span['text']]
    while pieces and not pieces[0][1].strip():
        pieces.pop(0)
    while pieces and not pieces[-1][1].strip():
        pieces.pop()
    if pieces:
        pieces[0] = (pieces[0][0], pieces[0][1].lstrip())
        pieces[-1] = (pieces[-1][0], pieces[-1][1].rstrip())
    return pieces


def _pdf_unit(lines, page_width=0) -> dict | None:
    """Un passage du PDF fait de `lines` (lignes de `get_text('dict')`) : son cadre, son texte (les
    lignes réunies par une espace — elles ne sont que le retour à la ligne du cadre) et son texte
    BALISÉ (`_mark`), son style DOMINANT (celui du plus grand nombre de caractères) et son
    interlignage. None : pas de texte, ou une formule."""
    import fitz
    pieces = []
    for line in lines:
        own = _line_pieces(line)
        if own:
            pieces += ([(None, ' ')] if pieces else []) + own
    text = ''.join(text for _, text in pieces)
    if not text.strip():
        return None
    math = sum(len(span['text'].strip()) for line in lines for span in line['spans']
               if any(m in span['font'].upper() for m in _MATH_FONTS))
    if math * 2 > len(text.replace(' ', '')):
        return None
    marked, tags, style = _mark(pieces)
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
    rows = len(_rows(lines))
    # Une seule rangée (une cellule, un titre) : son cadre n'a que la hauteur du texte, et
    # l'interligne par défaut du moteur HTML (~1,2) ne tiendrait jamais dedans — le texte se
    # réduisait quelle que soit la place à côté (mesuré le 2026-10-29 sur un tableau).
    leading = 1.0 if rows == 1 else min(max(leading, 1.0), 1.6) if leading else None
    return {'rect': rect, 'text': text, 'marked': marked, 'tags': tags, 'style': style,
            'rotate': rotate, 'rows': rows,
            'align': _alignment(lines, rect, page_width, rows), 'leading': leading}


def _alignment(lines, rect, page_width, rows=0) -> str:
    """L'alignement LU sur la position des lignes : centré (toutes les lignes centrées sur le
    cadre — sur la page pour une seule rangée), justifié (toutes sauf la dernière vont d'un bord à
    l'autre), sinon à gauche."""
    edges = [(line['bbox'][0], line['bbox'][2]) for line in lines]
    middle = (rect.x0 + rect.x1) / 2
    if rows == 1 or len(edges) == 1:
        return 'center' if page_width and abs(middle - page_width / 2) < 2 else 'left'
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


def _rows(lines) -> list:
    """Les lignes regroupées par rangée (côte à côte)."""
    rows = []
    for line in lines:
        row = next((row for row in rows if _same_band(row[0], line)), None)
        if row is None:
            rows.append([line])
        else:
            row.append(line)
    return rows


def _column_alignment(line, siblings) -> str:
    """L'alignement d'une cellule LU sur sa colonne : une autre ligne du tableau, sur une autre
    rangée, finit au même bord droit sans commencer au même bord gauche (« right »), ou partage
    son milieu (« center ») ; '' sinon."""
    x0, x1 = line['bbox'][0], line['bbox'][2]
    others = [o['bbox'] for o in siblings if o is not line and not _same_band(o, line)]
    if any(abs(o[2] - x1) < 1 and abs(o[0] - x0) > 2 for o in others):
        return 'right'
    if any(abs((o[0] + o[2]) / 2 - (x0 + x1) / 2) < 1 and abs(o[0] - x0) > 2 for o in others):
        return 'center'
    return ''


def _split_tabular(lines) -> list:
    """Les passages d'un bloc. Un bloc de TABLEAU (au moins deux rangées portant plusieurs lignes
    côte à côte — PyMuPDF garde chaque cellule comme une ligne à part, mais range tout le tableau
    dans un bloc) donne une cellule par passage, et ses lignes empilées seules dans leur rangée (la
    légende dessous, un intertitre de groupe) un passage par suite. Sinon, le bloc entier : un
    paragraphe que coupe une formule n'a qu'une rangée double."""
    rows = _rows(lines)
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


def _figure_regions(page) -> list:
    """Les cadres des FIGURES de la page, lus par l'analyse de mise en page de PyMuPDF
    (`pymupdf-layout`, installée par la route le 2026-10-29 ; ses modèles tournent sur le
    processeur, ~0,3 s par page). Sans elle, aucune : la page se lit comme avant."""
    import fitz
    try:
        import pymupdf.layout  # noqa: F401 — inscrit l'analyseur auprès de PyMuPDF
        page.get_layout()
    except Exception:
        return []
    return [fitz.Rect(region[:4]) for region in page.layout_information or []
            if len(region) > 4 and region[4] == 'picture']


def _split_labels(lines) -> list:
    """Les ÉTIQUETTES d'un bloc de figure : une ligne rejoint l'étiquette dont la dernière ligne
    est juste au-dessus d'elle et en vis-à-vis (« Convolutional » / « Layers » : une étiquette sur
    deux lignes, traduite d'un tenant) ; sinon elle en commence une — la lettre d'un axe posée sous
    un titre de cadre n'est pas la suite du titre."""
    labels = []
    for line in lines:
        x0, y0, x1, y1 = line['bbox']
        for label in labels:
            a0, _, a1, a3 = label[-1]['bbox']
            overlap = min(a1, x1) - max(a0, x0)
            gap = y0 - a3
            if (overlap > 0.5 * min(a1 - a0, x1 - x0) and -1 <= gap <= 0.6 * (y1 - y0)
                    and line.get('dir') == label[-1].get('dir')):
                label.append(line)
                break
        else:
            labels.append([line])
    return labels


def _pdf_blocks(page) -> list:
    """Les passages de texte d'une page, dans l'ordre du fichier (voir `_pdf_unit`) — un bloc de
    tableau donne un passage par cellule (`_split_tabular`), un bloc de figure un passage par
    étiquette (`_split_labels`)."""
    import fitz
    figures = None
    units = []
    for block in page.get_text('dict')['blocks']:
        if block.get('type') != 0:
            continue
        if figures is None:
            figures = _figure_regions(page)
        x0, y0, x1, y1 = block['bbox']
        center = fitz.Point((x0 + x1) / 2, (y0 + y1) / 2)
        in_figure = any(center in region for region in figures)
        parts = _split_labels(block['lines']) if in_figure else _split_tabular(block['lines'])
        for lines in parts:
            unit = _pdf_unit(lines, page.rect.width)
            if unit and not in_figure and len(parts) > 1 and len(lines) == 1:
                unit['align'] = _column_alignment(lines[0], block['lines']) or unit['align']
            if unit:
                units.append(unit)
    return units


def _read_pdf_blocks(path, markup=False) -> list:
    import fitz
    field = 'marked' if markup else 'text'
    with fitz.open(str(path)) as pdf:
        return [unit[field] for page in pdf for unit in _pdf_blocks(page)]


def _pdf_html(unit, new: str, markup: bool) -> str:
    """Le HTML du nouveau texte : chaque passage balisé dans SON style, le reste dans le style du
    bloc ; des balises illisibles, le texte nu."""
    import html
    pieces = _parse_markup(new, unit['tags']) if markup else None
    if pieces is None:
        return html.escape(strip_markup(new) if markup else new)
    return ''.join(html.escape(text) if tag is None
                   else f'<span style="{_css(unit["tags"][tag])}">{html.escape(text)}</span>'
                   for tag, text in pieces)


def _free_span(page, rect, obstacles, vertical=False) -> tuple:
    """La place libre de part et d'autre du cadre, sur sa propre bande (sa hauteur ; sa largeur
    pour un texte tourné d'un quart de tour) : `(début, fin)` jusqu'au premier obstacle de chaque
    côté, sinon la marge de la page."""
    if vertical:
        low, high = page.rect.y0 + 36, page.rect.y1 - 36
        for other in obstacles:
            if other.x0 < rect.x1 - 1 and other.x1 > rect.x0 + 1:
                if other.y0 >= rect.y1 - 1:
                    high = min(high, other.y0 - 2)
                elif other.y1 <= rect.y0 + 1:
                    low = max(low, other.y1 + 2)
        return min(low, rect.y0), max(high, rect.y1)
    low, high = page.rect.x0 + 36, page.rect.x1 - 36
    for other in obstacles:
        if other.y0 < rect.y1 - 1 and other.y1 > rect.y0 + 1:
            if other.x0 >= rect.x1 - 1:
                high = min(high, other.x0 - 2)
            elif other.x1 <= rect.x0 + 1:
                low = max(low, other.x1 + 2)
    return min(low, rect.x0), max(high, rect.x1)


def _room(page, unit, obstacles) -> list:
    """Les cadres agrandis dans la place LIBRE, à essayer dans l'ordre. Vers le bas jusqu'au
    premier obstacle (texte, image, trait) placé dessous et en vis-à-vis, sinon la marge ; et,
    pour un passage d'une seule RANGÉE (un titre, une cellule, une étiquette), sur sa bande : du
    côté que laisse son alignement (à droite s'il est à gauche, à gauche s'il est à droite, des
    deux côtés autant s'il est centré), puis des deux côtés (le titre d'un cadre de figure, bordé
    à droite). Un passage de plusieurs rangées garde sa largeur : il se replie comme l'original.
    Un texte tourné d'un quart de tour s'allonge dans son sens d'écriture."""
    import fitz
    rect = unit['rect']
    others = [o for o in obstacles if o != rect]
    if unit['rotate'] in (90, 270):
        low, high = _free_span(page, rect, others, vertical=True)
        half = min(rect.y0 - low, high - rect.y1)
        return [fitz.Rect(rect.x0, rect.y0 - half, rect.x1, rect.y1 + half),
                fitz.Rect(rect.x0, low, rect.x1, high)]
    if unit['rotate']:
        return []
    bottom = page.rect.y1 - 36
    for other in others:
        if other.y0 >= rect.y1 - 1 and other.x0 < rect.x1 - 1 and other.x1 > rect.x0 + 1:
            bottom = min(bottom, other.y0 - 2)
    bottom = max(bottom, rect.y1)
    if unit['rows'] != 1:
        return [fitz.Rect(rect.x0, rect.y0, rect.x1, bottom)]
    low, high = _free_span(page, rect, others)
    if unit['align'] == 'right':
        left, right = low, rect.x1
    elif unit['align'] == 'center':
        half = min(rect.x0 - low, high - rect.x1)
        left, right = rect.x0 - half, rect.x1 + half
    else:
        left, right = rect.x0, high
    return [fitz.Rect(left, rect.y0, right, bottom), fitz.Rect(low, rect.y0, high, bottom)]


def _place(page, unit, html_text, css, boxes) -> None:
    """Le texte dans son cadre à sa TAILLE d'origine ; s'il ne tient pas, dans chacun des cadres
    agrandis (`_room`) ; et seulement ensuite, réduit pour tenir dans le dernier."""
    import fitz
    rect = unit['rect']
    vertical = unit['rotate'] in (90, 270)
    thickness = rect.width if vertical else rect.height
    need = unit['style'][3] * 1.15 - thickness
    if unit['rows'] == 1 and need > 0:
        # Une rangée seule : le cadre de la ligne n'a pas la place des jambages ; il s'épaissit
        # d'autant, centré sur la ligne d'origine.
        dx, dy = (need / 2, 0) if vertical else (0, need / 2)
        thick = [fitz.Rect(r.x0 - dx, r.y0 - dy, r.x1 + dx, r.y1 + dy) for r in [rect] + boxes]
        rect, boxes = thick[0], thick[1:]
    boxes = [box for box in boxes if box != rect]
    attempts = [(rect, 1)] + [(box, 1) for box in boxes] + [((boxes or [rect])[-1], 0)]
    for box, low in attempts:
        if page.insert_htmlbox(box, html_text, css=css, scale_low=low,
                               rotate=unit['rotate'])[0] >= 0:
            return


def _rewrite_pdf_blocks(path, out_path, replacements, markup=False) -> None:
    import fitz
    field = 'marked' if markup else 'text'
    with fitz.open(str(path)) as pdf:
        index = 0
        for page in pdf:
            units, todo = _pdf_blocks(page), []
            for unit in units:
                if index in replacements:
                    new = _splice(unit[field], replacements[index])
                    if new != unit[field]:
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
                _place(page, unit, _pdf_html(unit, new, markup),
                       '* {' + _css(unit['style'], unit['leading'], unit['align']) + '}',
                       _room(page, unit, obstacles))
        pdf.save(str(out_path), garbage=4, deflate=True)


# ── Les deux gestes ───────────────────────────────────────────────────────────────────────────
def read_segments(path, unit: str = '', markup: bool = False) -> list:
    """Le texte de chaque segment du document (voir l'en-tête pour ce qu'est un segment ;
    `unit='block'` : un PDF par blocs ; `markup` : le texte BALISÉ de sa mise en forme, pour un
    DOCX et un PDF par blocs — voir « Balises de mise en forme »)."""
    ext = _ext(path)
    if ext in TEXT_EXTS:
        return [_read_plain(path)[0]]
    if ext == '.docx':
        paragraphs = _docx_paragraphs(_open_docx(path))
        if markup:
            return [_docx_groups(p)[2] for p in paragraphs]
        return [_paragraph_text(p) for p in paragraphs]
    return _read_pdf_blocks(path, markup) if unit == 'block' else _read_pdf(path)


def write_replacements(path, out_path, replacements: dict, unit: str = '',
                       markup: bool = False) -> str:
    """Le document `path` réécrit dans `out_path`, chaque passage remplacé SUR PLACE — les index
    sont ceux de `read_segments(path, unit, markup)`, et un nouveau texte balisé rend à chaque
    passage sa mise en forme."""
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
        _rewrite_pdf_blocks(path, out_path, changes, markup)
    elif ext == '.docx':
        document = _open_docx(path)
        paragraphs = _docx_paragraphs(document)
        rewrite = _rewrite_paragraph_marked if markup else _rewrite_paragraph
        for index, items in changes.items():
            rewrite(paragraphs[index], items)
        _scrub_docx(document)
        document.save(str(out_path))
    else:
        _rewrite_pdf(path, out_path, changes, _read_pdf(path))
    return str(out_path)
