"""
doc_facts — régénère la COUCHE FACTUELLE des .md de référence (ROADMAP §16.9 ①).

La frontière est nette et NE DOIT PAS bouger :
  - reste écrit à la main : l'intention, les décisions, le pourquoi, les pièges ;
  - se génère : les chiffres et tableaux d'adoption (outils décrits, références de
    modèles résolvables, couverture du round-trip), aujourd'hui recopiés à la main
    et donc périssables — et déjà inventés une fois (« 31/42 » déduit, réel : 91/91).

Mécanisme : blocs délimités dans des .md EXISTANTS (jamais de nouveau fichier),
régénérés en place, `--check` refuse un bloc périmé. Aucun chiffre n'est plus saisi
à la main — donc plus inventable. Ne pas généraliser au-delà : un doc entièrement
généré perdrait ce qui fait sa valeur.

Marqueurs (dans le .md) :
    <!-- WAMA:FAITS(id) — généré par « python manage.py doc_facts », ne pas éditer -->
    …contenu régénéré…
    <!-- /WAMA:FAITS(id) -->

Usage :
    python manage.py doc_facts                # régénère tous les blocs en place
    python manage.py doc_facts --check        # code sortie 1 si un bloc est périmé
    python manage.py doc_facts --only outils  # un seul fait
"""
import re
from pathlib import Path

from django.core.management.base import BaseCommand


# ── Faits : chaque fonction rend le CONTENU markdown du bloc (déterministe, trié) ──

def _fait_outils():
    """Surface outils : registre, descriptions dérivées, arguments documentés."""
    from wama.tool_api import TOOL_REGISTRY, tool_descriptions
    desc = tool_descriptions()
    decrits = sum(1 for d in desc.values() if (d.get('description') or '').strip())
    args = sum(len(d.get('args') or {}) for d in desc.values())
    return (
        f"- Outils au registre (`TOOL_REGISTRY`) : **{len(TOOL_REGISTRY)}**\n"
        f"- Outils décrits (`tool_descriptions()`, dérivé) : **{decrits}/{len(desc)}**\n"
        f"- Arguments documentés (types/choix/bornes/défauts) : **{args}**"
    )


def _fait_modeles():
    """Références de modèles du corpus, résolues contre le catalogue AIModel."""
    import json
    from django.conf import settings
    from wama.model_manager.models import AIModel

    connues = set(AIModel.objects.values_list('model_key', flat=True))
    dossier = Path(settings.BASE_DIR) / 'manifests' / 'apps'
    total, resolues, pendantes = 0, 0, []
    fichiers = sorted(dossier.glob('*.json'))
    for f in fichiers:
        body = (json.loads(f.read_text(encoding='utf-8')).get('body') or {})
        for cle in ((body.get('models') or {}).get('catalog_keys') or []):
            total += 1
            if cle in connues:
                resolues += 1
            else:
                pendantes.append(f"{f.stem}:{cle}")
    lignes = [
        f"- Manifestes du corpus (`manifests/apps/`) : **{len(fichiers)}**",
        f"- Références de modèles (`body.models.catalog_keys`) : **{resolues}/{total} résolvables**"
        f" contre le catalogue `AIModel.model_key`",
    ]
    if pendantes:
        lignes.append(f"- ⚠ Pendantes : {', '.join(sorted(pendantes)[:10])}")
    return '\n'.join(lignes)


def _fait_roundtrip():
    """Tableau par app : couverture de projection, fidélité, verdict — via _roundtrip."""
    from wama.common.app_registry import APP_CATALOG
    from wama.common.management.commands.manifest_roundtrip import Command as Roundtrip
    from wama.common.sandbox import non_sandbox_apps

    rt = Roundtrip()
    lignes = ["| App | Facettes | Projetables | Fidélité | Validation |",
              "|---|---|---|---|---|"]
    # Jumelles bac à sable exclues (même règle que conformité/export — fuite mesurée 18/08).
    for app_id in non_sandbox_apps(APP_CATALOG):
        r = rt._roundtrip(app_id)
        if 'erreur' in r:
            lignes.append(f"| {app_id} | — | — | — | {r['erreur']} |")
            continue
        fid = '✅ aucun écart' if not r['ecarts_fidelite'] else f"❌ {len(r['ecarts_fidelite'])} écart(s)"
        val = '✅ OK' if not r['erreurs_validation'] else f"❌ {len(r['erreurs_validation'])} erreur(s)"
        lignes.append(f"| {app_id} | {len(r['facettes_extraites'])} "
                      f"| {r['couverture_projection']} | {fid} | {val} |")
    return '\n'.join(lignes)


