"""
Parsing des fichiers RTMaps .rec — brique WAMA généraliste (acquisition/synchro de
données). Autonome (aucune dépendance à une app) : destinée à migrer vers `wama_data`
quand il existera, ou à rester ici si `wama_lab` l'utilise aussi.
"""
from .rec_parser import parse_rec, rec_time_to_seconds

__all__ = ["parse_rec", "rec_time_to_seconds"]
