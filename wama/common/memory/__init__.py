"""
Mémoire & RAG — brique unique. Doc de référence : `WAMA_MEMORY.md`.

CE QU'ELLE FAIT : retrouver le bon morceau de texte, pour le bon utilisateur, au bon moment.
Les quatre usages visés (auto-amélioration wama-dev-ai, assistant IA, mémoire de travail
utilisateur, RAG documentaire) n'ont qu'UN mécanisme — d'où une brique, pas un module RAG plus
un module mémoire.

CE QU'ELLE NE FAIT PAS : juger, résumer à l'écriture, ni appliquer une fusion toute seule.

⚠ ÉTAT : AUCUN APPELANT (jalon 3 de `WAMA_MEMORY.md §10`). La brique est complète et testable,
mais rien dans WAMA ne l'invoque : le Hook B de `prompt_pipeline` (jalon 6) reste un no-op.
Ne pas la brancher sans avoir soldé les jalons 4-5 (projections + indexation).
"""

from .store import expire, forget, merge, recall, remember

__all__ = ['remember', 'recall', 'forget', 'merge', 'expire']
