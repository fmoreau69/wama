"""
Contrat de la tâche `text-to-music` — ce que le COMPOSER appelle (`wama/composer/tasks.py`).

Les deux backends musicaux (AudioCraft, audio.cpp) portaient la MÊME signature `generate(...)`
recopiée, sans qu'aucun contrat ne la déclare. Conséquence mesurée le 2026-10-01 : le rôle
`backend` de wama-dev-ai, écrivant le backend de YuE2, ne recevait que le contrat commun
(`load`/`process`) — il a produit un `process(style=, lyrics=)` que le composer n'appelle
jamais. Le contrat de tâche (`backend_inventory.TASK_CONTRACTS`) est ce qui dit au rôle quelle
méthode écrire, et aux deux backends existants ce qu'ils ont en commun.
"""
from abc import abstractmethod
from typing import Callable, Optional

from .base import BaseModelBackend


def split_caption_lyrics(prompt: str) -> tuple[str, str]:
    """
    (caption, lyrics) depuis le prompt unique du composer. La convention de la TÂCHE met la
    DESCRIPTION en tête et les PAROLES dans des sections taguées (`[verse]`, `[chorus]`…) :
    on coupe à la première ligne qui ouvre un tag. Sans tag de paroles → instrumental
    (`[instrumental]` — les paroles sont requises par le moteur, le tag est la convention
    pour ne pas en chanter). Annoncé dans la description du modèle, pas de magie cachée.

    Écrite pour MiniMax-Music3 (`audiocpp_backend`) ; remontée dans le contrat le 2026-10-01 :
    YuE2 attend la même forme (style + paroles en `[Verse]`/`[Chorus]`), et un second backend
    musical ne doit pas réinventer sa découpe.
    """
    lines = (prompt or '').splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith('['):
            caption = '\n'.join(lines[:i]).strip()
            lyrics = '\n'.join(lines[i:]).strip()
            return caption or 'A song.', lyrics
    return (prompt or '').strip() or 'An instrumental piece.', '[instrumental]'


class MusicGenerationBackend(BaseModelBackend):
    """Génère un fichier audio depuis une consigne — un modèle `text-to-music` du catalogue."""

    def process(self, **kwargs):
        """Point d'entrée générique (contrat commun) → délègue à `generate()`."""
        return self.generate(**kwargs)

    @abstractmethod
    def generate(
        self,
        model_id: str,
        prompt: str,
        duration: float,
        output_path: str,
        melody_path: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        on_audio: Optional[Callable] = None,
    ) -> str:
        """Écrit l'audio généré dans `output_path` et rend ce chemin.

        `model_id`          : identifiant du modèle (dernier segment de sa clé de catalogue) ;
        `prompt`            : la consigne de l'utilisateur, déjà routée (traduite si le modèle
                              l'exige) par le composer — description en tête, paroles éventuelles
                              en sections `[verse]`/`[chorus]` : `split_caption_lyrics(prompt)`
                              les sépare, ne jamais réinventer la découpe ;
        `duration`          : durée visée, en secondes — un moteur qui ne la maîtrise pas la
                              traite comme une borne, et le DIT ;
        `melody_path`       : audio de référence facultatif — un moteur qui ne l'accepte pas le
                              REFUSE en le disant, jamais en l'ignorant ;
        `progress_callback` : reçoit un pourcentage (0-100) ;
        `on_audio`          : facultatif, `(tableau, fréquence)` d'un aperçu pendant le calcul.
        """
