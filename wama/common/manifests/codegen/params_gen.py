"""
Facette params → `params.py` au LITTÉRAL (cible `params` d'app_sandbox substitute).

Pourquoi cette cible existe (mesuré le 2026-08-31) : la jumelle converter_01 tournait sur
une COPIE de params.py antérieure au 18/08 — sans le contexte 'panel', `WamaParams.render`
et le read/apply du volet filtraient TOUT (0 champ, EN SILENCE) pendant que le manifeste,
lui, était à jour (19/20 params avec 'panel'). Un fichier copié dérive de sa source ; un
fichier généré du manifeste la suit. `params.py` était le seul consommé par les vues et
gabarits GÉNÉRÉS à ne pas être substituable.

Même couche de démarrage que `write_back_app` (facette params, builtin/app.py, qui RÉUTILISE
`render_params_source` ci-dessous — un seul constructeur de texte) : schémas au littéral
(résultat évalué du manifeste), fichier marqué, à raffiner vers derive_from_model quand la
facette processing génèrera le modèle.
"""
from wama.common.manifests.builtin.app import _GEN_MARK


def render_params_source(app_id: str, schemas: dict) -> str:
    """Texte complet d'un params.py au littéral (docstring marquée + un attribut par schéma)."""
    import pprint
    mark = _GEN_MARK.format(app_id=app_id)
    lignes = [
        '"""',
        f"{mark} — params.py GÉNÉRÉ (facette params).",
        '',
        'Couche de DÉMARRAGE : schémas au LITTÉRAL (résultat évalué du manifeste). À raffiner',
        'vers derive_from_model(...) + sources dynamiques quand la facette processing génèrera',
        'le modèle Django — les valeurs dérivées redeviendront alors dérivées. Ne pas éditer à',
        'la main : rejouer write_back (ou app_sandbox substitute params) après modification du',
        'manifeste.',
        '',
        "⚠ SÉLECTEUR DE MODÈLE — il se déclare `options_source: 'catalog'` (+ `options_query`",
        "   nommant le DOMAINE : task / model_type / modality), JAMAIS par une liste `choices`",
        '   écrite ici. Une liste en dur signifie qu\'un modèle installé n\'apparaîtra jamais à',
        "   l'utilisateur sans édition de code — c'est ce que mesure le critère de grille",
        "   `model_options_catalog` (F4). Le domaine BORNE la liste ; les entrées fournies la",
        '   GRISENT côté client (WamaInputMatch) — lister n\'est pas pouvoir choisir.',
        '"""',
        '',
    ]
    for attr in sorted(schemas):
        rendu = pprint.pformat(schemas[attr], width=96, sort_dicts=False).split('\n')
        lignes.append(f"{attr} = {rendu[0]}")
        pad = ' ' * (len(attr) + 3)
        lignes += [pad + l for l in rendu[1:]]
        lignes.append('')
    # ── Alias de COMPATIBILITÉ des symboles publics (mesuré le 2026-09-03, describer_01) ──
    # Un params.py MAIN expose deux symboles : `<X>` (liste de Param) ET `<X>_JSON`
    # (schema_to_dicts). Le généré ne rend que la forme _JSON du manifeste — or les
    # consommateurs COPIÉS de la jumelle importent l'autre (`models.gear_data` : `from
    # .params import PARAMS`) : ImportError AU RENDU DE CHAQUE CARD, file « vide » sur une
    # page 200 (le smoke du juge mesurait une file VIDE). Les briques (card_gear,
    # card_chips, effective_settings) acceptent Param OU dict (`_pget`, 31/08) : l'alias
    # dict est un consommable légitime, pas un mensonge de type.
    for attr in sorted(schemas):
        if attr.endswith('_JSON'):
            lignes.append(f"{attr[:-5]} = {attr}  # alias compat (les briques acceptent les dicts)")
    lignes.append('')
    return '\n'.join(lignes)


def render_params(manifest: dict):
    """Contrat substitute : (src, raison). None si la facette manque au manifeste."""
    body = manifest.get('body') or {}
    schemas = (body.get('params') or {}).get('schemas') or {}
    if not schemas:
        return None, 'facette params absente du manifeste'
    app_id = manifest.get('key')
    src = render_params_source(app_id, schemas)
    compile(src, f'<params_gen app:{app_id}>', 'exec')   # jamais un fichier insyntaxique
    raison = f"{len(schemas)} schéma(s) au littéral ({', '.join(sorted(schemas))})"
    en_dur = _selecteurs_de_modele_en_dur(schemas)
    if en_dur:
        # SIGNALÉ, pas corrigé : ce générateur rend le manifeste au littéral — il n'invente
        # rien (c'est sa raison d'être : « un fichier copié dérive de sa source, un fichier
        # généré la suit »). Injecter ici `options_source` ferait mentir le manifeste sur ce
        # que l'app fait. Le défaut se corrige DANS le manifeste ; on le dit fort pour que
        # personne ne génère une app non conforme sans le savoir.
        raison += (f" — ⚠ sélecteur(s) de modèle à liste EN DUR : {', '.join(en_dur)} ; "
                   "déclarer `options_source: 'catalog'` au manifeste (critère F4 "
                   "`model_options_catalog`)")
    return src, raison


#: Noms de paramètre qui désignent un CHOIX DE MODÈLE dans les schémas d'app existants.
#: Liste d'OBSERVATION (relevée sur les 10 apps), pas une convention imposée : elle sert à
#: SIGNALER, jamais à décider — un paramètre inconnu d'ici ne déclenche rien.
_NOMS_SELECTEUR_MODELE = ('model', 'tts_model', 'ai_model', 'engine', 'backend',
                          'ai_model_audio', 'model_name')


def _selecteurs_de_modele_en_dur(schemas: dict) -> list:
    """Paramètres qui CHOISISSENT un modèle avec une liste écrite à la main."""
    fautifs = []
    for attr, schema in (schemas or {}).items():
        for p in (schema or []):
            if not isinstance(p, dict) or p.get('name') not in _NOMS_SELECTEUR_MODELE:
                continue
            if p.get('options_source') == 'catalog':
                continue
            if p.get('choices') or p.get('option_groups'):
                fautifs.append(f"{attr}.{p['name']}")
    return fautifs
