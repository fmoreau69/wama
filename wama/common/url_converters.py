"""La CLÉ d'un élément d'app dans une route commune — `<item:pk>` (2026-10-31).

Les routes communes qui désignent un élément d'app (aperçu, détail, surface, « Envoyer vers »,
résultat) n'acceptaient qu'un numéro (`<int:pk>`). Les apps du monde Lab ont des clés UUID
(`face_analyzer.AnalysisSession`, `cam_analyzer`) : décision de Fabien, 2026-10-31 — les pièces
communes acceptent les deux, plutôt que de migrer les clés des apps (option A).

Déclaré UNE fois ici, enregistré à l'import du module (le registre des convertisseurs de Django est
global) : un `urls.py` qui écrit `<item:…>` importe ce module. Il remplace les routes JUMELLES
`<uuid:pk>` posées le 2026-10-29 pour les seules surfaces.

`to_python` rend un `int` ou un `uuid.UUID` — jamais une chaîne : Django sait convertir l'un vers
l'autre champ (`int(UUID)`, `UUID(int=…)`), donc une clé de l'autre forme finit en 404 propre, pas
en erreur 500. ⚠ Le PARTAGE n'en suit pas : ses tables désignent l'objet par un entier
(`ObjectGrant.object_id`) — un chantier du domaine Collaboration, décision à prendre.
"""
import uuid

from django.urls import register_converter

UUID_PATTERN = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'


class ItemKeyConverter:
    """Un numéro d'élément, ou un UUID."""
    regex = f'[0-9]+|{UUID_PATTERN}'

    def to_python(self, value):
        return int(value) if value.isdigit() else uuid.UUID(value)

    def to_url(self, value):
        return str(value)


register_converter(ItemKeyConverter, 'item')
