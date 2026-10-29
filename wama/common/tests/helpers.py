"""Doublures PARTAGÉES par les tests de plusieurs apps (ce module n'est pas un module de tests :
la découverte ne lit que `tests*.py`)."""
import os

#: La conversion en ligne que joue le process « Sortie » (`output_formats.apply_output_settings`)
#: — l'adresse à remplacer par `stand_in_conversion` dans un test qui ne convertit rien.
INLINE_CONVERSION = 'wama.converter.utils.inline_convert.apply_inline_conversion'


def stand_in_conversion(path, fmt, preset='balanced', **_kw):
    """Doublure du convertisseur : écrit la cible à côté de la source (son contenu, marqué du
    format — un test peut lire d'où vient un rendu), retire la source, rend la cible. Était
    recopiée dans six fichiers de tests (2026-10-04)."""
    target = os.path.splitext(path)[0] + '.' + fmt
    with open(path, 'rb') as src:
        content = src.read()
    with open(target, 'wb') as out:
        out.write(content + b'>' + fmt.encode())
    if target != path:
        os.remove(path)
    return target


def video_with_sound(folder: str, name: str, audio_codec: str, video_filter: str = None) -> str:
    """Une vidéo RÉELLE de 3 s (mire 64×48 à 20 i/s, la 440 Hz en son), au conteneur que dit
    `name` et au codec audio `audio_codec` ; `video_filter` (avec cadence variable) pour retirer
    des images. Écrite par ffmpeg dans `folder`. Née dans les tests du floutage (2026-10-28),
    partagée le 2026-10-29 quand l'agrandissement vidéo de l'enhancer a rejoint le même rendu."""
    import subprocess
    from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe
    path = os.path.join(folder, name)
    command = [get_ffmpeg_exe(), '-y', '-loglevel', 'error',
               '-f', 'lavfi', '-i', 'testsrc=size=64x48:rate=20:duration=3',
               '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=3']
    if video_filter:
        command += ['-vf', video_filter, '-fps_mode', 'vfr']
    command += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', audio_codec, path]
    subprocess.run(command, check=True)
    return path


def media_streams(path: str):
    """`(conteneur, {type: flux})` d'un média lu par ffprobe, chaque flux avec sa `duration` —
    Matroska ne la porte que dans ses étiquettes (`DURATION` = « 00:00:03.000000000 »)."""
    import json
    import subprocess
    from wama.common.utils.ffmpeg_utils import get_ffprobe_exe
    out = subprocess.run([get_ffprobe_exe(), '-v', 'error', '-show_entries',
                          'stream=codec_type,codec_name,duration,width,height'
                          ':stream_tags=DURATION:format=format_name', '-of', 'json', path],
                         capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    streams = {}
    for stream in data['streams']:
        if 'duration' not in stream and (stream.get('tags') or {}).get('DURATION'):
            h, m, s = stream['tags']['DURATION'].split(':')
            stream['duration'] = str(int(h) * 3600 + int(m) * 60 + float(s))
        streams[stream['codec_type']] = stream
    return data['format']['format_name'], streams


def frame_times(path: str) -> list:
    """Le temps de présentation de CHAQUE image du flux vidéo, en secondes."""
    import subprocess
    from wama.common.utils.ffmpeg_utils import get_ffprobe_exe
    out = subprocess.run([get_ffprobe_exe(), '-v', 'error', '-select_streams', 'v:0',
                          '-show_entries', 'frame=best_effort_timestamp_time',
                          '-of', 'csv=p=0', path], capture_output=True, text=True, check=True)
    return [float(line.strip(',')) for line in out.stdout.split() if line.strip(',')]


def run_data_migration(function, field: str, rows: dict) -> dict:
    """Joue une fonction de migration de DONNÉES (`RunPython`) sur une table EN MÉMOIRE :
    `rows` = {pk: valeur du champ `field`}, modifié en place et rendu. Couvre ce qu'utilisent les
    migrations de préfixage en clés de catalogue (`exclude(<champ>__in / __contains)`,
    `filter(pk= / <champ>__startswith=)`, `values_list`, `update`) — sans base, donc sans dépendre
    de l'état du catalogue. Était écrite pour le seul `ai_model` de l'enhancer (2026-10-06) ;
    l'avatarizer (`animation_model`, 2026-10-07) en avait besoin sous un autre nom de champ."""
    from unittest import mock

    class _Rows:
        def __init__(self, pks):
            self.pks = list(pks)

        def _keep(self, test):
            return _Rows(pk for pk in self.pks if test(rows[pk]))

        def exclude(self, **lookup):
            (key, arg), = lookup.items()
            if key == f'{field}__in':
                return self._keep(lambda v: v not in arg)
            if key == f'{field}__contains':
                return self._keep(lambda v: arg not in (v or ''))
            if key == f'{field}__startswith':
                return self._keep(lambda v: not (v or '').startswith(arg))
            raise AssertionError(f'lookup non couvert par la doublure : {key}')

        def filter(self, **lookup):
            (key, arg), = lookup.items()
            if key == 'pk':
                return _Rows([arg])
            if key == f'{field}__startswith':
                return self._keep(lambda v: (v or '').startswith(arg))
            if key == f'{field}__in':
                return self._keep(lambda v: v in arg)
            raise AssertionError(f'lookup non couvert par la doublure : {key}')

        def values_list(self, *fields):
            return [(pk, rows[pk]) for pk in self.pks]

        def update(self, **values):
            for pk in self.pks:
                rows[pk] = values[field]

    model = type('Model', (), {'objects': _Rows(rows)})
    function(mock.Mock(get_model=lambda app, name: model), None)
    return rows
