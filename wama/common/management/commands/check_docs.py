"""
Vérifie MÉCANIQUEMENT que les docs de référence disent vrai sur le code.

Pourquoi cette commande existe (constat Fabien, 2026-08-02) : « à chaque session, des oublis,
des documents non lus ou lus partiellement, des réinventions, des fonctionnements concurrents
qui faussent la route tracée, alors que tout est consigné ». Le skill `/doc-sync` décrit déjà
le bon processus — mais un skill dépend de la DILIGENCE de celui qui le lance. Une commande,
elle, échoue.

C'est exactement le remède qui a marché pour la conformité : la grille est passée de booléens
déclarés à `check_app_conformity` (74 critères MESURÉS) parce que les statuts déclarés dérivent.
Même médecine appliquée aux docs.

  python manage.py check_docs              # rapport
  python manage.py check_docs --strict     # code de sortie 1 s'il reste des CASSÉ

NE FAIT PAS DOUBLON avec `check_app_conformity` : celle-ci mesure la conformité par APP
(facettes F1–F8) ; celle-là vérifie l'INTÉGRITÉ des références doc→code et doc→doc.

ÉTENDUE AUX SKILLS le 2026-08-27 (`.claude/skills/*/SKILL.md`). Pourquoi : l'audit du 26/08 a
trouvé que **8 des 11 skills portaient des chiffres ou des chemins faux**, dont `/brique` qui
envoyait explorer `common/data/`, package déporté vers `wama_data/` le 22/08. Aucune n'était
couverte par un contrôle — cette commande s'arrêtait aux `.md` de référence. Or **un skill est
de la doctrine EXÉCUTABLE** : un chemin mort dans un `.md` se discute, dans un skill il se fait
obéir, et la session suivante va chercher dans un dossier disparu.

⚠ CE QUE CE CONTRÔLE NE VOIT PAS, et il faut le savoir : il vérifie que les RÉFÉRENCES existent,
pas que les CHIFFRES disent vrai. Le pire défaut du 26/08 — `/port-app` annonçant « F6/F7/F8 :
ZÉRO critère » alors que les 82 critères couvrent les 8 facettes — serait passé au travers. Le
remède à celui-là est doctrinal, pas mécanique : dans un skill, un chiffre mesurable est remplacé
par LA COMMANDE qui le mesure, la valeur ne subsistant que datée (cf. `/conformite`, `/smoke`).
"""
import re
from pathlib import Path

from django.core.management.base import BaseCommand

# Docs de référence (CLAUDE.md : « un domaine = un fichier »).
DOCS = [
    'WAMA_APP_GENERATION_ROUTE.md', 'WAMA_APP_CONVENTIONS.md', 'WAMA_MANIFEST_SPEC.md',
    'WAMA_MANIFEST_ARCHITECTURE.md', 'PROJECT_STATUS.md', 'ROADMAP.md', 'WAMA_LLM.md',
    'CLAUDE.md', 'STUDIO_VISION.md', 'TRANSCRIBER_REFERENCE_AUDIT.md',
    # Carte des mécanismes transversaux : sa TABLE est générée (doc_facts, fait `mecanismes`)
    # et donc ingénérable, mais ses chemins écrits à la main — l'intro, les documents de
    # référence — méritent le même contrôle que les autres. Ajoutée le 2026-08-13.
    'WAMA_MECANISMES.md',
]

#: Les skills sont DÉCOUVERTES, jamais énumérées ici. Une liste figée est exactement le défaut
#: que cette extension corrige : `/brique` listait un package disparu depuis quatre jours.
SKILLS_GLOB = '.claude/skills/*/SKILL.md'

# `chemin.py:123` ou `chemin.py:123-130`
REF_LIGNE = re.compile(r'`?([\w/\\.\-]+\.(?:py|js|html|css|sh|json|md)):(\d+)')
# Lien markdown vers un .md
LIEN_MD = re.compile(r'\[[^\]]+\]\(([^)\s#]+\.md)[^)]*\)')
# `chemin/vers/fichier.py` cité en backticks, sans numéro de ligne
REF_FICHIER = re.compile(r'`([\w/\\.\-]+\.(?:py|js|html|css|sh))`')
# `WAMA_LLM.md` ou `wama/common/README.md` cité en backticks. Ajouté le 2026-08-27 : les skills
# et les docs se renvoient massivement les uns aux autres SANS lien markdown (392 réfs dans les
# docs, 47 dans les skills) — c'était l'angle mort le plus large du contrôle.
REF_MD = re.compile(r'`([\w/\\.\-]+\.md)`')