#: Dossiers jamais parcourus pour compter les consommateurs (mêmes exclusions d'esprit que
#: `check_redundancy`) : code vendored, artefacts, et l'arbre de dépendances. Sans cet élagage
#: le comptage part sur des dizaines de milliers de fichiers — la leçon `/mnt/d` de `check_docs`.
_DOSSIERS_EXCLUS = {
    'venv_win', 'venv_linux', 'node_modules', '.git', 'migrations', 'staticfiles',
    'static', 'media', 'logs', 'AI-models', '__pycache__', 'wama-dev-ai', 'patches',
    'musetalk', 'codeformer',   # vendored upstream
}


def _modules_python(base):
    """Chemins .py de NOTRE code (relatifs à base), vendored et artefacts élagués."""
    import os

    for racine in ('wama', 'wama_lab'):
        depart = base / racine
        if not depart.is_dir():
            continue
        for dossier, sous, fichiers in os.walk(depart):
            sous[:] = [d for d in sous if d not in _DOSSIERS_EXCLUS]
            for f in fichiers:
                if f.endswith('.py'):
                    yield Path(dossier, f).relative_to(base).as_posix()


def _sources_front(base):
    """Chemins .html/.js de NOTRE front (templates + static d'app), relatifs à base.

    Corpus des CONSOMMATEURS des briques front (js/partials déclarés au registre) : une brique
    est consommée par la balise <script>/l'include qui la référence, pas par un import Python.
    `staticfiles/` (copies collectées) reste élagué — compter une copie mentirait — et
    `vendors/` (libs tierces vendorées) aussi ; `static` est réadmis, c'est là que vit le front.
    """
    import os

    exclus = (_DOSSIERS_EXCLUS - {'static'}) | {'vendors'}
    for racine in ('wama', 'wama_lab'):
        depart = base / racine
        if not depart.is_dir():
            continue
        for dossier, sous, fichiers in os.walk(depart):
            sous[:] = [d for d in sous if d not in exclus]
            for f in fichiers:
                if f.endswith(('.html', '.js')):
                    yield Path(dossier, f).relative_to(base).as_posix()


