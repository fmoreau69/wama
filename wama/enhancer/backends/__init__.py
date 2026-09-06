"""Backends de l'Enhancer — moteurs d'amélioration audio et d'upscaling image/vidéo.

⚠ Paquet CRÉÉ le 2026-09-06. L'app n'en avait pas : ses backends au contrat commun vivaient
dans `utils/audio_enhancer.py`, donc **invisibles** au registre des backends, qui ne balaie que
`<app>/backends/`. Conséquence mesurée : ses 9 modèles ne pouvaient pas déclarer un moteur qui
se résolve, et l'invariant « tout backend concret déclare `ENGINE` » passait au vert sans les
voir — *un invariant ne vaut que sur le périmètre qu'il balaie*.

`utils/` garde ce qui n'est PAS un moteur (helpers de format, téléchargement de poids) : la
frontière est le contrat, pas le sujet.
"""
from .ai_upscaler import AIUpscaler
from .audio_enhancer import DeepFilterNetBackend, ResembleEnhanceBackend

__all__ = ['ResembleEnhanceBackend', 'DeepFilterNetBackend', 'AIUpscaler']
