"""Un mot ou un texte COMPARABLE à ce qu'une personne tape : casse et accents repliés, bords
retirés — « mediatheque » trouve « Médiathèque », « resume.pdf » trouve « Résumé.PDF », `!Modèle`
vaut `!modele`.

Domicile unique depuis le 2026-11-06 : la recherche de fichiers (`user_files`), celle des pages
(`navigation`) et les commandes de l'assistant (`assistant_commands`) portaient chacune la même
fonction privée `_fold`, la troisième écrite le jour même (relevée à la revérification).
"""
import unicodedata


def fold(text) -> str:
    decomposed = unicodedata.normalize('NFKD', str(text or ''))
    return ''.join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip()