def _fait_mecanismes():
    """
    Carte des mécanismes transversaux + les trois formes d'oubli.

    Le registre (`common/mecanismes.py`) est la SOURCE ; ce bloc n'en est que le rendu. On
    compte les consommateurs par l'IMPORT du module — un mécanisme que personne n'importe est
    une brique morte, et c'est le cas qu'on veut voir sans avoir à le chercher à la main.
    """
    import re
    from django.conf import settings

    from wama.common.mecanismes import ASSUMES_LOCAUX, MECANISMES

    base = Path(settings.BASE_DIR)
    # Balayage d'adoption : la logique vivait ICI en closure, elle a un 2ᵉ consommateur depuis
    # le 19/08 (contrôle de jonction mécanismes↔grille) → extraite dans le commun plutôt que
    # dupliquée. Le rendu ci-dessous est INCHANGÉ (fidélité vérifiée par `doc_facts --check`).
    # ⚠ Forme d'import IMPORTANTE : `from wama.common.services.mecanismes_scan import …`.
    # Le détecteur de consommateurs cherche `from <module> import` / `import <module>` — la
    # forme `from wama.common.services import mecanismes_scan` lui ÉCHAPPE, et le module
    # apparaissait « sans consommateur » alors que cette ligne l'utilise (mesuré 19/08).
    from wama.common.services.mecanismes_scan import (charger_sources, consommateurs,
                                                      criteres_orphelins,
                                                      mecanismes_sans_critere, modules_python)

    modules = list(modules_python(base))
    sources = charger_sources(base)

    def _consommateurs(mecanisme):
        return consommateurs(mecanisme, sources)

    # Une sous-table par DOMAINE (ordre du registre) : un tableau unique de 60+ lignes ne se
    # lit pas — demande Fabien du 2026-08-13 en intégrant la couche UI générée.
    lignes = []
    orphelins = []
    absents = []
    domaines = []
    for m in MECANISMES:
        if m.domaine not in domaines:
            domaines.append(m.domaine)
    for dom in domaines:
        du_domaine = sorted((m for m in MECANISMES if m.domaine == dom), key=lambda x: x.nom)
        lignes.append(f"\n#### {dom or 'Sans domaine'} ({len(du_domaine)})\n")
        lignes.append("| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |")
        lignes.append("|---|---|---|---|---|")
        for m in du_domaine:
            existe = (base / m.domicile).exists()
            if not existe:
                absents.append(f"{m.cle} → {m.domicile}")
            conso = _consommateurs(m) if existe else []
            if existe and not conso:
                orphelins.append(f"`{m.cle}` ({m.domicile})")
            doc = f"`{m.doc}`" if m.doc else "—"
            etat = str(len(conso)) if conso else ("⚠ **0**" if existe else "❌ absent")
            lignes.append(f"| **{m.nom}** | {m.role} | `{m.domicile}` | {doc} | {etat} |")

    # Modules de `common/` non rattachés : la réponse mécanique à « qu'ai-je oublié de tracer ».
    # ASSUMES_LOCAUX en est soustrait (assumer est un acte DÉCLARÉ avec raison, pas un oubli) —
    # sans cette soustraction la liste ne pouvait jamais converger et cessait d'être lue (45
    # noms au 2026-08-13). Deux gardes d'honnêteté : un module à la fois assumé ET déclaré est
    # une contradiction ; un assumé dont le fichier a disparu est une entrée périmée.
    declares = {m.domicile for m in MECANISMES} | {a for m in MECANISMES for a in m.annexes}
    # `wama/common/backends/` ajouté le 2026-08-13 : il manquait, et c'est ce qui a rendu
    # INVISIBLE de la carte la brique qui ALIMENTE tout le suivi des modèles
    # (`BaseModelBackend` et ses trois enveloppes). Un dossier hors balayage ne produit
    # aucun signal — ni « non rattaché », ni rien : le trou était silencieux.
    # `wama/common/static/common/js/` ajouté le 2026-08-19 — MÊME leçon, côté FRONT cette fois :
    # le balayage ne regardait que des dossiers Python, donc 4 briques communes vivaient hors
    # carte sans le moindre signal, dont les DEUX du transport (`wama-audio-player.js`,
    # `wama-shuttle.js`). Une brique front invisible de la carte l'est aussi de la jonction avec
    # la grille : personne ne pouvait voir qu'aucun critère ne les vérifiait.
    dossiers_balayes = ('wama/common/services/', 'wama/common/utils/',
                        'wama/common/backends/',
                        'wama/common/static/common/js/',
                        'wama/model_manager/services/', 'wama/studio/services/')
    # `modules` ne contient que du .py : le front est balayé à part (mêmes exclusions).
    balayables = list(modules) + [rel for rel in sources
                                  if rel.startswith('wama/common/static/common/js/')]
    candidats = sorted(
        rel for rel in balayables
        if rel.startswith(dossiers_balayes)
        and not rel.endswith('__init__.py') and rel not in declares
        and rel not in ASSUMES_LOCAUX
    )
    contradictions = sorted(set(ASSUMES_LOCAUX) & declares)
    assumes_perimes = sorted(p for p in ASSUMES_LOCAUX if not (base / p).exists())

    lignes.append("")
    _trous = mecanismes_sans_critere(sources)
    lignes.append(f"**Mécanismes déclarés : {len(MECANISMES)}** · "
                  f"domiciles absents : {len(absents)} · sans consommateur : {len(orphelins)} · "
                  f"assumés locaux : {len(ASSUMES_LOCAUX)} · "
                  f"modules balayés non rattachés : {len(candidats)} · "
                  f"**de niveau app sans critère de grille : {len(_trous)}**")
    if contradictions:
        lignes.append(f"- ❌ **Assumé ET déclaré** (contradiction, retirer d'un des deux) : "
                      + ', '.join(f"`{c}`" for c in contradictions))
    if assumes_perimes:
        lignes.append(f"- ❌ **Assumé dont le fichier a disparu** (entrée périmée d'ASSUMES_LOCAUX) : "
                      + ', '.join(f"`{c}`" for c in assumes_perimes))
    if absents:
        lignes.append(f"- ❌ **Domicile introuvable** : {', '.join(absents)}")
    if orphelins:
        lignes.append(f"- ⚠ **Sans consommateur** (brique morte ou pas encore adoptée) : "
                      f"{', '.join(orphelins)}")

    # 4ᵉ FORME D'OUBLI (jonction mécanismes↔grille, décision Fabien 19/08) : un mécanisme
    # ADOPTÉ PAR DES APPS que la grille de conformité ne vérifie nulle part. C'est le trou qui
    # laisse une app sortir à 100 % sans avoir adopté la brique — mesuré sur `card_gear`,
    # annoncé « porté aux 9 apps » alors que 8 l'exposent et que transcriber/anonymizer
    # écrivent encore leurs data-* à la main. Les mécanismes d'INFRASTRUCTURE (aucune app ne
    # les consomme : bench, mirror_sync, retention…) en sont exclus mécaniquement — un critère
    # par app n'y aurait aucun sens ; c'est ce qui remplace un seuil arbitraire.
    trous_grille = mecanismes_sans_critere(sources)
    orphelins_liaison = criteres_orphelins()
    if orphelins_liaison:
        lignes.append(f"- ❌ **Liaison de critère cassée** (clé absente du registre — la "
                      f"jonction est inerte) : "
                      + ', '.join(f"`{c}`" for c in orphelins_liaison))
    if trous_grille:
        lignes.append(f"\n<details><summary>⚠ <b>{len(trous_grille)} mécanisme(s) de niveau "
                      f"app SANS critère de grille</b> — adoptés par des apps, vérifiés par "
                      f"aucun critère (<code>Criterion.mecanisme</code>) : une app peut sortir "
                      f"à 100 % sans les avoir adoptés</summary>\n")
        lignes.append("| Mécanisme | Adopté par | Domicile |")
        lignes.append("|---|---|---|")
        for m, apps in trous_grille:
            lignes.append(f"| `{m.cle}` — {m.nom} | **{len(apps)}** app(s) : "
                          f"{', '.join(apps)} | `{m.domicile}` |")
        lignes.append("\n</details>")
    if candidats:
        # Rendu en liste par dossier plutôt qu'en paragraphe : c'est un BACKLOG à traiter, pas
        # une note de bas de page. Un mur de 54 noms ne se lit pas et ne se traite donc jamais.
        lignes.append(f"\n<details><summary>⚠ <b>{len(candidats)} module(s) balayé(s) "
                      f"non rattachés au registre</b> — à déclarer dans "
                      f"<code>wama/common/mecanismes.py</code>, ou à assumer comme utilitaires "
                      f"locaux (tout n'est pas un mécanisme transversal)</summary>\n")
        for dossier in dossiers_balayes:
            noms = [c.split('/')[-1] for c in candidats if c.startswith(dossier)]
            if noms:
                lignes.append(f"\n`{dossier}` ({len(noms)}) — "
                              + ' · '.join(f"`{n}`" for n in noms))
        lignes.append("\n</details>")
    if ASSUMES_LOCAUX:
        lignes.append(f"\n<details><summary>Assumés utilitaires locaux : "
                      f"{len(ASSUMES_LOCAUX)} (chacun avec sa raison — "
                      f"<code>ASSUMES_LOCAUX</code>, wama/common/mecanismes.py)</summary>\n")
        for chemin, raison in sorted(ASSUMES_LOCAUX.items()):
            lignes.append(f"- `{chemin.split('/')[-1]}` — {raison}")
        lignes.append("\n</details>")
    return '\n'.join(lignes)


