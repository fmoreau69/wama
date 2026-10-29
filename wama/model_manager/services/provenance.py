"""
Identité d'un modèle chez son éditeur — et pose de cette identité PAR LE MANIFESTE.

POURQUOI CE MODULE. Trois endroits interrogeaient déjà HuggingFace pour la même chose :
`prospector.prospect_hf` (licence des candidats), `backfill_platform_refs._licenses` (licence
des installés) et — c'était le trou — RIEN du côté installation. Un modèle ajouté par URL via
l'assistant arrivait donc au catalogue aussi anonyme que les 70 issus du scan disque : le
`register_after_install()` qui suit l'installation n'est qu'un `full_sync`, et la découverte ne
sait rien de la licence ni de l'auteur.

LE CHEMIN, ET POURQUOI IL PASSE PAR LE MANIFESTE.
    installation → sync → la ligne AIModel EXISTE (faits de découverte : chemin, format, classes)
                        → manifeste = extraction + identité de l'éditeur superposée
                        → write_back → le catalogue reçoit licence/auteur/platform_ref
                        → le manifeste est écrit au corpus

L'ordre n'est pas une coquetterie. `write_back_model` REFUSE de créer une ligne (un modèle se
découvre, il ne se déclare pas) : la ligne doit donc préexister. Et l'identité doit transiter par
le manifeste plutôt que d'être écrite en base directement, sinon le corpus resterait à l'écart et
la prochaine extraction n'aurait rien à porter — c'est exactement la boucle qui se refermait sur
du vide avant le 2026-08-12.

CE QUI N'EST PAS FAIT ICI. Aucune déduction : si l'éditeur ne déclare pas de licence, le champ
reste vide. Voir la doctrine de `backfill_platform_refs`.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from wama.common.external_sources import hf_platform_ref

logger = logging.getLogger(__name__)


def huggingface_identity(repo_id: str) -> Optional[dict]:
    """
    `{license, author, platform_ref, gated}` lu sur la carte du dépôt, ou None si injoignable.

    L'auteur et la licence viennent de la MÊME requête : les séparer coûterait un aller-retour
    par modèle pour deux faits posés sur la même table. `gated` a rejoint le lot pour cette
    raison exacte (2026-09-07) — `model_info()` le rend dans la réponse déjà demandée, donc
    l'ignorer coûtait un fait, pas une requête.
    """
    repo_id = (repo_id or '').strip()
    if not repo_id:
        return None
    try:
        from huggingface_hub import HfApi
    except ImportError:
        logger.debug("[provenance] huggingface_hub absent")
        return None
    try:
        # La lecture du Hub de la prospection, et sa reprise sur 429 (2026-10-29 : un rattrapage de
        # ~300 cartes a reçu 298 refus d'affilée — la limite de débit, pas des dépôts absents).
        from .prospector import _hub_model_info
        info = _hub_model_info(HfApi(), repo_id)
    except Exception as e:
        logger.info(f"[provenance] {repo_id} injoignable : {type(e).__name__}")
        return None

    license_id = ''
    try:
        card = info.card_data
        license_id = (card.to_dict().get('license') if card else None) or ''
    except Exception:
        license_id = ''
    # À défaut du champ `author`, le namespace du dépôt : sur HuggingFace, `org/repo` EST
    # l'éditeur — ce n'est pas une déduction, c'est la façon dont la plateforme nomme.
    author = (getattr(info, 'author', '') or repo_id.partition('/')[0] or '')

    # Régime d'ACCÈS au dépôt (`AIModel.GATED_*`). HuggingFace rend `False` / 'auto' / 'manual' ;
    # WAMA écrit 'no' pour le libre VÉRIFIÉ, afin que le vide reste disponible pour « inconnu ».
    # Cette réponse ne dit JAMAIS « inconnu » : on vient d'interroger le dépôt.
    raw = getattr(info, 'gated', None)
    gated = 'no' if raw in (None, False) else str(raw)[:8]

    # Ce que la carte DÉCLARE d'autre, traduit mécaniquement (`prospector.card_facts`,
    # 2026-09-19) : tâche (pipeline + tags), langues, moteur. La chaîne relisait cette carte
    # à l'installation et n'en gardait que l'identité — 25 langues de canary jetées, ACE-Step
    # rangé en ambiance alors que ses tags disent musique. Sous `declared`, pour que les
    # lecteurs de l'identité (`set_identity`, `backfill_platform_refs`) n'y voient rien.
    from .prospector import card_facts
    facts = card_facts(getattr(info, 'pipeline_tag', None), getattr(info, 'tags', None) or (),
                       card, getattr(info, 'library_name', None) or '')

    return {
        'license': str(license_id)[:64],
        'author': str(author)[:200],
        'platform_ref': hf_platform_ref(repo_id),
        'gated': gated,
        # Les PUBLICATIONS que l'auteur rattache à son modèle (2026-10-10) — même requête.
        'publications': arxiv_ids(getattr(info, 'tags', None) or ()),
        # Le modèle dont ce dépôt est une QUANTIFICATION (2026-10-29) — même requête.
        **quantized_base_identity(getattr(info, 'tags', None) or (), repo_id),
        'declared': {'capabilities': facts['capabilities'], 'engine': facts['engine']},
    }


#: Étiquette que le Hub pose sur un dépôt dont la carte déclare `base_model` avec la relation
#: `quantized` : `base_model:quantized:<org/nom>`.
_QUANTIZED_TAG = 'base_model:quantized:'


def quantized_base_identity(tags, repo_id: str = '') -> dict:
    """`{base_model, base_model_relation: 'quantized'}` quand le dépôt se DÉCLARE la quantification
    d'UN modèle (étiquette `base_model:quantized:<dépôt>` du Hub), `{}` sinon.

    POURQUOI (2026-10-29, question de Fabien : « olm-ocr n'est jamais prévu ») : un GGUF EST son
    modèle d'origine, et c'est par lui que le banc l'apparie (`AIModel.quantized_base`,
    `benchmark_sync._local_repos`). Ce lien n'était posé que si l'installation le recevait de la
    prospection (`identity_for_spec`, descripteur `base_model`) : chandra-ocr-2 en Q6_K, entré
    autrement, restait SANS note alors que sa carte nomme `datalab-to/chandra-ocr-2` (85,8 sur
    olmOCR-Bench) — et le tirage ne le comparait à rien. La relation `quantized` SEULE : une LoRA ou
    un affinage déclarent aussi un `base_model`, qui n'est pas ce qu'ils SONT. Plusieurs bases
    déclarées : aucune n'est choisie.

    ⚠ L'étiquette du Hub se TROMPE parfois (relevé au passage à blanc du 2026-10-29) : il déduit
    `quantized` des fichiers du dépôt, et nomme alors le socle d'un AFFINAGE — `Qwen3-Embedding-4B-GGUF`
    « quantification » de `Qwen3-4B-Base`, `Ministral-3-8B-Instruct` de la version `Base`. Un tel lien
    donnerait la note du socle. La base n'est donc retenue que si le dépôt porte son NOM COMPLET :
    le filtre strict des variantes de la prospection (`prospector.names_the_same_model`)."""
    from .prospector import names_the_same_model
    bases = {str(t)[len(_QUANTIZED_TAG):].strip() for t in tags or ()
             if str(t).startswith(_QUANTIZED_TAG)}
    bases.discard('')
    if len(bases) != 1:
        return {}
    base = bases.pop()
    if base.lower() == (repo_id or '').lower() or not names_the_same_model(base, repo_id):
        return {}
    from wama.model_manager.models import BASE_RELATION_QUANTIZED
    return {'base_model': base, 'base_model_relation': BASE_RELATION_QUANTIZED}


#: Identifiant arXiv (forme moderne `AAMM.NNNNN`, version facultative) — ce que le Hub écrit dans
#: les étiquettes `arxiv:<id>` d'un dépôt.
_ARXIV_ID = re.compile(r'^\d{4}\.\d{4,5}(v\d+)?$')


def arxiv_ids(tags) -> list:
    """Les identifiants arXiv qu'une carte Hugging Face rattache au modèle, dans son ordre.

    Le Hub pose une étiquette `arxiv:<id>` pour chaque article cité par la carte : c'est la
    déclaration de l'AUTEUR (mesuré le 2026-10-10 : LightOnOCR-3 en porte 2, DeepSeek-OCR-2 2,
    Falcon-OCR 1). Rien n'est cherché ailleurs, rien n'est déduit d'un nom.
    """
    out = []
    for tag in tags or ():
        tag = str(tag)
        if tag.startswith('arxiv:'):
            ident = tag[len('arxiv:'):].strip()
            if _ARXIV_ID.match(ident) and ident not in out:
                out.append(ident)
    return out


def ollama_identity(name: str) -> Optional[dict]:
    """
    Identité d'un modèle Ollama. La plateforme n'expose ni licence ni auteur exploitables par
    l'API locale : on ne pose que ce qui est vrai — l'identité de plateforme.
    """
    family = (name or '').split(':', 1)[0].strip()
    if not family:
        return None
    return {'platform_ref': f"ollama:{family}"}


def cloud_identity(item: dict) -> Optional[dict]:
    """Identité d'un modèle DISTANT : le dépôt HuggingFace que le fournisseur sert, quand il le
    nomme (alias `org/nom` chez Albert) — même forme que `huggingface_identity`, sans requête.
    None quand aucun dépôt n'est nommé (Anthropic). C'est ce `platform_ref` qui relie
    `albert:bge-m3` à `ollama:bge-m3` ou à un snapshot local du même modèle.
    """
    repo_id = next((str(a) for a in ((item or {}).get('aliases') or []) if '/' in str(a)), '')
    if not repo_id:
        return None
    return {'platform_ref': hf_platform_ref(repo_id)}


def identity_for_spec(spec: dict) -> Optional[dict]:
    """Identité déductible du descripteur d'installation (`install_from_spec`)."""
    spec = spec or {}
    kind, ref = spec.get('kind'), (spec.get('ref') or '').strip()
    if not ref:
        return None
    if kind == 'hf':
        return huggingface_identity(ref)
    if kind == 'ollama':
        if ref.lower().startswith('hf.co/'):
            # Un GGUF du Hub tiré par Ollama (`spec_for_choice`, 2026-10-10) : il VIENT du dépôt
            # GGUF (`platform_ref`) et il EST, quantifié, le modèle canonique du candidat
            # (`base_model`, porté par le descripteur, relation `quantized` — le vocabulaire de la
            # carte du Hub) — c'est par lui que le banc l'apparie, en borne haute comme tout GGUF
            # (`benchmark_sync`, garde « local souvent Q4 »). Jusqu'au 2026-10-27 ce second fait
            # vivait dans `hf_id`, que `platform_ref` répétait partout ailleurs.
            repo = ref[len('hf.co/'):].split(':', 1)[0]
            from wama.model_manager.models import BASE_RELATION_QUANTIZED
            base = (spec.get('base_model') or '').strip()
            return {'platform_ref': hf_platform_ref(repo),
                    **({'base_model': base, 'base_model_relation': BASE_RELATION_QUANTIZED}
                       if base and base.lower() != repo.lower() else {})}
        return ollama_identity(ref)
    if kind == 'yolo':
        # Poids officiels ultralytics : le dépôt est connu (c'est l'URL que `pull_yolo_weights`
        # construit), et la licence sera lue DANS le fichier par `weights_metadata` — on ne la
        # code pas en dur ici.
        return {'platform_ref': 'github:ultralytics/assets'}
    if kind == 'github':
        # La VERSION est le modèle (pilote `github`, 2026-10-07) : `platform_ref` désigne sa page,
        # que la fiche déclarée de la plateforme (`external_sources`, source `github`) rend telle
        # quelle.
        # La licence vient du spec quand la prospection l'a relevée sur la version — jamais
        # supposée ici.
        from wama.common.external_sources import github_platform_ref, github_release_of
        platform_ref = github_platform_ref(ref)
        if not platform_ref:
            return None
        # L'éditeur est le propriétaire du dépôt qui publie la version — le pendant du slug
        # d'organisation qu'une carte HF rend (`set_identity` ne l'écrit que sur un vide).
        identity = {'platform_ref': platform_ref,
                    'author': github_release_of(ref)[0].partition('/')[0]}
        if spec.get('license'):
            identity['license'] = spec['license']
        return identity
    if kind == 'files':
        # Les fichiers qu'une app déclare (pilote `files`, 2026-10-11) : l'identité du MODÈLE est
        # celle que sa découverte pose (dépôt, moteur) ; la provenance de chaque FICHIER voyage
        # avec lui (`extra_info['declared_files']`, résultat de l'installation). On n'en déduit
        # rien ici : l'origine d'un fichier peut être un miroir, et un miroir n'est pas un auteur.
        return None
    return None


