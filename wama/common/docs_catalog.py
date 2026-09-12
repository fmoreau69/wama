"""
Catalogue des DOCS — les documents de WAMA, déclarés UNE fois, lisibles depuis WAMA.

POURQUOI CE MODULE (demande de Fabien, 2026-09-11)

    Donner un accès en lecture seule à la doc depuis le menu du profil. Or la liste des docs de
    référence existait déjà DEUX fois à la main : la table « Fichiers de référence par domaine »
    d'`AGENTS.md`, et `DOCS` dans `check_docs.py` — dont le commentaire exigeait de les tenir à
    jour « dans le même commit ». Un registre portant sa propre liste en aurait fait une
    troisième. Ce module est donc LA déclaration : le registre `docs`, la page de lecture et
    `check_docs` en dérivent. La table d'`AGENTS.md` reste écrite à la main (c'est de la
    doctrine, elle explique), mais `tests_docs_catalog` échoue si elle cite un doc absent d'ici.

TROIS PUBLICS (cadre posé par Fabien le 2026-08-12, acté le 2026-09-11 — AGENTS.md §Trois docs)

    `audience` dit à qui un document s'adresse. La doc de CONSTRUCTION — la trace et la vision de
    WAMA, qui vivent au fil des décisions — est faite de fichiers `.md` écrits à la main. Les docs
    DÉVELOPPEUR et UTILISATEUR en DÉRIVENT : un `plan` déclaré ici même dit quels extraits et
    quels faits de registre les composent, et `doc_facts` écrit le `.md` (`doc_plans.py`). Trois
    pages développeur restent calculées à la lecture (`generator`, `dev_docs.py`) — l'amorçage
    du 11/09, à reverser en plans (ROADMAP §25.1 ⑥).

SÉCURITÉ — on ne lit que ce qui est DÉCLARÉ

    La page reçoit une CLÉ, jamais un chemin : il n'existe aucune URL par laquelle demander
    `../.env`. Le HTML brut des `.md` est échappé, et un lien vers un fichier non déclaré est
    rendu en texte — la page ne sert pas de navigateur du dépôt.

RENDU — markdown-it-py, pas Python-Markdown

    Les deux sont installés (le premier via `rich`, le second via `tensorboard`), aucun n'était
    importé par WAMA. markdown-it-py l'emporte sur deux points qui comptent ici : son flux de
    TOKENS permet de neutraliser le HTML, de réécrire les liens et de poser les ancres sans
    reparser du HTML.
"""
from __future__ import annotations

import html as _html
import importlib
import posixpath
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

#: ⚠ Les VALEURS sont un vocabulaire de DONNÉE (filtres `data-f-*`, futures déclarations) : elles
#: ne se renomment pas avec les identifiants (AGENTS.md §nommage, règle 3).
CONSTRUCTION = 'construction'
DEVELOPER = 'developpeur'
USER = 'utilisateur'
AUDIENCES = {
    CONSTRUCTION: "Construction — la trace et la vision de WAMA",
    DEVELOPER: "Développeur — étendre WAMA",
    USER: "Utilisateur — se servir de WAMA",
}
AUDIENCE_BADGES = {CONSTRUCTION: 'doc de construction', DEVELOPER: 'doc développeur',
                   USER: 'doc utilisateur'}

#: Familles = les regroupements de la table d'AGENTS.md, pour la facette de la page.
FAMILIES = {
    'doctrine': 'Doctrine & harnais',
    'architecture': 'Architecture & génération',
    'ui': 'Interface & file',
    'ia': 'Couche IA',
    'mondes': 'Mondes & apps',
    'exploitation': 'Infra, droits & données',
    'suivi': 'Suivi des chantiers',
}


# ── Étapes d'un PLAN de doc dérivée (ROADMAP §25.1 ③, construites par `doc_plans.build`) ──

@dataclass(frozen=True)
class Excerpt:
    """Une section de la doc de construction, marquée pour le public de la doc dérivée."""
    #: Clé du doc source, dans ce catalogue.
    doc: str
    #: Titre EXACT de la section dans la source (un titre renommé casse le plan : c'est voulu).
    section: str
    #: Titre dans la doc dérivée ; vide = celui de la source.
    title: str = ''


