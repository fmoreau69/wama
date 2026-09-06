"""Backends du Face Analyzer — l'adaptateur WAMA autour des moteurs d'analyse faciale.

Créé le 2026-09-05 pour **fermer le lien modèle↔moteur**, préalable au retrait de
`AIModel.backend_ref` : les 3 poids DeepFace déclaraient `runtime.engine = 'deepface'` alors
qu'aucun backend ne déclarait piloter ce moteur. Leur verdict de disponibilité n'était donc
sauvé que par `backend_ref` — c'est-à-dire par le champ qu'on veut retirer.

⚠ Ce n'est PAS le portage de l'app (les apps Lab entreront au général plus tard, décision
Fabien) : il n'y a ici ni `ROUTES`, ni `RESULT`, ni `NATURE_FIELD`, parce que la chaîne de
génération de tâches ne s'applique pas encore à cette app. Ce qui EST posé, c'est la moitié
BACKEND du lien — et elle est posée au format de la cible, pour que le portage la trouve faite.
"""
from .deepface_backend import DeepFaceBackend

__all__ = ['DeepFaceBackend']
