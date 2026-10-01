"""
Évaluer les moteurs du transcriber sur un corpus OUVERT, à la demande — `WAMA_QUALITE §9bis`.

RIEN D'INVENTÉ EN AVAL. La commande ne fait que PRÉPARER des entrées et poser des cards ; tout
le reste est la chaîne existante :
  · l'audio d'un enregistrement et sa référence entrent en MÉDIATHÈQUE SYSTÈME (natures `speech`
    et `document`, brique `media_library.system_files`) — une fois, pour tous ;
  · « comparer N moteurs = un LOT de N cards sur le même audio » : chaque card DÉSIGNE l'audio
    système (`add_to_transcriber` → `designate`, pas de copie), le lot porte la référence
    (`attach_reference`), le squelette commun mesure à la fin (`result_evaluation.evaluate`) ;
  · les notes montent au model_manager par `internal_quality` (section « Qualité »), au
    protocole `text_v2`.

    # préparer 3 réunions de SUMM-RE (téléchargement temporaire, supprimé après usage)
    python manage.py asr_eval_corpus summ-re --recordings 3

    # et poser un lot par enregistrement dans la file de <login>, puis lancer
    python manage.py asr_eval_corpus summ-re --recordings 3 --user <login> --start

    # ajouter des CONFIGURATIONS au lot de chaque enregistrement
    python manage.py asr_eval_corpus summ-re --recordings 3 --user <login> --preprocess --start
    python manage.py asr_eval_corpus summ-re --recordings 3 --user <login> --engines whisper --vad off --start

    # FLEURS-CS : enregistrements qui CHANGENT de langue, choisis par leurs langues
    python manage.py asr_eval_corpus fleurs-cs --require fr,en --exact --recordings 8 --user <login> --language-mode multi

    # tableau des mesures des cards posées (erreur par mot, accord de langue)
    python manage.py asr_eval_corpus fleurs-cs --require fr,en --exact --recordings 8 --user <login> --report

    # BANC DES PRÉTRAITEMENTS (2026-09-30) : SUMM-RE sous dégradation CONTRÔLÉE, et un corpus RÉEL
    # de qualité moyenne (CFPP2000) pour vérifier que la dégradation prédit la même chose
    python manage.py asr_eval_corpus summ-re --user <login> --engines whisper --degrade noise_snr15 far_field --start
    python manage.py asr_eval_corpus cfpp --recordings 3 --user <login> --engines whisper --level --start
    # l'ordre « nivellement PUIS débruitage » sans toucher au worker : audio nivelé d'avance
    python manage.py asr_eval_corpus cfpp --recordings 3 --user <login> --engines whisper --leveled-input --preprocess --start

DEUX CORPUS, DEUX LECTURES, UNE CHAÎNE :
  · **SUMM-RE** — une RÉUNION MIXÉE, pas des pistes. Le corpus livre une piste micro-cravate par
    locuteur ; le cas d'usage réel est un enregistrement de salle. Les pistes sont
    rééchantillonnées à 16 kHz, sommées, normalisées en crête ; la référence fusionne leurs
    segments par instant de début. ⚠ Sur la parole SUPERPOSÉE, l'ordre des mots de la référence
    est celui des débuts de segments : biais commun à tous les moteurs du lot (niveau, pas classement).
  · **FLEURS-CS** — des phrases lues de FLEURS mises bout à bout en 2 à 8 langues (≥ 5 min).
    Chaque phrase porte sa langue et ses temps : la référence est un WebVTT dont chaque réplique
    marque sa langue (`<lang fr>…</lang>`, balisage STANDARD de WebVTT) — le lecteur du
    transcriber l'ôte du texte mesuré et la rend par segment, ce qui mesure l'ACCORD de langue.
    ⚠ Bascules SYNTHÉTIQUES (locuteurs différents, aucune transition naturelle), et plus
    fréquentes (8-15 s) que la fenêtre de décision de langue (30 s) : ce corpus mesure la LIMITE
    de cette fenêtre, pas un usage courant.
"""
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

#: Modèles comparés par défaut — clés de catalogue, comme la card les stocke (un ancien nom de
#: moteur passé à `--engines` est encore lu : `catalogue_value`). Un distant se passe par sa clé
#: (`--engines albert:whisper-large-v3`) : il est appelé avec la clé Albert de `--user`.
DEFAULT_ENGINES = ('transcriber:whisper', 'transcriber:qwen3-asr-1.7b', 'transcriber:canary-1b-v2',
                   'transcriber:parakeet-tdt-0.6b-v3')

#: Corpus déclarés : clé → manifeste `dataset` (la source, sa licence, sa langue y vivent).
CORPORA = {'summ-re': 'manifests/datasets/summ-re.json',
           'fleurs-cs': 'manifests/datasets/fleurs-cs.json',
           'cfpp': 'manifests/datasets/cfpp.json'}

