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
        '"""',
        '',
    ]
    for attr in sorted(schemas):
        rendu = pprint.pformat(schemas[attr], width=96, sort_dicts=False).split('\n')
        lignes.append(f"{attr} = {rendu[0]}")
        pad = ' ' * (len(attr) + 3)
        lignes += [pad + l for l in rendu[1:]]
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
    return src, f"{len(schemas)} schéma(s) au littéral ({', '.join(sorted(schemas))})"