@dataclass(frozen=True)
class Facts:
    """Un bloc calculé depuis les registres : `module:fonction` qui rend du markdown."""
    generator: str


@dataclass(frozen=True)
class Doc:
    key: str
    #: Relatif à BASE_DIR, séparateur `/`. VIDE pour une page calculée à la lecture.
    path: str
    label: str
    family: str
    description: str
    audience: str = CONSTRUCTION
    #: Journal DATÉ : ce qu'il écrit était vrai à sa date. Ses renvois `.md` vers un document
    #: depuis archivé sont des faits d'histoire — `check_docs` ne les contrôle donc pas.
    journal: bool = False
    #: `module:fonction` qui rend le markdown d'une page CALCULÉE à la lecture. Exclusif de `path`.
    generator: str = ''
    #: Plan d'une doc DÉRIVÉE : étapes `Excerpt` / `Facts`. Exige un `path` — le fichier écrit.
    plan: tuple = ()


DOCS: Tuple[Doc, ...] = (
    # ── doctrine ──
    Doc('agents', 'AGENTS.md', 'AGENTS — la doctrine', 'doctrine',
        "Source unique des règles de développement : philosophie, règles obligatoires, "
        "conventions, table des fichiers de référence. Lue par tout agent et par un humain."),
    Doc('claude', 'CLAUDE.md', 'CLAUDE — le harnais Claude Code', 'doctrine',
        "Les seules règles propres au harnais Claude Code (permissions, hooks). Importe "
        "AGENTS.md et n'en recopie rien."),
    # ── architecture & génération ──
    Doc('mecanismes', 'WAMA_MECANISMES.md', 'Carte des mécanismes', 'architecture',
        "Index des briques transversales : où vit quoi, qui l'utilise. Sa table est générée "
        "depuis le registre des mécanismes."),
    Doc('generation-route', 'WAMA_APP_GENERATION_ROUTE.md', "Route d'auto-génération des apps",
        'architecture',
        "Facettes F1–F8, briques communes, chaîne dépôt → app, et ce qu'une génération ne doit "
        "plus redécouvrir. À lire avant de créer ou modifier une app."),
    Doc('app-conventions', 'WAMA_APP_CONVENTIONS.md', "Conventions d'app", 'architecture',
        "Conventions UI et architecture de toutes les apps, capacités d'app, checklist de "
        "création."),
    Doc('manifest-spec', 'WAMA_MANIFEST_SPEC.md', 'Manifestes — formalisme', 'architecture',
        "Le formalisme des sept kinds de manifestes : app, library, model, function, pipeline, "
        "project, dataset."),
    Doc('manifest-architecture', 'WAMA_MANIFEST_ARCHITECTURE.md', 'Manifestes — flux et schéma',
        'architecture',
        "Comment circulent les manifestes : extraction, composition, projection vers les "
        "registres."),
    Doc('transcriber-audit', 'TRANSCRIBER_REFERENCE_AUDIT.md', "Audit de l'app de référence",
        'architecture',
        "Le Transcriber comme étalon : audit de conformité et checklist de fin d'app."),
    Doc('verification', 'WAMA_VERIFICATION.md', 'Vérification', 'architecture',
        "Comment on sait que ça marche : grille d'adoption contre grille fonctionnelle, "
        "catalogue des gestes, couverture."),
    Doc('common-readme', 'wama/common/README.md', 'Briques communes — carte', 'architecture',
        "Carte d'entrée du dossier des briques communes."),
    # ── interface & file ──
    Doc('card-design', 'CARD_DESIGN.md', 'Formalisme de card', 'ui',
        "Anatomie des cards, trois densités, lots."),
    Doc('modes-queue', 'MODES_QUEUE_UX.md', 'File et modes applicatifs', 'ui',
        "UX de la file d'attente et des modes d'app."),
    Doc('volets', 'WAMA_VOLETS.md', 'Volets gauche et droit', 'ui',
        "Ossature des volets, états contextuels, mode simplifié, repli — état mesuré des pages."),
    Doc('inspector-fields', 'INSPECTOR_DETAIL_FIELDS.md', "Champs de l'inspecteur", 'ui',
        "Schéma canonique des champs de détail affichés par l'inspecteur."),
    Doc('input-matching', 'INPUT_MODEL_MATCHING.md', 'Appariement entrée ↔ modèle', 'ui',
        "Quel modèle accepte quelle entrée, et comment l'interface le montre."),
    Doc('batch-format', 'BATCH_FORMAT.md', 'Format des fichiers de lot', 'ui',
        "Le format des fichiers batch (txt, csv, pdf, docx)."),
    # ── couche IA ──
    Doc('llm', 'WAMA_LLM.md', 'Couche LLM', 'ia',
        "Prompts, skills, traduction et enrichissement, routage de modèle, surfaces de "
        "l'assistant."),
    Doc('memory', 'WAMA_MEMORY.md', 'Mémoire & RAG', 'ia',
        "Mémoire d'agent, mémoire de travail et RAG comme un seul mécanisme, plus le journal "
        "utilisateur."),
    Doc('apprentissage', 'WAMA_APPRENTISSAGE.md', 'Apprentissage (ML/DL)', 'ia',
        "Modèles appris, couche statistique, MLflow — WAMA déclare, déclenche et réingère ; il "
        "n'entraîne pas."),
    Doc('prospection', 'wama/model_manager/PROSPECTION_PIPELINE.md', 'Prospection de modèles',
        'ia', "Veille et prospection de modèles : la chaîne et ses juges."),
    # ── mondes & apps ──
    Doc('vision', 'docs/WAMA_VISION_COMPLET.md', "Vision d'ensemble", 'mondes',
        "La vision produit, unique, confrontée au réel section par section."),
    Doc('studio', 'STUDIO_VISION.md', 'Studio & production AV', 'mondes',
        "Vision du studio et de la production audiovisuelle."),
    Doc('data-world', 'WAMA_DATA_WORLD.md', 'Monde Data', 'mondes',
        "Périmètre du monde Data et cartographie de corpus."),
    Doc('data-function-cards', 'WAMA_DATA_FUNCTION_CARDS.md', 'Fonctions Data — catalogue',
        'mondes', "Le catalogue des fonctions de traitement du monde Data."),
    Doc('cam-chaine', 'wama_lab/cam_analyzer/CAM_ANALYZER_CHAINE_TRAITEMENT.md',
        'Cam Analyzer — chaîne de traitement', 'mondes',
        "La chaîne de traitement de Cam Analyzer et sa conception."),
    Doc('cam-changelog', 'wama_lab/cam_analyzer/CAM_ANALYZER_CHANGELOG.md',
        'Cam Analyzer — historique', 'mondes',
        "Journal des évolutions de Cam Analyzer.", journal=True),
    Doc('cam-readme', 'wama_lab/cam_analyzer/README.md', 'Cam Analyzer — carte', 'mondes',
        "Carte d'entrée de l'app Lab."),
    Doc('transcriber-correction', 'wama/transcriber/TRANSCRIBER_CORRECTION.md',
        'Transcriber — correction assistée', 'mondes',
        "La page de correction manuelle assistée par IA."),
    Doc('enhancer', 'wama/enhancer/README.md', 'Enhancer', 'mondes',
        "Upscaling image et vidéo, et branche audio."),
    # ── infra, droits & données ──
    Doc('profiles', 'PROFILES_PERMISSIONS.md', 'Profils, permissions, rétention', 'exploitation',
        "Profils, droits d'accès, notifications, rétention."),
    Doc('infra', 'INFRA_WSL_VS_WINDOWS.md', 'Infra WSL2 ↔ Windows', 'exploitation',
        "Ce qui tourne où, entre WSL2 et Windows."),
    Doc('media-storage', 'MEDIA_STORAGE_TIERING.md', 'Médias : stockage et import',
        'exploitation', "Stockage, tiering, intégrité et voies d'import des médias."),
    Doc('licensing', 'LICENSING.md', 'Licences & dépôt', 'exploitation',
        "Licence du dépôt, politique, code vendorisé, dépôt officiel."),
    # ── suivi des chantiers ──
    Doc('project-status', 'PROJECT_STATUS.md', "Point d'étape des chantiers", 'suivi',
        "Photo des chantiers et handoffs de session. Journal daté : ce qui y est écrit était "
        "vrai à sa date.", journal=True),
    Doc('roadmap', 'ROADMAP.md', 'Roadmap', 'suivi', "Les chantiers ouverts et leur ordre."),
    Doc('removal-ledger', 'REMOVAL_LEDGER.md', 'Registre des retraits', 'suivi',
        "Ce qui a été retiré, et pourquoi."),
    # ── DÉVELOPPEUR — DÉRIVÉE par plan (fichier écrit par `doc_facts`) ──
    Doc('dev-registres', 'docs/dev/registres.md', 'Les registres de WAMA', 'architecture',
        "Quand une chose mérite un registre, les natures d'actualisation, et chaque registre de "
        "WAMA — dérivé de la doc de construction et des registres eux-mêmes.",
        audience=DEVELOPER,
        plan=(Excerpt('data-world', '9quinquies.2 LE CRITÈRE — trois questions, dans cet ordre',
                      title='Quand une chose mérite un registre'),
              Facts('wama.common.dev_docs:registres_natures'),
              Facts('wama.common.dev_docs:registres_fiches'),
              Facts('wama.common.dev_docs:kinds_manifeste'))),
    # ── DÉVELOPPEUR — calculées à la lecture (amorçage du 11/09, à reverser en plans) ──
    Doc('dev-parcours', '', "Parcours d'entrée", 'doctrine',
        "L'ordre dans lequel lire la doc pour étendre WAMA ; chaque étape reprend la description "
        "que le document déclare.",
        audience=DEVELOPER, generator='wama.common.dev_docs:parcours'),
    Doc('dev-briques', '', 'Briques communes — API', 'architecture',
        "Chaque mécanisme transversal avec l'API publique de son module : signatures et "
        "docstrings lues dans le code.",
        audience=DEVELOPER, generator='wama.common.dev_docs:briques'),
)

