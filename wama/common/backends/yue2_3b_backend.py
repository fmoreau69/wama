"""
Backend YuE2‑3B – moteur « yue ».

Les poids du modèle sont déjà installés ; on les récupère via
`component_paths('huggingface:m-a-p/YuE2-3B')` (rôle « model ») et le VAE via
`component_repos('huggingface:m-a-p/YuE2-3B')` (rôle « vae »).  
Le moteur est fourni sous forme de paquet vendorisé : le code se trouve dans
`settings.BACKEND_VENDOR_DIR/yue/` et s’importe avec
`self.import_vendored('<paquet>.<module>', subdir='src')`.  
Le backend charge une instance de `YuE2Pipeline` (vendored) et l’utilise pour
générer le fichier audio demandé. Le moteur ne supporte pas le paramètre
`melody_path` ; il ne contrôle pas directement la durée, on le signale dans le
log. La VRAM du processus est libérée à `unload()` via
`torch.cuda.set_per_process_memory_fraction(1.0)`.
"""

import logging
import os
from pathlib import Path
from typing import Callable, Optional

from .music_generation_base import MusicGenerationBackend, split_caption_lyrics

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Inventaire des modèles supportés (module‑level)
# ----------------------------------------------------------------------
SUPPORTED_MODELS = {
    "m-a-p/YuE2-3B": {
        "name": "YuE2‑3B",
        "description": "Frontier music generation model (text‑to‑music) with editable scores.",
        "vram": 8.8,
    },
}


