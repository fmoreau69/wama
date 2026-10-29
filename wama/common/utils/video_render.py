"""Rendu d'une vidéo image par image — chaque image à SON horodatage d'origine, le son recopié.

Le geste commun de toute app qui TRANSFORME les images d'une vidéo et la rend : le floutage de
l'anonymizer et du cam_analyzer (`detections.rewrite_media`), l'agrandissement de l'enhancer
(`enhancer/backends/media_backend.enhance_video`). Né le 2026-10-28 dans `detections.py` pour le
floutage (décision de Fabien : le moins de conversions possible, l'audio rendu sans
désynchronisation) ; sorti ici le 2026-10-29 quand l'enhancer, qui rendait une vidéo MUETTE par
un réencodage de PNG à cadence constante, en est devenu le second appelant (décision de Fabien :
« on porte l'upscale vidéo sur le rendu commun en conservant le son comme Anonymizer »).

Sans Django ni app : la Data et le Lab peuvent l'appeler.
"""
import os


def render_video(source: str, paint, output_path: str, *, on_frame=None, progress=None) -> str:
    """Réécrit la vidéo `source` en passant chaque image par `paint(indice, image) -> image`, et
    rend le chemin RÉELLEMENT écrit.

    La vidéo sort dans le conteneur de `output_path` — le format d'origine quand l'appelant y met
    l'extension de la source — en UN seul encodage, avec les codecs qu'emploierait une conversion
    vers ce format (`converter.video_backend.rendering_encoding`) :
      • chaque image est écrite à SON horodatage d'origine (PyAV) — une vidéo à cadence variable
        garde ses temps image par image, et rien ne s'étire ;
      • l'audio de la source est RECOPIÉ paquet par paquet, à ses propres temps, quand le
        conteneur accepte son codec (sinon encodé au codec du conteneur, à ses temps) : jamais
        étiré ni rééchantillonné en durée, donc ni décalé ni changé de hauteur.
    Un conteneur hors de la table sort en `.mp4`. Les images sont lues par OpenCV (la rotation
    déclarée appliquée, comme la détection les a lues) ; la taille de la sortie est celle de la
    première image PEINTE — un agrandissement change la taille, un floutage la garde. Toutes les
    images peintes ont donc la même taille.

    `paint`    : `(indice, image BGR) -> image BGR` ; il peut rendre l'image reçue telle quelle ;
    `on_frame` : `callback(indice, image d'origine, image peinte)` — l'aperçu « pendant » de la
                 tâche, qu'elle limite elle-même dans le temps ;
    `progress` : `callback(faites, total)`.

    Écrit à côté puis substitué : une coupure ne laisse jamais un fichier à moitié écrit à la place
    du rendu."""
    import cv2
    stem, ext = os.path.splitext(output_path)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise RuntimeError(f"Vidéo illisible : {os.path.basename(source)}")
    try:
        return _write_timed_video(capture, source, stem, ext, paint, on_frame, progress)
    finally:
        capture.release()


