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
    WAMA, qui vivent au fil des décisions — est écrite à la main. Les docs DÉVELOPPEUR et
    UTILISATEUR en DÉRIVENT : un `plan` déclaré ici même dit quels extraits et quels faits de
    registre les composent, et `doc_facts` écrit le `.md` (`doc_plans.py`).

    TOUT EST FICHIER `.md` (Fabien, 2026-09-13) : lisible depuis le dépôt ET depuis WAMA. Les
    pages « calculées à la lecture » de l'amorçage du 11/09 (champ `generator`) n'existaient que
    dans WAMA, pour les administrateurs — un agent ne pouvait pas les lire. Reversées en plans le
    2026-09-14 (ROADMAP §25.1 ⑥), et le mécanisme retiré avec elles, faute d'usage.

SÉCURITÉ — on ne lit que ce qui est DÉCLARÉ

    La page reçoit une CLÉ, jamais un chemin : il n'existe aucune URL par laquelle demander
    `../.env`. Le HTML brut des `.md` est échappé, et un lien vers un fichier non déclaré est
    rendu en texte — la page ne sert pas de navigateur du dépôt.

QUI LIT QUOI (`visible_to`)

    La doc UTILISATEUR : tout compte connecté (Fabien, 2026-09-14). La doc de construction et la
    doc développeur : les administrateurs (11/09). Pour un compte qui ne peut pas la lire, une doc
    N'EXISTE PAS — absente du catalogue, 404 au lecteur, et un lien qui la vise rendu en texte.

RENDU — markdown-it-py, pas Python-Markdown

    Les deux sont installés (le premier via `rich`, le second via `tensorboard`), aucun n'était
    importé par WAMA. markdown-it-py l'emporte sur deux points qui comptent ici : son flux de
    TOKENS permet de neutraliser le HTML, de réécrire les liens et de poser les ancres sans
    reparser du HTML.
