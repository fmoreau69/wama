"""
Audit des licences — VUE DÉRIVÉE sur les registres, jamais un registre de plus.

POURQUOI DÉRIVÉE. Les licences vivent déjà dans quatre registres (`AIModel`, `Library`,
`UserAsset`, `SystemAsset`) et dans la couche manifeste. Un « catalogue des licences » qui
STOCKERAIT sa propre copie deviendrait un cinquième registre à tenir à jour, qui divergerait des
autres — la maladie que la règle « un domaine, une source » combat ailleurs dans WAMA. Ce module
ne fait donc que LIRE et RECOUPER ; il n'a aucune écriture.

CE QU'IL RÉPOND, et qui n'était répondable nulle part avant le 2026-08-12 :
  • quelle est la clause la plus contraignante de tout ce que WAMA embarque ;
  • en publiant un résultat de l'app X, quelles licences ai-je traversées (app → modèles →
    librairies, via les `requires` des manifestes d'app) ;
  • qu'est-ce qui est non commercial ;
  • qu'est-ce que je dois citer — d'où l'insistance sur `author`, sans lequel une licence à
    attribution est une obligation qu'on ne peut pas tenir.

DEUX PARTIS PRIS, explicites parce qu'ils sont discutables.
  1. `inconnue` est classée PLUS contraignante que « non commerciale », pas moins. Une licence
     qu'on n'a pas établie ne permet rien tant qu'on ne l'a pas lue : la traiter comme neutre
     ferait passer un trou d'inventaire pour un feu vert.
  2. `other` (valeur rendue telle quelle par HuggingFace pour les licences maison — FLUX, LTX,
     Hunyuan…) est classée « à qualifier », pas « permissive ». Elle DOIT être ouverte à la main.
"""
from __future__ import annotations

import re
from collections import defaultdict

#: Familles, de la plus permissive à la plus contraignante. `rang` sert au « moins permissif ».
#: INTERDITE dépasse INCONNUE : une licence LUE qui ne concède aucun droit sur notre territoire
#: (cas Hunyuan : « excluding the territory of the European Union ») interdit plus sûrement
#: qu'une licence non lue — le trou d'inventaire laisse au moins l'espoir d'un feu vert.
PERMISSIVE, COPYLEFT_FAIBLE, COPYLEFT_FORT, NON_COMMERCIAL, A_QUALIFIER, INCONNUE, INTERDITE = range(7)

FAMILLES = {
    PERMISSIVE:       ('Permissive', 'Usage libre, y compris commercial.'),
    COPYLEFT_FAIBLE:  ('Copyleft faible', 'Redistribution des modifications de la brique elle-même.'),
    COPYLEFT_FORT:    ('Copyleft fort', 'Contamine l’œuvre dérivée ; AGPL couvre l’usage en réseau.'),
    NON_COMMERCIAL:   ('Non commerciale', 'Recherche et enseignement seulement.'),
    A_QUALIFIER:      ('À qualifier', 'Licence maison — à lire une par une.'),
    INCONNUE:         ('Inconnue', 'Non établie : ne permet rien tant qu’elle n’est pas lue.'),
    INTERDITE:        ('Interdite (territoire)', 'Lue : aucun droit concédé dans l’UE — ne pas utiliser.'),
}

