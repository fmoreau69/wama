"""
data-* du bouton ⚙ d'une card — GÉNÉRATION COMMUNE dérivée du schéma (extraite 2026-08-18).

Contrat consommé par `WamaInspector.initFromSchema` (cardSettings) : à la sélection d'une
card, le volet inspecteur REFLÈTE ses réglages en lisant les data-* du bouton ⚙. Jusqu'ici
chaque app les écrivait À LA MAIN dans son template de card (describer/synthesizer : 5
attributs chacun, booléens via |yesno) — hardcode remplacé par cette dérivation du SCHÉMA
(source unique : ajouter un Param en contexte 'item' suffit, le gear suit).

Usage (property de modèle) :
    @property
    def gear_data(self):
        from wama.common.utils.card_gear import gear_data
        from .params import PARAMS
        return gear_data(self, PARAMS)                                   # champs de modèle
        # ou, si les valeurs vivent dans un JSON :
        # return gear_data(self, PARAMS, values={**(self.options or {})})

Template de card :
    {% for k, v in obj.gear_data.items %}data-{{ k }}="{{ v }}" {% endfor %}

Règles :
- TOUS les params de contexte 'item' sont émis ('' si absents) — un changement de
  sélection ne laisse pas les valeurs de la card précédente dans le volet ;
- booléens aplatis en 'true'/'false' (le apply de la brique JS ne reconnaît pas le
  'True' de Python) ;
- la valeur vient de `values` (dict, ex. options JSON) puis de l'attribut de modèle
  HOMONYME (schémas derive_from_model : noms = champs) ; `extra` force/complète ;
- clés émises À TIRETS (`output_format` → `data-output-format`) : le dataset les expose
  en camelCase, lu PAR LES DEUX consommateurs — le cardSettings dérivé (qui teste
  underscore PUIS camel) ET le JS existant des apps (préremplissage de modale :
  `btn.dataset.outputStyle`…). Une émission underscore casse le second — mesuré sur
  describer le 18/08.
"""


def _flat(v):
    """Valeur d'attribut data-* : booléens JS-compatibles, None → ''."""
    if v is True:
        return 'true'
    if v is False:
        return 'false'
    return '' if v is None else v


def gear_data(instance, params, values=None, extra=None) -> dict:
    """dict {nom-a-tirets: valeur aplatie} pour les data-* du bouton ⚙ (voir docstring)."""
    out = {}
    src = values or {}
    for p in params:
        if 'item' not in (getattr(p, 'contexts', None) or ()):
            continue
        key = p.name.replace('_', '-')
        if p.name in src:
            out[key] = _flat(src[p.name])
        else:
            out[key] = _flat(getattr(instance, p.name, None))
    for k, v in (extra or {}).items():
        out[k.replace('_', '-')] = _flat(v)
    return out