"""
from __future__ import annotations

import html as _html
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
    #: Relatif à BASE_DIR, séparateur `/`.
    path: str
    label: str
    family: str
    description: str
    audience: str = CONSTRUCTION
    #: Journal DATÉ : ce qu'il écrit était vrai à sa date. Ses renvois `.md` vers un document
    #: depuis archivé sont des faits d'histoire — `check_docs` ne les contrôle donc pas.
    journal: bool = False
    #: Plan d'une doc DÉRIVÉE : étapes `Excerpt` / `Facts`. Le fichier `path` est écrit par
    #: `doc_facts` — il ne s'édite jamais à la main.
    plan: tuple = ()


DOCS: Tuple[Doc, ...] = (
    # ── doctrine ──
    Doc('agents', 'AGENTS.md', 'AGENTS — la doctrine', 'doctrine',
        "Source unique des règles de développement : philosophie, règles obligatoires, "
        "conventions, table des fichiers de référence. Lue par tout agent et par un humain."),
    Doc('claude', 'CLAUDE.md', 'CLAUDE — le harnais Claude Code', 'doctrine',
        "Les seules règles propres au harnais Claude Code (permissions, hooks). Importe "
        "AGENTS.md et n'en recopie rien."),
    # Le point d'entrée du dépôt. Son arborescence de la doc est un bloc GÉNÉRÉ depuis ce
    # catalogue (`doc_facts`, fait `arborescence_docs`) — palier C du déménagement, 2026-09-14.
    Doc('readme', 'README.md', 'README — présentation et carte de la doc', 'doctrine',
        "Présentation de WAMA, installation, architecture — et l'arborescence de la doc, "
        "générée depuis ce catalogue."),
    # ── architecture & génération ──
    Doc('mecanismes', 'docs/construction/architecture/WAMA_MECANISMES.md', 'Carte des mécanismes',
        'architecture',
        "Index des briques transversales : où vit quoi, qui l'utilise. Sa table est générée "
        "depuis le registre des mécanismes."),
    Doc('generation-route', 'docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
        "Route d'auto-génération des apps", 'architecture',
        "Facettes F1–F8, briques communes, chaîne dépôt → app, et ce qu'une génération ne doit "
        "plus redécouvrir. À lire avant de créer ou modifier une app."),
    Doc('app-conventions', 'docs/construction/architecture/WAMA_APP_CONVENTIONS.md',
        "Conventions d'app", 'architecture',
        "Conventions UI et architecture de toutes les apps, capacités d'app, checklist de "
        "création."),
    Doc('manifest-spec', 'docs/construction/architecture/WAMA_MANIFEST_SPEC.md',
        'Manifestes — formalisme', 'architecture',
        "Le formalisme des sept kinds de manifestes : app, library, model, function, pipeline, "
        "project, dataset."),
    Doc('manifest-architecture', 'docs/construction/architecture/WAMA_MANIFEST_ARCHITECTURE.md',
        'Manifestes — flux et schéma', 'architecture',
        "Comment circulent les manifestes : extraction, composition, projection vers les "
        "registres."),
    Doc('transcriber-audit', 'docs/construction/architecture/TRANSCRIBER_REFERENCE_AUDIT.md',
        "Audit de l'app de référence", 'architecture',
        "Le Transcriber comme étalon : audit de conformité et checklist de fin d'app."),
    Doc('verification', 'docs/construction/architecture/WAMA_VERIFICATION.md', 'Vérification',
        'architecture',
        "Comment on sait que ça marche : grille d'adoption contre grille fonctionnelle, "
        "catalogue des gestes, couverture."),
    Doc('common-readme', 'wama/common/README.md', 'Briques communes — carte', 'architecture',
        "Carte d'entrée du dossier des briques communes."),
    # ── interface & file ──
    Doc('card-design', 'docs/construction/ui/CARD_DESIGN.md', 'Formalisme de card', 'ui',
        "Anatomie des cards, trois densités, lots."),
    Doc('modes-queue', 'docs/construction/ui/MODES_QUEUE_UX.md', 'File et modes applicatifs', 'ui',
        "UX de la file d'attente et des modes d'app."),
    Doc('volets', 'docs/construction/ui/WAMA_VOLETS.md', 'Volets gauche et droit', 'ui',
        "Ossature des volets, états contextuels, mode simplifié, repli — état mesuré des pages."),
    Doc('inspector-fields', 'docs/construction/ui/INSPECTOR_DETAIL_FIELDS.md',
        "Champs de l'inspecteur", 'ui',
        "Schéma canonique des champs de détail affichés par l'inspecteur."),
    Doc('input-matching', 'docs/construction/ui/INPUT_MODEL_MATCHING.md',
        'Appariement entrée ↔ modèle', 'ui',
        "Quel modèle accepte quelle entrée, et comment l'interface le montre."),
    Doc('batch-format', 'docs/construction/ui/BATCH_FORMAT.md', 'Format des fichiers de lot', 'ui',
        "Le format des fichiers batch (txt, csv, pdf, docx)."),
    # ── couche IA ──
    Doc('llm', 'docs/construction/ia/WAMA_LLM.md', 'Couche LLM', 'ia',
        "Prompts, skills, traduction et enrichissement, routage de modèle, surfaces de "
        "l'assistant."),
    Doc('memory', 'docs/construction/ia/WAMA_MEMORY.md', 'Mémoire & RAG', 'ia',
        "Mémoire d'agent, mémoire de travail et RAG comme un seul mécanisme, plus le journal "
        "utilisateur."),
    Doc('apprentissage', 'docs/construction/ia/WAMA_APPRENTISSAGE.md', 'Apprentissage (ML/DL)',
        'ia',
        "Modèles appris, couche statistique, MLflow — WAMA déclare, déclenche et réingère ; il "
        "n'entraîne pas."),
    Doc('prospection', 'wama/model_manager/PROSPECTION_PIPELINE.md', 'Prospection de modèles',
        'ia', "Veille et prospection de modèles : la chaîne et ses juges."),
    # ── mondes & apps ──
    Doc('vision', 'docs/construction/mondes/WAMA_VISION_COMPLET.md', "Vision d'ensemble", 'mondes',
        "La vision produit, unique, confrontée au réel section par section."),
    Doc('studio', 'docs/construction/mondes/STUDIO_VISION.md', 'Studio & production AV', 'mondes',
        "Vision du studio et de la production audiovisuelle."),
    Doc('data-world', 'docs/construction/mondes/WAMA_DATA_WORLD.md', 'Monde Data', 'mondes',
        "Périmètre du monde Data et cartographie de corpus."),
    Doc('data-function-cards', 'docs/construction/mondes/WAMA_DATA_FUNCTION_CARDS.md',
        'Fonctions Data — catalogue', 'mondes',
        "Le catalogue des fonctions de traitement du monde Data."),
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
    Doc('profiles', 'docs/construction/exploitation/PROFILES_PERMISSIONS.md',
        'Profils, permissions, rétention', 'exploitation',
        "Profils, droits d'accès, notifications, rétention."),
    Doc('infra', 'docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md', 'Infra WSL2 ↔ Windows',
        'exploitation', "Ce qui tourne où, entre WSL2 et Windows."),
    Doc('media-storage', 'docs/construction/exploitation/MEDIA_STORAGE_TIERING.md',
        'Médias : stockage et import', 'exploitation',
        "Stockage, tiering, intégrité et voies d'import des médias."),
    Doc('licensing', 'docs/construction/exploitation/LICENSING.md', 'Licences & dépôt',
        'exploitation', "Licence du dépôt, politique, code vendorisé, dépôt officiel."),
    # ── suivi des chantiers ──
    Doc('project-status', 'docs/construction/suivi/PROJECT_STATUS.md',
        "Point d'étape des chantiers", 'suivi',
        "Photo des chantiers et handoffs de session. Journal daté : ce qui y est écrit était "
        "vrai à sa date.", journal=True),
    Doc('roadmap', 'docs/construction/suivi/ROADMAP.md', 'Roadmap', 'suivi',
        "Les chantiers ouverts et leur ordre."),
    Doc('removal-ledger', 'docs/construction/suivi/REMOVAL_LEDGER.md', 'Registre des retraits',
        'suivi', "Ce qui a été retiré, et pourquoi."),
    # ── docs de MODULE — ils restent à côté de leur code (décision de Fabien, 2026-09-13) ──
    # Déclarés pour être lisibles depuis WAMA et contrôlés par `check_docs` ; ils ne partent pas
    # dans `docs/` au déménagement (ROADMAP §25.4). Les archives, elles, ne se déclarent pas.
    Doc('patches', 'patches/README.md', 'Patches de compatibilité des venvs', 'exploitation',
        "Les correctifs des librairies tierces à réappliquer après une installation propre du "
        "venv, et leur registre."),
    Doc('ai-models', 'AI-models/README.md', 'AI-models — le dossier des poids', 'exploitation',
        "Où vivent les poids des modèles de WAMA, et comment le dossier s'organise."),
    Doc('ai-models-arbo', 'AI-models/models/README.md', 'AI-models — arborescence par domaine',
        'exploitation', "L'arborescence des modèles, rangés par domaine."),
    Doc('vendor-engines', 'wama/common/backends/vendor/README.md', 'Moteurs vendorisés',
        'exploitation',
        "Les moteurs livrés en code source (dépôts tiers clonés à l'installation, exécutés en "
        "sous-processus) — rien n'y est du code WAMA."),
    Doc('dev-ai', 'wama-dev-ai/README.md', 'wama-dev-ai — agent de développement local', 'ia',
        "L'agent local (Ollama) : audits en lecture seule, génération bornée, rôles producteurs "
        "de manifestes. Claude réfléchit, wama-dev-ai exécute, l'humain valide."),
    Doc('imager', 'wama/imager/README.md', 'Imager', 'mondes',
        "Génération d'images et de vidéos : backends interchangeables, fichiers de référence, "
        "mots-clés imposés, enrichissement de prompt."),
    Doc('face-analyzer', 'wama_lab/face_analyzer/README.md', 'Face Analyzer', 'mondes',
        "Analyse faciale en vidéo expérimentale (monde Lab) : variables comportementales et "
        "physiologiques, croisables avec les autres données du laboratoire."),
    Doc('cam-projet-ena-casa', 'wama_lab/cam_analyzer/projects/ENA_CASA.md',
        'Cam Analyzer — un projet (ENA_CASA)', 'mondes',
        "Les spécificités d'un projet cam_analyzer : données, calibration, rig. Une configuration "
        "de l'app, pas une propriété — façonné comme le futur manifeste."),
    # ── DÉVELOPPEUR — DÉRIVÉE par plan (fichiers écrits par `doc_facts`, jamais à la main) ──
    Doc('dev-parcours', 'docs/dev/parcours.md', "Parcours d'entrée", 'doctrine',
        "L'ordre dans lequel lire la doc pour étendre WAMA ; chaque étape reprend la description "
        "que le document déclare.",
        audience=DEVELOPER,
        plan=(Facts('wama.common.dev_docs:reading_path'),)),
    Doc('dev-registres', 'docs/dev/registres.md', 'Les registres de WAMA', 'architecture',
        "Quand une chose mérite un registre, les natures d'actualisation, et chaque registre de "
        "WAMA — dérivé de la doc de construction et des registres eux-mêmes.",
        audience=DEVELOPER,
        plan=(Excerpt('data-world', '9quinquies.2 LE CRITÈRE — trois questions, dans cet ordre',
                      title='Quand une chose mérite un registre'),
              Facts('wama.common.dev_docs:registry_natures'),
              Facts('wama.common.dev_docs:registry_entries'),
              Facts('wama.common.dev_docs:manifest_kinds'))),
    Doc('dev-briques', 'docs/dev/briques.md', 'Briques communes — API', 'architecture',
        "Chaque mécanisme transversal avec l'API publique de son module : signatures et "
        "docstrings lues dans le code.",
        audience=DEVELOPER,
        plan=(Facts('wama.common.dev_docs:bricks_api'),)),
    # ── UTILISATEUR — DÉRIVÉE par plan, filtrée par la PORTE registre (ROADMAP §25.1 ⑤) ──
    Doc('user-transcriber-correction', 'docs/utilisateur/transcriber-correction.md',
        'Transcriber — corriger une transcription', 'mondes',
        "L'éditeur de correction : ses deux modes, ses raccourcis, la bande de qualité. N'y "
        "entre que ce que le registre des applications confirme — la vision reste dans la spec.",
        audience=USER,
        plan=(Excerpt('transcriber-correction', '9. Corriger une transcription — le guide',
                      title='Corriger une transcription'),)),
)

BY_KEY: Dict[str, Doc] = {d.key: d for d in DOCS}
BY_PATH: Dict[str, Doc] = {d.path: d for d in DOCS}


def get(key: str) -> Optional[Doc]:
    return BY_KEY.get(key)


def visible_to(doc: Doc, admin: bool) -> bool:
    """Un compte connecté lit la doc utilisateur ; un administrateur lit tout."""
    return admin or doc.audience == USER


def checked_paths() -> List[str]:
    """Les cibles de `check_docs` : les docs ÉCRITS À LA MAIN, dans l'ordre de déclaration.

    ⚠ Les docs DÉRIVÉES n'y sont pas (2026-09-14). Elles se confrontent par leurs SOURCES — la
    doc de construction, contrôlée ici — et par `doc_facts --check`, qui refuse un fichier dérivé
    qui n'est plus ce que son plan produit. Contrôler leurs références reviendrait à soumettre à
    `check_docs` les docstrings du code que `briques` publie, que rien n'y engage aujourd'hui ;
    leurs liens, eux, viennent des chemins de ce catalogue, dont l'existence est testée.
    """
    return [d.path for d in DOCS if not d.plan]


def journal_paths() -> set:
    return {d.path for d in DOCS if d.journal}


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
        'journal': doc.journal, 'generated': bool(doc.plan),
        'exists': False, 'lines': 0, 'modified': None,
    }
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


def render_doc(doc: Doc, admin: bool = True) -> dict:
    """`{'html', 'toc'}` du doc, tel que le lit un administrateur ou non — les liens vers une doc
    qu'il ne peut pas lire deviennent du texte. Lève `FileNotFoundError` si le fichier manque."""
    f = file_of(doc)
    stamp = _stamp(f)
    cle = (doc.path, admin)
    hit = _RENDERED.get(cle)
    if hit and hit[0] == stamp:
        return hit[1]
    out = render_markdown(f.read_text(encoding='utf-8', errors='replace'), doc.path,
                          visible=lambda d: visible_to(d, admin))
    _RENDERED[cle] = (stamp, out)
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


