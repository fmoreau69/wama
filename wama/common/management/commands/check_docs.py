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
"""
import re
from pathlib import Path

from django.core.management.base import BaseCommand

# Docs de référence (CLAUDE.md : « un domaine = un fichier »).
DOCS = [
    'WAMA_APP_GENERATION_ROUTE.md', 'WAMA_APP_CONVENTIONS.md', 'WAMA_MANIFEST_SPEC.md',
    'WAMA_MANIFEST_ARCHITECTURE.md', 'PROJECT_STATUS.md', 'ROADMAP.md', 'WAMA_IA_TRANSVERSE.md',
    'CLAUDE.md', 'STUDIO_VISION.md', 'TRANSCRIBER_REFERENCE_AUDIT.md',
    # Carte des mécanismes transversaux : sa TABLE est générée (doc_facts, fait `mecanismes`)
    # et donc ingénérable, mais ses chemins écrits à la main — l'intro, les documents de
    # référence — méritent le même contrôle que les autres. Ajoutée le 2026-08-13.
    'WAMA_MECANISMES.md',
]

# `chemin.py:123` ou `chemin.py:123-130`
REF_LIGNE = re.compile(r'`?([\w/\\.\-]+\.(?:py|js|html|css|sh|json|md)):(\d+)')
# Lien markdown vers un .md
LIEN_MD = re.compile(r'\[[^\]]+\]\(([^)\s#]+\.md)[^)]*\)')
# `chemin/vers/fichier.py` cité en backticks, sans numéro de ligne
REF_FICHIER = re.compile(r'`([\w/\\.\-]+\.(?:py|js|html|css|sh))`')


class Command(BaseCommand):
    help = "Vérifie que les références des docs de référence pointent sur du code qui existe."

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true',
                            help="Code de sortie 1 s'il reste des références CASSÉES.")
        parser.add_argument('--doc', help="Ne vérifier qu'un document.")

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
        exts = ('.py', '.js', '.html', '.css', '.sh', '.json')
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

        docs = [o['doc']] if o.get('doc') else DOCS
        casses, perimes, ambigus, verifies = [], [], [], 0

        for nom in docs:
            f = base / nom
            if not f.exists():
                casses.append((nom, 0, f"document de référence ABSENT"))
                continue
            texte = f.read_text(encoding='utf-8', errors='replace')
            lignes = texte.splitlines()

            for i, ligne in enumerate(lignes, 1):
                # Une référence peut désigner un fichier VOLONTAIREMENT absent : cible d'un
                # chantier, fichier supprimé, plan remplacé, patch appliqué dans un venv.
                # Le doc le dit — parfois sur la ligne SUIVANTE (constaté sur
                # PROJECT_STATUS:1040, dont le « SUPPRIMÉ » est en 1041). Fenêtre ±1.
                voisinage = ' '.join(lignes[max(0, i - 2):i + 1]).lower()
                intentionnel = any(m in voisinage for m in (
                    'supprimé', 'supprime', 'remplacé', 'remplace par', 'à créer', 'a creer',
                    'cible :', 'cible:', 'à faire', 'archivé', 'archive', 'n\'existe',
                    'site-packages', 'venv_', 'ancien plan', '~~'))
                if intentionnel:
                    continue
                # ── liens vers d'autres .md ────────────────────────────────
                for cible in LIEN_MD.findall(ligne):
                    verifies += 1
                    if not (base / cible.replace('\\', '/')).exists():
                        casses.append((nom, i, f"lien .md mort → {cible}"))

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

        w(f"\n{'=' * 84}")
        w(f"INTÉGRITÉ DOCS → CODE  ({len(docs)} documents, {verifies} références vérifiées)")
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
