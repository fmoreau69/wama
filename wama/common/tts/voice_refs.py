"""Voix de RÉFÉRENCE — la brique COMMUNE : résolution d'un preset en fichier, groupes du menu,
libellés, téléchargement. Les voix VIVENT EN MÉDIATHÈQUE (`SystemAsset(asset_type='voice')`,
`media_library/system/`) depuis le 2026-09-13 — plan `MEDIA_STORAGE_TIERING §9.4`.

Ce que ce module SAIT, et d'où :
  * une voix de référence = une ligne `SystemAsset(voice)` ; sa taxonomie (langue, âge, genre,
    variante) = ses `attributes` (construction A′, `media_library/natures.py`) — plus une
    arborescence `<langue>/<âge>/<genre>_<âge>[_<n>]_<iso>.wav` parcourue à la main ;
  * `SystemAsset.name` = l'IDENTIFIANT DE PRESET D'AVANT (`french/adult/male_adult_1_fr`,
    `default`, `female_1`…) : c'est ce que les lignes en base STOCKENT (frontière des données,
    décision D5), donc elles résolvent par ce nom sans conversion. Une sélection NOUVELLE se
    fait par `sa_<id>` ;
  * `speaker_wav_for` est LA porte des workers et des aperçus (la CAPACITÉ du moteur décide,
    D7) ; `resolve_speaker_wav` résout `sa_`/`ua_`/`cv_`/nom ; `describe_voice` libelle ;
    `voice_reference_groups` dérive les optgroups d'une REQUÊTE ; `download_missing_voice_refs`
    verse dans la médiathèque (jamais un fichier nu).

⚠ PORTÉ AU COMMUN le 2026-09-12 depuis `synthesizer/utils/voice_utils.py` (quatre
consommateurs : synthesizer, avatarizer, `voice_options`, et — hors Django — `tts_service.py`,
qui ne résout plus rien depuis le 13/09). Constat de Fabien : *« ça n'a pas de sens de laisser
les voix dans le synthesizer »* — vrai des fichiers, vrai du code qui les cherche.

⚠ `common/tts/voices.py` (à côté) est AUTRE CHOSE : la résolution voix↔langue de Kokoro pour
l'assistant. L'un nomme, l'autre localise ; les fusionner est une question ouverte.
"""

import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tables de conversion (libellés) — les VALEURS sont celles de `natures.py` ('voice')
# ---------------------------------------------------------------------------

_LANG_CODE_TO_LABEL: Dict[str, str] = {  # wama:redondance-ok — labels d'affichage par langue (info nouvelle)
    'fr': 'Français', 'en': 'English', 'es': 'Español',
    'de': 'Deutsch', 'it': 'Italiano', 'pt': 'Português',
    'ja': '日本語', 'zh': '中文', 'ko': '한국어',
    'nl': 'Nederlands', 'pl': 'Polski', 'ru': 'Русский',
}

_AGE_TO_LABEL: Dict[str, str] = {
    'child': 'Enfant', 'adult': 'Adulte', 'elderly': 'Senior',
}

# Sort key for age (child < adult < elderly)
_AGE_ORDER: Dict[str, int] = {'child': 0, 'adult': 1, 'elderly': 2}

_GENDER_TO_LABEL: Dict[str, str] = {
    'male': 'Homme', 'female': 'Femme',
}