def _write_timed_video(capture, source, stem, ext, paint, on_frame, progress) -> str:
    """Le corps de `render_video` : les images lues par OpenCV, peintes, encodées par PyAV chacune
    à son horodatage d'origine ; l'audio de la source recopié (ou encodé) à ses propres temps,
    entrelacé au fil de l'écriture."""
    from fractions import Fraction

    import av
    import cv2

    from wama.converter.backends.video_backend import rendering_encoding

    source_media = av.open(source)
    in_video = source_media.streams.video[0] if source_media.streams.video else None
    in_audio = source_media.streams.audio[0] if source_media.streams.audio else None
    audio_codec = in_audio.codec_context.name if in_audio is not None else ''
    encoding = rendering_encoding(ext.lstrip('.'), audio_codec)
    if encoding is None:
        ext = '.mp4'
        encoding = rendering_encoding('mp4', audio_codec)
    final, writing = stem + ext, f'{stem}.writing{ext}'
    # Les temps OpenCV (`CAP_PROP_POS_MSEC`) partent du début du CONTENEUR — le plus tôt de ses
    # flux, pas celui de la vidéo (MESURÉ : un MKV dont l'Opus démarre 7 ms avant l'image donnait
    # 7 ms à la première image) ; ceux de l'audio recopié sont ABSOLUS. Le départ du conteneur
    # (`start_time`, en microsecondes) remet les deux sur la même horloge.
    start_ms = (source_media.start_time / 1000.0
                if source_media.start_time is not None else 0.0)
    step_ms = 1000.0 / float((in_video.average_rate if in_video is not None else None) or 25)
    unit = Fraction(1, 1000)

    output = av.open(writing, 'w', format=encoding['format'], options=encoding['muxer_options'])
    video_out, audio_out, resampler = None, None, None
    audio_packets = source_media.demux(in_audio) if in_audio is not None else iter(())
    pending = []                                     # paquet audio lu d'avance, pas encore écrit

    def write_audio(until_s=None):
        """Écrit l'audio de la source jusqu'au temps `until_s` (tout, si None)."""
        while True:
            packet = pending.pop() if pending else next(audio_packets, None)
            if packet is None:
                return
            if packet.pts is not None and until_s is not None \
                    and float(packet.pts * packet.time_base) > until_s:
                pending.append(packet)
                return
            if encoding['audio_copy']:
                if packet.dts is None:
                    continue
                packet.stream = audio_out
                output.mux(packet)
                continue
            for decoded in packet.decode():
                for frame in resampler.resample(decoded):
                    for encoded in audio_out.encode(frame):
                        output.mux(encoded)

    try:
        if in_audio is not None:
            if encoding['audio_copy']:
                audio_out = output.add_stream_from_template(in_audio)
            else:
                audio_out = output.add_stream(encoding['acodec'], rate=in_audio.rate,
                                              layout=in_audio.layout.name)
                audio_out.bit_rate = 192_000
                resampler = av.AudioResampler(
                    format=audio_out.codec_context.codec.audio_formats[0].name,
                    layout=in_audio.layout.name, rate=in_audio.rate)
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        last_pts, index = -1, 0
        while True:
            ok, image = capture.read()
            if not ok:
                break
            painted = paint(index, image)
            if video_out is None:
                # La taille se lit sur l'image PEINTE : OpenCV a appliqué la rotation déclarée, et
                # un agrandissement (l'enhancer) change la taille de la sortie.
                height, width = painted.shape[:2]
                video_out = output.add_stream(encoding['vcodec'])
                video_out.width, video_out.height = width, height
                video_out.pix_fmt = encoding['pix_fmt']
                video_out.codec_context.time_base = unit
                video_out.codec_context.options = encoding['video_options']
            # Le temps D'ORIGINE de cette image ; à défaut (conteneur qui n'en donne pas), la
            # suivante de la cadence moyenne. Toujours croissant : un encodeur l'exige.
            position = capture.get(cv2.CAP_PROP_POS_MSEC)
            pts = int(round(start_ms + position)) if position or index == 0 else -1
            if pts <= last_pts:
                pts = int(round(last_pts + step_ms)) if last_pts >= 0 else 0
            last_pts = pts
            frame = av.VideoFrame.from_ndarray(painted, format='bgr24').reformat(
                format=encoding['pix_fmt'])
            frame.pts, frame.time_base = pts, unit
            for packet in video_out.encode(frame):
                output.mux(packet)
            if audio_out is not None:
                write_audio(until_s=pts / 1000.0)
            if on_frame:
                on_frame(index, image, painted)
            index += 1
            if progress:
                progress(index, total or index)
        if video_out is None:
            raise RuntimeError(f"Vidéo sans aucune image : {os.path.basename(source)}")
        for packet in video_out.encode(None):
            output.mux(packet)
        if audio_out is not None:
            write_audio()
            if not encoding['audio_copy']:
                for frame in resampler.resample(None):
                    for encoded in audio_out.encode(frame):
                        output.mux(encoded)
                for encoded in audio_out.encode(None):
                    output.mux(encoded)
        output.close()
    except BaseException:
        # BaseException : une interruption (la garde-temps du squelette comprise) ne laisse pas
        # le fichier en cours d'écriture derrière elle — ce que le `work_dir` de l'ancienne route
        # vidéo de l'enhancer couvrait déjà.
        try:
            output.close()
        except Exception:
            pass                       # l'erreur qui compte est celle d'au-dessus
        if os.path.exists(writing):
            os.remove(writing)
        raise
    finally:
        source_media.close()
    os.replace(writing, final)
    return final