#: Identifiant normalisé → (famille, exige une attribution).
#: Table de DOMAINE (ce qu'une licence permet) : elle ne se dérive d'aucune donnée du dépôt,
#: contrairement aux listes de classes ou de spécialités qu'on a supprimées ailleurs.
_CATALOGUE = {
    'mit':                    (PERMISSIVE, True),
    'apache-2.0':             (PERMISSIVE, True),
    'bsd-3-clause':           (PERMISSIVE, True),
    'bsd-2-clause':           (PERMISSIVE, True),
    'bsd':                    (PERMISSIVE, True),
    'isc':                    (PERMISSIVE, True),
    'cc0-1.0':                (PERMISSIVE, False),
    'unlicense':              (PERMISSIVE, False),
    'etalab-2.0':             (PERMISSIVE, True),
    'openrail++':             (PERMISSIVE, True),
    'creativeml-openrail-m':  (PERMISSIVE, True),
    'mpl-2.0':                (COPYLEFT_FAIBLE, True),
    'lgpl-3.0':               (COPYLEFT_FAIBLE, True),
    'lgpl-2.1':               (COPYLEFT_FAIBLE, True),
    'gpl-3.0':                (COPYLEFT_FORT, True),
    'gpl-2.0':                (COPYLEFT_FORT, True),
    'agpl-3.0':               (COPYLEFT_FORT, True),
    'cc-by-4.0':              (PERMISSIVE, True),
    'cc-by-sa-4.0':           (COPYLEFT_FAIBLE, True),
    'cc-by-nc-4.0':           (NON_COMMERCIAL, True),
    'cc-by-nc-sa-4.0':        (NON_COMMERCIAL, True),
    'cc-by-nc-nd-4.0':        (NON_COMMERCIAL, True),
    'apple-amlr':             (NON_COMMERCIAL, True),
    'other':                  (A_QUALIFIER, True),
    # ── Licences maison QUALIFIÉES (lues une par une le 2026-08-21, textes éditeur) ──────────
    # Le classement « permissive » des community licenses suit le précédent OpenRAIL déjà dans
    # cette table : des restrictions d'usage existent, mais recherche ET commercial sont permis
    # à l'échelle d'un labo. Le détail (plafonds, attribution) se lit sur la page liée (`url`).
    'gemma-terms':            (PERMISSIVE, True),      # Gemma Terms of Use (Gemma ≤3) — usage policy Google
    'sam-license':            (PERMISSIVE, True),      # SAM License (Meta, SAM3) — pas de clause NC
    'higgs-community':        (PERMISSIVE, True),      # Boson Higgs Audio 2 — commercial < 100k utilisateurs/an
    'ltxv-open-weights':      (PERMISSIVE, True),      # LTXV Open Weights — gratuit < 10 M$ de CA annuel
    'cpml-1.0':               (NON_COMMERCIAL, True),  # Coqui Public Model License — NC strict (Coqui dissoute)
    'flux-1-dev-non-commercial': (NON_COMMERCIAL, True),  # FLUX.1 [dev] NC — les SORTIES restent libres
    'cogvideox-license':      (NON_COMMERCIAL, True),  # CogVideoX — recherche libre ; commercial = enregistrement
    'hunyuan-community':      (INTERDITE, True),       # Tencent Hunyuan — « excluding … European Union »
}

#: Graphies rencontrées en amont → identifiant normalisé. PyPI rend du texte libre
#: (« Apache 2.0 License », « BSD 3-Clause License »), HuggingFace du SPDX minuscule : sans
#: ce recoupement la même licence comptait deux fois dans la synthèse.
_ALIAS = {
    'apache 2.0': 'apache-2.0', 'apache-2': 'apache-2.0', 'apache': 'apache-2.0',
    'apache software license': 'apache-2.0',
    'bsd 3-clause': 'bsd-3-clause', 'bsd-3': 'bsd-3-clause', 'bsd license': 'bsd',
    'mit license': 'mit', 'the mit license': 'mit',
    'gnu general public license v3': 'gpl-3.0',
    'gnu affero general public license v3': 'agpl-3.0', 'agpl': 'agpl-3.0', 'agpl-3': 'agpl-3.0',
    'cc0': 'cc0-1.0', 'cc-by-nc': 'cc-by-nc-4.0', 'cc-by': 'cc-by-4.0',
    'etalab': 'etalab-2.0', 'licence ouverte': 'etalab-2.0',
    'isc license': 'isc',
}


