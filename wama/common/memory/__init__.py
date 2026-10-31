"""
Mémoire & RAG — brique unique. Doc de référence : `WAMA_MEMORY.md`.

CE QU'ELLE FAIT : retrouver le bon morceau de texte, pour le bon utilisateur, au bon moment.
Les quatre usages visés (auto-amélioration wama-dev-ai, assistant IA, mémoire de travail
utilisateur, RAG documentaire) n'ont qu'UN mécanisme — d'où une brique, pas un module RAG plus
un module mémoire.

CE QU'ELLE NE FAIT PAS : juger, résumer à l'écriture, ni appliquer une fusion toute seule.

ÉTAT (2026-10-31) : appelée par le Hook B de `prompt_pipeline` (`_rappel_rag`, opt-in `rag=True`
— aucune app ne l'active encore) et par l'assistant : ses domaines déclarés `rag=True`
(`assistant_skills`) et ses outils (`tool_api` : rappel, indexation par geste).
Jalons et suite : `WAMA_MEMORY.md §10`. *(Cette ligne disait « AUCUN APPELANT » : c'était l'état
du jalon 3.)*
"""

from .store import expire, forget, merge, recall, reindex, remember

#: `reindex` n'est pas une 6e opération du contrat memorywire : c'est l'ENTRETIEN du substrat
#: (calculer les vecteurs manquants par lot). Il est exporté parce qu'il est le complément
#: obligatoire de `remember(embed=False)` — sans lui, une écriture sans vecteur resterait
#: introuvable en sémantique.
__all__ = ['remember', 'recall', 'forget', 'merge', 'expire', 'reindex']