BY_KEY: Dict[str, Doc] = {d.key: d for d in DOCS}
#: Docs-FICHIERS seulement : une page calculée n'a pas de chemin vers lequel un lien mènerait.
BY_PATH: Dict[str, Doc] = {d.path: d for d in DOCS if d.path}


def get(key: str) -> Optional[Doc]:
    return BY_KEY.get(key)


def checked_paths() -> List[str]:
    """Les cibles de `check_docs` — les docs-fichiers, dans l'ordre de déclaration."""
    return [d.path for d in DOCS if d.path]


def journal_paths() -> set:
    return {d.path for d in DOCS if d.path and d.journal}


def file_of(doc: Doc) -> Path:
    from django.conf import settings
    return Path(settings.BASE_DIR) / doc.path


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Fiches (catalogue) et rendu (lecteur) — DÉRIVÉS du disque, mis en cache sur (mtime, taille)
# ──────────────────────────────────────────────────────────────────────────────────────────────

#: {chemin → ((mtime_ns, taille), valeur)}. Le cache ne change pas la nature DÉRIVÉE du
#: registre : la clé est l'empreinte du fichier, un `.md` modifié est relu au rendu suivant.
_LINES: Dict[str, tuple] = {}
_RENDERED: Dict[str, tuple] = {}