class YuE2Backend(MusicGenerationBackend):
    """Backend pour le modèle YuE2‑3B (moteur « yue »)."""

    # ── métadonnées requises par le contrat commun ───────────────────────
    ENGINE = "yue"
    # `mido` (2026-10-01, route library) : lecture des partitions MIDI (`_midi_events`).
    REQUIRED_PACKAGES = ["torch", "soundfile", "mido"]
    name = "YuE2-3B"
    display_name = "YuE2‑3B – Text‑to‑Music"
    recommended_vram_gb = 8.8
    description = "YuE2‑3B – génération musicale à partir de texte, via le moteur yue."
    VENDORED = True
    #: La chaîne du moteur est déjà en deux temps (`YuE2Pipeline.plan()` → partition, puis le
    #: rendu qui la suit) : la card du composer les montre comme deux process (`plan_score`).
    supports_score_planning = True
    #: Graine fixe tant que le composer n'en fournit pas — la MÊME pour la partition et le rendu.
    SEED = 0

    # ------------------------------------------------------------------
    # Gestion du cycle de vie
    # ------------------------------------------------------------------
    def __init__(self):
        self._pipeline = None
        self._warm = False

    @property
    def is_loaded(self) -> bool:
        return self._warm

    def load(self, model: Optional[str] = None) -> bool:
        """
        Initialise le pipeline YuE2.

        Le paramètre *model* n’est pas utilisé ; le backend charge toujours le
        modèle déclaré dans le catalogue « huggingface:m-a-p/YuE2-3B ».
        """
        # Import du code vendorisé
        pipeline_mod = self.import_vendored("yue2.pipeline", subdir="src")
        YuE2Pipeline = getattr(pipeline_mod, "YuE2Pipeline")

        # Chemins des poids du modèle principal
        from wama.common.utils.model_components import component_paths, component_repos

        model_paths = component_paths("huggingface:m-a-p/YuE2-3B")
        if "model" not in model_paths:
            raise RuntimeError("Composant « model » introuvable pour YuE2‑3B")
        model_dir = model_paths["model"].parent

        # Chemins du VAE (déclaré comme dépôt séparé)
        repos = component_repos("huggingface:m-a-p/YuE2-3B")
        vae_info = repos.get("vae")
        if not vae_info:
            raise RuntimeError("Composant « vae » introuvable pour YuE2‑3B")
        vae_repo, vae_cache = vae_info

        # Instanciation du pipeline – on désactive le progress bar interne
        self._pipeline = YuE2Pipeline.from_pretrained(
            model=model_dir,
            vae=vae_repo,
            cache_dir=str(vae_cache),
            progress=False,
        )
        self._warm = True
        return True

    def unload(self) -> None:
        """Libère le pipeline et réinitialise la limite de VRAM du processus."""
        self._pipeline = None
        self._warm = False
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.set_per_process_memory_fraction(1.0)
                torch.cuda.empty_cache()
        except Exception:
            pass

    #: Le compilateur de partition DU MOTEUR (vendorisé, importé tel quel — jamais recopié) :
    #: notes → ABC dans le dialecte instrumental de YuE2 (mélodie en voix `Ins`).
    SCORE_COMPILER_DIR = "skills/yue2-music/instrumental/scripts"
    #: Grille de quantification : 1/8 de noire (= L:1/32), la grille binaire du compilateur.
    MIDI_GRID = 8

    @classmethod
    def _score_abc(cls, score_path: str) -> str:
        """Le texte ABC d'une partition — ou un refus qui DIT pourquoi.

        - `.abc` : donné tel quel ;
        - `.mid`/`.midi` (2026-10-01) : lu par `mido` (route `library`), réduit à UNE ligne
          mélodique (`_midi_events`), puis compilé par le compilateur du moteur — un
          convertisseur générique produirait un ABC hors des conventions de YuE2 ;
        - MusicXML : refusé en le disant (mido ne lit que le MIDI)."""
        suffix = Path(score_path).suffix.lower()
        if suffix in (".mid", ".midi"):
            compiler = cls.import_vendored("compile_score", subdir=cls.SCORE_COMPILER_DIR)
            try:
                text, _check = compiler.compile_events(cls._midi_events(score_path))
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"Partition MIDI non convertible pour YuE2 : {exc}") from exc
            return text
        if suffix != ".abc":
            raise ValueError(
                f"YuE2‑3B suit une partition ABC ou MIDI ; la conversion {suffix or 'de ce fichier'} → ABC "
                "n'est pas disponible (MusicXML : l'exporter en MIDI ou en ABC).")
        text = Path(score_path).read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            raise ValueError("La partition ABC fournie est vide.")
        return text

    @classmethod
    def _midi_events(cls, midi_path: str) -> dict:
        """Un fichier MIDI → les ÉVÉNEMENTS du compilateur du moteur (`event-schema.md`) :
        `{bpm, key, bars, notes}`, temps en noires (fractions sur la grille `MIDI_GRID`).

        Le compilateur n'accepte qu'UNE ligne mélodique : la polyphonie est réduite à la note la
        plus HAUTE de chaque attaque (ligne de dessus), chaque note s'arrête à l'attaque suivante,
        et la batterie (canal 10) est écartée. Tempo, mesure et tonalité : les premiers que le
        fichier déclare, sinon 120, 4/4, Do. Une seule consommatrice aujourd'hui — à extraire
        dans `common/` au second consommateur d'une lecture MIDI."""
        import math
        from fractions import Fraction

        import mido

        midi = mido.MidiFile(midi_path)
        tpb = midi.ticks_per_beat or 480
        tempo, meter, key = None, None, None
        started, notes, tick = {}, [], 0
        for msg in mido.merge_tracks(midi.tracks):
            tick += msg.time
            if msg.type == "set_tempo" and tempo is None:
                tempo = msg.tempo
            elif msg.type == "time_signature" and meter is None:
                meter = (msg.numerator, msg.denominator)
            elif msg.type == "key_signature" and key is None:
                key = msg.key
            elif msg.type in ("note_on", "note_off") and getattr(msg, "channel", 0) != 9:
                slot = (msg.channel, msg.note)
                if msg.type == "note_on" and msg.velocity > 0:
                    started.setdefault(slot, tick)
                elif slot in started:
                    notes.append((started.pop(slot), tick, msg.note))
        if not notes:
            raise ValueError("aucune note jouée dans le fichier MIDI (batterie exceptée)")

        def q(ticks):
            return Fraction(round(ticks * cls.MIDI_GRID / tpb), cls.MIDI_GRID)

        lead = {}
        for start, end, pitch in notes:
            s, e = q(start), q(end)
            e = max(e, s + Fraction(1, cls.MIDI_GRID))
            if s not in lead or pitch > lead[s][1]:
                lead[s] = (e, pitch)
        onsets = sorted(lead)
        events = []
        for i, s in enumerate(onsets):
            e, pitch = lead[s]
            if i + 1 < len(onsets):
                e = min(e, onsets[i + 1])
            events.append([str(s), str(e - s), int(pitch)])
        num, den = meter or (4, 4)
        bar = Fraction(4 * num, den)
        end = max(Fraction(ev[0]) + Fraction(ev[1]) for ev in events)
        n_bars = max(1, math.ceil(end / bar))
        try:
            compiler = cls.import_vendored("compile_score", subdir=cls.SCORE_COMPILER_DIR)
            compiler.key_accidentals(key or "C")
        except Exception:
            key = None                                   # tonalité illisible : Do, sans deviner
        return {
            "bpm": max(1, round(mido.tempo2bpm(tempo))) if tempo else 120,
            "key": key or "C",
            "bars": [{"meter": f"{num}/{den}"}] + [{} for _ in range(n_bars - 1)],
            "notes": events,
        }

    # ------------------------------------------------------------------
    # Partition (process `plan`)
    # ------------------------------------------------------------------
    def plan_score(self, model_id: str, prompt: str,
                   progress_callback: Optional[Callable[[int], None]] = None) -> str:
        """La partition ABC que le moteur écrit pour *prompt* — l'étape `plan()` de son pipeline,
        appelée seule. `generate(score_path=…)` la reprend telle quelle (« Using provided
        score ») : même découpe style/paroles, même graine, donc le même morceau qu'en un appel."""
        if not self.is_loaded:
            self.load()
        style, lyrics = split_caption_lyrics(prompt)
        if progress_callback:
            progress_callback(0)
        try:
            planned = self._pipeline.plan(style=style, lyrics=lyrics, cot="full", seed=self.SEED)
        except Exception as exc:
            logger.exception("Échec de la planification YuE2‑3B")
            raise RuntimeError(f"YuE2 score planning failed: {exc}") from exc
        text = (planned.abc or "").strip()
        if not text:
            raise RuntimeError("YuE2 n'a rendu aucune partition pour cette consigne.")
        if progress_callback:
            progress_callback(100)
        return text

    # ------------------------------------------------------------------
    # Génération
    # ------------------------------------------------------------------
    def generate(
        self,
        model_id: str,
        prompt: str,
        duration: float,
        output_path: str,
        melody_path: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        on_audio: Optional[Callable] = None,
        score_path: Optional[str] = None,
    ) -> str:
        """
        Génère un fichier audio à partir du *prompt*.

        - *model_id* : ignoré (le backend ne gère qu’un seul modèle : YuE2‑3B).
        - *prompt* : texte complet fourni par le compositeur ; on le découpe en
          style (caption) et paroles via :func:`split_caption_lyrics`.
        - *duration* : le moteur ne contrôle pas la durée ; on le consigne dans le log.
        - *melody_path* : non supporté ; une exception est levée si fourni.
        - *progress_callback* : reçoit 0 → 100 % approximatif.
        - *on_audio* : callback ``(numpy.ndarray, int)`` appelé une fois que le
          tableau audio final est disponible.
        """
        # *score_path* (port `reference_score`, 2026-10-01) : une partition ABC est donnée telle
        # quelle au pipeline (`abc=`, « Using provided score ») ; MIDI et MusicXML sont REFUSÉS
        # en le disant tant que leur conversion n'est pas câblée (`_score_abc`).
        abc = self._score_abc(score_path) if score_path else None
        if melody_path is not None:
            raise ValueError("YuE2‑3B ne supporte pas le paramètre melody_path")

        # Chargement paresseux si nécessaire
        if not self.is_loaded:
            self.load()

        # Découpage du prompt
        style, lyrics = split_caption_lyrics(prompt)

        # Le moteur ne gère pas explicitement la durée ; on le loggue.
        logger.info(
            "[YuE2Backend] durée demandée %.2f s – le moteur ne la contraint pas, il la traite comme borne",
            duration,
        )

        # Progression initiale
        if progress_callback:
            progress_callback(0)

        # Génération via le pipeline vendorisé
        # Le pipeline expose un appel direct (voir README du moteur) :
        #   pipe(style=..., lyrics=..., cot="full", seed=...)
        # On utilise un seed fixe (`SEED`) si le compositeur n’en fournit pas.
        seed = self.SEED
        try:
            # Le pipeline accepte les arguments *style* et *lyrics*.
            song_result = self._pipeline(
                style=style,
                lyrics=lyrics,
                cot="full",
                seed=seed,
                **({"abc": abc} if abc else {}),
            )
        except Exception as exc:
            logger.exception("Échec de la génération YuE2‑3B")
            raise RuntimeError(f"YuE2 generation failed: {exc}") from exc

        if progress_callback:
            progress_callback(80)

        # Sauvegarde du fichier audio
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        saved_path = song_result.save(output_path)

        # Callback audio (tableau numpy, fréquence d’échantillonnage)
        if on_audio:
            try:
                on_audio(song_result.audio, song_result.sample_rate)
            except Exception:
                logger.exception("Erreur dans le callback on_audio")

        if progress_callback:
            progress_callback(100)

        return str(saved_path)
