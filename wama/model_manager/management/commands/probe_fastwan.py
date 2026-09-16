"""
Sonde FastWan 2.2 TI2V 5B SANS `fastvideo` — préparer le test (à blanc), puis le jouer (GPU).

POURQUOI (demande de Fabien, 2026-09-14)
    Le snapshot déclare `_class_name = WanDMDPipeline`, absent de diffusers 0.37 : il vient du
    paquet `fastvideo`, dont l'installation casse le venv partagé (torch 2.12, transformers 5.x
    qui emporterait les patches Higgs — PROJECT_STATUS §CLÔTURE 08→09/09, décision en attente).
    Or TOUS ses composants sont des classes standard (`WanTransformer3DModel`, `AutoencoderKLWan`,
    `UMT5EncoderModel`, `UniPCMultistepScheduler`), et le constructeur de `WanPipeline` prend
    exactement les clés de son `model_index.json`. HYPOTHÈSE : `WanPipeline` + un pas DMD suffit.

DEUX TEMPS
    (défaut) À BLANC — AUCUN GPU, AUCUN poids. Exige `CUDA_VISIBLE_DEVICES=""` : torch ne voit
        alors aucune carte, aucun contexte CUDA ne peut naître (crashs hôte : la rampe d'init CUDA
        est le facteur commun). Vérifie : chemin catalogue, clés du model_index ↔ signature de
        `WanPipeline`, classes présentes dans CE venv, configurations chargeables, paramètres
        comptés sur le périphérique `meta` (estimation mémoire), cohérence du pas DMD sur CPU.
    --generate — GPU, pour Fabien, machine sous les yeux. Refusé sous `WAMA_GPU_SAFE_MODE` et
        sans `--confirm-gpu`. Déchargement CPU activé (le catalogue estime 29 Go > 24 Go).

L'ÉCHANTILLONNAGE DMD (réglages du README du dépôt : 3 pas `1000,757,522`)
    ⚠ HYPOTHÈSE À VALIDER AU GPU : sigma = t / 1000 (flow matching), prédiction de flux
    v = bruit − x0, donc x0 = x_t − sigma·v ; au pas suivant x = (1 − sigma')·x0 + sigma'·bruit
    NEUF. Sans CFG (modèle distillé). `--sampler unipc3` joue le scheduler DÉCLARÉ à 3 pas, pour
    comparer les deux voies à graine égale.

À lancer depuis WSL2 (venv_linux) — Windows n'a pas le droit de lire le snapshot :
    CUDA_VISIBLE_DEVICES= venv_linux/bin/python manage.py probe_fastwan
"""
import importlib
import inspect
import json
import os
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

#: Identifiant du modèle dans l'imager ET dans le backend Wan (2026-09-15). Le pas DMD, son
#: scheduler et le dossier des poids vivent désormais dans `wan_video_backend` : la sonde les
#: IMPORTE, pour tester exactement ce que l'imager exécutera.
MODEL_ID = 'fastwan-2.2-ti2v-5b'
#: Clé de CATALOGUE du même modèle : la sonde résout son backend par elle
#: (`backend_for_key`), elle n'importe aucune classe par son chemin — budget `ROUTE §10.3`,
#: tenu par `tests_backend_adoption`. Le MODÈLE porte son moteur, le backend s'en dérive.
CATALOG_KEY = f'imager:{MODEL_ID}'
#: Prompt négatif du README (il n'agit qu'avec du CFG ; gardé pour la comparaison).
NEGATIF = ("Bright tones, overexposed, static, blurred details, subtitles, style, works, "
           "paintings, images, static, overall gray, worst quality, low quality, JPEG compression "
           "residue, ugly, incomplete, extra fingers, poorly drawn hands, poorly drawn faces, "
           "deformed, disfigured, misshapen limbs, fused fingers, still picture, messy background, "
           "three legs, many people in the background, walking backwards")


