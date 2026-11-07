"""Un JSON injecté DANS un `<script>` : `{{ params_json|script_json }}`.

Les gabarits d'app passent leurs schémas et leurs valeurs au JavaScript en ligne
(`schema: {{ params_json|… }}`). Avec `|safe`, le texte part tel quel : une donnée qu'un
utilisateur a saisie — le nom d'une voix, une licence, un libellé — et qui contient
`</script>` FERME le bloc, et ce qui suit s'exécute chez qui ouvre la page (XSS stocké entre
comptes, relevé par l'audit de sécurité du 2026-11-06 ; 164 injections dans 27 gabarits).

Ce filtre applique l'échappement de `json_script` de Django (`<`, `>`, `&`, U+2028, U+2029 en
`\\uXXXX`) à un JSON DÉJÀ sérialisé par la vue. C'est sans effet sur la valeur : dans un JSON,
ces caractères n'apparaissent que DANS une chaîne, où `\\u003C` se relit `<`. La vue garde donc
son contexte (une chaîne JSON, que les tests relisent par `json.loads`), le gabarit ne change que
le filtre. Une valeur qui n'est pas une chaîne est sérialisée ici, avec l'encodeur de Django.

Un gabarit NEUF préfère `{{ valeur|json_script:"id" }}` (la valeur Python, lue côté JS par
`JSON.parse(…textContent)`) ; ce filtre sert l'idiome en ligne existant. Garde :
`wama/common/tests/tests_script_json.py` (aucun `|safe` dans un `<script>`).
"""
import json

from django import template
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.safestring import mark_safe

register = template.Library()

#: La table de `django.utils.html.json_script` — recopiée parce qu'elle y est privée.
SCRIPT_ESCAPES = {
    ord('<'): '\\u003C',
    ord('>'): '\\u003E',
    ord('&'): '\\u0026',
    0x2028: '\\u2028',
    0x2029: '\\u2029',
}


def script_json_text(value) -> str:
    """Le texte à poser dans un `<script>` : la chaîne JSON reçue, ou la valeur sérialisée."""
    text = value if isinstance(value, str) else json.dumps(value, cls=DjangoJSONEncoder)
    return text.translate(SCRIPT_ESCAPES)


@register.filter(is_safe=True)
def script_json(value):
    """`{{ x_json|script_json }}` : un JSON qui ne peut pas fermer le `<script>` qui le porte."""
    return mark_safe(script_json_text(value))