#: Documents qui sont des JOURNAUX : ils consignent ce qui était vrai À UNE DATE (§REPRISE,
#: relevés d'audit datés). Y citer un `.md` depuis archivé ou supprimé n'est pas une erreur —
#: c'est le compte rendu exact de la mesure d'alors, et le « corriger » falsifierait l'archive.
#: Vécu le 2026-08-27 : le relevé « 8 fichiers orphelins » (PROJECT_STATUS:1151) en nommait
#: quatre depuis disparus, et les réécrire aurait effacé la mesure.
#:
#: La frontière est nette et ne vaut QUE pour les renvois `.md` : un document qui n'existe plus
#: est un fait d'histoire, un CHEMIN DE CODE qui n'existe plus est une affirmation sur le code
#: d'aujourd'hui. Les références de code de ces mêmes journaux restent donc contrôlées.
JOURNAUX = {'PROJECT_STATUS.md'}

#: Convention de nommage de la mémoire Claude. Vérifié le 2026-08-27 : 134 fichiers mémoire la
#: suivent, et AUCUN `.md` du dépôt — l'exclusion ne peut donc pas masquer une vraie référence.
_MEMOIRE = re.compile(r'^(project|reference|feedback|user)_[\w\-]+\.md$')


#: La mémoire Claude (`memory/*.md`, `MEMORY.md`, et les mêmes fichiers cités SANS leur dossier)
#: vit HORS du dépôt : la citer n'est pas une référence morte. Faux positif déjà documenté dans
#: le skill `/doc-sync`. Sans cette exclusion, le contrôle .md rendait 25 alertes sur 28 dans
#: cette seule classe — et « un contrôle qui crie au loup est pire que pas de contrôle ».
def _hors_depot(chemin):
    c = chemin.replace('\\', '/')
    return (c == 'MEMORY.md' or c.startswith('memory/')
            or bool(_MEMOIRE.match(c.rsplit('/', 1)[-1])))


