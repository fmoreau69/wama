"""Détection et occultation des DONNÉES PERSONNELLES d'un texte — brique commune (ROADMAP §16.4bis).

Consommateurs prévus : le domaine document de l'Anonymizer, la porte de l'assistant avant tout
appel à un modèle distant, les souvenirs partagés de la mémoire. Un seul vocabulaire d'entités
(`entities`), une union de détecteurs orchestrée par Presidio — chaque détecteur est un BACKEND du
contrat `pii-detection` (`common/backends/pii_detection_base.py`).

Ce paquet n'importe rien de lourd à son ouverture : Presidio et les modèles ne se chargent qu'à
l'usage.
"""