def normaliser_licence(brut) -> str:
    """
    Texte libre → identifiant canonique. `''` si rien d'exploitable.

    'AGPL-3.0 License (https://ultralytics.com/license)' → 'agpl-3.0'
    'Apache 2.0 License'                                 → 'apache-2.0'
    'BSD 3-Clause License'                               → 'bsd-3-clause'

    Consommé aussi par `model_manager.services.weights_metadata` : la normalisation appartient au
    domaine licence, pas au lecteur de poids qui n'en est qu'un producteur parmi d'autres.
    """
    if not brut:
        return ''
    texte = str(brut).strip().lower()
    if not texte:
        return ''
    # On coupe ce qui suit une parenthèse ou une virgule : les amonts collent souvent l'URL.
    texte = re.split(r'[(,]', texte, 1)[0].strip()
    texte = texte.rstrip('.').strip()
    if texte in _CATALOGUE:
        return texte
    if texte in _ALIAS:
        return _ALIAS[texte]
    sans_suffixe = re.sub(r'\s+licen[cs]e$', '', texte).strip()
    if sans_suffixe in _CATALOGUE:
        return sans_suffixe
    if sans_suffixe in _ALIAS:
        return _ALIAS[sans_suffixe]
    # Premier jeton plausible (« agpl-3.0 license » sans espace normalisable).
    m = re.match(r'^([a-z0-9.+-]{2,})', sans_suffixe)
    if m and m.group(1) in _CATALOGUE:
        return m.group(1)
    return sans_suffixe[:64] or ''


def qualifier(licence: str) -> dict:
    """`{id, famille, rang, libelle, attribution}` — `rang` croît avec la contrainte."""
    ident = normaliser_licence(licence)
    if not ident:
        rang, attribution = INCONNUE, True
        ident = ''
    else:
        rang, attribution = _CATALOGUE.get(ident, (A_QUALIFIER, True))
    libelle, explication = FAMILLES[rang]
    return {'id': ident, 'rang': rang, 'famille': libelle,
            'explication': explication, 'attribution': attribution}


# ── Inventaire des registres ──────────────────────────────────────────────────────────────

def _lignes_modeles():
    from wama.model_manager.models import AIModel
    for m in AIModel.objects.filter(is_proposed=False).order_by('model_key'):
        yield {'registre': 'model', 'cle': m.model_key, 'nom': m.name,
               'licence': m.license, 'auteur': m.author,
               'url': m.platform_url, 'detail': m.get_model_type_display()}


def _lignes_librairies():
    from wama.common.models import Library
    for l in Library.objects.all().order_by('key'):
        yield {'registre': 'library', 'cle': l.key, 'nom': l.name or l.key,
               'licence': l.license, 'auteur': l.author,
               'url': l.repository or None, 'detail': l.version or ''}


def _lignes_medias(user=None):
    from wama.media_library.models import SystemAsset, UserAsset
    for a in SystemAsset.objects.filter(is_active=True).order_by('name'):
        yield {'registre': 'media', 'cle': f"system:{a.pk}", 'nom': a.name,
               'licence': a.license, 'auteur': a.author,
               'url': a.source_url or None, 'detail': a.get_asset_type_display()}
    qs = UserAsset.objects.all()
    if user is not None and user.is_authenticated:
        # Une page d'audit ne doit pas révéler les médias des autres : on s'en tient au
        # périmètre visible (privé de l'utilisateur + partages unité/public).
        try:
            from wama.common.models import scoped_visible_q
            qs = qs.filter(scoped_visible_q(user, owner_field='user'))
        except Exception:
            qs = qs.filter(user=user)
    for a in qs.order_by('name'):
        yield {'registre': 'media', 'cle': f"user:{a.pk}", 'nom': a.name,
               'licence': a.license, 'auteur': a.author,
               'url': a.source_url or None, 'detail': a.get_asset_type_display()}


def inventaire(user=None) -> list:
    """Toutes les lignes des registres, chacune qualifiée. Aucune écriture."""
    lignes = []
    for source in (_lignes_modeles(), _lignes_librairies(), _lignes_medias(user)):
        for ligne in source:
            ligne['q'] = qualifier(ligne['licence'])
            lignes.append(ligne)
    return lignes


# ── Traversée par app (composition déclarée par les manifestes) ────────────────────────────

