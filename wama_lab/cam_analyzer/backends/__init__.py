"""Backends du Cam Analyzer — l'adaptateur WAMA autour de ses moteurs d'analyse.

⚠ Paquet CRÉÉ le 2026-09-06. L'app n'en avait pas : son estimateur de profondeur vivait dans
`utils/depth_estimator.py`, donc **invisible** au registre des backends. Conséquence mesurée
par `manage.py check_backend_links` : `huggingface:depthpro` déclarait le moteur
`transformers` — installé — sans qu'aucun backend ne se déclare capable de servir CE modèle.

Ce n'est PAS le portage de l'app (les apps Lab entreront au général plus tard, décision
Fabien) : c'est la moitié BACKEND du lien modèle↔moteur, posée au format de la cible.
"""
from .depth_backend import DepthProBackend

__all__ = ['DepthProBackend']
