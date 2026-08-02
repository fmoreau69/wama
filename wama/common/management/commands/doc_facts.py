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

    rt = Roundtrip()
    lignes = ["| App | Facettes | Projetables | Fidélité | Validation |",
              "|---|---|---|---|---|"]
    for app_id in sorted(APP_CATALOG):
        r = rt._roundtrip(app_id)
        if 'erreur' in r:
            lignes.append(f"| {app_id} | — | — | — | {r['erreur']} |")
            continue
        fid = '✅ aucun écart' if not r['ecarts_fidelite'] else f"❌ {len(r['ecarts_fidelite'])} écart(s)"
        val = '✅ OK' if not r['erreurs_validation'] else f"❌ {len(r['erreurs_validation'])} erreur(s)"
        lignes.append(f"| {app_id} | {len(r['facettes_extraites'])} "
                      f"| {r['couverture_projection']} | {fid} | {val} |")
    return '\n'.join(lignes)


# fait → (fichier de référence, fonction). Un fait vit dans UN doc (un domaine = un fichier).
FAITS = {
    'outils': ('WAMA_APP_GENERATION_ROUTE.md', _fait_outils),
    'modeles': ('WAMA_MANIFEST_SPEC.md', _fait_modeles),
    'roundtrip': ('WAMA_MANIFEST_ARCHITECTURE.md', _fait_roundtrip),
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
