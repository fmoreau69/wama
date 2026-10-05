"""
Compréhension de fichiers de référence (ROADMAP §10.B / §16.6, hook de la PromptPipeline).

Transforme un ou plusieurs fichiers fournis À LA VOLÉE (image, document, texte) en un RÉSUMÉ
textuel concis, destiné à être replié dans un prompt comme **contexte de grounding**. Multimodal :
- image    → description via `vision_probe.describe_image_ollama` (modèle vision Ollama local) ;
- doc/texte → texte extrait via `batch_parsers.extract_batch_file_text` (.txt/.md/.csv/.pdf/.docx).

C'est la « graine compréhension des fichiers d'entrée » de §10.B — DISTINCTE du RAG :
compréhension PONCTUELLE de l'entrée, AUCUNE persistance / store vectoriel.

DEUX LECTURES, déclarées par la cible de prompt (`PROMPT_TARGETS[…]['reference_reading']`,
2026-10-01 — la référence de MISE EN PAGE du Writer) :
- `content` (défaut) : ce que le fichier DIT — texte extrait, description d'image ;
- `form` : comment il est FAIT — pour un HTML, ses styles et son squelette (balises et classes,
  sans le texte) ; pour une image, sa mise en page, ses couleurs, sa typographie. Un format dont
  on ne sait pas lire la forme (PDF, DOCX…) est ÉCARTÉ et l'écran le dit : en extraire le texte
  ferait passer un contenu pour un style.
⚠ Le HTML n'était lu par AUCUNE des deux jusqu'au 2026-10-01 : un document de référence `.html`
donné au Writer était ignoré sans un message.

Garde-fous RESSOURCES (pas de cascade) :
- **Data-gated** : ne fait rien si aucun fichier n'est fourni (l'utilisateur a explicitement
  joint une référence → le coût est attendu). Pas besoin d'interrupteur maître.
- **Budget de caractères** par fichier + global → pas d'explosion du prompt.
- **Plafond du nombre d'images** (chaque image = 1 appel vision) pour borner le coût.
- **Fail-safe** : un fichier illisible est ignoré (jamais d'exception remontée à l'app).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tiff'}
_DOC_EXTS = {'.txt', '.md', '.csv', '.pdf', '.docx'}
_HTML_EXTS = {'.html', '.htm'}

#: Les deux lectures d'une référence (voir l'en-tête).
READINGS = ('content', 'form')

#: Budgets par lecture : (caractères par fichier, budget global). Une FORME se lit en styles et en
#: squelette, plus longs qu'un résumé de contenu — un CSS tronqué à 1 200 caractères perd la
#: palette et la typographie, qui viennent souvent après les règles de mise en page.
_BUDGETS = {'content': (1200, 3000), 'form': (6000, 9000)}
_MAX_IMAGES = 2              # chaque image = 1 appel vision → borner


def comprehend_files(paths, *, language: str = 'en', console=None, timeout: int = 120,
                     reading: str = 'content') -> str:
    """
    Comprend une liste de fichiers de référence → bloc de contexte texte concis (ou '' si rien).

    `language` : langue de description souhaitée (= langue du prompt après routing).
    `reading`  : `content` (ce que le fichier dit) ou `form` (comment il est fait) — cf. l'en-tête.
    """
    if not paths:
        return ''
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    if reading not in READINGS:
        reading = 'content'
    per_file, total = _BUDGETS[reading]

    parts: list[str] = []
    skipped: list[str] = []
    used = 0
    images_done = 0
    for p in paths:
        p = str(p)
        if not p or not os.path.exists(p):
            continue
        ext = os.path.splitext(p)[1].lower()
        name = os.path.basename(p)
        try:
            if ext in _IMAGE_EXTS:
                if images_done >= _MAX_IMAGES:
                    continue
                chunk = _describe_image(p, language, timeout, reading)
                images_done += 1
            elif ext in _HTML_EXTS:
                chunk = _html_form(p) if reading == 'form' else _html_text(p)
            elif ext in _DOC_EXTS and reading == 'content':
                chunk = _extract_doc(p)
            else:
                if reading == 'form':
                    skipped.append(name)
                continue
        except Exception as e:  # fail-safe : un fichier ne doit jamais casser le run
            logger.debug(f"[reference_comprehension] {name}: {e}")
            continue

        chunk = (chunk or '').strip()
        if not chunk:
            continue
        chunk = chunk[:per_file]
        if used + len(chunk) > total:
            chunk = chunk[:max(0, total - used)]
        if not chunk:
            break
        parts.append(f"- {name} : {chunk}")
        used += len(chunk)
        if used >= total:
            break

    if console and skipped:
        console(f"⚠ Mise en page non lue pour {', '.join(skipped)} : seule celle d'un HTML ou d'une "
                f"image se lit aujourd'hui — en extraire le texte ferait passer un contenu pour un style.")
    if not parts:
        return ''
    if console:
        what = 'de mise en page' if reading == 'form' else 'de référence'
        console(f"📎 {len(parts)} fichier(s) {what} pris en compte ({used} caractères de contexte).")
    return "\n".join(parts)


# ── interne ──────────────────────────────────────────────────────────────────────
def _describe_image(path: str, language: str, timeout: int, reading: str = 'content') -> str:
    from wama.model_manager.services.vision_probe import describe_image_ollama
    try:
        from wama.describer.backends.image_backend import _best_ollama_vision_model
        model = _best_ollama_vision_model()
    except Exception:
        model = None
    lang_name = 'en français' if (language or 'en').startswith('fr') else f"in {language}"
    if reading == 'form':
        prompt = (f"Describe only the VISUAL DESIGN of this page or slide ({lang_name}): layout and "
                  "grid, colours (with hex values if you can), typography (families, sizes, weights), "
                  "spacing, decorative elements. Do not describe or repeat its text content.")
    else:
        prompt = f"Describe this reference image precisely and concisely ({lang_name})."
    # Modèle vide → résolu par la route commune DANS describe_image_ollama (point unique,
    # audit 19/08) — l'ancien repli littéral 'gemma4:12b' aurait pourri à son remplacement.
    res = describe_image_ollama(path, model=model or '', prompt=prompt, timeout=timeout)
    return res.get('description', '') if res.get('ok') else ''


def _extract_doc(path: str) -> str:
    from wama.common.utils.batch_parsers import extract_batch_file_text
    return extract_batch_file_text(path) or ''


def _read_html(path: str):
    from bs4 import BeautifulSoup
    with open(path, encoding='utf-8', errors='replace') as fh:
        return BeautifulSoup(fh.read(), 'html.parser')


def _html_text(path: str) -> str:
    """CONTENU d'un HTML : son texte visible (scripts et styles écartés)."""
    soup = _read_html(path)
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    return ' '.join(soup.get_text(' ').split())


