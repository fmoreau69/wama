"""
Context processors du socle commun.

`volet_defaut` garantit que `volet` est TOUJOURS un dict complet dans les gabarits, y compris
pour les pages qui ne déclarent rien — c'est ce qui rend le défaut « les trois sections »
sûr sans obliger les 10 apps à écrire quoi que ce soit. Voir `wama/common/utils/volet.py`.
"""
from __future__ import annotations

from wama.common.utils.volet import VOLET_DEFAUT


def volet_defaut(request):
    """Déclaration de volet par DÉFAUT ; une vue qui passe `volet` la remplace (elle est
    empilée au-dessus du contexte des processors)."""
    return {'volet': VOLET_DEFAUT}