def set_identity(model_key: str, identity: dict, *, capabilities: dict = None,
                   engine: str = None, composition: dict = None, apply: bool = True,
                   export: bool = True) -> dict:
    """
    Pose l'identité — et les capacités DÉCLARÉES — sur un modèle DU CATALOGUE, en passant
    par son manifeste.

    `capabilities` : clés déclarées par l'amont (la tâche du spec d'installation, les
    modalités et entrées qu'elle implique, les langues de la carte). Même règle que
    l'identité : elles COMPLÈTENT le manifeste extrait, elles n'écrasent jamais une clé déjà
    établie. Jusqu'au 2026-09-18 la tâche était écrite directement en base APRÈS l'export
    (`record_after_install`) : le manifeste du corpus naissait sans tâche, et la porte des
    capacités se refermait derrière elle.
    `engine` : le moteur déclaré par la carte (`library_name` reconnu par un backend), posé
    dans `composition.runtime.engine` seulement s'il n'y en a pas — c'est ce que
    `plan_model_integration` réclamait à la main (« aucun moteur déclaré »).
    `composition` : l'anatomie JUGÉE en amont (le `spec.composition` d'un candidat semé par le
    scout). Même règle : `components` et `runtime.engine` ne comblent qu'un vide.

    Retourne un compte rendu : `{model, applied, posed, projected, corpus, error?}` (clés
    passées en anglais le 2026-09-19).
    Ne lève pas — une provenance manquée ne doit pas faire échouer une installation réussie.
    """
    # API PUBLIQUE de la couche manifeste (`ingest`), pas le builtin du kind : c'est elle qui
    # porte le contrat extract → validate → write_back, et qui dispatche par kind.
    from wama.common.manifests.ingest import extract, validate, write_back

    capabilities = dict(capabilities or {})
    composition = dict(composition or {})
    if not identity and not capabilities and not engine and not composition:
        return {'model': model_key, 'applied': False, 'error': 'aucune identité à poser'}
    identity = identity or {}

    try:
        manifest = extract('model', model_key)
    except Exception as e:
        return {'model': model_key, 'applied': False,
                'error': f"extraction impossible : {type(e).__name__}: {e}"}
    if not manifest:
        return {'model': model_key, 'applied': False,
                'error': "aucun AIModel de cette clé — lancer sync_models d'abord"}

    # Superposition : l'identité de l'éditeur COMPLÈTE l'extraction, elle ne l'écrase pas quand
    # elle n'a rien à dire (une valeur vide ne doit pas effacer une valeur déjà établie).
    # `author` va plus loin : il ne s'écrase JAMAIS — la carte HF rend un slug d'organisation
    # (parfois l'org miroir), toujours plus pauvre qu'un auteur curé. Il ne fait que remplir
    # un champ vide (défaut vécu le 2026-08-27 : 6 auteurs curés écrasés par un backfill).
    ident = manifest.setdefault('body', {}).setdefault('identity', {})
    posed = []
    for field in ('license', 'author', 'platform_ref', 'base_model', 'base_model_relation'):
        value = (identity.get(field) or '').strip()
        if field == 'author' and ident.get('author'):
            continue
        # `other` n'est pas un fait : c'est le placeholder du Hub pour « licence maison ». Une
        # qualification déjà posée (cpml-1.0, hunyuan-community…) est plus précise — règle de
        # `backfill_platform_refs`, apprise le 2026-08-12, qui vaut pour toute pose (2026-10-22).
        if field == 'license' and value == 'other' and ident.get('license') not in (None, '', 'other'):
            continue
        if value and ident.get(field) != value:
            ident[field] = value
            posed.append(field)
    # Régime d'ACCÈS au dépôt (2026-10-22) : `huggingface_identity` le lit dans la même requête,
    # mais rien ne le recopiait — une installation par la route le PERDAIT, et seule la passe
    # `backfill_platform_refs --licenses` l'écrivait, en base. C'est l'état courant du dépôt amont :
    # il se pose dès qu'il est connu, jamais un vide (« inconnu » ≠ « libre »).
    from wama.model_manager.models import AIModel
    gated = identity.get('gated')
    if gated in (AIModel.GATED_LIBRE, AIModel.GATED_AUTO, AIModel.GATED_MANUEL) \
            and ident.get('gated') != gated:
        ident['gated'] = gated
        posed.append('gated')
    # Publications de la carte (2026-10-10) : même règle que la licence — l'éditeur fait foi
    # quand il dit quelque chose, une liste vide n'efface rien.
    publications = [str(p) for p in (identity.get('publications') or []) if p]
    if publications and ident.get('publications') != publications:
        ident['publications'] = publications
        posed.append('publications')
    # Capacités déclarées : on ne comble qu'un VIDE (une tâche établie par la découverte, ou
    # par un manifeste antérieur, prime sur celle du spec — règle inchangée depuis le 02/09).
    caps = manifest['body'].setdefault('capabilities', {})
    for key, value in capabilities.items():
        if value not in (None, '', [], {}) and not caps.get(key):
            caps[key] = value
            posed.append(f'capabilities.{key}')
    # Anatomie JUGÉE en amont (2026-09-29) : le scout la déclare sur le candidat, l'installation
    # s'en servait pour tirer les bons fichiers (`allow_patterns`)… puis la PERDAIT — elle
    # n'atteignait ni `AIModel.composition` ni le corpus. Même règle que le reste : un vide.
    engine = engine or (composition.get('runtime') or {}).get('engine')
    if composition.get('components'):
        current = manifest['body'].get('composition') or {}
        if not current.get('components'):
            manifest['body']['composition'] = {**current, 'components': composition['components']}
            posed.append('composition.components')

    # Moteur déclaré : même règle, on ne comble qu'un vide (le manifeste d'un modèle composé,
    # ou la déclaration d'une app, priment sur ce que la carte laisse deviner).
    if engine:
        composition = manifest['body'].setdefault('composition', {}) or {}
        manifest['body']['composition'] = composition
        runtime = composition.setdefault('runtime', {})
        if not runtime.get('engine'):
            runtime['engine'] = engine
            posed.append('composition.runtime.engine')

    # On VALIDE avant de projeter : un `platform_ref` mal formé ou une plateforme inconnue est
    # refusé par le kind (`validate_model_body`), et il vaut mieux le voir ici qu'écrire une
    # identité que le corpus rejettera ensuite.
    errors = validate(manifest)
    if errors:
        return {'model': model_key, 'applied': False,
                'error': f"manifeste invalide : {'; '.join(errors[:3])}"}

    try:
        plan = write_back(manifest, apply=apply)
    except Exception as e:
        return {'model': model_key, 'applied': False,
                'error': f"projection impossible : {type(e).__name__}: {e}"}

    corpus = None
    if apply and export:
        try:
            # La porte commune du corpus (`common/manifests/corpus.py`) : la commande d'export,
            # que le runner de tests coupe.
            from wama.common.manifests.corpus import follow
            corpus = follow(model_key, kind='model')
        except Exception as e:
            corpus = f"échec : {type(e).__name__}: {e}"

    return {'model': model_key, 'applied': bool(apply), 'posed': posed,
            'projected': plan, 'corpus': corpus}