#: Séparateur des variantes dérivées d'un enregistrement :
#: `<audio>[__<profil>][__leveled][__resemble-<mode>]`.
VARIANT_SEPARATOR = '__'
#: Modes de Resemble Enhance (branche audio de l'enhancer, `run_audio_enhancement`) mesurés par le
#: banc : l'AMÉLIORATION seule, et amélioration + débruitage. Le prétraitement du transcriber, lui,
#: n'est que le débruitage DeepFilterNet (`utils/audio_preprocessor.py`) — c'est lui que mesurent
#: `--preprocess` et les premières colonnes du banc (2026-10-01, remarque de Fabien).
ENHANCE_MODES = ('enhance', 'both')
#: CFPP : entretiens retenus entre 10 et 75 min (un enregistrement de quelques minutes est un
#: fragment, un de plus d'une heure et quart coûte trop de GPU par configuration).
CFPP_MIN_SECONDS, CFPP_MAX_SECONDS = 600, 4500
#: Durée ESTIMÉE d'un MP3 de l'archive par sa taille (≈ 128 kbit/s, mesuré : 45 Mo pour 47 min).
#: Lire les 42 fiches Dublin Core coûtait une requête chacune au Hub : 429 dès le plan
#: (2026-09-30). L'estimation ne sert qu'à CHOISIR ; la durée versée est celle du décodage.
MP3_BYTES_PER_SECOND = 16000
#: Lecture de l'archive par blocs de 32 Mo : un MP3 de 100 Mo = 4 requêtes, pas 100.
ARCHIVE_BLOCK_BYTES = 32 << 20

SAMPLE_RATE = 16000
PEAK = 0.9


@dataclass
class Recording:
    """Un enregistrement du corpus : où le lire (fichiers, blocs), et ce qu'on en a lu."""
    recording_id: str
    files: set = field(default_factory=set)          # parquets qui le portent
    speakers: set = field(default_factory=set)       # SUMM-RE : pistes attendues
    languages: list = field(default_factory=list)    # FLEURS-CS : langues annoncées
    row_group: tuple = None                          # FLEURS-CS : (fichier, bloc)
    tracks: dict = field(default_factory=dict)       # SUMM-RE : speaker → (échantillons, segments)
    seconds: float = None                            # CFPP : durée ESTIMÉE (taille du mp3)


def asset_name(corpus: str, split: str, recording_id: str) -> str:
    return f'{corpus}_{split}_{recording_id}'


def reference_name(corpus: str, split: str, recording_id: str) -> str:
    """Le document de référence se retrouve par son NOM : `<nom de l'audio>_reference`."""
    return f'{asset_name(corpus, split, recording_id)}_reference'


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


def is_masked_transcript(text: str) -> bool:
    """Une piste « transcrite » par des JETONS seulement (`sil`, `w_1`, `w_2`…) : sa parole est
    dans l'audio mais pas dans la référence. Au-delà de 90 % de jetons, la piste est masquée."""
    import re
    tokens = (text or '').split()
    if not tokens:
        return False
    placeholders = sum(1 for t in tokens if re.fullmatch(r'sil|w_\d+', t))
    return placeholders / len(tokens) > 0.9


def tagged_spans(tagged: str) -> list:
    """`<fr><start:11.64>texte<end:19.44>…` (FLEURS-CS) → [(début, fin, langue, texte)]."""
    import re
    return [(float(start), float(end), lang, ' '.join(text.split()))
            for lang, start, text, end in re.findall(
                r'<([a-z]{2,3})><start:([\d.]+)>(.*?)<end:([\d.]+)>', tagged or '', re.S)]


def language_vtt(spans: list) -> str:
    """Les répliques d'un enregistrement multilingue en WebVTT, langue marquée `<lang xx>`."""
    blocks = ['WEBVTT\n']
    for i, (start, end, lang, text) in enumerate((s for s in spans if s[3]), 1):
        blocks.append(f"{i}\n{srt_time(start).replace(',', '.')} --> "
                      f"{srt_time(end).replace(',', '.')}\n<lang {lang}>{text}</lang>\n")
    return '\n'.join(blocks)


def languages_by_time(spans: list) -> list:
    """Les langues d'un enregistrement, la plus parlée d'abord."""
    seconds = {}
    for start, end, lang, _ in spans:
        seconds[lang] = seconds.get(lang, 0.0) + max(0.0, end - start)
    return sorted(seconds, key=seconds.get, reverse=True)


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


