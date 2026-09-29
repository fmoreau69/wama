"""
Évaluer les moteurs du transcriber sur un corpus OUVERT, à la demande — `WAMA_QUALITE §9bis`.

RIEN D'INVENTÉ EN AVAL. La commande ne fait que PRÉPARER des entrées et poser des cards ; tout
le reste est la chaîne existante :
  · l'audio d'une réunion et sa référence entrent en MÉDIATHÈQUE SYSTÈME (natures `speech` et
    `document`, brique `media_library.system_files`) — une fois, pour tous ;
  · « comparer N moteurs = un LOT de N cards sur le même audio » : chaque card DÉSIGNE l'audio
    système (`add_to_transcriber` → `designate`, pas de copie), le lot porte la référence
    (`attach_reference`), le worker mesure à la fin (`result_evaluation.evaluate`) ;
  · les notes montent au model_manager par `internal_quality` (section « Qualité »), au
    protocole `text_v2`.

    # préparer 3 réunions du test (téléchargement temporaire, supprimé après usage)
    python manage.py asr_eval_corpus summ-re --meetings 3

    # et poser un lot par réunion dans la file de <login>, puis lancer
    python manage.py asr_eval_corpus summ-re --meetings 3 --user <login> --start

    # ajouter des CONFIGURATIONS au lot de chaque réunion (prétraitement, filtre de parole)
    python manage.py asr_eval_corpus summ-re --meetings 3 --user <login> --preprocess --start
    python manage.py asr_eval_corpus summ-re --meetings 3 --user <login> --engines whisper --vad off --start

UNE RÉUNION MIXÉE, PAS DES PISTES. SUMM-RE livre une piste micro-cravate par locuteur ; le cas
d'usage réel est un enregistrement de salle. Les pistes sont rééchantillonnées à 16 kHz,
sommées, normalisées en crête ; la référence fusionne leurs segments par instant de début.
⚠ Sur la parole SUPERPOSÉE, l'ordre des mots de la référence est celui des débuts de segments :
un moteur qui la rend dans un autre ordre y perd des mots. C'est un biais commun à tous les
moteurs du lot — il déplace le niveau, pas le classement.
"""
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

#: Moteurs comparés par défaut — clés de catalogue ou moteurs, comme les accepte la card.
DEFAULT_ENGINES = ('whisper', 'transcriber:qwen3-asr-1.7b', 'transcriber:canary-1b-v2',
                   'transcriber:parakeet-tdt-0.6b-v3')

#: Corpus déclarés : clé → manifeste `dataset` (la source, sa licence, sa langue y vivent).
CORPORA = {'summ-re': 'manifests/datasets/summ-re.json'}

SAMPLE_RATE = 16000
PEAK = 0.9


@dataclass
class Meeting:
    meeting_id: str
    files: set = field(default_factory=set)          # parquets qui portent ses pistes
    speakers: set = field(default_factory=set)
    tracks: dict = field(default_factory=dict)       # speaker → (échantillons 16 kHz, segments)


def asset_name(corpus: str, split: str, meeting_id: str) -> str:
    return f'{corpus}_{split}_{meeting_id}'


def reference_name(corpus: str, split: str, meeting_id: str) -> str:
    """Le document de référence se retrouve par son NOM : `<nom de l'audio>_reference`."""
    return f'{asset_name(corpus, split, meeting_id)}_reference'