def _give_to_author(keys, owner) -> list:
    """Les lignes `keys` encore SYSTÈME passent à `owner`, privées (`ROADMAP §29` étape 3).
    Une ligne qui a déjà un auteur ne change pas de main. Rend les clés données."""
    from wama.common.models import ScopedVisibility
    from wama.model_manager.models import AIModel
    rows = AIModel.objects.filter(model_key__in=list(keys), owner__isnull=True)
    given = sorted(rows.values_list('model_key', flat=True))
    rows.update(owner=owner, visibility=ScopedVisibility.VIS_PRIVATE)
    return given


def record_after_install(spec: dict, appeared_keys, owner=None) -> dict:
    """
    Après installation + sync : pose l'identité sur les modèles qui viennent d'APPARAÎTRE.

    `cles_apparues` vient de `SyncResult.added_keys` — c'est le sync qui sait ce qu'il a créé.
    La clé d'un modèle est FABRIQUÉE par la découverte (`{source}:{…}`) à partir de ce qu'elle
    trouve sur le disque : elle n'est pas prévisible depuis le descripteur d'installation, et
    la re-dériver par une photo avant/après serait à la fois redondant et sujet aux courses.

    Repli quand rien n'apparaît (réinstallation, ou modèle déjà catalogué) : on vise la ligne
    qui porte déjà cette identité de plateforme, pour que relancer l'installation reste utile.

    `owner` (2026-10-18, `ROADMAP §29` étape 3) : l'auteur des lignes APPARUES — jamais d'une ligne
    du repli, qui existait avant ce geste (un système réinstallé reste système). Posé AVANT
    l'identité : `set_identity` réexporte au corpus versionné, qui n'admet que le système
    (`manifest_export`) ; un modèle privé n'y entre donc pas, même un instant.
    """
    from wama.model_manager.models import AIModel

    appeared = sorted(appeared_keys or ())
    identity = identity_for_spec(spec)
    if not identity:
        given = _give_to_author(appeared, owner) if owner is not None else []
        return {'identity': None, 'models': [], **({'owner': given} if given else {}),
                'note': f"aucune identité déductible pour kind={spec.get('kind')!r}"}

    targets = sorted(appeared_keys or ())
    if not targets:
        # ⚠ `is_proposed=False` OBLIGATOIRE (2026-08-31) : pendant `install_candidate`, la ligne
        # CANDIDATE existe encore (elle n'est supprimée qu'après) et porte le même platform_ref —
        # sans ce filtre, l'identité se posait aussi sur elle et son manifeste partait au corpus,
        # orphelin dès la suppression du candidat (2 fichiers `proposed__*` constatés).
        ref = identity.get('platform_ref') or ''
        targets = sorted(AIModel.objects.filter(platform_ref=ref, is_proposed=False)
                        .values_list('model_key', flat=True)) if ref else []

    # ⚠ GARDE DE CONCORDANCE (2026-08-31) : `added_keys` liste ce que LE SYNC vient de créer —
    # pas ce que CETTE installation a installé. Trois installs HF concurrentes l'ont prouvé :
    # la première finie (Kokoro-ONNX) a synchronisé pendant que les deux autres téléchargeaient,
    # son sync a découvert LEURS snapshots partiels (added_keys = les 3), et elle a posé SON
    # identité sur les trois lignes — corpus avec dépôt/author croisés. On ne pose l'identité
    # que sur une ligne qui la revendique déjà (`platform_ref` posé par la découverte) ou qui
    # n'en a pas.
    expected_ref = (identity.get('platform_ref') or '').lower()
    if expected_ref:
        discarded = [c for c in targets
                    if (AIModel.objects.filter(model_key=c)
                        .values_list('platform_ref', flat=True).first() or '').lower()
                    not in ('', expected_ref)]
        if discarded:
            logger.info("[provenance] %d ligne(s) écartée(s) (dépôt étranger — install "
                        "concurrente probable) : %s", len(discarded), discarded)
            targets = [c for c in targets if c not in discarded]

    # L'AUTEUR, après la garde de concordance (une ligne d'une installation concurrente ne lui
    # revient pas) et avant l'identité, donc avant l'export au corpus.
    given = (_give_to_author([c for c in targets if c in appeared], owner)
             if owner is not None else [])

    # La TÂCHE du candidat (2026-09-02). Le balayage générique d'un snapshot HF catalogue un
    # modèle sans savoir ce qu'il FAIT : `table-transformer-detection` est arrivé installé
    # avec `task=None` alors que son candidat portait `detect` — donc hors de toute sélection
    # par tâche et de tout banc. Le spec la porte (`spec.task`) ; elle entre dans le MANIFESTE
    # avec l'identité (2026-09-18), donc AVANT la projection et l'export au corpus — et jamais
    # par-dessus une tâche déjà établie (`set_identity` ne comble qu'un vide).
    # Et ce que la tâche IMPLIQUE (modalités, entrées — `TASK_DEFAULT_INPUTS`, 2026-09-19) :
    # sans cela un modèle installé sans app restait invisible de l'appariement entrée ↔ modèle.
    # Même règle : on ne comble qu'un vide.
    # Et ce que la CARTE déclare (2026-09-19, `huggingface_identity` → `declared`) : tâche
    # quand le spec n'en porte pas, langues, moteur. La tâche du spec (candidat jugé) prime.
    from wama.model_manager.models import default_inputs_for
    card = identity.pop('declared', None) or {}
    task = (spec.get('task') or '').strip() or (card.get('capabilities') or {}).get('task') or ''
    declared = dict(card.get('capabilities') or {})
    if task:
        declared.update({'task': task, **default_inputs_for(task)})
    # Les capacités JUGÉES sur le candidat (2026-10-06, Swin2SR : `scale: 4` perdu à
    # l'installation) priment sur la carte et sur les défauts de la tâche — la tâche du spec,
    # elle, reste celle qui vient d'être posée.
    declared.update({k: v for k, v in (spec.get('capabilities') or {}).items() if k != 'task'})
    # Le moteur de la carte ne vaut qu'à défaut de celui qu'un rôle a JUGÉ sur le candidat.
    judged = spec.get('composition') or {}
    posed = [set_identity(c, identity, capabilities=declared,
                          engine=(judged.get('runtime') or {}).get('engine') or card.get('engine'),
                          composition=judged)
             for c in targets]
    return {'identity': identity, 'models': posed, **({'task': task} if task else {}),
            **({'owner': given} if given else {})}