class Command(BaseCommand):
    help = "Sonde FastWan 2.2 sans fastvideo : à blanc (défaut, sans GPU) ou --generate (GPU)."

    def add_arguments(self, parser):
        parser.add_argument('--generate', action='store_true',
                            help="Génère une vidéo (GPU). Exige --confirm-gpu et --out.")
        parser.add_argument('--confirm-gpu', action='store_true',
                            help="Confirmation explicite de la charge GPU.")
        parser.add_argument('--sampler', choices=('dmd', 'unipc3'), default='dmd')
        parser.add_argument('--prompt', default="A red fox running through snowy woods at dawn")
        parser.add_argument('--out', help="Fichier .mp4 de sortie (hors media/).")
        parser.add_argument('--height', type=int, default=480)
        parser.add_argument('--width', type=int, default=832)
        parser.add_argument('--frames', type=int, default=49, help="4k+1 (49, 81, 121…)")
        parser.add_argument('--seed', type=int, default=1024)
        parser.add_argument('--fps', type=int, default=24)

    # ── commun ──────────────────────────────────────────────────────────────────────────────
    def _snapshot(self) -> Path:
        # Même résolution que le backend (dossier du profil + dépôt déclaré) : la sonde teste
        # les poids que l'imager chargera, pas une ligne de catalogue.
        from wama.common.backends.manager import backend_for_key
        backend = backend_for_key(CATALOG_KEY)
        if backend is None:
            raise CommandError(f"{CATALOG_KEY} : aucun backend résolu par le catalogue "
                               f"(modèle absent, sans moteur déclaré, ou base indisponible)")
        hf_id = backend.SUPPORTED_MODELS[MODEL_ID][1]
        racine = Path(backend.cache_dir_for(MODEL_ID)) / f"models--{hf_id.replace('/', '--')}"
        snaps = sorted((racine / 'snapshots').glob('*'))
        if not snaps:
            raise CommandError(f"aucun snapshot sous {racine}")
        return snaps[-1]

    def _ok(self, ok, msg):
        self.stdout.write((self.style.SUCCESS('  ✓ ') if ok else self.style.ERROR('  ✗ ')) + msg)
        return ok

    def handle(self, *args, **o):
        if o['generate']:
            return self._generer(o)
        return self._a_blanc()

    # ── à blanc ─────────────────────────────────────────────────────────────────────────────
    def _a_blanc(self):
        if os.environ.get('CUDA_VISIBLE_DEVICES', None) != '':
            raise CommandError('le mode à blanc exige CUDA_VISIBLE_DEVICES="" (aucune carte '
                               'visible, donc aucun contexte CUDA possible)')
        import torch
        from accelerate import init_empty_weights
        from diffusers import WanPipeline
        from wama.common.backends.wan_video_backend import (
            FASTWAN_DMD_TIMESTEPS, dmd_step, make_dmd_scheduler)

        snap = self._snapshot()
        self.stdout.write(f"Snapshot : {snap}")
        bilan = []
        index = json.loads((snap / 'model_index.json').read_text(encoding='utf-8'))
        bilan.append(self._ok(True, f"pipeline déclaré : {index.get('_class_name')} "
                                    f"(absent de diffusers — attendu)"))

        attendus = {p for p in inspect.signature(WanPipeline.__init__).parameters if p != 'self'}
        declares = {k for k in index if not k.startswith('_')}
        bilan.append(self._ok(attendus == declares,
                              f"clés du model_index ↔ WanPipeline : écart {sorted(attendus ^ declares) or 'aucun'}"))

        for nom, valeur in index.items():
            if isinstance(valeur, list) and len(valeur) == 2 and valeur[0]:
                lib, cls = valeur
                try:
                    getattr(importlib.import_module(lib), cls)
                    bilan.append(self._ok(True, f"{nom} : {lib}.{cls} présent dans ce venv"))
                except (ImportError, AttributeError) as e:
                    bilan.append(self._ok(False, f"{nom} : {lib}.{cls} ABSENT ({e})"))

        total = 0
        from diffusers import AutoencoderKLWan, WanTransformer3DModel
        from transformers import AutoConfig, UMT5EncoderModel
        for nom, charger in (
            ('transformer', lambda: WanTransformer3DModel.from_config(
                WanTransformer3DModel.load_config(snap / 'transformer'))),
            ('vae', lambda: AutoencoderKLWan.from_config(
                AutoencoderKLWan.load_config(snap / 'vae'))),
            ('text_encoder', lambda: UMT5EncoderModel(
                AutoConfig.from_pretrained(snap / 'text_encoder'))),
        ):
            try:
                with init_empty_weights():
                    modele = charger()
                n = sum(p.numel() for p in modele.parameters())
                total += n
                bilan.append(self._ok(True, f"{nom} : {n / 1e9:.2f} Md paramètres "
                                            f"(~{n * 2 / 1e9:.1f} Go en bf16)"))
            except Exception as e:
                bilan.append(self._ok(False, f"{nom} : configuration inchargeable ({e})"))
        self.stdout.write(f"  → total ~{total * 2 / 1e9:.1f} Go en bf16 (hors activations) — "
                          f"déchargement CPU prévu au mode --generate")

        # Cohérence du pas DMD sur tenseurs CPU : x_t construit à partir de x0 connu.
        g = torch.Generator().manual_seed(0)
        x0 = torch.randn(1, 4, 2, 8, 8, generator=g)
        bruit = torch.randn(x0.shape, generator=g)
        s = 757 / 1000
        x_t = (1 - s) * x0 + s * bruit
        v = bruit - x0
        final = dmd_step(v, x_t, 757, None)
        neuf = torch.randn(x0.shape, generator=g)
        suite = dmd_step(v, x_t, 757, 522, neuf)
        bilan.append(self._ok(torch.allclose(final, x0, atol=1e-5)
                              and torch.allclose(suite, 0.478 * x0 + 0.522 * neuf, atol=1e-5),
                              "pas DMD : x0 retrouvé, re-bruitage au pas suivant cohérent"))
        sch = make_dmd_scheduler(generator=torch.Generator().manual_seed(0))
        sch.set_timesteps(3)
        bilan.append(self._ok([int(t) for t in sch.timesteps] == list(FASTWAN_DMD_TIMESTEPS)
                              and sch.config.num_train_timesteps == 1000,
                              f"scheduler DMD : pas {[int(t) for t in sch.timesteps]}"))

        bilan.append(self._ok(not torch.cuda.is_initialized(), "aucun contexte CUDA créé"))
        if not all(bilan):
            raise CommandError("sonde à blanc : au moins un contrôle en échec")
        self.stdout.write(self.style.SUCCESS("Sonde à blanc OK — le test GPU est prêt : "
                                             "probe_fastwan --generate --confirm-gpu --out …"))

    # ── GPU ─────────────────────────────────────────────────────────────────────────────────
    def _generer(self, o):
        if os.environ.get('WAMA_GPU_SAFE_MODE', '').strip() not in ('', '0', 'false', 'False'):
            raise CommandError("refusé sous WAMA_GPU_SAFE_MODE")
        if not o['confirm_gpu']:
            raise CommandError("charge GPU : ajouter --confirm-gpu (machine sous les yeux)")
        if not o['out']:
            raise CommandError("--out requis (un .mp4 hors de media/)")
        if (o['frames'] - 1) % 4:
            raise CommandError("--frames doit valoir 4k+1 (49, 81, 121…)")

        import torch
        from diffusers import WanPipeline
        from diffusers.utils import export_to_video
        from wama.common.backends.wan_video_backend import (
            FASTWAN_DMD_TIMESTEPS, make_dmd_scheduler)

        snap = self._snapshot()
        generateur = torch.Generator('cpu').manual_seed(o['seed'])
        extra = ({'scheduler': make_dmd_scheduler(generator=generateur)}
                 if o['sampler'] == 'dmd' else {})
        debut = time.monotonic()
        pipe = WanPipeline.from_pretrained(str(snap), torch_dtype=torch.bfloat16, **extra)
        pipe.enable_model_cpu_offload()
        self.stdout.write(f"Chargé en {time.monotonic() - debut:.0f} s — sampler {o['sampler']}")

        debut = time.monotonic()
        video = pipe(prompt=o['prompt'], negative_prompt=NEGATIF, height=o['height'],
                     width=o['width'], num_frames=o['frames'], num_inference_steps=len(FASTWAN_DMD_TIMESTEPS),
                     guidance_scale=1.0, generator=generateur).frames[0]
        export_to_video(video, o['out'], fps=o['fps'])
        self.stdout.write(self.style.SUCCESS(
            f"Vidéo écrite : {o['out']} ({time.monotonic() - debut:.0f} s de génération)"))