# fait → (fichier de référence, fonction). Un fait vit dans UN doc (un domaine = un fichier).
FAITS = {
    'outils': ('WAMA_APP_GENERATION_ROUTE.md', _fait_outils),
    'modeles': ('WAMA_MANIFEST_SPEC.md', _fait_modeles),
    'roundtrip': ('WAMA_MANIFEST_ARCHITECTURE.md', _fait_roundtrip),
    'mecanismes': ('WAMA_MECANISMES.md', _fait_mecanismes),
}

OUVRANT = "<!-- WAMA:FAITS({fid}) — généré par « python manage.py doc_facts », ne pas éditer -->"
FERMANT = "<!-- /WAMA:FAITS({fid}) -->"


class Command(BaseCommand):
    help = "Régénère les blocs de faits mesurés des .md de référence (§16.9 ①)."

    def add_arguments(self, parser):
        parser.add_argument('--check', action='store_true',
                            help="Ne rien écrire ; code sortie 1 si un bloc est périmé/absent.")
        parser.add_argument('--only', choices=sorted(FAITS),
                            help="Ne traiter que ce fait.")

    def handle(self, *args, **o):
        from django.conf import settings
        racine = Path(settings.BASE_DIR)
        perimes = []

        for fid, (fichier, calcule) in sorted(FAITS.items()):
            if o['only'] and fid != o['only']:
                continue
            chemin = racine / fichier
            texte = chemin.read_text(encoding='utf-8')
            ouvrant, fermant = OUVRANT.format(fid=fid), FERMANT.format(fid=fid)
            motif = re.compile(re.escape(ouvrant) + r"\n(.*?)" + re.escape(fermant), re.S)
            m = motif.search(texte)
            if not m:
                perimes.append((fid, fichier, "marqueurs absents"))
                self.stdout.write(self.style.ERROR(
                    f"{fid}: marqueurs absents de {fichier} — poser "
                    f"« {ouvrant} » / « {fermant} » à l'endroit choisi."))
                continue

            frais = calcule().strip()
            courant = m.group(1).strip()
            if courant == frais:
                self.stdout.write(self.style.SUCCESS(f"{fid}: à jour ({fichier})"))
                continue
            if o['check']:
                perimes.append((fid, fichier, "bloc périmé"))
                self.stdout.write(self.style.ERROR(f"{fid}: PÉRIMÉ ({fichier})"))
                continue
            chemin.write_text(motif.sub(f"{ouvrant}\n{frais}\n{fermant}", texte, count=1),
                              encoding='utf-8')
            self.stdout.write(self.style.WARNING(f"{fid}: régénéré ({fichier})"))

        if perimes:
            self.stdout.write(f"\n{len(perimes)} bloc(s) à régénérer : python manage.py doc_facts")
            if o['check']:
                raise SystemExit(1)