def _stamp(f: Path) -> tuple:
    st = f.stat()
    return (st.st_mtime_ns, st.st_size)


def entry(doc: Doc) -> dict:
    """La fiche d'un doc pour sa card : déclaration + ce que le disque dit de lui."""
    out = {
        'key': doc.key, 'path': doc.path, 'label': doc.label, 'description': doc.description,
        'family': doc.family, 'family_label': FAMILIES.get(doc.family, doc.family),
        'audience': doc.audience, 'audience_label': AUDIENCES.get(doc.audience, doc.audience),
        'audience_badge': AUDIENCE_BADGES.get(doc.audience, doc.audience),
        'journal': doc.journal,
        # « générée » = pas écrite à la main (plan OU calcul) ; « live » = calculée à la lecture.
        'generated': bool(doc.generator or doc.plan), 'live': bool(doc.generator),
        'generator': doc.generator,
        'exists': False, 'lines': 0, 'modified': None,
    }
    if doc.generator:
        # Rien à mesurer sur le disque : la page n'existe qu'à la lecture. La calculer ici pour
        # afficher un nombre de lignes coûterait la page entière à chaque affichage du catalogue.
        out['exists'] = True
        return out
    f = file_of(doc)
    try:
        stamp = _stamp(f)
    except OSError:
        return out
    hit = _LINES.get(doc.path)
    if hit and hit[0] == stamp:
        lines = hit[1]
    else:
        data = f.read_bytes()
        lines = data.count(b'\n') + (1 if data and not data.endswith(b'\n') else 0)
        _LINES[doc.path] = (stamp, lines)
    out.update(exists=True, lines=lines, modified=datetime.fromtimestamp(stamp[0] / 1e9))
    return out


