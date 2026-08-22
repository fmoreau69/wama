"""
Déclaration du VOLET DROIT par la page — `WAMA_VOLETS.md §8 n°2`.

LE PROBLÈME. `base.html` rend les trois sections (Médias, Paramètres, Actions) pour TOUTE page
qui l'étend. Mesuré le 2026-08-22 : sur 35 pages, **17 n'en déclarent aucune** et héritent donc
de **51 cadres vides** — « Médias / Sélectionnez un fichier pour l'aperçu » sur la page de
connexion, « Actions » sans une seule action sur la matrice d'accès. Le volet y est un décor.

LE PRINCIPE. Une page DÉCLARE son volet ; sans déclaration, elle garde les trois sections.
Le défaut est donc l'état d'AVANT : les 10 apps n'ont rien à écrire et ne changent pas d'un
pixel (c'est la contrainte n°1 du chantier). Seules les pages transversales déclarent, et ce
qu'elles déclarent est un RETRAIT.

POURQUOI UN DICT COMPLET, ET PAS `{% if volet.medias %}` SUR UN DICT PARTIEL. Une variable
absente vaut « faux » dans un `{% if %}` Django : un dict partiel masquerait donc les sections
non citées, exactement l'inverse du défaut voulu. Deux issues : un filtre maison
(`volet|section:'medias'`) ou un dict TOUJOURS complet. On prend le second — `_filter_bar.html`
a tranché la même question dans le même sens (« en ajouter un pour ça seul serait un mécanisme
de plus à connaître »). Le context processor `volet_defaut` garantit le dict complet ; une vue
qui déclare le remplace en entier, et `volet()` le construit pour elle.

USAGE (dans la vue) ::

    from wama.common.utils.volet import volet, VOLET_AUCUN

    context['volet'] = VOLET_AUCUN                       # page sans volet du tout
    context['volet'] = volet(medias=False)               # garde Paramètres + Actions
    context['volet'] = volet(tete=True, medias=False,    # accueil : avatar seul en tête
                             parametres=False, actions=False)

⚠ `tete` n'est PAS une section : c'est le bloc libre `right_panel_top`, sans cadre ni titre.
Il faut le déclarer parce qu'un gabarit ne peut pas dire s'il est vide, et qu'un volet réduit à
ce seul bloc doit rester rendu (cas de `home.html` et de son avatar).
"""
from __future__ import annotations

# Clés = ce que `base.html` sait rendre. `actif` est DÉRIVÉE, jamais écrite à la main.
SECTIONS = ('tete', 'medias', 'parametres', 'actions')


def volet(*, tete: bool = False, medias: bool = True,
          parametres: bool = True, actions: bool = True) -> dict:
    """Déclaration de volet, toujours COMPLÈTE (cf. le pourquoi dans l'en-tête du module)."""
    d = {'tete': bool(tete), 'medias': bool(medias),
         'parametres': bool(parametres), 'actions': bool(actions)}
    # `actif` : le volet a-t-il quoi que ce soit à montrer ? Sinon `base.html` ne rend PAS
    # l'`<aside>` — et le corps récupère la largeur que le CSS lui réservait (classe
    # `wama-sans-volet`). Sans ce dernier point, retirer les cadres laisserait une bande
    # vide de 360 px : on aurait déplacé le décor au lieu de l'enlever.
    d['actif'] = any(d[k] for k in SECTIONS)
    return d


#: Défaut HISTORIQUE — les trois sections, aucun bloc de tête. C'est ce que rend une page qui
#: ne déclare rien, donc l'état d'avant le 2026-08-22 pour les 35 pages.
VOLET_DEFAUT = volet()

#: Aucun volet : ni sections, ni bloc de tête. Pour les pages où il n'a jamais rien porté.
VOLET_AUCUN = volet(medias=False, parametres=False, actions=False)