def _html_form(path: str) -> str:
    """FORME d'un HTML : ses styles, puis son squelette — balises, classes et ids, sans le texte
    (le texte d'une référence de forme n'est pas à reprendre : on ne l'expose même pas)."""
    soup = _read_html(path)
    styles = '\n'.join(s.get_text() for s in soup.find_all('style'))
    links = [l.get('href') for l in soup.find_all('link', rel='stylesheet') if l.get('href')]
    body = soup.body or soup
    for tag in body(['script', 'noscript', 'svg']):
        tag.decompose()

    def skeleton(node, depth, out, budget):
        for child in getattr(node, 'children', []):
            if not getattr(child, 'name', None) or budget[0] <= 0:
                continue
            budget[0] -= 1
            attrs = ''.join(f'.{c}' for c in (child.get('class') or []))
            attrs += f"#{child['id']}" if child.get('id') else ''
            out.append('  ' * depth + child.name + attrs)
            skeleton(child, depth + 1, out, budget)
        return out

    lines = skeleton(body, 0, [], [400])
    parts = []
    if styles.strip():
        # Plafonné pour laisser sa place au squelette dans le budget d'un fichier.
        parts.append('STYLES:\n' + ' '.join(styles.split())[:4000])
    if links:
        parts.append('FEUILLES EXTERNES: ' + ', '.join(links[:5]))
    if lines:
        parts.append('SQUELETTE:\n' + '\n'.join(lines))
    return '\n'.join(parts)
