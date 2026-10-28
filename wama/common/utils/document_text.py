"""La COUCHE TEXTE d'un document — lire ses passages, puis les réécrire SUR PLACE en conservant tout
le reste (2026-10-28, ROADMAP §16.4bis, vision §5.4).

    read_segments(path)                               → [texte du segment 0, texte du segment 1, …]
    write_replacements(path, out_path, replacements)  → out_path

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


# ── Les deux gestes ───────────────────────────────────────────────────────────────────────────
def read_segments(path) -> list:
    """Le texte de chaque segment du document (voir l'en-tête pour ce qu'est un segment)."""
    ext = _ext(path)
    if ext in TEXT_EXTS:
        return [_read_plain(path)[0]]
    if ext == '.docx':
        return [_paragraph_text(p) for p in _docx_paragraphs(_open_docx(path))]
    return _read_pdf(path)


def write_replacements(path, out_path, replacements: dict) -> str:
    """Le document `path` réécrit dans `out_path`, chaque passage remplacé SUR PLACE."""
    ext = _ext(path)
    os.makedirs(os.path.dirname(os.path.abspath(str(out_path))), exist_ok=True)
    changes = {int(k): list(v) for k, v in (replacements or {}).items() if v}
    if ext in TEXT_EXTS:
        text, encoding = _read_plain(path)
        Path(out_path).write_bytes(_splice(text, changes.get(0, [])).encode(encoding))
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