def srt_time(seconds: float) -> str:
    ms = int(round(max(seconds, 0.0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def merged_srt(tracks: dict) -> str:
    """Les segments de toutes les pistes, triés par début, étiquetés `[Locuteur NNN]` — la forme
    que lit `transcript_documents.parse_cues` (l'étiquette n'entre pas dans le texte mesuré)."""
    cues = sorted(
        (seg['start'], seg['end'], speaker, ' '.join((seg.get('transcript') or '').split()))
        for speaker, (_, segments) in tracks.items() for seg in segments)
    blocks = [f'{i}\n{srt_time(start)} --> {srt_time(end)}\n[Locuteur {speaker}] {text}\n'
              for i, (start, end, speaker, text) in enumerate((c for c in cues if c[3]), 1)]
    return '\n'.join(blocks)


def mix_tracks(tracks: dict):
    """Somme des pistes (déjà à 16 kHz), complétées à la plus longue, normalisée en crête."""
    import numpy as np
    length = max(len(samples) for samples, _ in tracks.values())
    mix = np.zeros(length, dtype=np.float32)
    for samples, _ in tracks.values():
        mix[:len(samples)] += samples
    peak = float(np.abs(mix).max()) if length else 0.0
    if peak > 0:
        mix *= PEAK / peak
    return mix


def decode_track(wav_bytes: bytes):
    """WAV d'une piste → échantillons float32 mono à 16 kHz."""
    import io
    from math import gcd

    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    samples, rate = sf.read(io.BytesIO(wav_bytes), dtype='float32', always_2d=True)
    samples = samples.mean(axis=1)
    if rate != SAMPLE_RATE:
        g = gcd(SAMPLE_RATE, rate)
        samples = resample_poly(samples, SAMPLE_RATE // g, rate // g).astype(np.float32)
    return samples


class Command(BaseCommand):
    help = ("Prépare un corpus d'évaluation ASR ouvert en médiathèque système, et pose un lot "
            "de cards par enregistrement (un moteur par card, la référence sur le lot).")

    def add_arguments(self, parser):
        parser.add_argument('corpus', choices=sorted(CORPORA))
        parser.add_argument('--split', default='test')
        parser.add_argument('--meetings', type=int, default=3,
                            help="Nombre de réunions (dans l'ordre du corpus). Défaut : 3.")
        parser.add_argument('--user', help="Login : pose un lot par réunion dans SA file.")
        parser.add_argument('--engines', nargs='+', default=list(DEFAULT_ENGINES))
        parser.add_argument('--preprocess', action='store_true',
                            help="Cards avec le prétraitement audio (débruitage IA DeepFilterNet).")
        parser.add_argument('--vad', choices=('auto', 'on', 'off'), default='auto',
                            help="Filtre de parole de Whisper (sans effet sur les autres moteurs).")
        parser.add_argument('--start', action='store_true', help="Lance les cards posées.")
        parser.add_argument('--dry-run', action='store_true',
                            help="Plan seulement : quelles réunions, quels fichiers, rien d'écrit.")

    def handle(self, *args, **o):
        manifest = json.loads((Path(settings.BASE_DIR) / CORPORA[o['corpus']]).read_text('utf-8'))
        source = manifest['body']['source']
        meetings = self.plan(source, o['split'], o['meetings'])
        for m in meetings:
            self.stdout.write(f"  {m.meeting_id} : {len(m.speakers)} locuteurs, "
                              f"{len(m.files)} fichier(s)")
        if o['dry_run']:
            return
        assets = self.prepare(o['corpus'], source, o['split'], meetings)
        if o['user']:
            self.post_batches(o['user'], assets, o['engines'], o['start'],
                              preprocess=o['preprocess'], vad=o['vad'])

    # ── plan : quelles pistes, dans quels fichiers — sans rien télécharger ──────────────────
    def plan(self, source, split, count):
        """Lit la seule colonne `meeting_id`/`speaker_id` de chaque parquet (lecture par plages
        HTTP : le pied du fichier et deux petites colonnes, jamais l'audio)."""
        import pyarrow.parquet as pq
        from huggingface_hub import HfApi, HfFileSystem

        repo, revision = source['repo_id'], source.get('revision')
        files = sorted(f for f in HfApi().list_repo_files(repo, repo_type='dataset',
                                                         revision=revision)
                       if f.startswith(f'data/{split}/') and f.endswith('.parquet'))
        if not files:
            raise CommandError(f"aucun parquet sous data/{split}/ dans {repo}")
        fs = HfFileSystem()
        meetings = {}
        for name in files:
            with fs.open(f'datasets/{repo}@{revision}/{name}' if revision
                         else f'datasets/{repo}/{name}', 'rb') as fh:
                table = pq.ParquetFile(fh).read(columns=['meeting_id', 'speaker_id'])
            for meeting_id, speaker in zip(table.column('meeting_id').to_pylist(),
                                           table.column('speaker_id').to_pylist()):
                m = meetings.setdefault(meeting_id, Meeting(meeting_id))
                m.files.add(name)
                m.speakers.add(speaker)
            if len(meetings) > count:
                break                  # la réunion suivante a commencé : les N premières sont complètes
        chosen = list(meetings.values())[:count]
        self.stdout.write(f"{repo} [{split}] : {len(chosen)} réunion(s) retenue(s)")
        return chosen

    # ── préparation : télécharger, mixer, verser en médiathèque système ────────────────────
    def prepare(self, corpus, source, split, meetings):
        import io

        import pyarrow.parquet as pq
        import soundfile as sf
        from huggingface_hub import hf_hub_download

        from wama.media_library.models import SystemAsset
        from wama.media_library.system_files import ingest_system_file

        # Déjà en médiathèque : rien à retélécharger (la préparation est idempotente).
        todo = [m for m in meetings if not SystemAsset.objects.filter(
            asset_type='speech', name=asset_name(corpus, split, m.meeting_id)).exists()]
        needed = sorted({f for m in todo for f in m.files})
        wanted = {m.meeting_id: m for m in todo}
        work = Path(tempfile.mkdtemp(prefix=f'{corpus}_'))
        try:
            for name in needed:
                self.stdout.write(f"  téléchargement {name}")
                local = self.download(hf_hub_download, source, name, work)
                table = pq.read_table(local, columns=['meeting_id', 'speaker_id', 'audio',
                                                      'segments'])
                for row in table.to_pylist():
                    m = wanted.get(row['meeting_id'])
                    if m is not None:
                        m.tracks[row['speaker_id']] = (decode_track(row['audio']['bytes']),
                                                       row['segments'] or [])
                del table
                Path(local).unlink(missing_ok=True)            # jamais plus d'un parquet sur disque
                for m in [m for m in wanted.values() if m.speakers <= set(m.tracks)]:
                    self.ingest_meeting(corpus, source, split, m, work, ingest_system_file, sf)
                    del wanted[m.meeting_id]
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if wanted:
            raise CommandError(f"pistes incomplètes : {', '.join(sorted(wanted))}")
        return [SystemAsset.objects.get(asset_type='speech',
                                        name=asset_name(corpus, split, m.meeting_id))
                for m in meetings]

    def download(self, hf_hub_download, source, name, work, attempts=5):
        """Le Hub limite les appels (429, vécu le 2026-09-29 au 2ᵉ fichier, jeton compris) : on
        attend et on reprend, plutôt que d'abandonner une préparation à moitié faite."""
        import time
        for attempt in range(1, attempts + 1):
            try:
                return hf_hub_download(source['repo_id'], name, repo_type='dataset',
                                       revision=source.get('revision'), local_dir=work)
            except Exception as exc:
                if attempt == attempts or '429' not in repr(exc.__cause__ or exc) + repr(exc):
                    raise
                wait = 60 * attempt
                self.stdout.write(f"    429 du Hub — nouvel essai dans {wait} s")
                time.sleep(wait)

    def ingest_meeting(self, corpus, source, split, meeting, work, ingest_system_file, sf):
        name = asset_name(corpus, split, meeting.meeting_id)
        mix = mix_tracks(meeting.tracks)
        wav = work / f'{name}.wav'
        sf.write(str(wav), mix, SAMPLE_RATE, subtype='PCM_16')
        srt = work / f'{name}_reference.srt'
        srt.write_text(merged_srt(meeting.tracks), encoding='utf-8')
        common = {'source_url': f"https://huggingface.co/datasets/{source['repo_id']}",
                  'license': source.get('license', '')}
        ingest_system_file(
            'speech', name, wav, mime_type='audio/wav', duration=len(mix) / SAMPLE_RATE,
            attributes={'language': source.get('language', ''), 'speakers': len(meeting.tracks),
                        'corpus': corpus, 'split': split, 'recording': meeting.meeting_id},
            description=f"Réunion {meeting.meeting_id} ({corpus}, {split}) : "
                        f"{len(meeting.tracks)} pistes mixées à 16 kHz.", **common)
        ingest_system_file(
            'document', reference_name(corpus, split, meeting.meeting_id), srt,
            mime_type='application/x-subrip',
            description=f"Transcription de référence de {name} (segments des pistes fusionnés).",
            **common)
        wav.unlink(missing_ok=True)
        srt.unlink(missing_ok=True)
        meeting.tracks.clear()
        self.stdout.write(self.style.SUCCESS(f"  {name} versé en médiathèque ({len(mix) / SAMPLE_RATE / 60:.1f} min)"))

    # ── lots : un par réunion, une CONFIGURATION par card, la référence sur le lot ──────────
    def post_batches(self, login, assets, engines, start, *, preprocess=False, vad='auto'):
        """Une configuration = moteur × prétraitement × filtre de parole — exactement les
        réglages que l'évaluation distingue (`config_params` du transcriber). Un nouvel appel
        avec d'autres options AJOUTE ses cards au lot de la réunion : toutes les configurations
        d'une réunion se comparent au même endroit. Une configuration déjà posée ne l'est pas
        deux fois."""
        from django.contrib.auth import get_user_model
        from django.core.files import File

        from wama.common.services.result_evaluation import attach_reference
        from wama.common.utils.batch_common import attach_to_batch
        from wama.media_library.models import SystemAsset
        from wama.tool_api import add_to_transcriber, start_transcriber
        from wama.transcriber.models import BatchTranscript, BatchTranscriptItem, Transcript

        user = get_user_model().objects.filter(username=login).first()
        if user is None:
            raise CommandError(f"utilisateur inconnu : {login}")
        for asset in assets:
            on_audio = Transcript.objects.filter(user=user, audio=asset.file.name)
            link = (BatchTranscriptItem.objects.filter(transcript__in=on_audio)
                    .select_related('batch').order_by('batch_id').first())
            batch = link.batch if link else BatchTranscript.objects.create(user=user, total=0)
            row = (batch.items.order_by('-row_index').values_list('row_index', flat=True)
                   .first() or -1) + 1
            new_cards = []
            for engine in engines:
                # Le filtre de parole n'existe que chez Whisper (`workers._vad_filter_for`) :
                # le varier sur un autre moteur poserait deux fois la même configuration.
                engine_vad = vad if engine == 'whisper' else 'auto'
                if on_audio.filter(backend=engine, preprocess_audio=preprocess,
                                   vad_mode=engine_vad).exists():
                    continue
                # Diarisation coupée : elle ne change pas le texte mesuré, seulement le temps.
                result = add_to_transcriber(user, asset.file.name, backend=engine,
                                            enable_diarization=False,
                                            preprocess_audio=preprocess, vad_mode=engine_vad)
                if 'error' in result:
                    raise CommandError(f"{asset.name} / {engine} : {result['error']}")
                card = Transcript.objects.get(pk=result['transcript_id'])
                attach_to_batch(card, batch, row, item_model=BatchTranscriptItem,
                                fk_name='transcript')
                row += 1
                new_cards.append(card)
            if not new_cards:
                self.stdout.write(f"  {asset.name} : configuration déjà posée (lot #{batch.pk})")
                continue
            reference = SystemAsset.objects.get(asset_type='document',
                                                name=f'{asset.name}_reference')
            # Toutes les cards du lot : le fichier de référence reste UN, partagé (le poser sur
            # les seules nouvelles en ferait une seconde copie).
            cards = [item.transcript for item in batch.items.select_related('transcript')]
            with open(reference.file.path, 'rb') as fh:
                attach_reference('transcriber', cards,
                                 File(fh, name=Path(reference.file.name).name))
            self.stdout.write(self.style.SUCCESS(
                f"  lot #{batch.pk} : {asset.name}, +{len(new_cards)} cards "
                f"(#{new_cards[0].pk}–#{new_cards[-1].pk})"))
            if start:
                for card in new_cards:
                    started = start_transcriber(user, card.pk)
                    if 'error' in started:
                        self.stderr.write(f"    #{card.pk} : {started['error']}")