def _target(href: str, source_path: str, visible=None) -> Optional[str]:
    """Où mène un lien. `None` = lien externe gardé tel quel ; `''` = PAS de lien (fichier non
    déclaré, ou doc que le lecteur ne peut pas lire — `visible`) ; sinon l'URL du lecteur, ancre
    comprise."""
    if href.startswith('#'):
        return href
    if _SCHEME.match(href):
        return None if href.lower().startswith(('http:', 'https:', 'mailto:')) else ''
    chemin, _, ancre = href.partition('#')
    if not chemin:
        return href
    rel = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), unquote(chemin)))
    doc = BY_PATH.get(rel.lstrip('/'))
    if doc is None or (visible is not None and not visible(doc)):
        return ''
    from django.urls import reverse
    return reverse('common:doc_read', args=[doc.key]) + (f'#{ancre}' if ancre else '')


def _raw(content: str):
    from markdown_it.token import Token
    t = Token('html_inline', '', 0)
    t.content = content
    return t


def _rewrite_links(children: list, source_path: str, visible=None) -> list:
    out, ouverts = [], []
    for c in children:
        if c.type == 'link_open':
            href = str(c.attrGet('href') or '')
            cible = _target(href, source_path, visible)
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


def render_markdown(text: str, source_path: str = '', visible=None) -> dict:
    """Markdown → `{'html', 'toc'}`. `source_path` sert à résoudre les liens relatifs ;
    `visible(doc)` dit si le lecteur peut suivre un lien vers ce doc (tous, par défaut)."""
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
            tok.children = _rewrite_links(tok.children, source_path, visible)
    return {'html': md.renderer.render(tokens, md.options, {}), 'toc': toc}