def entries() -> List[dict]:
    return [entry(d) for d in DOCS]


def generate(doc: Doc) -> str:
    """Le markdown d'une page CALCULÉE — son générateur, appelé à la lecture."""
    module, _, fonction = doc.generator.partition(':')
    return getattr(importlib.import_module(module), fonction)()


def render_doc(doc: Doc) -> dict:
    """`{'html', 'toc'}` du doc. Lève `FileNotFoundError` si le fichier déclaré manque."""
    if doc.generator:
        # Une page calculée peut renvoyer vers les pages de WAMA (`/common/backends/`) : c'est
        # nous qui l'écrivons. Un `.md` du dépôt, lui, ne le peut pas — cf. `_target`.
        return render_markdown(generate(doc), '', site_links=True)
    f = file_of(doc)
    stamp = _stamp(f)
    hit = _RENDERED.get(doc.path)
    if hit and hit[0] == stamp:
        return hit[1]
    out = render_markdown(f.read_text(encoding='utf-8', errors='replace'), doc.path)
    _RENDERED[doc.path] = (stamp, out)
    return out


_SCHEME = re.compile(r'^[a-z][a-z0-9+.\-]*:', re.I)


def _slug(text: str, seen: Dict[str, int]) -> str:
    """Ancre à la manière de GitHub (minuscules, ponctuation retirée, espaces → tirets), pour
    que les renvois `(#section)` écrits dans les docs visent la même chose ici et sur le dépôt.
    Les lettres accentuées sont GARDÉES (`\\w` est unicode), comme le fait GitHub."""
    base = re.sub(r'[^\w\- ]', '', text.strip().lower()).replace(' ', '-') or 'section'
    n = seen.get(base, 0)
    seen[base] = n + 1
    return base if n == 0 else f'{base}-{n}'


def _inline_text(tok) -> str:
    """Texte VISIBLE d'un titre — sans `**`, backticks ni cibles de lien."""
    return ''.join(c.content for c in (tok.children or [])
                   if c.type in ('text', 'code_inline')).strip()


def _target(href: str, source_path: str, site_links: bool = False) -> Optional[str]:
    """Où mène un lien. `None` = lien externe gardé tel quel ; `''` = PAS de lien (fichier non
    déclaré) ; sinon l'URL du lecteur, ancre comprise.

    `site_links` : une page CALCULÉE peut viser une page de WAMA (`/common/…`). Refusé aux `.md`
    du dépôt, où `/x` désigne un fichier à la racine — le suivre mènerait à une 404 ou pire."""
    if href.startswith('#'):
        return href
    if _SCHEME.match(href):
        return None if href.lower().startswith(('http:', 'https:', 'mailto:')) else ''
    chemin, _, ancre = href.partition('#')
    if not chemin:
        return href
    if site_links and chemin.startswith('/') and not chemin.endswith('.md'):
        return href
    rel = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), unquote(chemin)))
    doc = BY_PATH.get(rel.lstrip('/'))
    if doc is None:
        return ''
    from django.urls import reverse
    return reverse('common:doc_read', args=[doc.key]) + (f'#{ancre}' if ancre else '')