class Command(BaseCommand):
    help = "Vérifie que les références des docs de référence pointent sur du code qui existe."

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true',
                            help="Code de sortie 1 s'il reste des références CASSÉES.")
        parser.add_argument('--doc', help="Ne vérifier qu'un document (exclut les skills).")
        parser.add_argument('--skills', action='store_true',
                            help="Ne vérifier que `.claude/skills/*/SKILL.md`.")

    # Index nom-de-fichier → chemins, construit UNE fois. La version précédente faisait un
    # glob('**/…') par référence non résolue : 300 s sur ce dépôt (venvs inclus).
    _index = None

    def _construire_index(self, base):
        # `os.walk` avec élagage EN PLACE : `rglob` descendait quand même dans AI-models/ et
        # media/ avant de filtrer, ce qui prenait plusieurs minutes sur /mnt/d (montage lent).
        import os
        # Élagage NOMINATIF à la racine seulement : exclure tout dossier nommé « manifests »
        # aurait aussi masqué `wama/common/manifests/` — c'est le bug qui faisait passer
        # `manifests/projection.py` pour une référence morte.
        exclus_racine = {'venv_linux', 'venv_win', 'node_modules', 'staticfiles', 'AI-models',
                         'media', 'logs', 'docs', 'manifests', 'htmlcov'}
        # `.md` indexé depuis le 2026-08-27 : sans lui, un doc cité par son seul nom
        # (`CAM_ANALYZER_CHANGELOG.md`, qui vit dans `wama_lab/cam_analyzer/`) passait pour mort.
        exts = ('.py', '.js', '.html', '.css', '.sh', '.json', '.md')
        index = {}
        for racine, dossiers, fichiers in os.walk(base):
            if Path(racine) == base:
                dossiers[:] = [d for d in dossiers
                               if d not in exclus_racine and not d.startswith('.')]
            else:
                dossiers[:] = [d for d in dossiers
                               if d not in ('__pycache__', 'node_modules') and not d.startswith('.')]
            for nom in fichiers:
                if nom.endswith(exts):
                    index.setdefault(nom, []).append(Path(racine) / nom)
        return index

    def _resoudre(self, base, chemin):
        """Un chemin cité peut être relatif à la racine, ou partiel (`common/utils/x.py`)."""
        chemin = chemin.replace('\\', '/')
        for essai in (base / chemin, base / 'wama' / chemin):
            if essai.exists():
                return essai
        if self._index is None:
            self._index = self._construire_index(base)
        candidats = [t for t in self._index.get(Path(chemin).name, [])
                     if str(t).replace('\\', '/').endswith(chemin)]
        if len(candidats) == 1:
            return candidats[0]
        # Plusieurs apps ont `utils/auto_model.py`, `backends/manager.py`… La doc s'appuie sur
        # le contexte de la phrase : c'est AMBIGU, pas cassé. Un contrôle qui crie au loup est
        # pire que pas de contrôle — c'est justement le reproche de sur-confiance.
        return 'AMBIGU' if candidats else None

    def handle(self, *args, **o):
        from django.conf import settings
        base = Path(settings.BASE_DIR)
        w, s, e, warn = self.stdout.write, self.style.SUCCESS, self.style.ERROR, self.style.WARNING

        # Cibles = les .md de référence + les skills DÉCOUVERTES. `--doc` restreint aux docs ;
        # `--skills` restreint aux skills (utile après une passe sur `.claude/skills/`).
        cibles = []
        if not o.get('skills'):
            cibles += [(n, base / n) for n in ([o['doc']] if o.get('doc') else DOCS)]
        if not o.get('doc'):
            cibles += [(str(p.relative_to(base)).replace('\\', '/'), p)
                       for p in sorted(base.glob(SKILLS_GLOB))]

        casses, perimes, ambigus, verifies = [], [], [], 0

        for nom, f in cibles:
            if not f.exists():
                casses.append((nom, 0, f"document de référence ABSENT"))
                continue
            texte = f.read_text(encoding='utf-8', errors='replace')
            lignes = texte.splitlines()

            # Invariant propre aux skills : le `name:` du frontmatter DOIT valoir le nom du
            # dossier, sinon le skill ne s'invoque pas sous le nom qu'on croit. Vérifié à la
            # main le 26/08 (les 11 étaient bonnes) — donc à mécaniser, pas à re-vérifier.
            if f.name == 'SKILL.md':
                verifies += 1
                attendu = f.parent.name
                m = re.search(r'^name:\s*(.+?)\s*$', texte[:texte.find('\n---', 3) + 1
                                                          if texte.startswith('---') else 0],
                              re.M)
                if not m:
                    casses.append((nom, 1, "frontmatter sans `name:`"))
                elif m.group(1) != attendu:
                    casses.append((nom, 1, f"`name: {m.group(1)}` ≠ dossier `{attendu}`"))

            for i, ligne in enumerate(lignes, 1):
                # Une référence peut désigner un fichier VOLONTAIREMENT absent : cible d'un
                # chantier, fichier supprimé, plan remplacé, patch appliqué dans un venv.
                # Le doc le dit — parfois sur la ligne SUIVANTE (constaté sur
                # PROJECT_STATUS:1040, dont le « SUPPRIMÉ » est en 1041).
                #
                # La fenêtre était ±1 ; élargie en arrière à la PUCE ENTIÈRE le 2026-08-27. Une
                # puce qui énumère cinq documents archivés porte son « (archivés `docs/archive/`) »
                # en tête : au 5ᵉ, trois lignes plus bas, le qualificatif était hors fenêtre et le
                # contrôle criait au loup (vécu : WAMA_APP_GENERATION_ROUTE:1007). Un qualificatif
                # vaut pour l'ÉNONCÉ, pas pour la ligne physique où le retour à la ligne est tombé.
                debut = i - 1
                while debut > 0:
                    prec = lignes[debut - 1]
                    if not prec.strip() or prec.lstrip()[:1] in ('-', '*', '|', '#', '>'):
                        break
                    debut -= 1
                voisinage = ' '.join(lignes[max(0, debut - 1):i + 1]).lower()
                # 'renommé' / 'ex-`' ajoutés le 2026-08-27 avec le contrôle des `.md` : un doc
                # renommé reste cité sous son ancien nom, VOLONTAIREMENT, pour que la recherche
                # aboutisse (`PROMPT_PIPELINE.md` → `WAMA_IA_TRANSVERSE.md` → `WAMA_LLM.md`).
                # 'ex-`' porte le backtick : 'ex-' seul matcherait « exemple », « existe »…
                intentionnel = any(m in voisinage for m in (
                    'supprimé', 'supprime', 'remplacé', 'remplace par', 'à créer', 'a creer',
                    'cible :', 'cible:', 'à faire', 'archivé', 'archive', 'n\'existe',
                    'site-packages', 'venv_', 'ancien plan', '~~',
                    'renommé', 'renomme', 'ex-`'))
                if intentionnel:
                    continue
                # ── liens vers d'autres .md ────────────────────────────────
                for cible in LIEN_MD.findall(ligne):
                    if _hors_depot(cible):
                        continue
                    verifies += 1
                    if not (base / cible.replace('\\', '/')).exists():
                        casses.append((nom, i, f"lien .md mort → {cible}"))

                # ── .md cités en backticks ────────────────────────────────
                for cible in REF_MD.findall(ligne) if nom not in JOURNAUX else ():
                    if _hors_depot(cible):
                        continue
                    verifies += 1
                    r = self._resoudre(base, cible)
                    if r == 'AMBIGU':
                        ambigus.append((nom, i, cible))
                    elif r is None:
                        casses.append((nom, i, f"doc inexistant → {cible}"))

                # ── références fichier:ligne ──────────────────────────────
                for chemin, num in REF_LIGNE.findall(ligne):
                    if chemin.endswith('.md'):
                        continue
                    verifies += 1
                    cible = self._resoudre(base, chemin)
                    if cible == 'AMBIGU':
                        ambigus.append((nom, i, f"{chemin}:{num}"))
                        continue
                    if cible is None:
                        casses.append((nom, i, f"fichier inexistant → {chemin}:{num}"))
                        continue
                    try:
                        n = len(cible.read_text(encoding='utf-8', errors='replace').splitlines())
                    except Exception:
                        continue
                    if int(num) > n:
                        perimes.append((nom, i, f"{chemin}:{num} — le fichier n'a que {n} lignes"))

                # ── fichiers cités sans numéro ────────────────────────────
                for chemin in REF_FICHIER.findall(ligne):
                    if '/' not in chemin and '\\' not in chemin:
                        continue          # nom nu (ex. `models.py`) : trop ambigu
                    verifies += 1
                    r = self._resoudre(base, chemin)
                    if r == 'AMBIGU':
                        ambigus.append((nom, i, chemin))
                    elif r is None:
                        casses.append((nom, i, f"fichier inexistant → {chemin}"))

        nb_sk = sum(1 for n, _ in cibles if n.endswith('SKILL.md'))
        w(f"\n{'=' * 84}")
        w(f"INTÉGRITÉ DOCS+SKILLS → CODE  ({len(cibles) - nb_sk} documents, {nb_sk} skills, "
          f"{verifies} références vérifiées)")
        w('=' * 84)

        if casses:
            w(e(f"\nCASSÉ ({len(casses)}) — la référence ne pointe sur rien :"))
            for doc, i, msg in casses:
                w(e(f"  {doc}:{i}  {msg}"))
        if perimes:
            w(warn(f"\nPÉRIMÉ ({len(perimes)}) — le fichier existe, la ligne n'existe plus :"))
            for doc, i, msg in perimes:
                w(warn(f"  {doc}:{i}  {msg}"))
        if not casses and not perimes:
            w(s("\nAucune référence cassée ni périmée."))

        w("")
        w(f"Bilan : {len(casses)} cassée(s), {len(perimes)} périmée(s) sur {verifies} vérifiée(s).")
        if o['strict'] and casses:
            raise SystemExit(1)
