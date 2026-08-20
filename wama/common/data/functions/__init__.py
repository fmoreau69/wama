"""
Bibliothèque de traitement WAMA Data (capability-first), catégorisée par DOMAINE.

Importer ce paquet enregistre tout le catalogue de fonctions (les modules qui appellent
`register(FunctionSpec(...))` s'auto-déclarent à l'import). Certains modules sont des
**libs helper** (parsing, géométrie) utilisées PAR des fonctions, pas des FunctionSpec.

Domaines (axe orthogonal à `DataType` = type de donnée et `FunctionCategory` = rôle) :
  - `io/`         : ingest / parsing de formats source (RTMaps `.rec`…)
  - `geometry/`   : placement monde, projections, formes spatiales, métriques de placement
  - `kinematics/` : vitesse / accélération / TTC / collision / extrapolation
  - `driving/`    : analyse de conduite (portée d'une toolbox tierce) — freinage, map-matching GPS,
                    sections, annotations opérateur

Voir `WAMA_DATA_FUNCTION_CARDS.md`.
"""
from . import io          # noqa: F401
from . import geometry    # noqa: F401
from . import kinematics  # noqa: F401
from . import driving     # noqa: F401
from . import geo         # noqa: F401
