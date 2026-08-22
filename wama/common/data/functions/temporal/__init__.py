"""
temporal/ — fonctions de SEGMENTATION, déclarées au catalogue.

Domaine transverse (contrairement à `driving/`, `geo/`, `kinematics/`) : segmenter un signal ne
suppose aucun métier. C'est la raison d'être de l'axe DOMAINE — il est orthogonal au `data_type`
et à la `category`.

Pourquoi ces fonctions sont déclarées ici et non laissées dans `segmentation.py` : la règle §7bis
(« tout traitement se déclare ») est aussi le garde-fou **G1/G3** du monde DATA. Une fonction qui
n'entre pas au `FUNCTION_CATALOG` est invisible du canvas studio, donc inchaînable, donc hors du
pipeline — et l'on se retrouve à réécrire à la main ce qui aurait dû se composer.
"""
from . import segmentation  # noqa: F401  (l'import enregistre les FunctionSpec)