def _requires_par_app() -> dict:
    """`{app_id: [(kind, key), …]}` lu dans le corpus de manifestes d'app."""
    import json
    from pathlib import Path

    from django.conf import settings

    dossier = Path(settings.BASE_DIR) / 'manifests' / 'apps'
    resultat = {}
    if not dossier.is_dir():
        return resultat
    for fichier in sorted(dossier.glob('*.json')):
        try:
            manifeste = json.loads(fichier.read_text(encoding='utf-8'))
        except Exception:
            continue
        besoins = [(r.get('kind'), r.get('key'))
                   for r in (manifeste.get('requires') or [])
                   if isinstance(r, dict) and r.get('kind') and r.get('key')]
        resultat[manifeste.get('key') or fichier.stem] = besoins
    return resultat


def par_app(lignes=None) -> list:
    """
    Pour chaque app : les licences TRAVERSÉES par ce qu'elle requiert, et la plus contraignante.

    C'est la question qui compte au moment de publier un résultat — et elle se CALCULE depuis la
    composition déjà déclarée (`requires`), elle ne se saisit pas. C'est ce qui empêche cette vue
    de devenir un registre de plus.
    """
    lignes = lignes if lignes is not None else inventaire()
    index = {(l['registre'], l['cle']): l for l in lignes}
    apps = []
    for app_id, besoins in sorted(_requires_par_app().items()):
        traversees, manquants = {}, 0
        for kind, key in besoins:
            ligne = index.get((kind, key))
            if ligne is None:
                manquants += 1
                continue
            q = ligne['q']
            cle_licence = q['id'] or '(inconnue)'
            entree = traversees.setdefault(
                cle_licence, {'id': cle_licence, 'q': q, 'n': 0, 'exemples': []})
            entree['n'] += 1
            if len(entree['exemples']) < 3:
                entree['exemples'].append(ligne['nom'])
        pire = max((e['q'] for e in traversees.values()), key=lambda q: q['rang'], default=None)
        apps.append({
            'app': app_id,
            'licences': sorted(traversees.values(), key=lambda e: (-e['q']['rang'], e['id'])),
            'pire': pire,
            'requires': len(besoins),
            'hors_registre': manquants,
        })
    return apps


def synthese(user=None) -> dict:
    """Photo complète : lignes, répartition, plus contraignante, et ce qu'il faut citer."""
    lignes = inventaire(user)

    par_licence = defaultdict(lambda: {'n': 0, 'q': None, 'registres': defaultdict(int)})
    for l in lignes:
        cle = l['q']['id'] or '(inconnue)'
        par_licence[cle]['n'] += 1
        par_licence[cle]['q'] = l['q']
        par_licence[cle]['registres'][l['registre']] += 1
    repartition = sorted(
        ({'id': k, **v, 'registres': dict(v['registres'])} for k, v in par_licence.items()),
        key=lambda e: (-e['q']['rang'], -e['n']),
    )

    connues = [l for l in lignes if l['q']['id']]
    pire = max((l['q'] for l in connues), key=lambda q: q['rang'], default=None)

    # À citer = licence à attribution ET auteur connu. Le cas « attribution exigée mais auteur
    # inconnu » est compté à part : c'est une dette juridique, pas un détail d'affichage.
    a_citer = [l for l in lignes if l['q']['attribution'] and l['q']['id'] and l['auteur']]
    attribution_sans_auteur = [l for l in lignes
                               if l['q']['attribution'] and l['q']['id'] and not l['auteur']]

    return {
        'lignes': lignes,
        'repartition': repartition,
        'pire': pire,
        'apps': par_app(lignes),
        'stats': {
            'total': len(lignes),
            'connues': len(connues),
            'inconnues': len(lignes) - len(connues),
            'non_commercial': sum(1 for l in lignes if l['q']['rang'] == NON_COMMERCIAL),
            'a_qualifier': sum(1 for l in lignes if l['q']['rang'] == A_QUALIFIER),
            'a_citer': len(a_citer),
            'attribution_sans_auteur': len(attribution_sans_auteur),
        },
        'attribution_sans_auteur': attribution_sans_auteur,
    }
