"""
Le corpus d'ÉPREUVE du monde Data — où vit la base réelle, et pourquoi elle ne suffit pas.

⚠ POURQUOI CE FICHIER (2026-08-24). Le chemin de la base d'expérimentation était **recopié dans
trois fichiers de test** (`core/tests_temporal`, `core/tests_segmentation`,
`sources/tests_sources`). Quand Fabien l'a déplacée sous `claude/WAMA-Data/`, les trois se sont
mis à sauter **en silence** — un `skipUnless` sur un chemin périmé ne dit pas « le chemin a
changé », il dit « absente », ce qui est faux et rassurant.

Un chemin recopié trois fois est une duplication comme une autre : il vit ici, une seule fois.

⚠ ET LA LEÇON QUI COMPTE DAVANTAGE : le lecteur `.trip` — le plus complexe du monde — n'avait
**AUCUNE couverture** hors de cette base. Elle pèse 1,28 Go, vit hors dépôt (`claude/` est
gitignoré) et peut donc disparaître ou bouger sans que rien ne casse : les tests se contentent de
sauter. C'est exactement le garde-fou **G7** (« cas complet de bout en bout — nécessite un
échantillon réduit VERSIONNÉ »).

La réponse retenue n'est pas de committer un binaire, c'est de **GÉNÉRER** un `.trip` minimal au
schéma relevé (`sources/tests_sources.py::_trip_synthetique`). La base réelle garde son rôle —
éprouver le volume, les six cadences, les valeurs sales — mais elle n'est plus la CONDITION de
toute vérification.
"""
from __future__ import annotations

from pathlib import Path

#: Racine du dépôt (ce fichier vit à la racine du monde `wama_data/`).
RACINE = Path(__file__).resolve().parents[1]

_EXEMPLE = RACINE / 'claude' / 'WAMA-Data' / 'Exemple_trip'

#: Base d'expérimentation réelle — HORS DÉPÔT, donc absente sur une installation neuve.
#: ⚠ Déplacée sous `claude/WAMA-Data/` le 2026-08-24 ; les tests qui la citaient en dur ont
#: silencieusement commencé à sauter. Un seul domicile désormais.
BASE_REELLE = _EXEMPLE / 'RecFile_REC_20190502_144710.trip'

#: Le `.rec` dont ce `.trip` a été TIRÉ — 1,54 Go, RTMaps v4.5.3 (2019).
#: ⚠ Avoir l'ENTRÉE et la SORTIE du même enregistrement fait de ce couple le banc d'essai du
#: portage `rec2trip` : un lecteur WAMA s'y confronte à un résultat de référence produit par BIND,
#: au lieu d'être jugé sur lui-même.
REC_2019 = _EXEMPLE / 'RecFile_REC_20190502_144710.rec'

#: Un second `.rec`, RTMaps **v4.8.0** (2022) — 40 Mo, avec ses CSV par flux, sa vidéo et son
#: `.inf`. ⚠ Il est INDISPENSABLE et pas redondant : la grammaire du `.idy` a changé entre les
#: deux versions (le nom de table a disparu), et un lecteur validé sur un seul des deux
#: échantillons casserait sur l'autre (`WAMA_DATA_WORLD.md §6.6bis ②`).
REC_2022 = (RACINE / 'media' / 'cam_analyzer' / '1' / 'input' / 'ENA_CASA'
            / '20220404_124000_RecFile_Data' / 'RecFile_Data_20220404_124000.rec')

#: Export CSV que RTMaps a produit LUI-MÊME du flux GPS de `REC_2022`. Sert de contre-épreuve
#: INDÉPENDANTE : le lecteur doit retrouver les mêmes instants et les mêmes valeurs.
CSV_GPS_2022 = REC_2022.with_name(REC_2022.stem + '_GPS_NMEA0183_3_oPosition.csv')


def raison_absence(chemin=None) -> str:
    """Message de `skipUnless` — il doit dire OÙ on a cherché, pas seulement « absente ».

    Un skip qui annonce « base absente » sans le chemin fait passer un DÉPLACEMENT pour une
    absence légitime. C'est précisément ce qui s'est produit le 2026-08-24.
    """
    return f"corpus absent ({chemin or BASE_REELLE}) — hors dépôt, ou déplacé"
