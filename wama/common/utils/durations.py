"""Les DURÉES LISIBLES de WAMA — une écriture côté serveur (2026-11-19, demande de Fabien : « une
petite fonction au commun pour aligner les durées en heures, minutes et secondes […] il faudrait
qu'elle soit utilisée partout où il y a des durées » ; recensement : `INSPECTOR_DETAIL_FIELDS`,
bloc du 2026-11-19 — une dizaine de réécritures, deux jumelles qui n'arrondissaient pas pareil).

Jumelle JS : `WamaDurations` (`common/js/wama-durations.js`) — mêmes formes, mêmes règles ; la garde
`tests_display_format` les joue côte à côte. Trois formes, chacune pour ce qu'elle dit :

  • l'HORLOGE (`format_clock`, `format_duration`) — une durée de média, une position : « 1:35 »,
    « 1:02:30 » (les heures au-delà de 59:59), au dixième ou à la milliseconde en option
    (« 1:23.4 », « 0:05.123 ») ;
  • les UNITÉS (`format_elapsed`) — un temps de traitement, une attente : « 45 s », « 1 min 05 s »,
    « 1 h 02 min » (décision de Fabien, 2026-11-19 : gardée à côté de l'horloge, pour une attente) ;
  • l'horodatage SRT (`srt_timestamp`) — « 00:01:35,400 », la forme d'un fichier de sous-titres.

Règle commune : la valeur est TRONQUÉE, jamais arrondie (décision de Fabien, 2026-11-19 : comme le
lecteur — 95,6 s se lit « 1:35 ») ; seule l'écriture SRT arrondit à la milliseconde, la forme qui
a produit les références de la médiathèque, dont les mesures dépendent à l'octet.
"""
import math


def _seconds(value):
    """Un nombre de secondes ≥ 0, ou None quand la valeur ne se lit pas."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return max(0.0, number)


def format_clock(seconds, precision: int = 0) -> str:
    """``95.4 -> '1:35'``, ``3750 -> '1:02:30'``, ``(83.45, 1) -> '1:23.4'`` — une POSITION ou une
    durée en horloge ; 0 se lit « 0:00 ». `precision` : 0, 1 (dixièmes) ou 3 (millisecondes)
    chiffres après la seconde, tronqués. '' pour une valeur illisible."""
    total = _seconds(seconds)
    if total is None:
        return ''
    whole = int(total)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    out = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
    if precision > 0:
        fraction = int((total - whole) * 10 ** precision + 1e-6)
        out += f".{fraction:0{precision}d}"
    return out


def format_duration(seconds) -> str:
    """La DURÉE d'un média en horloge (``95.4 -> '1:35'``) — '' quand elle est inconnue ou nulle."""
    total = _seconds(seconds)
    return format_clock(total) if total else ''


def format_elapsed(seconds) -> str:
    """Un temps de traitement, une attente, en UNITÉS : « 45 s », « 1 min 05 s », « 2 min »,
    « 1 h 02 min » — '' quand il est inconnu ou nul."""
    total = _seconds(seconds)
    if not total or int(total) <= 0:
        return ''
    whole = int(total)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} h {minutes:02d} min" if minutes else f"{hours} h"
    if minutes:
        return f"{minutes} min {secs:02d} s" if secs else f"{minutes} min"
    return f"{secs} s"


def srt_timestamp(seconds) -> str:
    """``95.4 -> '00:01:35,400'`` — l'horodatage d'un fichier SRT, ARRONDI à la milliseconde (la forme
    de `asr_eval_corpus`, qui a produit les références SRT de la médiathèque)."""
    ms = int(round((_seconds(seconds) or 0.0) * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}'