# Pattern: {gender}_{age}[_{variant}]_{lang}.wav
_FILE_PATTERN = re.compile(
    r'^(male|female)_(child|adult|elderly)(?:_(\d+))?_([a-z]{2,5})\.wav$',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Presets PLATS hérités (`default`, `male_1`…) : des lignes `SystemAsset(voice)` comme les
# autres, nommées par leur id. Ce qu'on SAIT d'elles : ce sont des clips LJSpeech (Linda
# Johnson, femme adulte anglophone — certifié) ; `male_1`/`male_2` en sont AUSSI (catalogue),
# leur nom ment sur le genre. On ne pose que la LANGUE, volontairement : (1) un genre déduit
# du nom mentirait ; (2) une ligne qui porte langue+âge+genre ENTRE dans les groupes du menu
# (`voice_reference_groups`), et ces cinq-là n'y ont jamais figuré — `default` est un groupe
# à part, les quatre autres ne sont plus proposées (elles restent RÉSOLUES pour les 96 lignes
# qui les stockent). L'empreinte du menu d'avant/après en dépend.
# ---------------------------------------------------------------------------
LEGACY_FLAT_VOICES: Dict[str, Dict] = {  # wama:redondance-ok — ce qu'on SAIT de chaque preset plat (info nouvelle : la langue), pas une recopie des choices
    'default':  {'language': 'en'},
    'female_1': {'language': 'en'},
    'female_2': {'language': 'en'},
    'male_1':   {'language': 'en'},
    'male_2':   {'language': 'en'},
}


def attributes_from_voice_id(voice_id: str) -> Dict:
    """Les `attributes` (nature `voice`) qu'un identifiant de preset PORTE.

    `french/adult/male_adult_1_fr` → {language: 'fr', age: 'adult', gender: 'male', variant: 1}
    (la langue vient du SUFFIXE du fichier, pas du dossier) ; un id plat hérité → ce qu'on en
    sait (table ci-dessus) ; sinon {} — l'appelant décide s'il refuse ou verse sans attribut.
    """
    parts = (voice_id or '').split('/')
    if len(parts) == 3:
        m = _FILE_PATTERN.match(parts[2] + '.wav')
        if m:
            gender, age, variant, lang = m.groups()
            attrs = {'language': lang.lower(), 'age': age.lower(), 'gender': gender.lower()}
            if variant:
                attrs['variant'] = int(variant)
            return attrs
    return dict(LEGACY_FLAT_VOICES.get(voice_id, {}))


# ---------------------------------------------------------------------------
# Libellés et groupes — DÉRIVÉS des `attributes` (plus d'un scan de dossier)
# ---------------------------------------------------------------------------

def _group_label(attrs: Dict) -> str:
    lang = str(attrs.get('language', '')).lower()
    age = str(attrs.get('age', '')).lower()
    return f"{_LANG_CODE_TO_LABEL.get(lang, lang.upper())} — {_AGE_TO_LABEL.get(age, age.capitalize())}"


def _option_label(attrs: Dict) -> str:
    gender = str(attrs.get('gender', '')).lower()
    label = _GENDER_TO_LABEL.get(gender, gender.capitalize())
    variant = attrs.get('variant')
    return label + (f" {variant}" if variant else "")


def _voice_label(asset) -> str:
    """`Français — Adulte — Homme 1` si la ligne porte sa taxonomie, sinon son nom."""
    attrs = asset.attributes or {}
    if all(k in attrs for k in ('language', 'age', 'gender')):
        return f"{_group_label(attrs)} — {_option_label(attrs)}"
    return asset.name


def _sort_key(attrs: Dict) -> tuple:
    """Français d'abord, puis English, puis les autres par LIBELLÉ affiché ; enfants < adultes
    < seniors. ⚠ Seul écart mesuré avec le scan de dossier d'avant (empreinte du 13/09) : les
    « autres » langues se rangeaient par nom de DOSSIER anglais (german, italian, portuguese,
    spanish) — un ordre que l'utilisateur ne voyait pas ; ici Deutsch, Español, Italiano,
    Português, l'ordre de ce qu'il lit."""
    lang = str(attrs.get('language', '')).lower()
    return (0 if lang == 'fr' else 1 if lang == 'en' else 2,
            _LANG_CODE_TO_LABEL.get(lang, lang.upper()),
            _AGE_ORDER.get(str(attrs.get('age', '')).lower(), 9))


def voice_reference_groups() -> List[Dict]:
    """Les optgroups du menu « voix de référence », DÉRIVÉS de la médiathèque :

        [{'group': 'Français — Adulte',
          'voices': [{'id': 'sa_12', 'label': 'Homme 1'}, …]}, …]

    Une ligne entre dans un groupe si elle porte langue, âge ET genre ; les presets plats
    hérités (`default`, `male_1`…) n'en portent pas tous et restent hors des groupes, comme
    avant (« Voix par défaut » est un groupe à part, servi par l'appelant).
    """
    try:
        from wama.media_library.models import SystemAsset
        rows = list(SystemAsset.objects.filter(asset_type='voice', is_active=True)
                    .filter(attributes__has_keys=['language', 'age', 'gender'])
                    .only('id', 'name', 'attributes'))
    except Exception as exc:                       # base absente : un menu vide, pas une erreur
        logger.warning(f"[voice_refs] médiathèque illisible : {exc}")
        return []

    groups: Dict[tuple, Dict] = {}
    for a in rows:
        attrs = a.attributes or {}
        key = (str(attrs['language']).lower(), str(attrs['age']).lower())
        groups.setdefault(key, {'group': _group_label(attrs), 'voices': [], '_attrs': attrs})
        groups[key]['voices'].append(
            {'id': f'sa_{a.pk}', 'label': _option_label(attrs),
             '_ord': (str(attrs['gender']).lower(), int(attrs.get('variant') or 0))})
    out = []
    for key, g in sorted(groups.items(), key=lambda kv: _sort_key(kv[1]['_attrs'])):
        # `language` accompagne chaque voix : c'est ce que les filtres croisent avec les langues
        # du moteur (`data-language` sur l'option — marche 6, `WamaModelCaps.cloneVoiceFilter`).
        voices = [{'id': v['id'], 'label': v['label'], 'language': key[0]}
                  for v in sorted(g['voices'], key=lambda v: v['_ord'])]
        out.append({'group': g['group'], 'voices': voices})
    return out


# ---------------------------------------------------------------------------
# Résolution preset → chemin absolu
# ---------------------------------------------------------------------------

def _system_voice(name_or_pk, by_pk: bool = False):
    """La ligne `SystemAsset(voice)` désignée — par NOM (l'id de preset d'avant) ou par pk
    (`sa_<pk>`) ; `None` si absente, inactive, ou sans fichier sur disque."""
    try:
        from wama.media_library.models import SystemAsset
        qs = SystemAsset.objects.filter(asset_type='voice', is_active=True)
        row = (qs.filter(pk=int(name_or_pk)) if by_pk else qs.filter(name=name_or_pk)).first()
    except Exception:
        return None
    if row is None or not row.file:
        return None
    try:
        return row if os.path.isfile(row.file.path) else None
    except Exception:
        return None


def _system_voice_path(name_or_pk, by_pk: bool = False) -> Optional[str]:
    row = _system_voice(name_or_pk, by_pk)
    return row.file.path if row is not None else None


def readable_voice_assets(user):
    """Les voix de médiathèque qu'un utilisateur a le DROIT d'employer : les SIENNES **et celles
    qui lui sont partagées** (décision de Fabien, 2026-09-21 : *« une voix partagée doit être
    accessible en fonction des droits de chacun »*).

    ⚠ UN SEUL lecteur pour les DEUX surfaces — le SÉLECTEUR (`utils/voice_options.py`) et la
    RÉSOLUTION (`resolve_speaker_wav` ci-dessous). C'est tout l'enjeu : jusqu'au 21/09 les deux
    filtraient `user=user` chacun de son côté, et les ouvrir séparément aurait reproduit le
    défaut du « Envoyer vers… » (`WAMA_VERIFICATION §Geste 14`) — proposer un choix que le
    serveur refuse ensuite. Ici le refus serait MUET : `resolve_speaker_wav` replie sur la voix
    `default`, donc on aurait synthétisé avec la mauvaise voix sans un message d'erreur.

    ⚠ Le compte de service anonyme est une VRAIE ligne `User`, et `scoped_visible_q` pose
    `Q(visibility='public')` HORS du test d'authentification : sans cette garde, un visiteur
    hériterait des voix publiques de tout le parc. Même garde qu'`api_list` (médiathèque).

    `user=None` (aucun contexte d'utilisateur — tests, résolution par nom) garde le comportement
    d'avant : aucune restriction. Les trois appelants réels passent tous un utilisateur.
    """
    from wama.accounts.views import ANONYMOUS_USERNAME
    from wama.media_library.models import UserAsset

    qs = UserAsset.objects.filter(asset_type='voice')
    if user is None:
        return qs
    if getattr(user, 'username', '') == ANONYMOUS_USERNAME:
        return qs.filter(user=user)
    return qs.visible_to(user)


def resolve_speaker_wav(voice_preset: str, user=None) -> Optional[str]:
    """
    Résout un voice_preset en chemin `speaker_wav` (audio de référence) pour le CLONAGE
    de voix. Logique CENTRALISÉE, partagée par les workers et les aperçus :
      - sa_<id> → SystemAsset (médiathèque commune — les voix de référence) ;
      - ua_<id> → UserAsset (médiathèque de l'utilisateur ; `user` la restreint) ;
      - cv_<id> → CustomVoice (hérité) ;
      - bark_*  → None (Bark résout ses locuteurs dans son backend) ;
      - sinon   → la voix de référence qui porte ce NOM (`french/adult/male_adult_1_fr`,
                  `female_1`… — les ids que les lignes en base stockent, décision D5).
    Repli : la voix `default` de la médiathèque — XTTS EXIGE un fichier, lui en donner un est
    plus sûr que de lui en refuser un (c'était déjà le sens du repli disque). `None` seulement
    si la médiathèque n'a pas non plus de `default`.
    """
    if not voice_preset:
        return _system_voice_path('default')
    if voice_preset.startswith('bark_v2_'):
        return None
    if voice_preset.startswith('sa_'):
        return _system_voice_path(voice_preset[3:], by_pk=True) or _system_voice_path('default')
    if voice_preset.startswith('ua_'):
        try:
            # Les voix VISIBLES, pas seulement les miennes (21/09) — mesuré avant de resserrer
            # sur `asset_type='voice'` : aucune valeur `ua_` n'est stockée en base à ce jour.
            ua = readable_voice_assets(user).filter(pk=int(voice_preset[3:])).first()
            if ua and ua.file:
                return ua.file.path
        except Exception:
            pass
        return _system_voice_path('default')
    if voice_preset.startswith('cv_'):
        try:
            from wama.synthesizer.models import CustomVoice
            cv = CustomVoice.objects.filter(pk=int(voice_preset[3:])).first()
            if cv and cv.audio:
                return cv.audio.path
        except Exception:
            pass
        return _system_voice_path('default')
    return _system_voice_path(voice_preset) or _system_voice_path('default')


def is_cloned_voice(voice_preset: str) -> bool:
    """Cette voix est-elle un CLONAGE (`ua_<id>` médiathèque de l'utilisateur, `cv_<id>` hérité) ?
    Jumeau SERVEUR de `WamaModelCaps.isClonedVoice` — même prédicat, deux langages ; c'est ce
    que le tirage automatique lit pour exiger `supports_cloning` (décision Fabien 13/09).
    ⚠ Une voix de RÉFÉRENCE (`sa_<id>`) n'est pas un clonage au sens de l'UI : tout moteur la
    reçoit comme `speaker_wav` s'il clone, l'ignore sinon."""
    return str(voice_preset or '').startswith(('ua_', 'cv_'))


def model_supports_cloning(model_key: str) -> Optional[bool]:
    """Le moteur du modèle `model_key` CLONE-t-il ? — `True`/`False` si quelque chose le dit,
    `None` si rien ne le dit.

    Autorité, dans l'ordre : la CLASSE de moteur (`backend_for_key`, le flag `supports_cloning`
    du contrat commun), puis la ligne de catalogue (`AIModel.capabilities`, réconciliée sur
    le moteur par `apply_engine_flags`). Aucune liste de clés ici : c'est la règle D7 de
    `MEDIA_STORAGE_TIERING §9.1` — *la capacité décide, jamais `tts_model == 'coqui-xtts'`*.
    ⚠ Ce test-là était d'ailleurs MORT au moment de le retirer (13/09) : `tts_model` porte la
    clé entière (`synthesizer:coqui-xtts`, 100 % des lignes), la comparaison au nom nu n'était
    jamais vraie, et c'est le SERVICE qui résolvait la voix à la place de Django.
    """
    if not model_key:
        return None
    try:
        from wama.common.backends.manager import backend_for_key
        cls = backend_for_key(model_key)
    except Exception:                          # hors Django, base absente : pas de verdict ici
        cls = None
    if cls is not None:
        return bool(getattr(cls, 'supports_cloning', False))
    try:
        from wama.model_manager.models import AIModel
        ligne = AIModel.objects.filter(model_key=model_key).only('capabilities').first()
    except Exception:
        ligne = None
    caps = (getattr(ligne, 'capabilities', None) or {})
    if 'supports_cloning' in caps:
        return bool(caps['supports_cloning'])
    return None


def speaker_wav_for(model_key: str, voice_preset: str, user=None,
                    reference_path: Optional[str] = None) -> Optional[str]:
    """LA porte des workers et des aperçus : le `speaker_wav` à passer au service TTS.

    - le moteur ne clone PAS (déclaré) → `None`, quelle que soit la voix choisie : l'UI grise
      déjà ces moteurs pour une voix clonée (`WamaInputMatch.voiceSlot`) ; ici on ne fait que
      tenir la même règle côté serveur ;
    - le moteur clone, ou rien ne le dit → un fichier de référence par job (`reference_path`)
      prime, sinon `resolve_speaker_wav` (ua_/cv_/presets). Un moteur INCONNU reçoit donc
      une voix : XTTS l'EXIGE, un moteur sans clonage l'ignore — le sens sûr.

    Le service (`tts_service.py`) ne résout plus rien : tout `speaker_wav` vient d'ici (D6).
    """
    if model_supports_cloning(model_key) is False:
        return None
    if reference_path:
        return reference_path
    return resolve_speaker_wav(voice_preset, user)


def ingest_voice_file(name: str, path, *, source_url: str = '', license: str = '',
                      description: str = '', replace: bool = False):
    """Verse UN fichier de voix dans la médiathèque comme `SystemAsset(voice)` nommé `name`,
    attributs déduits de l'id (`attributes_from_voice_id`). Idempotent : un nom déjà porté est
    rendu tel quel (ou son fichier REMPLACÉ si `replace`). Le stockage Django COPIE sous
    `media_library/system/` — l'appelant décide du sort de l'original.

    C'est LE point d'entrée commun de l'ingest initial (`ingest_voice_refs`) et des
    téléchargements (`download_missing_voice_refs`) : une voix n'entre jamais autrement.
    """
    import wave

    from django.core.files import File

    from wama.media_library.models import SystemAsset

    path = Path(path)
    existing = SystemAsset.objects.filter(asset_type='voice', name=name).first()
    if existing is not None and not replace:
        return existing

    duration = None
    try:
        with wave.open(str(path), 'rb') as w:
            duration = w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        pass

    asset = existing or SystemAsset(name=name, asset_type='voice')
    asset.attributes = attributes_from_voice_id(name)
    asset.mime_type = 'audio/wav'
    asset.file_size = path.stat().st_size
    asset.duration = duration
    if source_url:
        asset.source_url = source_url
    if license:
        asset.license = license
    if description:
        asset.description = description
    with open(path, 'rb') as fh:
        # `upload_to` décide du domicile (`media_library/system/`) — on ne compose aucun chemin.
        asset.file.save(path.name, File(fh), save=False)
    asset.save()
    return asset


# ---------------------------------------------------------------------------
# Catalogue de téléchargement automatique
# ---------------------------------------------------------------------------

# Domicile UNIQUE de ces deux bases : la brique commune TTS et le registre de sources. Elles
# étaient recopiées ici et dans `workers.py` (2026-09-01).
from wama.common.tts.constants import LJ_BASE as _LJ_BASE
from wama.common.external_sources import base_url as _base_url

_XTTS_BASE = _base_url('huggingface') + '/coqui/XTTS-v2/resolve/main/samples'

# Clé  = chemin relatif SANS .wav dans voice_references/
# Valeur = liste de (url, description) essayées dans l'ordre ; la première qui
#          réussit est conservée. LJSpeech sert de fallback fiable pour l'anglais.
#
# Note sur les genres :
#   - LJSpeech (LJ001-*.wav) = Linda Johnson, femme adulte anglophone (certifié)
#   - XTTS-v2 *_sample.wav   = voix de démonstration multilingues (adultes)
#     Le genre exact peut varier selon la langue ; remplacer par de vraies
#     voix étiqueté es si la précision est importante.
VOICE_DOWNLOAD_CATALOG: Dict[str, List[tuple]] = {
    # ── Fallback racine ───────────────────────────────────────────────────
    'default': [
        (f"{_LJ_BASE}/LJ001-0001.wav", "LJSpeech EN female (default)"),
    ],

    # ── Anglais — Adulte ──────────────────────────────────────────────────
    'english/adult/female_adult_1_en': [
        (f"{_LJ_BASE}/LJ001-0001.wav", "LJSpeech EN female clip 1"),
    ],
    'english/adult/female_adult_2_en': [
        (f"{_LJ_BASE}/LJ001-0010.wav", "LJSpeech EN female clip 2"),
    ],
    'english/adult/male_adult_1_en': [
        (f"{_XTTS_BASE}/en_sample.wav",      "XTTS-v2 EN reference sample"),
        (f"{_LJ_BASE}/LJ001-0015.wav",       "LJSpeech EN fallback"),
    ],
    'english/adult/male_adult_2_en': [
        (f"{_XTTS_BASE}/en_sample.wav",      "XTTS-v2 EN reference sample"),
        (f"{_LJ_BASE}/LJ001-0020.wav",       "LJSpeech EN fallback"),
    ],

    # ── Français — Adulte ─────────────────────────────────────────────────
    # Note : le dépôt coqui/XTTS-v2 ne fournit qu'un seul échantillon par langue
    # ({lang}_sample.wav) — pas de variantes gender (_male_/_female_, supprimées
    # car 404). Les voix diversifiées proviennent de VoxPopuli (catalogue datasets).
    'french/adult/female_adult_1_fr': [
        (f"{_XTTS_BASE}/fr_sample.wav",        "XTTS-v2 FR reference sample"),
    ],
    'french/adult/female_adult_2_fr': [
        (f"{_XTTS_BASE}/fr_sample.wav",        "XTTS-v2 FR fallback"),
    ],
    'french/adult/male_adult_1_fr': [
        (f"{_XTTS_BASE}/fr_sample.wav",        "XTTS-v2 FR fallback"),
    ],

    # ── Espagnol — Adulte ─────────────────────────────────────────────────
    'spanish/adult/female_adult_1_es': [
        (f"{_XTTS_BASE}/es_sample.wav", "XTTS-v2 ES reference sample"),
    ],

    # ── Allemand — Adulte ─────────────────────────────────────────────────
    'german/adult/female_adult_1_de': [
        (f"{_XTTS_BASE}/de_sample.wav", "XTTS-v2 DE reference sample"),
    ],

    # ── Italien — Adulte ──────────────────────────────────────────────────
    # (it_sample.wav absent du dépôt XTTS-v2 → italien uniquement via VoxPopuli)

    # ── Portugais — Adulte ────────────────────────────────────────────────
    'portuguese/adult/female_adult_1_pt': [
        (f"{_XTTS_BASE}/pt_sample.wav", "XTTS-v2 PT reference sample"),
    ],
}


# ---------------------------------------------------------------------------
# Catalogue datasets HuggingFace (VoxPopuli)
# ---------------------------------------------------------------------------
# Priorité : VoxPopuli (Facebook, sans auth, locuteurs diversifiés) >
#            URLs directes du VOICE_DOWNLOAD_CATALOG.
#
# Note : Mozilla Common Voice a été retiré de HuggingFace en octobre 2025
# et migré vers datacollective.mozillafoundation.org — non intégré ici.

# Mapping : rel_path → vp_lang_code pour VoxPopuli (Facebook, sans auth)
# Common Voice a été retiré de HuggingFace en octobre 2025 (migré vers
# datacollective.mozillafoundation.org) — VoxPopuli est désormais la source
# principale pour les voix avec locuteurs diversifiés.
_VOICE_DATASETS_CATALOG: Dict[str, str] = {
    # ── Anglais ───────────────────────────────────────────────────────────
    'english/adult/female_adult_1_en': 'en',
    'english/adult/female_adult_2_en': 'en',
    'english/adult/male_adult_1_en':   'en',
    'english/adult/male_adult_2_en':   'en',
    'english/elderly/female_elderly_en': 'en',
    'english/elderly/male_elderly_en':   'en',
    'english/child/female_child_en':     'en',
    'english/child/male_child_en':       'en',

    # ── Français ─────────────────────────────────────────────────────────
    'french/adult/female_adult_1_fr': 'fr',
    'french/adult/female_adult_2_fr': 'fr',
    'french/adult/male_adult_1_fr':   'fr',
    'french/adult/male_adult_2_fr':   'fr',
    'french/elderly/female_elderly_fr': 'fr',
    'french/elderly/male_elderly_fr':   'fr',
    'french/child/female_child_fr':     'fr',
    'french/child/male_child_fr':       'fr',

    # ── Espagnol ──────────────────────────────────────────────────────────
    'spanish/adult/female_adult_1_es': 'es',
    'spanish/adult/male_adult_1_es':   'es',

    # ── Allemand ──────────────────────────────────────────────────────────
    'german/adult/female_adult_1_de': 'de',
    'german/adult/male_adult_1_de':   'de',

    # ── Italien ───────────────────────────────────────────────────────────
    'italian/adult/female_adult_1_it': 'it',
    'italian/adult/male_adult_1_it':   'it',
}

# Speakers déjà utilisés par session (évite de prendre le même locuteur
# pour deux slots différents du même catalogue).
_used_vp_speakers: Dict[str, set] = {}   # {lang: {speaker_id, ...}}

_VP_MIN_S, _VP_MAX_S = 5.0, 15.0    # durée acceptable pour la référence vocale
_VP_MAX_ITER = 10_000                # limite de sécurité pour l'itération streaming

#: Les ÂGES qu'une source peut réellement fournir. VoxPopuli = débats du Parlement européen,
#: sans champ d'âge : des adultes, et rien d'autre. Un créneau « child » ou « elderly » n'en
#: reçoit donc JAMAIS de clip — il en recevait un jusqu'au 2026-09-21, sous un âge inventé.
_SOURCE_AGE_COVERAGE = {'voxpopuli': {'adult'}}


def _url_source_gender(url: str) -> str:
    """Le genre ÉTABLI d'une source URL, ou '' s'il ne l'est pas.

    Une source au genre inconnu ne remplit AUCUN créneau genré : c'est ce qui fermait mal la
    porte jusqu'au 2026-09-21 — les créneaux masculins anglais retombaient sur LJSpeech, et
    les trois créneaux français adultes (deux féminins, un masculin) sur le MÊME échantillon.
      • LJSpeech : une seule locutrice, femme adulte — certifié (voir le catalogue ci-dessus).
      • XTTS-v2 : MESURÉ le 21/09, F0 médiane sur trames voisées (`MEDIA_STORAGE_TIERING
        §9.4bis`) — fr 133 Hz et es 125 Hz : hommes ; de 196 Hz et pt 198 Hz : femmes.
        L'échantillon anglais n'a jamais été téléchargé : son genre n'est pas établi.
    """
    if url.startswith(_LJ_BASE):
        return 'female'
    return {
        f"{_XTTS_BASE}/fr_sample.wav": 'male',
        f"{_XTTS_BASE}/es_sample.wav": 'male',
        f"{_XTTS_BASE}/de_sample.wav": 'female',
        f"{_XTTS_BASE}/pt_sample.wav": 'female',
    }.get(url, '')


def _save_audio_array(arr, sr: int, target: Path) -> bool:  # noqa: ANN001
    """Écrit un tableau numpy audio en WAV. Retourne True si succès."""
    try:
        import soundfile as sf
        sf.write(str(target), arr, sr)
    except ImportError:
        try:
            import numpy as np
            from scipy.io import wavfile
            arr_int16 = (arr * 32767).astype(np.int16)
            wavfile.write(str(target), sr, arr_int16)
        except Exception as exc:
            logger.warning(f"[voice_refs] Impossible d'écrire le WAV (soundfile/scipy requis) : {exc}")
            return False
    except Exception as exc:
        logger.warning(f"[voice_refs] Erreur écriture WAV : {exc}")
        return False

    ok = target.exists() and target.stat().st_size > 1024
    if not ok:
        target.unlink(missing_ok=True)
    return ok



def _decode_audio_item(audio) -> tuple:  # noqa: ANN001
    """
    Décode un item audio de `datasets` SANS torchcodec.

    `datasets` 4.x décode la colonne Audio via torchcodec par défaut, ce qui
    casse dès que torchcodec/FFmpeg ne sont pas parfaitement alignés avec la
    version de torch (cf. `libtorchcodec` / `undefined symbol _ZN3c10...`).
    On contourne en demandant les octets bruts (decode=False côté appelant)
    puis en décodant avec soundfile (libsndfile), sans dépendance torch.

    Accepte :
      - dict déjà décodé : {'array': ndarray, 'sampling_rate': int}
      - dict brut        : {'bytes': b'...', 'path': '...'} (decode=False)
    Retourne (array, sampling_rate) ou (None, None) en cas d'échec.
    """
    import io
    import os

    if isinstance(audio, dict) and audio.get('array') is not None:
        return audio['array'], audio.get('sampling_rate')

    try:
        import soundfile as sf
    except ImportError:
        return None, None

    raw = audio.get('bytes') if isinstance(audio, dict) else None
    if raw:
        try:
            arr, sr = sf.read(io.BytesIO(raw))
            return arr, sr
        except Exception:
            pass

    path = audio.get('path') if isinstance(audio, dict) else None
    if path and os.path.exists(path):
        try:
            arr, sr = sf.read(path)
            return arr, sr
        except Exception:
            pass

    return None, None


def _normalize_gender(value) -> str:
    """'male' / 'female' / '' — tolère les formes courtes et la casse des jeux de données."""
    v = str(value or '').strip().lower()
    return {'m': 'male', 'f': 'female'}.get(v, v if v in ('male', 'female') else '')


#: Bornes de F0 médiane sur de la parole adulte. Entre les deux : zone grise, NON tranchée.
_F0_MALE_BELOW, _F0_FEMALE_ABOVE = 150.0, 180.0


def _measured_gender(arr, sr: int):
    """Le genre que la VOIX fait entendre : 'male' / 'female', '' si non établi (zone grise,
    trop peu de trames voisées), None si l'instrument manque.

    Pourquoi mesurer alors que VoxPopuli étiquette le genre : mesuré le 2026-09-22, après le
    retéléchargement filtré sur l'étiquette, **2 clips sur 9 étiquetés « male » sonnaient à 262 et
    184 Hz** — confirmé par DEUX instruments indépendants (autocorrélation, puis pYIN, robuste aux
    erreurs d'octave). L'étiquette de la source ne suffit donc pas : on ne pose un genre que si la
    voix le fait entendre (`MEDIA_STORAGE_TIERING §9.4bis`).
    """
    try:
        import librosa
        import numpy as np
    except ImportError:
        return None
    y = np.asarray(arr, dtype=np.float32)
    if y.ndim > 1:
        y = y.mean(axis=1)
    f0, voiced, _ = librosa.pyin(y, fmin=65, fmax=400, sr=sr, frame_length=1024)
    f0 = f0[voiced & ~np.isnan(f0)]
    if len(f0) < 10:
        return ''
    median = float(np.median(f0))
    if median < _F0_MALE_BELOW:
        return 'male'
    if median > _F0_FEMALE_ABOVE:
        return 'female'
    return ''


def _file_digest(path: Path) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _library_voice_digests(except_name: str = '') -> set:
    """Empreintes des fichiers des AUTRES voix de la médiathèque.

    Pourquoi : `_used_vp_speakers` ne vit que le temps d'un processus. Mesuré le 2026-09-22 —
    deux passages successifs ont donné à `male_adult_1_en` et `male_adult_2_en` le MÊME clip :
    deux voix du menu, une seule personne. Le flux de VoxPopuli est ordonné, le premier clip qui
    passe les filtres est donc toujours le même ; seule la médiathèque se souvient de ce qui est
    déjà pris.
    """
    try:
        from wama.media_library.models import SystemAsset
        rows = SystemAsset.objects.filter(asset_type='voice').exclude(name=except_name)
        return {_file_digest(r.file.path) for r in rows if r.file and Path(r.file.path).is_file()}
    except Exception:
        return set()


def _try_voxpopuli(target: Path, vp_lang: str, gender: str = '',
                   exclude_digests=frozenset()) -> bool:
    """
    Télécharge un clip depuis VoxPopuli (Facebook/Meta). Aucune authentification requise.

    ⚠⚠ Cette docstring disait jusqu'au 2026-09-21 : « Pas de métadonnées genre/âge ». C'était
    FAUX pour le genre — le schéma du jeu de données porte `gender` et `speaker_id` (lu le
    21/09 à l'API d'information de HuggingFace). La boucle retenait donc le PREMIER clip d'un
    locuteur neuf, sans regarder son genre, et le versait sous un nom qui en annonçait un :
    **12 contradictions sur 25 voix jugeables**, mesurées par F0 (`MEDIA_STORAGE_TIERING
    §9.4bis`). `gender` filtre désormais ; un clip au genre absent ou différent est SAUTÉ — ce
    qu'on ne sait pas, on ne le promet pas.
    ⚠ L'ÂGE, lui, n'y est vraiment pas : ce sont des débats du Parlement européen, des adultes.
    Aucun créneau « enfant » ni « âgé » ne peut en venir (`_SOURCE_AGE_COVERAGE`).

    Retourne True si un clip a été enregistré avec succès.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        return False
    try:
        from datasets import Audio
    except ImportError:
        Audio = None

    # Langues supportées par VoxPopuli
    _VP_LANGS = {'en', 'fr', 'de', 'es', 'it', 'pt', 'pl', 'nl',
                 'fi', 'hu', 'ro', 'sk', 'sl', 'et', 'hr', 'lt', 'lv', 'cs', 'bg', 'da'}
    if vp_lang not in _VP_LANGS:
        return False

    # Patch de compatibilité transformers 4.57+ (PreTrainedTokenizerBase déplacé)
    try:
        import transformers as _tr
        if not hasattr(_tr, 'PreTrainedTokenizerBase'):
            _tr.PreTrainedTokenizerBase = _tr.tokenization_utils_base.PreTrainedTokenizerBase
    except Exception:
        pass

    used = _used_vp_speakers.setdefault(vp_lang, set())

    try:
        logger.info(f"[voice_refs] VoxPopuli streaming : lang={vp_lang} …")
        ds = load_dataset(
            "facebook/voxpopuli", vp_lang,
            split="train",
            streaming=True,
        )
        # Décodage maison (soundfile) au lieu de torchcodec : on récupère les
        # octets bruts. Évite `Could not load libtorchcodec` quand torchcodec
        # n'est pas aligné avec torch/FFmpeg.
        if Audio is not None:
            try:
                ds = ds.cast_column("audio", Audio(decode=False))
            except Exception:
                pass
    except Exception as exc:
        logger.warning(f"[voice_refs] Impossible d'ouvrir VoxPopuli ({vp_lang}) : {exc}")
        return False

    try:
        for i, item in enumerate(ds):
            if i >= _VP_MAX_ITER:
                break

            speaker = item.get('speaker_id', str(i))
            if speaker in used:
                continue
            if gender and _normalize_gender(item.get('gender')) != gender:
                continue

            arr, sr = _decode_audio_item(item.get('audio'))
            if arr is None or not sr:
                continue
            duration = len(arr) / sr
            if not (_VP_MIN_S <= duration <= _VP_MAX_S):
                continue
            # L'étiquette de la source ne suffit pas (2/9 contredites, 22/09) : la voix doit FAIRE
            # ENTENDRE le genre demandé. Contredite ou zone grise → clip suivant. Instrument absent
            # (None) → on s'en tient à l'étiquette, faute de mieux.
            if gender:
                heard = _measured_gender(arr, sr)
                if heard is not None and heard != gender:
                    continue

            if _save_audio_array(arr, sr, target):
                used.add(speaker)
                # Déjà la voix d'un AUTRE nom de la médiathèque → clip suivant : deux voix du menu
                # ne sont jamais la même personne (22/09).
                if exclude_digests and _file_digest(target) in exclude_digests:
                    target.unlink(missing_ok=True)
                    continue
                logger.info(f"[voice_refs] VoxPopuli OK : {target.name} "
                            f"({duration:.1f}s, locuteur {speaker})")
                return True

    except Exception as exc:
        logger.warning(f"[voice_refs] Erreur streaming VoxPopuli : {exc}")

    return False


def _try_url_download(target: Path, sources: List[tuple]) -> bool:
    """Télécharge depuis une liste d'URLs directes. Retourne True si succès."""
    import urllib.request

    for url, description in sources:
        try:
            logger.info(f"[voice_refs] URL fallback : {description} …")
            urllib.request.urlretrieve(url, str(target))
            if target.exists() and target.stat().st_size > 1024:
                logger.info(f"[voice_refs] URL OK : {target.name} "
                            f"({target.stat().st_size // 1024} Ko)")
                return True
            target.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning(f"[voice_refs] Échec URL {url} : {exc}")
            target.unlink(missing_ok=True)

    return False


def _catalogue_names() -> set:
    return set(VOICE_DOWNLOAD_CATALOG) | set(_VOICE_DATASETS_CATALOG)


def _library_voice_names() -> set:
    try:
        from wama.media_library.models import SystemAsset
        return set(SystemAsset.objects.filter(asset_type='voice').values_list('name', flat=True))
    except Exception:
        return set()


def needs_voice_download() -> bool:
    """Vrai si une voix du catalogue n'est pas (encore) en médiathèque."""
    return bool(_catalogue_names() - _library_voice_names())


#: Provenance posée sur une voix TÉLÉCHARGÉE — la seule qu'on connaisse avec certitude.
_VOXPOPULI_URL = 'https://huggingface.co/datasets/facebook/voxpopuli'


def download_missing_voice_refs(force: bool = False, names=None) -> Dict[str, str]:
    """
    Télécharge les voix de référence manquantes et les VERSE en médiathèque.

    Stratégie pour chaque voix (dans l'ordre) :
      1. VoxPopuli (Facebook, sans auth) — locuteurs diversifiés, pip install datasets soundfile
      2. URLs directes (XTTS-v2 HuggingFace, LJSpeech GitHub) — fallback fiable
    Le fichier transite par un dossier temporaire ; c'est `ingest_voice_file` qui l'installe,
    avec sa provenance (`source_url` ; `license` seulement quand elle est CERTAINE — LJSpeech
    est du domaine public ; VoxPopuli et les échantillons XTTS-v2 restent à renseigner).

    ⚠ Le GENRE et l'ÂGE qu'annonce le nom sont des CONTRAINTES, plus des souhaits (21/09) :
    une source qui ne peut pas les garantir est sautée, et la voix finit en 'failed' plutôt
    que versée sous un libellé faux. *Un échec dit, plutôt qu'un mensonge muet.*

    Args:
        force: re-télécharge même si la voix est déjà en médiathèque (fichier remplacé).
        names: restreint le passage à ces noms (ex. les voix dont la mesure a contredit le
               libellé) ; None = tout le catalogue.

    Returns:
        dict {name: 'downloaded'|'skipped'|'failed'}
    """
    import shutil
    import tempfile

    results: Dict[str, str] = {}
    presentes = _library_voice_names()
    wanted_names = set(names) if names is not None else None
    tmp = Path(tempfile.mkdtemp(prefix='wama_voice_refs_'))
    try:
        for name in sorted(_catalogue_names()):
            if wanted_names is not None and name not in wanted_names:
                continue
            if name in presentes and not force:
                results[name] = 'skipped'
                continue

            target = tmp / (name.replace('/', '__') + '.wav')
            source_url, license_ = '', ''
            attrs = attributes_from_voice_id(name)
            gender, age = attrs.get('gender', ''), attrs.get('age', '')

            # ── 1. VoxPopuli — filtré par genre ; jamais pour un âge qu'il ne couvre pas ──
            if (name in _VOICE_DATASETS_CATALOG and _VOICE_DATASETS_CATALOG[name]
                    and (not age or age in _SOURCE_AGE_COVERAGE['voxpopuli'])):
                if _try_voxpopuli(target, _VOICE_DATASETS_CATALOG[name], gender=gender,
                                  exclude_digests=_library_voice_digests(except_name=name)):
                    source_url = _VOXPOPULI_URL

            # ── 2. URLs directes — une source au genre non établi ne remplit aucun créneau genré ──
            if not source_url and name in VOICE_DOWNLOAD_CATALOG:
                for url, description in VOICE_DOWNLOAD_CATALOG[name]:
                    if gender and _url_source_gender(url) != gender:
                        logger.info(f"[voice_refs] {name} : source refusée, genre non établi "
                                    f"ou contraire ({description})")
                        continue
                    if age and age != 'adult':
                        continue                  # aucune source URL ne documente un âge
                    if _try_url_download(target, [(url, description)]):
                        source_url = url
                        license_ = 'Public domain (LJSpeech)' if 'LJSpeech' in description else ''
                        break

            if not source_url:
                results[name] = 'failed'
                logger.error(f"[voice_refs] Toutes les sources ont échoué : {name}")
                continue
            try:
                ingest_voice_file(name, target, source_url=source_url, license=license_,
                                  replace=force)
                results[name] = 'downloaded'
            except Exception as exc:
                results[name] = 'failed'
                logger.error(f"[voice_refs] Versement en médiathèque impossible : {name} — {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    n_ok   = sum(1 for s in results.values() if s == 'downloaded')
    n_skip = sum(1 for s in results.values() if s == 'skipped')
    n_fail = sum(1 for s in results.values() if s == 'failed')
    logger.info(f"[voice_refs] Terminé : {n_ok} téléchargées, "
                f"{n_skip} déjà présentes, {n_fail} échec(s)")
    return results


def describe_voice(preset_value: str, user=None) -> str:
    """Le libellé d'une valeur de `voice_preset`, quelle que soit sa forme — pour AFFICHER
    (card, inspecteur) : `sa_<id>` / nom de référence → « Français — Adulte — Homme 1 » ;
    `ua_<id>` / `cv_<id>` → le nom donné par l'utilisateur ; preset plat ou Bark → le libellé
    de `VOICE_PRESET_CHOICES` ; sinon la valeur elle-même (on n'efface jamais une donnée).
    """
    if not preset_value:
        return ''
    if preset_value.startswith('sa_'):
        row = _system_voice(preset_value[3:], by_pk=True)
        return _voice_label(row) if row is not None else preset_value
    if preset_value.startswith('ua_'):
        try:
            from wama.media_library.models import UserAsset
            qs = UserAsset.objects.filter(pk=int(preset_value[3:]))
            if user is not None:
                qs = qs.filter(user=user)
            ua = qs.first()
            if ua:
                return ua.name
        except Exception:
            pass
        return preset_value
    if preset_value.startswith('cv_'):
        try:
            from wama.synthesizer.models import CustomVoice
            cv = CustomVoice.objects.filter(pk=int(preset_value[3:])).first()
            if cv:
                return cv.name
        except Exception:
            pass
        return preset_value
    from wama.common.tts.constants import VOICE_PRESET_CHOICES
    plat = dict(VOICE_PRESET_CHOICES).get(preset_value)
    if plat:
        return plat
    row = _system_voice(preset_value)
    if row is not None:
        return _voice_label(row)
    attrs = attributes_from_voice_id(preset_value)     # la ligne manque, l'id parle encore
    if all(k in attrs for k in ('language', 'age', 'gender')):
        return f"{_group_label(attrs)} — {_option_label(attrs)}"
    return preset_value