def _raw(content: str):
    from markdown_it.token import Token
    t = Token('html_inline', '', 0)
    t.content = content
    return t


def _rewrite_links(children: list, source_path: str, site_links: bool = False) -> list:
    out, ouverts = [], []
    for c in children:
        if c.type == 'link_open':
            href = str(c.attrGet('href') or '')
            cible = _target(href, source_path, site_links)
            if cible is None:
                c.attrSet('target', '_blank')
                c.attrSet('rel', 'noopener noreferrer')
            elif cible == '':
                # Rendu en TEXTE : un lien qui mène à un fichier brut du dépôt (ou nulle part)
                # ferait de la page un navigateur de fichiers — exactement ce qu'on ne veut pas.
                ouverts.append(True)
                out.append(_raw(f'<span class="wama-doc-horslien" '
                                f'title="{_html.escape("hors catalogue : " + href, quote=True)}">'))
                continue
            else:
                c.attrSet('href', cible)
            ouverts.append(False)
            out.append(c)
        elif c.type == 'link_close':
            if ouverts and ouverts.pop():
                out.append(_raw('</span>'))
            else:
                out.append(c)
        elif c.type == 'image':
            # Une image relative pointerait vers un fichier non servi : on dit ce qu'elle montre.
            alt = ''.join(ch.content for ch in (c.children or []))
            out.append(_raw(f'<span class="wama-doc-horslien">[image : {_html.escape(alt)}]</span>'))
        else:
            out.append(c)
    return out


_COMMENT = re.compile(r'<!--.*?-->', re.S)


def _neutralize_html(tok) -> None:
    """Le HTML brut d'un `.md` n'est JAMAIS exécuté — mais un COMMENTAIRE est masqué, comme sur
    GitHub. Corrigé le 2026-09-11 : avec `html=False`, les marqueurs `<!-- WAMA:FAITS(…) -->` et
    `<!-- WAMA:FAIT(…) -->` (invisibles sur le dépôt) s'affichaient en texte brut dans le lecteur.
    On parse donc le HTML pour le RECONNAÎTRE, et on n'en laisse passer que le silence : un
    commentaire disparaît, tout le reste est échappé en texte."""
    if tok.type == 'html_block':
        reste = _COMMENT.sub('', tok.content).strip()
        tok.content = f'<p>{_html.escape(reste)}</p>\n' if reste else ''
    elif tok.type == 'inline' and tok.children:
        for c in tok.children:
            if c.type == 'html_inline':
                c.content = ('' if _COMMENT.fullmatch(c.content.strip())
                             else _html.escape(c.content))


def render_markdown(text: str, source_path: str = '', site_links: bool = False) -> dict:
    """Markdown → `{'html', 'toc'}`. `source_path` sert à résoudre les liens relatifs."""
    from markdown_it import MarkdownIt

    # `html=True` pour que le HTML soit RECONNU, puis neutralisé token par token (voir
    # `_neutralize_html`) — jamais rendu tel quel.
    md = MarkdownIt('commonmark', {'html': True}).enable(['table', 'strikethrough'])
    tokens = md.parse(text)
    seen: Dict[str, int] = {}
    toc = []
    for i, tok in enumerate(tokens):
        _neutralize_html(tok)
        if tok.type == 'heading_open':
            titre = _inline_text(tokens[i + 1])
            ident = _slug(titre, seen)
            tok.attrSet('id', ident)
            niveau = int(tok.tag[1])
            if niveau <= 3:
                toc.append({'level': niveau, 'text': titre, 'id': ident})
        elif tok.type == 'inline' and tok.children:
            tok.children = _rewrite_links(tok.children, source_path, site_links)
    return {'html': md.renderer.render(tokens, md.options, {}), 'toc': toc}