def resampled(samples, rate: int):
    """Échantillons mono → float32 à 16 kHz (le décodeur commun garde parfois la fréquence
    d'origine : sa branche soundfile ne rééchantillonne pas, `audio_decode.decode_audio`)."""
    from math import gcd

    import numpy as np
    from scipy.signal import resample_poly
    samples = np.asarray(samples, dtype=np.float32)
    if rate != SAMPLE_RATE:
        g = gcd(SAMPLE_RATE, int(rate))
        samples = resample_poly(samples, SAMPLE_RATE // g, int(rate) // g).astype(np.float32)
    return samples


def decode_track(wav_bytes: bytes):
    """Audio encodé → échantillons float32 mono à 16 kHz."""
    import io

    import soundfile as sf
    samples, rate = sf.read(io.BytesIO(wav_bytes), dtype='float32', always_2d=True)
    return resampled(samples.mean(axis=1), rate)


def trs_cues(content: bytes) -> list:
    """Transcription au format TRANSCRIBER (`.trs`) → [(début, fin, n° de locuteur, texte)].

    Un tour (`Turn`) est découpé par ses `Sync` : chaque marque ouvre un passage qui court jusqu'à
    la suivante (ou la fin du tour). Un tour à plusieurs locuteurs (`speaker="spk1 spk2"`) donne
    la parole à chacun par `Who nb=…` sur le même passage — parole SUPERPOSÉE, donc deux répliques
    aux mêmes temps. Les `Event` (pauses, bruits, « mm mm ») et les `Comment` sont des
    annotations, pas des mots : ils sont retirés. Les locuteurs sont NUMÉROTÉS dans leur ordre de
    déclaration — le fichier porte leurs vrais noms, qui ne sont jamais recopiés.
    """
    import xml.etree.ElementTree as ET
    root = ET.fromstring(content)
    number = {s.get('id'): index for index, s in enumerate(root.iter('Speaker'), 1)}
    cues = []
    for turn in root.iter('Turn'):
        ids = (turn.get('speaker') or '').split()
        turn_end = float(turn.get('endTime') or 0)
        start = float(turn.get('startTime') or 0)
        speaker = ids[0] if ids else ''
        block = []                                      # [(locuteur, [mots])] du passage courant

        def say(text):
            if text and text.strip():
                if not block or block[-1][0] != speaker:
                    block.append((speaker, []))
                block[-1][1].append(text)

        def close(end):
            for who, words in block:
                text = ' '.join(' '.join(words).split())
                if text and who in number and end > start:
                    cues.append((start, end, number[who], text))
            block.clear()

        say(turn.text)
        for child in turn:
            if child.tag == 'Sync':
                close(float(child.get('time') or start))
                start = float(child.get('time') or start)
            elif child.tag == 'Who':
                index = int(child.get('nb') or 1) - 1
                speaker = ids[index] if 0 <= index < len(ids) else speaker
            say(child.tail)
        close(turn_end)
    return sorted(cues)


def cues_srt(cues: list) -> str:
    """Répliques `(début, fin, n°, texte)` → SRT étiqueté `[Locuteur N]` (lu par `parse_cues`)."""
    return '\n'.join(f'{i}\n{srt_time(start)} --> {srt_time(end)}\n[Locuteur {who}] {text}\n'
                     for i, (start, end, who, text) in enumerate(cues, 1))


def select_by_languages(candidates: list, require: set, exact: bool, count: int = None) -> list:
    """Les enregistrements dont les langues CONTIENNENT `require` (ou lui sont ÉGALES avec
    `exact`), et en comptent `count` si donné — dans l'ordre du corpus."""
    out = []
    for rec in candidates:
        langs = set(rec.languages)
        if require and not require <= langs:
            continue
        if exact and langs != require:
            continue
        if count and len(langs) != count:
            continue
        out.append(rec)
    return out


class Command(BaseCommand):
    help = ("Prépare un corpus d'évaluation ASR ouvert en médiathèque système, et pose un lot "
            "de cards par enregistrement (une configuration par card, la référence sur le lot).")

    def add_arguments(self, parser):
        parser.add_argument('corpus', choices=sorted(CORPORA))
        parser.add_argument('--split', default='test')
        parser.add_argument('--recordings', '--meetings', dest='recordings', type=int, default=3,
                            help="Nombre d'enregistrements (dans l'ordre du corpus). Défaut : 3.")
        parser.add_argument('--require', default='',
                            help="FLEURS-CS : langues exigées, séparées par des virgules (fr,en).")
        parser.add_argument('--exact', action='store_true',
                            help="FLEURS-CS : exactement les langues de --require, aucune autre.")
        parser.add_argument('--languages-count', type=int,
                            help="FLEURS-CS : nombre de langues de l'enregistrement.")
        parser.add_argument('--user', help="Login : pose un lot par enregistrement dans SA file.")
        parser.add_argument('--engines', nargs='+', default=list(DEFAULT_ENGINES))
        parser.add_argument('--preprocess', action='store_true',
                            help="Cards avec le prétraitement audio (débruitage IA DeepFilterNet).")
        parser.add_argument('--level', action='store_true',
                            help="Cards avec le nivellement de la parole (`speech_leveling`).")
        parser.add_argument('--vad', choices=('auto', 'on', 'off'), default='auto',
                            help="Filtre de parole des moteurs qui le déclarent (Whisper, "
                                 "Albert) ; sans effet sur les autres.")
        parser.add_argument('--language-mode', nargs='+', choices=('auto', 'single', 'multi'),
                            default=['auto'],
                            help="Réglage(s) « Langues parlées » des cards posées — plusieurs "
                                 "valeurs posent une configuration par valeur.")
        parser.add_argument('--diarization', nargs='+', metavar='PIPELINE',
                            help="Pipeline(s) de diarisation (pyannote : speaker-diarization-3.1, "
                                 "speaker-diarization-community-1) — une configuration par "
                                 "pipeline, mesurée en cpWER et DER. Absent : diarisation coupée.")
        from wama.common.utils.audio_degradation import PROFILES
        parser.add_argument('--degrade', nargs='+', choices=sorted(PROFILES), metavar='PROFILE',
                            help="Pose les cards sur des VARIANTES dégradées de chaque "
                                 "enregistrement (profils déclarés de `audio_degradation` : "
                                 f"{', '.join(sorted(PROFILES))}) — même référence que l'original.")
        parser.add_argument('--leveled-input', action='store_true',
                            help="Pose les cards sur l'audio (ou la variante) NIVELÉ d'avance : "
                                 "avec --preprocess, c'est l'ordre « nivellement puis débruitage ».")
        parser.add_argument('--enhance-input', choices=ENHANCE_MODES,
                            help="Pose les cards sur l'audio AMÉLIORÉ d'avance par Resemble Enhance "
                                 "(branche audio de l'enhancer) : « enhance » = amélioration seule, "
                                 "« both » = amélioration + débruitage. Après le nivellement si "
                                 "--leveled-input.")
        parser.add_argument('--start', action='store_true', help="Lance les cards posées.")
        parser.add_argument('--report', action='store_true',
                            help="Tableau des mesures des cards de --user sur ces enregistrements.")
        parser.add_argument('--dry-run', action='store_true',
                            help="Plan seulement : quels enregistrements, quels fichiers, rien d'écrit.")

    def handle(self, *args, **o):
        corpus = o['corpus']
        manifest = json.loads((Path(settings.BASE_DIR) / CORPORA[corpus]).read_text('utf-8'))
        source = manifest['body']['source']
        require = {x.strip() for x in o['require'].split(',') if x.strip()}
        if corpus == 'summ-re':
            recordings = self.plan_meetings(source, o['split'], o['recordings'])
        elif corpus == 'cfpp':
            o['split'] = 'all'                           # le corpus n'a pas de partition
            recordings = self.plan_archive(source, o['recordings'])
        else:
            recordings = self.plan_tagged(source, o['split'], o['recordings'], require,
                                          o['exact'], o['languages_count'])
        for r in recordings:
            detail = (f"{len(r.speakers)} locuteurs" if r.speakers
                      else f"~{r.seconds / 60:.0f} min (estimé)" if r.seconds
                      else f"langues {','.join(r.languages)}")
            self.stdout.write(f"  {r.recording_id} : {detail}, {len(r.files)} fichier(s)")
        if o['dry_run']:
            return
        if o['report']:
            return self.report(o['user'], corpus, o['split'], recordings)
        if corpus == 'summ-re':
            assets = self.prepare_meetings(corpus, source, o['split'], recordings)
        elif corpus == 'cfpp':
            assets = self.prepare_archive(corpus, source, o['split'], recordings)
        else:
            assets = self.prepare_tagged(corpus, source, o['split'], recordings)
        assets = [self.variant(asset, profile, o['leveled_input'], o['enhance_input'])
                  for asset in assets for profile in (o['degrade'] or [None])]
        if o['user']:
            from wama.common.backends.pyannote_diarizer import pipeline_choices
            served = [model_id for model_id, _ in pipeline_choices()]
            unknown = [p for p in o['diarization'] or () if p not in served]
            if unknown:
                raise CommandError(f"pipeline(s) inconnu(s) : {unknown} — servis : {served}")
            for language_mode in o['language_mode']:
                for diarization in o['diarization'] or [None]:
                    self.post_batches(o['user'], assets, o['engines'], o['start'],
                                      preprocess=o['preprocess'], level=o['level'], vad=o['vad'],
                                      language_mode=language_mode, diarization=diarization)

    # ── accès au Hub ───────────────────────────────────────────────────────────────────────
    def _parquets(self, source, split):
        from huggingface_hub import HfApi
        listing = self.with_retry(lambda: HfApi().list_repo_files(
            source['repo_id'], repo_type='dataset', revision=source.get('revision')))
        files = sorted(f for f in listing
                       if f.startswith(f'data/{split}') and f.endswith('.parquet'))
        if not files:
            raise CommandError(f"aucun parquet sous data/{split} dans {source['repo_id']}")
        return files

    @staticmethod
    def _plan_cache(source, split):
        """Le plan d'une RÉVISION ÉPINGLÉE ne change jamais : il se garde en cache local. Le Hub
        limite sévèrement les appels (429 en série, vécu le 2026-09-29)."""
        return (Path(tempfile.gettempdir()) / 'wama_eval_corpus'
                / f"{source['repo_id'].replace('/', '__')}@{source.get('revision')}_{split}.json")

    @staticmethod
    def _remote(source, name):
        """Chemin `HfFileSystem` d'un fichier : lecture par PLAGES HTTP, rien sur disque."""
        rev = source.get('revision')
        return (f"datasets/{source['repo_id']}@{rev}/{name}" if rev
                else f"datasets/{source['repo_id']}/{name}")

    def with_retry(self, call, attempts=5):
        """Le Hub limite les appels (429, vécu le 2026-09-29 au 2ᵉ fichier, jeton compris) : on
        attend et on reprend, plutôt que d'abandonner une préparation à moitié faite."""
        import time
        for attempt in range(1, attempts + 1):
            try:
                return call()
            except Exception as exc:
                if attempt == attempts or '429' not in repr(exc.__cause__ or exc) + repr(exc):
                    raise
                wait = 60 * attempt
                self.stdout.write(f"    429 du Hub — nouvel essai dans {wait} s")
                time.sleep(wait)

    # ── SUMM-RE : plan et préparation d'une réunion MIXÉE ─────────────────────────────────
    def plan_meetings(self, source, split, count):
        """Lit les colonnes `meeting_id`/`speaker_id`/`transcript` de chaque parquet (le pied du
        fichier et trois colonnes de texte, jamais l'audio).

        ⚠ Une réunion dont une piste est MASQUÉE est écartée : vécu le 2026-09-29 sur `008a_EARH`,
        la piste 028 n'est transcrite que par des jetons (`sil`, `w_1 w_2 …`) alors que l'audio
        porte sa parole — tous les moteurs y faisaient 66-69 % d'erreur, contre ~28 % ailleurs.
        """
        import pyarrow.parquet as pq
        from huggingface_hub import HfFileSystem

        fs = HfFileSystem()
        meetings, masked = {}, set()
        cache = self._plan_cache(source, split)
        known = json.loads(cache.read_text('utf-8')) if cache.exists() else {}
        for name in self._parquets(source, split):
            if name not in known:
                def read(name=name):
                    with fs.open(self._remote(source, name), 'rb') as fh:
                        return pq.ParquetFile(fh).read(
                            columns=['meeting_id', 'speaker_id', 'transcript'])
                table = self.with_retry(read)
                known[name] = [[mid, spk, is_masked_transcript(text)] for mid, spk, text in zip(
                    table.column('meeting_id').to_pylist(), table.column('speaker_id').to_pylist(),
                    table.column('transcript').to_pylist())]
                if source.get('revision'):
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps(known), encoding='utf-8')
            for meeting_id, speaker, is_masked in known[name]:
                m = meetings.setdefault(meeting_id, Recording(meeting_id))
                m.files.add(name)
                m.speakers.add(speaker)
                if is_masked:
                    masked.add(meeting_id)
            # La réunion la plus récente peut continuer dans le fichier suivant : on ne compte que
            # celles qui sont closes, et valides.
            closed = [m for m in list(meetings.values())[:-1] if m.recording_id not in masked]
            if len(closed) >= count:
                break
        for meeting_id in sorted(masked):
            self.stdout.write(self.style.WARNING(
                f"  {meeting_id} écartée : une piste n'est pas transcrite (jetons sil / w_N)"))
        chosen = [m for m in meetings.values() if m.recording_id not in masked][:count]
        self.stdout.write(f"{source['repo_id']} [{split}] : {len(chosen)} réunion(s) retenue(s)")
        return chosen

    def prepare_meetings(self, corpus, source, split, meetings):
        import pyarrow.parquet as pq
        from huggingface_hub import hf_hub_download

        from wama.media_library.models import SystemAsset

        # Déjà en médiathèque : rien à retélécharger (la préparation est idempotente).
        todo = [m for m in meetings if not SystemAsset.objects.filter(
            asset_type='speech', name=asset_name(corpus, split, m.recording_id)).exists()]
        needed = sorted({f for m in todo for f in m.files})
        wanted = {m.recording_id: m for m in todo}
        work = Path(tempfile.mkdtemp(prefix=f'{corpus}_'))
        try:
            for name in needed:
                self.stdout.write(f"  téléchargement {name}")
                local = self.with_retry(lambda: hf_hub_download(
                    source['repo_id'], name, repo_type='dataset',
                    revision=source.get('revision'), local_dir=work))
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
                    mix = mix_tracks(m.tracks)
                    self.ingest(corpus, source, split, m.recording_id, mix, work,
                                reference=(merged_srt(m.tracks), 'srt'),
                                attributes={'language': source.get('language', ''),
                                            'speakers': len(m.tracks)},
                                description=f"Réunion {m.recording_id} ({corpus}, {split}) : "
                                            f"{len(m.tracks)} pistes mixées à 16 kHz.")
                    m.tracks.clear()
                    del wanted[m.recording_id]
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if wanted:
            raise CommandError(f"pistes incomplètes : {', '.join(sorted(wanted))}")
        return self._assets(corpus, split, meetings)

    # ── FLEURS-CS : plan par langues, lecture du SEUL bloc qui porte l'enregistrement ──────
    def plan_tagged(self, source, split, count, require, exact, languages_count):
        """Lit les colonnes `languages`/`seed` de chaque parquet, bloc par bloc (le `seed` sert
        d'identifiant : le jeu n'en a pas d'autre)."""
        import pyarrow.parquet as pq
        from huggingface_hub import HfFileSystem

        # Relire 20 fichiers à chaque sélection coûtait plus de 10 min d'attente (429).
        cache = self._plan_cache(source, split)
        rows = json.loads(cache.read_text('utf-8')) if cache.exists() and source.get('revision') else None
        if rows is None:
            fs = HfFileSystem()
            rows = []
            for name in self._parquets(source, split):
                # UNE lecture des deux colonnes par fichier ; le bloc de chaque ligne se déduit
                # des métadonnées. Lire bloc par bloc multipliait les requêtes.
                def read(name=name):
                    with fs.open(self._remote(source, name), 'rb') as fh:
                        pf = pq.ParquetFile(fh)
                        sizes = [pf.metadata.row_group(g).num_rows
                                 for g in range(pf.metadata.num_row_groups)]
                        return sizes, pf.read(columns=['languages', 'seed'])
                sizes, table = self.with_retry(read)
                groups = [g for g, size in enumerate(sizes) for _ in range(size)]
                for index, (langs, seed) in enumerate(zip(table.column('languages').to_pylist(),
                                                          table.column('seed').to_pylist())):
                    rows.append([seed, sorted(langs), name, groups[index]])
            if source.get('revision'):
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(rows), encoding='utf-8')
        candidates = [Recording(f'seed{seed}', files={name}, languages=langs,
                                row_group=(name, group)) for seed, langs, name, group in rows]
        chosen = select_by_languages(candidates, require, exact, languages_count)[:count]
        self.stdout.write(f"{source['repo_id']} [{split}] : {len(chosen)} enregistrement(s) "
                          f"retenu(s) sur {len(candidates)}")
        return chosen

    def prepare_tagged(self, corpus, source, split, recordings):
        import pyarrow.parquet as pq
        from huggingface_hub import HfFileSystem

        from wama.media_library.models import SystemAsset

        todo = [r for r in recordings if not SystemAsset.objects.filter(
            asset_type='speech', name=asset_name(corpus, split, r.recording_id)).exists()]
        by_group = {}
        for r in todo:
            by_group.setdefault(r.row_group, {})[r.recording_id] = r
        fs = HfFileSystem()
        work = Path(tempfile.mkdtemp(prefix=f'{corpus}_'))
        try:
            for (name, group), wanted in sorted(by_group.items()):
                self.stdout.write(f"  lecture {name} bloc {group}")

                def read():
                    with fs.open(self._remote(source, name), 'rb') as fh:
                        return pq.ParquetFile(fh).read_row_group(
                            group, columns=['audio', 'transcription_tagged', 'seed'])
                table = self.with_retry(read)
                for row in table.to_pylist():
                    rec = wanted.get(f"seed{row['seed']}")
                    if rec is None:
                        continue
                    spans = tagged_spans(row['transcription_tagged'])
                    order = languages_by_time(spans)
                    samples = decode_track(row['audio']['bytes'])
                    self.ingest(corpus, source, split, rec.recording_id, samples, work,
                                reference=(language_vtt(spans), 'vtt'),
                                attributes={'language': order[0] if order else '',
                                            'languages': ','.join(order)},
                                description=f"FLEURS-CS {rec.recording_id} ({split}) : "
                                            f"{len(spans)} phrases lues en {len(order)} langues "
                                            f"({', '.join(order)}), mises bout à bout.")
                del table
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return self._assets(corpus, split, recordings)

    # ── CFPP2000 : une ARCHIVE lue par plages (seuls les membres retenus sont lus) ─────────
    def _archive(self, source):
        import zipfile
        from huggingface_hub import HfFileSystem
        handle = HfFileSystem().open(self._remote(source, source['archive']), 'rb',
                                     block_size=ARCHIVE_BLOCK_BYTES)
        return handle, zipfile.ZipFile(handle)

    def plan_archive(self, source, count):
        """Les enregistrements de l'archive (un dossier `record-N` : mp3 + `.trs`), leur durée
        ESTIMÉE par la taille du mp3 — le répertoire central du zip suffit, aucun membre n'est lu.
        Plan gardé en cache pour la révision épinglée. Retenus : les `count` premiers dont la
        durée estimée est dans [CFPP_MIN_SECONDS, CFPP_MAX_SECONDS]."""
        import re
        cache = self._plan_cache(source, 'all')
        plan = json.loads(cache.read_text('utf-8')) if cache.exists() else None
        if plan is None:
            handle, archive = self.with_retry(lambda: self._archive(source))
            try:
                folders = {}
                for info in archive.infolist():
                    folder, _, leaf = info.filename.partition('/')
                    if leaf:
                        folders.setdefault(folder, []).append(info)
            finally:
                handle.close()
            plan = []
            for folder, infos in folders.items():
                audio = [i for i in infos if i.filename.lower().endswith('.mp3')]
                turns = [i for i in infos if i.filename.lower().endswith('.trs')]
                if len(audio) == 1 and len(turns) == 1:
                    plan.append([folder, audio[0].filename, turns[0].filename,
                                 round(audio[0].file_size / MP3_BYTES_PER_SECOND)])
            plan.sort(key=lambda row: int(re.sub(r'\D', '', row[0]) or 0))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(plan), encoding='utf-8')
        chosen = [Recording(folder, files={audio, turns}, seconds=seconds)
                  for folder, audio, turns, seconds in plan
                  if seconds and CFPP_MIN_SECONDS <= seconds <= CFPP_MAX_SECONDS][:count]
        self.stdout.write(f"{source['repo_id']} : {len(chosen)} entretien(s) retenu(s) sur {len(plan)}")
        return chosen

    def prepare_archive(self, corpus, source, split, recordings):
        from wama.common.utils.audio_decode import decode_audio
        from wama.media_library.models import SystemAsset

        todo = [r for r in recordings if not SystemAsset.objects.filter(
            asset_type='speech', name=asset_name(corpus, split, r.recording_id)).exists()]
        if not todo:
            return self._assets(corpus, split, recordings)
        work = Path(tempfile.mkdtemp(prefix=f'{corpus}_'))
        handle, archive = self.with_retry(lambda: self._archive(source))
        try:
            for rec in todo:
                audio = next(n for n in rec.files if n.lower().endswith('.mp3'))
                turns = next(n for n in rec.files if n.lower().endswith('.trs'))
                self.stdout.write(f"  lecture {rec.recording_id}")
                mp3 = work / f'{rec.recording_id}.mp3'          # nom neutre : jamais le nom réel
                mp3.write_bytes(self.with_retry(lambda: archive.read(audio)))
                samples, rate = decode_audio(str(mp3), target_sr=SAMPLE_RATE, mono=True)
                samples = resampled(samples, rate)
                mp3.unlink(missing_ok=True)
                cues = trs_cues(self.with_retry(lambda: archive.read(turns)))
                self.ingest(corpus, source, split, rec.recording_id, samples, work,
                            reference=(cues_srt(cues), 'srt'),
                            attributes={'language': source.get('language', ''),
                                        'speakers': len({c[2] for c in cues})},
                            description=f"Entretien CFPP2000 {rec.recording_id} : "
                                        f"{len({c[2] for c in cues})} locuteurs, "
                                        f"{len(cues)} répliques, 16 kHz mono.")
        finally:
            handle.close()
            shutil.rmtree(work, ignore_errors=True)
        return self._assets(corpus, split, recordings)

    # ── variantes : dégradation contrôlée, audio nivelé d'avance ───────────────────────────
    def variant(self, asset, profile=None, leveled=False, enhance=None):
        """L'enregistrement tel qu'on le posera : l'original, sa variante DÉGRADÉE par un profil
        déclaré (`audio_degradation.PROFILES`), NIVELÉE d'avance (`speech_leveling`), et/ou
        AMÉLIORÉE par Resemble Enhance (`enhance` : 'enhance' | 'both'), dans cet ordre. Une
        variante est un audio SYSTÈME à part (son lot à elle), qui garde la référence de
        l'original (`attributes['reference']`). Idempotent : déjà versée, elle est reprise."""
        if not profile and not leveled and not enhance:
            return asset
        import soundfile as sf

        from wama.common.utils.audio_decode import decode_audio
        from wama.media_library.models import SystemAsset
        from wama.media_library.system_files import ingest_system_file

        parts = ([asset.name] + ([profile] if profile else []) + (['leveled'] if leveled else [])
                 + ([f'resemble-{enhance}'] if enhance else []))
        name = VARIANT_SEPARATOR.join(parts)
        existing = SystemAsset.objects.filter(asset_type='speech', name=name).first()
        if existing:
            return existing
        samples, rate = decode_audio(asset.file.path, target_sr=SAMPLE_RATE, mono=True)
        samples = resampled(samples, rate)
        steps = []
        if profile:
            from wama.common.utils.audio_degradation import PROFILES, degrade
            samples = degrade(samples, SAMPLE_RATE, profile)
            steps.append(PROFILES[profile]['label'])
        if leveled:
            from wama.common.utils.speech_leveling import level_speech
            samples = level_speech(samples, SAMPLE_RATE)
            steps.append('nivellement de la parole')
        work = Path(tempfile.mkdtemp(prefix='variant_'))
        try:
            wav = work / f'{name}.wav'
            sf.write(str(wav), samples, SAMPLE_RATE, subtype='PCM_16')
            if enhance:
                # La brique de l'enhancer, telle quelle (réglages par défaut de l'app : force de
                # débruitage 0,5, 64 évaluations) ; sortie à 44,1 kHz ramenée à 16 kHz.
                from wama.common.backends.audio_enhancer import run_audio_enhancement
                enhanced = work / f'{name}_resemble.wav'
                run_audio_enhancement(str(wav), str(enhanced), engine='resemble', mode=enhance,
                                      denoising_strength=0.5, quality=64)
                out, rate = sf.read(str(enhanced), dtype='float32', always_2d=True)
                samples = resampled(out.mean(axis=1), rate)
                sf.write(str(wav), samples, SAMPLE_RATE, subtype='PCM_16')
                steps.append('Resemble Enhance, ' + ('amélioration' if enhance == 'enhance'
                                                     else 'amélioration + débruitage'))
            attributes = {**(asset.attributes or {}), 'base': asset.name,
                          'reference': (asset.attributes or {}).get('reference')
                          or f'{asset.name}_reference',
                          'degradation': profile or '', 'leveled': bool(leveled),
                          'enhancement': f'resemble-{enhance}' if enhance else ''}
            ingest_system_file('speech', name, wav, mime_type='audio/wav',
                               duration=len(samples) / SAMPLE_RATE, attributes=attributes,
                               description=f"{asset.name} — {', '.join(steps)}.",
                               source_url=asset.source_url or '', license=asset.license or '')
        finally:
            shutil.rmtree(work, ignore_errors=True)
        self.stdout.write(self.style.SUCCESS(f"  variante {name} versée"))
        return SystemAsset.objects.get(asset_type='speech', name=name)

    # ── commun : versement en médiathèque système ─────────────────────────────────────────
    def ingest(self, corpus, source, split, recording_id, samples, work, *, reference,
               attributes, description):
        import soundfile as sf

        from wama.media_library.system_files import ingest_system_file

        name = asset_name(corpus, split, recording_id)
        wav = work / f'{name}.wav'
        sf.write(str(wav), samples, SAMPLE_RATE, subtype='PCM_16')
        text, ext = reference
        ref = work / f'{name}_reference.{ext}'
        ref.write_text(text, encoding='utf-8')
        common = {'source_url': f"https://huggingface.co/datasets/{source['repo_id']}",
                  'license': source.get('license', '')}
        ingest_system_file(
            'speech', name, wav, mime_type='audio/wav', duration=len(samples) / SAMPLE_RATE,
            attributes={**attributes, 'corpus': corpus, 'split': split, 'recording': recording_id},
            description=description, **common)
        ingest_system_file(
            'document', reference_name(corpus, split, recording_id), ref,
            mime_type='text/vtt' if ext == 'vtt' else 'application/x-subrip',
            description=f"Transcription de référence de {name}.", **common)
        wav.unlink(missing_ok=True)
        ref.unlink(missing_ok=True)
        self.stdout.write(self.style.SUCCESS(
            f"  {name} versé en médiathèque ({len(samples) / SAMPLE_RATE / 60:.1f} min)"))

    @staticmethod
    def _assets(corpus, split, recordings):
        from wama.media_library.models import SystemAsset
        return [SystemAsset.objects.get(asset_type='speech',
                                        name=asset_name(corpus, split, r.recording_id))
                for r in recordings]

    # ── lots : un par enregistrement, une CONFIGURATION par card, la référence sur le lot ──
    def post_batches(self, login, assets, engines, start, *, preprocess=False, level=False,
                     vad='auto', language_mode='auto', diarization=None):
        """Une configuration = moteur × prétraitement × nivellement × filtre de parole × langues
        × pipeline de diarisation (None = coupée) — exactement les réglages que l'évaluation
        distingue (`config_params` du transcriber). Un
        nouvel appel avec d'autres options AJOUTE ses cards au lot de l'enregistrement : toutes
        ses configurations se comparent au même endroit. Une configuration déjà posée ne l'est
        pas deux fois."""
        from django.core.files import File

        from wama.common.services.result_evaluation import attach_reference
        from wama.common.utils.batch_common import attach_to_batch
        from wama.media_library.models import SystemAsset
        from wama.tool_api import add_to_transcriber, start_transcriber
        from wama.transcriber.backends.manager import catalogue_value, filters_speech
        from wama.transcriber.models import BatchTranscript, BatchTranscriptItem, Transcript

        user = self._user(login)
        for asset in assets:
            on_audio = Transcript.objects.filter(user=user, audio=asset.file.name)
            link = (BatchTranscriptItem.objects.filter(transcript__in=on_audio)
                    .select_related('batch').order_by('batch_id').first())
            batch = link.batch if link else BatchTranscript.objects.create(user=user, total=0)
            row = (batch.items.order_by('-row_index').values_list('row_index', flat=True)
                   .first() or -1) + 1
            new_cards = []
            for engine in engines:
                # La card stocke une CLÉ de catalogue (route F4b ⑦) : un ancien nom de moteur passé
                # en option est lu comme elle l'écrit, sinon la configuration déjà posée ne se
                # reconnaîtrait pas (idempotence ci-dessous).
                engine = catalogue_value(engine)
                # Le filtre de parole n'existe que chez les moteurs qui le déclarent (Whisper,
                # Albert — `supports_vad_filter`) : le varier sur un autre moteur poserait deux
                # fois la même configuration.
                engine_vad = vad if filters_speech(engine) else 'auto'
                # Sans pipeline demandé, diarisation coupée : elle ne change pas le texte mesuré
                # (WER), seulement le temps. Demandée, elle se mesure en cpWER et DER.
                speakers = ({'enable_diarization': True, 'diarization_model': diarization}
                            if diarization else {'enable_diarization': False})
                if on_audio.filter(backend=engine, preprocess_audio=preprocess, level_speech=level,
                                   vad_mode=engine_vad, language_mode=language_mode,
                                   **speakers).exists():
                    continue
                result = add_to_transcriber(user, asset.file.name, backend=engine,
                                            preprocess_audio=preprocess, level_speech=level,
                                            vad_mode=engine_vad, language_mode=language_mode,
                                            **speakers)
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
            # Une variante garde la référence de l'original (`variant`).
            reference = SystemAsset.objects.get(
                asset_type='document',
                name=(asset.attributes or {}).get('reference') or f'{asset.name}_reference')
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

    @staticmethod
    def _user(login):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.filter(username=login).first()
        if user is None:
            raise CommandError(f"utilisateur inconnu : {login}")
        return user

    # ── rapport : ce que les cards ont produit, mesuré ─────────────────────────────────────
    def report(self, login, corpus, split, recordings):
        """Une ligne par card : configuration, erreur par mot et par caractère (lignes
        `ResultEvaluation`), et ACCORD DE LANGUE — la part du temps de parole de la référence
        où la langue du segment produit est la bonne (`spoken_language.language_agreement`)."""
        from wama.common.models import ResultEvaluation
        from wama.common.utils.spoken_language import language_agreement
        from wama.transcriber.models import Transcript
        from wama.transcriber.utils.transcript_documents import read_transcript_document

        from wama.media_library.models import SystemAsset
        user = self._user(login)
        bases = self._assets(corpus, split, recordings)
        # Chaque original, puis ses variantes (dégradées, nivelées) : un lot chacune.
        assets = [a for base in bases for a in [base] + list(SystemAsset.objects.filter(
            asset_type='speech', name__startswith=base.name + VARIANT_SEPARATOR).order_by('name'))]
        for asset in assets:
            self.stdout.write(f"\n{asset.name} — {asset.attributes.get('languages') or asset.attributes.get('language')}")
            for t in Transcript.objects.filter(user=user, audio=asset.file.name).order_by('pk'):
                rows = {r.metric: r.value for r in ResultEvaluation.objects.filter(
                    object_type='Transcript', object_id=t.pk)}
                agreement = None
                if t.reference_result and t.segments_json:
                    ref = read_transcript_document(t.reference_result.path).segments
                    agreement = language_agreement(ref, t.segments_json)['agreement']
                heard = sorted({s.get('language') for s in (t.segments_json or [])
                                if s.get('language')})
                fmt = lambda v: '—' if v is None else f'{100 * v:5.1f} %'
                self.stdout.write(
                    f"  #{t.pk:<5} {t.backend:<34} langues={t.language_mode:<6} "
                    f"prétr={'oui' if t.preprocess_audio else 'non'} "
                    f"nivel={'oui' if t.level_speech else 'non'} vad={t.vad_mode:<4} {t.status:<8} "
                    f"WER {fmt(rows.get('wer'))}  CER {fmt(rows.get('cer'))}  "
                    f"accord {fmt(agreement)}  entendues {','.join(heard) or '—'}"
                    + (f"  diar={t.diarization_model} cpWER {fmt(rows.get('cpwer'))} "
                       f"DER {fmt(rows.get('der'))}" if t.enable_diarization else ''))
