"""
Intégrité des gabarits Django — le piège du commentaire `{# … #}` MULTI-LIGNE.

  python manage.py check_templates            # rapport
  python manage.py check_templates --strict   # sortie 1 s'il reste un défaut
  python manage.py check_templates --json     # rapport machine

POURQUOI CETTE COMMANDE EXISTE (écrite le 2026-08-27, après SEPT récidives)
--------------------------------------------------------------------------
Le lexer de Django (`tag_re`) n'a pas `re.DOTALL` : un commentaire `{# … #}` étalé sur PLUSIEURS
lignes n'est **pas supprimé**. Il est rendu comme un **nœud texte littéral** dans le DOM. Les
dégâts constatés, tous diagnostiqués à un coût sans rapport avec la faute :

  · 2026-06-27  dans une piste `overflow:hidden` de 3 px → la barre de progression globale
                poussée hors de la zone clippée. Cassait `_global_progress.html`, donc 8 apps.
  · 2026-07-26  le commentaire contenait la chaîne `<template>` → élément jamais fermé qui a
                avalé les ~30 `<script>` du document. « Toutes les apps bloquées », console VIDE.
  · 2026-08-01  posé dans un conteneur `display:grid` → boîte anonyme de grille = LIGNE FANTÔME,
                +168 px de vide sur chaque card. Texte invisible : seule la géométrie trahissait.

La règle (« multi-ligne → `{% comment %}` ») est écrite depuis la 1ʳᵉ fois, et le réflexe de scan
depuis la 4ᵉ. Il y a eu trois récidives DE PLUS après. C'est la leçon du dépôt : une règle qui
demande de se souvenir n'est pas un contrôle. Le scan coûte 5 s ; les diagnostics ont coûté des
sessions entières.

CE QUE LA COMMANDE VÉRIFIE
--------------------------
1. `{# … #}` sur plusieurs lignes           → défaut FRANC (rendu comme du texte).
2. nom de balise HTML dans un `{# … #}`     → défaut FRANC même en mono-ligne : un reformatage
                                              ultérieur le rend dangereux (cas du 26/07).
3. `{#` sans `#}` sur la même ligne         → même famille, attrapé par 1 mais signalé à part
                                              quand le `#}` manque tout court.

CE QU'ELLE NE VÉRIFIE PAS : la syntaxe des gabarits en général (c'est le travail de Django), ni
le rendu. Elle attrape UNE famille de fautes, celle qui a récidivé sept fois.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

#: Racines scannées — les trois mondes. Une racine ABSENTE est ignorée en silence : le contrôle
#: ne doit pas rougir parce qu'un monde n'existe pas encore sur cette machine.
RACINES = ('wama', 'wama_lab', 'wama_data')

#: `re.DOTALL` ici est VOLONTAIRE et c'est tout le sujet : on cherche exactement ce que le lexer
#: de Django, lui, ne voit pas.
COMMENTAIRE = re.compile(r'\{#.*?#\}', re.DOTALL)

#: Ouverture sans fermeture sur la même ligne et sans `#}` du tout ensuite.
OUVERTURE_SEULE = re.compile(r'\{#(?!.*#\})', re.MULTILINE)

#: Noms de balises dont la présence dans un commentaire a déjà cassé une page. Volontairement
#: COURTE : elle liste les balises qui avalent du contenu quand elles restent ouvertes, pas
#: toutes les balises HTML — une liste exhaustive ferait rougir tous les commentaires de doc.
BALISES_AVALEUSES = ('template', 'script', 'style', 'textarea', 'iframe', 'noscript')
BALISE = re.compile(r'<\s*/?\s*(' + '|'.join(BALISES_AVALEUSES) + r')\b', re.IGNORECASE)


def _gabarits(base):
    """Tous les .html des trois mondes. `staticfiles/` est exclu : c'est une COPIE générée."""
    vus = []
    for racine in RACINES:
        dossier = Path(base) / racine
        if not dossier.is_dir():
            continue
        vus.extend(p for p in dossier.rglob('*.html')
                   if 'staticfiles' not in p.parts and 'node_modules' not in p.parts)
    return sorted(vus)


def scanner(base=None):
    """Renvoie la liste des défauts : [{fichier, ligne, genre, extrait}]."""
    base = base or settings.BASE_DIR
    defauts = []
    for chemin in _gabarits(base):
        try:
            texte = chemin.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as exc:
            defauts.append({'fichier': str(chemin), 'ligne': 0, 'genre': 'illisible',
                            'extrait': str(exc)})
            continue
        rel = str(chemin.relative_to(base)).replace('\\', '/')
        for m in COMMENTAIRE.finditer(texte):
            ligne = texte[:m.start()].count('\n') + 1
            corps = m.group(0)
            if '\n' in corps:
                defauts.append({'fichier': rel, 'ligne': ligne, 'genre': 'multi-ligne',
                                'extrait': corps[:70].replace('\n', ' ⏎ ')})
            balise = BALISE.search(corps)
            if balise:
                defauts.append({'fichier': rel, 'ligne': ligne, 'genre': 'balise-avaleuse',
                                'extrait': f"<{balise.group(1)}> dans un commentaire"})
        # Un `{#` qui ne se referme JAMAIS : la regex ci-dessus ne peut pas le voir.
        for m in OUVERTURE_SEULE.finditer(texte):
            if '#}' in texte[m.start():]:
                continue          # il se referme plus loin → déjà traité comme multi-ligne
            defauts.append({'fichier': rel, 'ligne': texte[:m.start()].count('\n') + 1,
                            'genre': 'jamais-refermé',
                            'extrait': texte[m.start():m.start() + 60].split('\n')[0]})
    return defauts


class Command(BaseCommand):
    help = ("Signale les commentaires de gabarit `{# … #}` multi-lignes (rendus comme du texte) "
            "et les noms de balises avaleuses écrits dans un commentaire.")

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true',
                            help="Sortie 1 si au moins un défaut (usage CI / nocturne).")
        parser.add_argument('--json', action='store_true', help="Rapport machine.")

    def handle(self, *args, **opts):
        base = Path(settings.BASE_DIR)
        defauts = scanner(base)
        total = len(_gabarits(base))

        if opts['json']:
            self.stdout.write(json.dumps({'gabarits': total, 'defauts': defauts},
                                         ensure_ascii=False, indent=2))
        else:
            self.stdout.write(f"INTÉGRITÉ DES GABARITS  ({total} fichiers .html)")
            if not defauts:
                self.stdout.write(self.style.SUCCESS(
                    "Aucun commentaire de gabarit dangereux."))
            else:
                self.stdout.write(self.style.ERROR(f"\nDÉFAUT ({len(defauts)}) :"))
                for d in defauts:
                    self.stdout.write(
                        f"  {d['fichier']}:{d['ligne']}  [{d['genre']}]  {d['extrait']}")
                self.stdout.write(
                    "\nRemède : `{% comment %} … {% endcomment %}` pour tout commentaire de plus "
                    "d'une ligne ; jamais de nom de balise dans un `{# … #}`.")
            self.stdout.write(f"\nBilan : {len(defauts)} défaut(s) sur {total} gabarit(s)")

        if opts['strict'] and defauts:
            raise SystemExit(1)
