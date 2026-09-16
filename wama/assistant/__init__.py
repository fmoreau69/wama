"""
AI-Assistant — app TRANSVERSALE de WAMA (décision de Fabien, 2026-09-15).

Le MOTEUR vit dans `wama/common/services/assistant_engine.py` : il est commun à toutes les
surfaces (web, API v1, canaux, MCP). Ce paquet ne porte que ce qu'une app DÉCLARE et que les
briques communes vont chercher par convention — à commencer par son schéma de paramètres
(`params.py`, lu par `param_schema.schema_for_app('assistant')`).

⚠ Ce n'est pas une app Django installée : aucun modèle, aucune URL ici. Sa déclaration au
catalogue d'apps (et le classement par monde) est menée dans une AUTRE session.
"""
