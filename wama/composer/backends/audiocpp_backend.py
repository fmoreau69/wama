"""
AudioCpp Backend — modèles MULTI-COMPOSANTS via le moteur audio.cpp (sous-processus).

Premier backend COMPOSÉ de WAMA (2026-08-27, cas d'école MiniMax-Music3) : il ne code aucune
anatomie de modèle — il LIT la déclaration (`AIModel.composition`, posée par le manifeste
`model`) et la traduit en invocation du binaire `audiocpp_cli` (audio.cpp, Apache 2.0,
https://github.com/0xShug0/audio.cpp) :

    composition.components[role→pattern]  →  --session-option <famille>.<role>_gguf=<fichier>
    composition.runtime.engine/family     →  --family <famille>

Même famille de geste que ffmpeg (binaire externe, override par variable d'environnement
`AUDIOCPP_BINARY`) et même motif gouverneur que MuseTalk/CodeFormer (`vram_reservation`
autour du sous-processus — la charge GPU est hors process, invisible des mesures torch).
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

from wama.common.backends.base import BaseModelBackend

logger = logging.getLogger(__name__)

#: Rôles que audio.cpp permet de sélectionner par fichier (session options). Les autres
#: composants (vocoder, condition_encoder) sont résolus par leurs noms par défaut dans le
#: package — leur pattern déclaré doit donc ÊTRE ce nom par défaut.
_SELECTABLE_ROLES = ('language_model', 'flow_transformer', 'rvq_depth_decoder')

#: Fichiers que le moteur ouvre EN DUR au chargement de base (assets.cpp,
#: `load_minimax_music3_assets`), AVANT d'appliquer les session options qui les remplacent
#: (session.cpp, `select_component_assets`). Conséquence vécue (1ʳᵉ génération, 2026-08-28) :
#: un package n'embarquant qu'une autre variante (le nôtre est Q8) échoue « missing MiniMax
#: Music 3 component GGUF: …language_model_q4_0.gguf » sans que l'override soit jamais lu.
_ENGINE_EAGER_DEFAULTS = {
    'minimax_music3': {
        'language_model': 'language_model_q4_0.gguf',
        'flow_transformer': 'transformer_q4_0.gguf',
        'rvq_depth_decoder': 'rvq_depth_decoder_q8_0.gguf',
    },
}


def ensure_engine_default_aliases(racine: Path, famille: str, compo: dict) -> None:
    """
    Pose un ALIAS (lien symbolique relatif, idempotent) du nom par défaut du moteur vers la
    variante DÉCLARÉE quand seul celle-ci est installée — le moteur ouvre l'alias au
    chargement de base puis charge de toute façon la variante déclarée via la session
    option. Contournement du défaut moteur ci-dessus (`_ENGINE_EAGER_DEFAULTS`), à retirer
    si audio.cpp applique un jour ses overrides avant d'ouvrir ses défauts.
    """
    defauts = _ENGINE_EAGER_DEFAULTS.get(famille, {})
    for c in compo.get('components', []):
        defaut, pattern = defauts.get(c.get('role') or ''), c.get('pattern')
        if not defaut or not pattern or defaut == pattern:
            continue
        alias, cible = racine / defaut, racine / pattern
        if alias.exists() or not cible.is_file():
            continue
        try:
            alias.symlink_to(pattern)
            logger.info("[Composer/audio.cpp] alias %s → %s (défaut moteur absent du "
                        "package)", defaut, pattern)
        except OSError as e:
            # Sans alias le moteur redira « missing component GGUF » — on aura dit pourquoi.
            logger.warning("[Composer/audio.cpp] alias %s impossible : %s", defaut, e)


def get_audiocpp_binary() -> str:
    """
    Chemin du binaire `audiocpp_cli` — env `AUDIOCPP_BINARY` d'abord (même motif
    qu'`FFMPEG_BINARY`), sinon l'emplacement de build canonique de cet hôte
    (`~/tools/audio.cpp`, WSL2 — hors du dépôt : un moteur n'est pas du code WAMA).
    """
    env = os.getenv('AUDIOCPP_BINARY')
    if env:
        return env
    return str(Path.home() / 'tools' / 'audio.cpp' / 'build' / 'linux-cuda-release'
               / 'bin' / 'audiocpp_cli')


def _snapshot_root(cache_dir, hf_id: str) -> Optional[Path]:
    """
    Racine du PACKAGE (= dossier snapshot HF courant) : c'est elle que `--model` attend —
    composants GGUF à la racine + `config/` + `tokenizer/`.
    """
    depot = Path(cache_dir) / f"models--{hf_id.replace('/', '--')}"
    ref = depot / 'refs' / 'main'
    try:
        rev = ref.read_text().strip()
        racine = depot / 'snapshots' / rev
        return racine if racine.is_dir() else None
    except OSError:
        return None


def split_caption_lyrics(prompt: str) -> tuple[str, str]:
    """
    (caption, lyrics) depuis le prompt unique du composer. Le contrat MiniMax-Music3 met la
    DESCRIPTION en tête et les PAROLES dans des sections taguées (`[verse]`, `[chorus]`…) :
    on coupe à la première ligne qui ouvre un tag. Sans tag de paroles → instrumental
    (`[instrumental]` — les paroles sont requises par le moteur, le tag est la convention
    pour ne pas en chanter). Annoncé dans la description du modèle, pas de magie cachée.
    """
    lignes = (prompt or '').splitlines()
    for i, l in enumerate(lignes):
        if l.strip().startswith('['):
            caption = '\n'.join(lignes[:i]).strip()
            lyrics = '\n'.join(lignes[i:]).strip()
            return caption or 'A song.', lyrics
    return (prompt or '').strip() or 'An instrumental piece.', '[instrumental]'


class AudioCppBackend(BaseModelBackend):
    """
    Génération musicale par le moteur audio.cpp — sous-processus, aucun paquet Python requis.

    SANS état persistant (le binaire charge/décharge à chaque appel, `mem_saver` étageant
    les composants) → même profil que AudioCraftBackend : load() réchauffe, unload() no-op.
    """

    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'audio-cpp'
    REQUIRED_PACKAGES: list = []
    recommended_vram_gb = 13.0
    description = "audio.cpp — modèles audio multi-composants GGUF (MiniMax-Music3…)."
    _warm = False

    @classmethod
    def is_available(cls) -> bool:
        return Path(get_audiocpp_binary()).is_file()

    def load(self, model: Optional[str] = None) -> bool:
        self._warm = True
        return True

    @property
    def is_loaded(self) -> bool:
        return self._warm

    def unload(self) -> None:
        self._warm = False

    def process(self, **kwargs):
        return self.generate(**kwargs)

    # ------------------------------------------------------------------

    def _composition(self, model_id: str) -> dict:
        """
        L'anatomie DÉCLARÉE du modèle — `AIModel.composition` de la ligne d'app
        (`composer:<model_id>`), posée par son manifeste. Source unique : le backend
        n'invente ni fichiers ni moteur ; une composition absente est une erreur DITE
        (écrire/projeter le manifeste), jamais un défaut silencieux.
        """
        from wama.model_manager.models import AIModel
        m = AIModel.objects.filter(model_key=f"composer:{model_id}").first()
        compo = (m.composition if m else None) or {}
        if not compo.get('components'):
            raise RuntimeError(
                f"composition non déclarée pour composer:{model_id} — écrire le manifeste "
                "model (body.composition) et le projeter (write_back) avant d'utiliser ce "
                "backend.")
        return compo

    def generate(
        self,
        model_id: str,
        prompt: str,
        duration: float,
        output_path: str,
        melody_path: Optional[str] = None,   # contrat commun — non supporté par ce moteur
        progress_callback: Optional[Callable[[int], None]] = None,
        on_audio: Optional[Callable] = None,
    ) -> str:
        from wama.common.services.resource_governor import vram_reservation
        from wama.composer.utils.model_config import COMPOSER_MODELS

        config = COMPOSER_MODELS.get(model_id)
        if config is None:
            raise ValueError(f"Modèle inconnu : {model_id}")
        # La composition d'abord : c'est l'erreur la plus actionnable (déclarer le manifeste),
        # et elle ne dépend pas de l'hôte — le binaire, lui, varie par machine.
        compo = self._composition(model_id)
        binaire = get_audiocpp_binary()
        if not Path(binaire).is_file():
            raise RuntimeError(
                f"binaire audio.cpp introuvable ({binaire}) — compiler audio.cpp ou poser "
                "AUDIOCPP_BINARY.")
        famille = (compo.get('runtime') or {}).get('family') or 'minimax_music3'
        racine = _snapshot_root(config['cache_dir'], config['hf_id'])
        if racine is None:
            raise RuntimeError(
                f"package {config['hf_id']} absent de {config['cache_dir']} — installer le "
                "modèle (model manager) d'abord.")
        ensure_engine_default_aliases(racine, famille, compo)

        if melody_path:
            # MiniMax-Music3 est TEXTE-SEUL (paroles + description) : aucune entrée audio de
            # référence — les workflows à référence mélodique sont d'autres produits MiniMax
            # (Music Cover / 2.6). L'UI ne propose la mélodie qu'à musicgen-melody
            # (inputs_optional) ; si un batch en passe une quand même, on le DIT.
            logger.warning("[Composer/audio.cpp] mélodie de référence ignorée — %s est "
                           "conditionné par le texte seul", model_id)

        caption, lyrics = split_caption_lyrics(prompt)
        cmd = [
            binaire, '--task', 'gen', '--family', famille,
            '--model', str(racine), '--backend', 'cuda',
            '--text', caption,
            '--request-option', f'lyrics={lyrics}',
            '--request-option', f'duration_sec={int(duration)}',
            '--out', output_path,
        ]
        for c in compo.get('components', []):
            if c.get('role') in _SELECTABLE_ROLES and c.get('pattern'):
                cmd += ['--session-option', f"{famille}.{c['role']}_gguf={c['pattern']}"]

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        if progress_callback:
            progress_callback(10)
        logger.info("[Composer/audio.cpp] %s — %s", model_id, ' '.join(cmd[1:12]))

        # Réservation VRAM le temps du sous-processus (motif MuseTalk : charge hors process,
        # invisible des mesures torch — sans elle, le gouverneur croirait le GPU libre).
        besoin = float(config.get('vram_gb') or self.recommended_vram_gb)
        # Mode dépannage GPU (WAMA_GPU_SAFE_MODE, crashs hôte) : ne lancer la montée en
        # charge que si la VRAM MESURÉE suffit — un résident (Ollama hôte, modèle torch d'un
        # autre worker) expirera pendant l'attente ; sinon on refuse EN LE DISANT.
        from wama.common.services.resource_governor import gpu_safe_mode, wait_for_free_vram
        if gpu_safe_mode():
            ok, libre = wait_for_free_vram(besoin, timeout_s=180)
            if not ok:
                raise RuntimeError(
                    f"mode dépannage GPU : {libre:.1f} Go libres mesurés < {besoin:.1f} Go "
                    "requis après 180 s d'attente — génération refusée plutôt que superposée. "
                    "Libérer la VRAM (Ollama hôte, autres tâches) ou WAMA_GPU_SAFE_MODE=0.")
        timeout = 1800 + int(duration) * 30
        with vram_reservation(f"composer.audiocpp:{os.getpid()}", besoin):
            if progress_callback:
                progress_callback(20)
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            queue = (proc.stderr or proc.stdout or '')[-2000:]
            raise RuntimeError(f"audiocpp_cli a échoué (code {proc.returncode}) : {queue}")
        if not Path(output_path).is_file():
            raise RuntimeError("audiocpp_cli s'est terminé sans produire le fichier de sortie")

        if progress_callback:
            progress_callback(90)
        if on_audio:
            try:
                import soundfile as sf
                audio_np, sr = sf.read(output_path)
                on_audio(audio_np, sr)
            except Exception:
                pass
        if progress_callback:
            progress_callback(100)
        return output_path
