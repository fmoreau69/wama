"""
Meta d'UI des moteurs TTS — brique COMMUNE aux apps qui exposent un select de moteur TTS.

Deux apps le font depuis le 2026-08-28 : le **synthesizer** (geste natif) et l'**avatarizer**
(pipeline dérivé texte→voix→avatar). Elles lisent le MÊME catalogue — `AIModel.source ==
'synthesizer'`, le lien app↔modèles étant `AIModel.source` — et affichent le même descriptif
de moteur. Extrait de `synthesizer/views.py` AU 2ᵉ CONSOMMATEUR : l'original a été remplacé
par un appel, jamais recopié (règle « zéro duplication », CLAUDE.md).

⚠ Ce module ne connaît AUCUNE de ses apps : la table valeur-d'option → suffixe-catalogue lui
est PASSÉE (`catalog_keys`), jamais importée. Même règle que le registre de fonctions — *le
substrat ne cite jamais ses producteurs*. Un `common/` qui importerait de `wama/<app>/`
inverserait la dépendance et rendrait la brique non réutilisable.

⚠⚠ `catalog_keys` est un jeu d'EXCEPTIONS, pas la liste des moteurs. La liste vient de
`TTS_MODEL_CHOICES` — c'est ce que le select propose RÉELLEMENT à l'utilisateur. La version
d'origine dérivait ses clés de `CATALOG_KEYS` (4 entrées) tout en peuplant le select depuis
`TTS_MODEL_CHOICES` (7 à l'époque) : `vits`, `tacotron2` et `speedy-speech` n'ont jamais reçu
de descriptif, et le commentaire qui l'expliquait (« pas d'entrée catalogue dédiée ») était
FAUX — mesuré le 2026-08-28, les 7 moteurs répondaient en identité à `synthesizer:<valeur>`.
*Une table de correspondance prise pour un inventaire perd tout ce qui n'a pas d'exception.*
(Ces trois moteurs ont été RETIRÉS le jour même — `REMOVAL_LEDGER` R32 — mais la règle vaut
indépendamment d'eux : c'est le raisonnement qui était faux, pas seulement son résultat.)

Django est importé PARESSEUSEMENT (dans les fonctions) : `common/tts/` est aussi consommé par
`tts_service.py`, service FastAPI qui n'a pas Django.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

#: Valeur d'`AIModel.source` sous laquelle vivent les moteurs TTS. Le préfixe est historique
#: (l'app synthesizer les a déclarés la première) ; il désigne le DOMAINE, pas l'app —
#: l'avatarizer lit le même jeu sans en posséder aucun.
TTS_CATALOG_SOURCE = 'synthesizer'


#: Tâche canonique qui DÉFINIT le parc TTS. C'est elle, et non `AIModel.source`, qui borne le
#: domaine depuis la route F4b : un moteur TTS sert plusieurs surfaces (le synthesizer le
#: déclare, l'avatarizer l'emprunte, l'assistant vocalise), et `source` est mono-valué.
TTS_TASK = 'text-to-speech'


def tts_engine_choices() -> list[tuple[str, str]]:
    """[(clé_catalogue, libellé)] des moteurs TTS — L'INVENTAIRE, tiré du CATALOGUE.

    Remplace `TTS_MODEL_CHOICES` comme source du select (route F4b étape ②, 2026-09-01).
    Mesuré avant de basculer : le catalogue portait **7** moteurs quand la liste en dur en
    proposait **4** — Kokoro-ONNX (installé la veille, 3,3 s de chargement contre 87,9 s pour
    le `.pt`), chatterbox et Audio8 étaient catalogués, téléchargés… et inchoisissables.

    Les valeurs sont les clés catalogue ENTIÈRES (`synthesizer:kokoro`), c'est-à-dire
    exactement ce que sert `/model-manager/api/models/options/?task=text-to-speech`. Le
    pré-rendu serveur et le peuplement JS parlent ainsi le MÊME vocabulaire : sans cela, le
    `sel.value = cur` de `_bindOptionSources` ne retrouverait pas la valeur courante et le
    select retomberait EN SILENCE sur sa première option.

    Repli `[]` assumé : sans catalogue, le select se peuple par l'endpoint. Rendre ici la
    vieille liste en dur ferait réapparaître l'ancien espace de clés — donc précisément la
    panne silencieuse qu'on vient de décrire.
    """
    try:
        from wama.model_manager.services import get_registry_models
        choices, _info = get_registry_models(None, task=TTS_TASK)
        return [(mid, nom) for mid, nom in choices]
    except Exception:                                    # catalogue indisponible / hors Django
        return []


def tts_engine_declared(key: str) -> Optional[str]:
    """Moteur DÉCLARÉ d'un modèle TTS — `composition.runtime.engine` au catalogue.

    C'est la voie GÉNÉRALE de dispatch de la route F4b : elle seule permet d'exécuter un
    modèle qu'aucune app ne déclare, dont le nom ne ressemble à aucun moteur
    (`onnx-community/Kokoro-82M-v1.0-ONNX` → `kokoro-onnx`). Le service TTS n'a pas Django :
    il ne peut pas lire le catalogue, on résout ici et on lui PASSE la réponse.

    `None` = rien de déclaré → l'appelant retombe sur le routage par le NOM, qui suffit aux
    moteurs historiques. On ne devine jamais un moteur : un mauvais routage silencieux est
    exactement ce que `engine_for_model` a cessé de faire (le repli `'coqui'` qui chargeait
    XTTS v2 à la place du moteur demandé).
    """
    if not key:
        return None
    try:
        from wama.model_manager.models import AIModel
        m = AIModel.objects.filter(model_key=key).only('composition').first()
        if not m:
            return None
        return ((m.composition or {}).get('runtime') or {}).get('engine') or None
    except Exception:
        return None


def tts_engine_label(key: str) -> str:
    """Libellé lisible d'un moteur TTS — le pendant de `get_FOO_display()` de Django.

    Django fabriquait cette méthode à partir du `choices=` du champ ; en retirant la liste du
    modèle (route F4b ②) on a retiré la méthode avec elle. Le libellé vient donc de là où vit
    désormais l'inventaire : le catalogue.

    Repli = la clé elle-même, jamais une chaîne vide : un moteur retiré du catalogue doit
    rester IDENTIFIABLE dans un travail ancien. Afficher « » à la place de
    `synthesizer:higgs-audio` transformerait une information en absence.
    """
    if not key:
        return ''
    for valeur, libelle in tts_engine_choices():
        if valeur == key:
            return libelle
    return key


def _engines() -> list[str]:
    """Moteurs réellement proposés à l'utilisateur (valeurs d'option du select).

    ⚠ Dérivait de `TTS_MODEL_CHOICES` en se disant « ce que le select propose RÉELLEMENT ».
    Cette phrase est devenue FAUSSE le 2026-09-01, quand le select est passé au catalogue :
    elle aurait rendu 4 moteurs là où l'utilisateur en voit 7, privant les 3 nouveaux de
    descriptif et d'appariement entrée↔modèle — sans que rien ne le signale. *Une source
    « de ce qui est proposé » doit suivre ce qui est proposé, sinon elle ment en silence.*
    """
    return [value for value, _label in tts_engine_choices()]


def _suffix_of(engine: str, catalog_keys: Optional[Mapping[str, str]]) -> str:
    """Suffixe catalogue d'un moteur — l'exception déclarée, sinon le moteur lui-même."""
    return (catalog_keys or {}).get(engine, engine)


def tts_input_match_meta(catalog_keys: Optional[Mapping[str, str]] = None
                         ) -> Dict[str, Dict[str, Any]]:
    """{valeur_option: {label, inputs_required, inputs_optional}} pour `WamaInputMatch`.

    Direction ENTRÉE→MODÈLE (une voix clonée désactive les moteurs sans clonage) ; la
    direction inverse est `WamaModelCaps`, qui va chercher ses capacités lui-même.
    Fail-safe {} hérité de `input_match_meta`.

    ⚠ Bornée par la TÂCHE depuis le 2026-09-01 (route F4b), plus par `AIModel.source` : les
    options du select viennent d'une requête par capacité, et une meta ancrée sur `source`
    n'aurait rien eu à dire des 3 moteurs d'une autre source — appariement MUET, sans erreur.
    `catalog_keys` n'est plus utilisé pour re-clé (les clés d'option SONT celles du catalogue) ;
    le paramètre reste accepté pour ne pas casser ses deux appelants, et parce qu'il demeure le
    point d'accroche déclaré d'un futur id divergent.
    """
    from wama.common.utils.input_match import input_match_meta
    return input_match_meta(task=TTS_TASK)


# ⚠ PAS de `tts_language_meta()` ici — une telle fonction a été écrite le 2026-08-29 puis
# RETIRÉE le jour même, avant d'avoir un consommateur. Elle projetait la couverture de langue
# de chaque moteur dans le contexte de gabarit… alors que `WamaModelCaps` (JS commun) va DÉJÀ
# chercher `AIModel.capabilities` par lui-même (`api/models/db/?source=synthesizer`) et filtre
# le select de langue sur `caps.languages` dans les DEUX apps. Le besoin réel — le 3ᵉ état
# `fallback_languages` — se règle donc DANS cette brique-là (`WamaModelCaps.langFilter`), pas
# par un second chemin vers le même fait. *Deux chemins vers un même fait finissent par en dire
# deux choses* : c'est précisément le défaut qu'on venait de solder côté registre (les
# `languages` déclarées en double, divergentes, dont une seule atteignait le catalogue).


def tts_model_help_meta(catalog_keys: Optional[Mapping[str, str]] = None
                        ) -> Dict[str, Dict[str, Any]]:
    """{valeur_option: {description, description_long, vram_gb}} pour `WamaModelHelp`.

    Lue du CATALOGUE `AIModel` (source unique). Fail-safe {} si le catalogue est
    indisponible : l'aide reste vide, la page ne tombe pas.

    ⚠ Une app dont le select est GÉNÉRÉ par `WamaParams` n'a pas besoin d'appeler ceci :
    `_bindModelHelp` auto-câble la brique et va chercher la meta via
    `WamaModelHelp.fetchCatalogMeta(help_source)`. Cette fonction sert aux selects écrits
    à la main (synthesizer), où la meta transite par le contexte de gabarit.

    ⚠ Les clés rendues sont les clés catalogue ENTIÈRES depuis le 2026-09-01 — comme les
    valeurs d'option. L'ancienne version RECOMPOSAIT une clé (`f"{source}:{suffixe}"`) à
    partir d'un moteur nu ; nourrie des nouvelles valeurs elle aurait fabriqué
    `synthesizer:synthesizer:kokoro` et rendu une meta vide, donc un descriptif absent sous
    chaque select. *Une clé qui se recompose est une clé qui se désynchronise.*
    """
    try:
        from wama.model_manager.models import AIModel
        cles = _engines()                       # déjà les clés catalogue entières
        meta: Dict[str, Dict[str, Any]] = {}
        for m in AIModel.objects.filter(model_key__in=cles):
            meta[m.model_key] = {
                'description': m.description_short or '',
                'description_long': m.description or '',
                'vram_gb': m.vram_gb,
            }
        return meta
    except Exception:
        return {}
