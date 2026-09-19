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
from typing import Optional

logger = logging.getLogger(__name__)


def huggingface_identity(hf_id: str) -> Optional[dict]:
    """
    `{license, author, platform_ref, hf_id, gated}` lu sur la carte du dépôt, ou None si injoignable.

    L'auteur et la licence viennent de la MÊME requête : les séparer coûterait un aller-retour
    par modèle pour deux faits posés sur la même table. `gated` a rejoint le lot pour cette
    raison exacte (2026-09-07) — `model_info()` le rend dans la réponse déjà demandée, donc
    l'ignorer coûtait un fait, pas une requête.
    """
    hf_id = (hf_id or '').strip()
    if not hf_id:
        return None
    try:
        from huggingface_hub import HfApi
    except ImportError:
        logger.debug("[provenance] huggingface_hub absent")
        return None
    try:
        info = HfApi().model_info(hf_id)
    except Exception as e:
        logger.info(f"[provenance] {hf_id} injoignable : {type(e).__name__}")
        return None

    license_id = ''
    try:
        card = info.card_data
        license_id = (card.to_dict().get('license') if card else None) or ''
    except Exception:
        license_id = ''
    # À défaut du champ `author`, le namespace du dépôt : sur HuggingFace, `org/repo` EST
    # l'éditeur — ce n'est pas une déduction, c'est la façon dont la plateforme nomme.
    author = (getattr(info, 'author', '') or hf_id.partition('/')[0] or '')

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
        'platform_ref': f"huggingface:{hf_id}",
        'hf_id': hf_id,
        'gated': gated,
        'declared': {'capabilities': facts['capabilities'], 'engine': facts['engine']},
    }


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
    hf_id = next((str(a) for a in ((item or {}).get('aliases') or []) if '/' in str(a)), '')
    if not hf_id:
        return None
    return {'platform_ref': f'huggingface:{hf_id}', 'hf_id': hf_id}


def identity_for_spec(spec: dict) -> Optional[dict]:
    """Identité déductible du descripteur d'installation (`install_from_spec`)."""
    spec = spec or {}
    kind, ref = spec.get('kind'), (spec.get('ref') or '').strip()
    if not ref:
        return None
    if kind == 'hf':
        return huggingface_identity(ref)
    if kind == 'ollama':
        return ollama_identity(ref)
    if kind == 'yolo':
        # Poids officiels ultralytics : le dépôt est connu (c'est l'URL que `pull_yolo_weights`
        # construit), et la licence sera lue DANS le fichier par `weights_metadata` — on ne la
        # code pas en dur ici.
        return {'platform_ref': 'github:ultralytics/assets'}
    return None


def set_identity(model_key: str, identity: dict, *, capabilities: dict = None,
                   engine: str = None, apply: bool = True, export: bool = True) -> dict:
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

    Retourne un compte rendu : `{model, applied, posed, projected, corpus, error?}` (clés
    passées en anglais le 2026-09-19).
    Ne lève pas — une provenance manquée ne doit pas faire échouer une installation réussie.
    """
    # API PUBLIQUE de la couche manifeste (`ingest`), pas le builtin du kind : c'est elle qui
    # porte le contrat extract → validate → write_back, et qui dispatche par kind.
    from wama.common.manifests.ingest import extract, validate, write_back

    capabilities = dict(capabilities or {})
    if not identity and not capabilities and not engine:
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
    for field in ('license', 'author', 'platform_ref', 'hf_id'):
        value = (identity.get(field) or '').strip()
        if field == 'author' and ident.get('author'):
            continue
        if value and ident.get(field) != value:
            ident[field] = value
            posed.append(field)
    # Capacités déclarées : on ne comble qu'un VIDE (une tâche établie par la découverte, ou
    # par un manifeste antérieur, prime sur celle du spec — règle inchangée depuis le 02/09).
    caps = manifest['body'].setdefault('capabilities', {})
    for key, value in capabilities.items():
        if value not in (None, '', [], {}) and not caps.get(key):
            caps[key] = value
            posed.append(f'capabilities.{key}')
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
            from django.core.management import call_command
            # On passe par la commande plutôt que de réécrire la règle de nommage du corpus
            # (`_nom_fichier`, qui assainit le `:` des clés modèle) : une seconde graphie
            # rendrait le glob inverse faux.
            call_command('manifest_export', model_key, kind='model', verbosity=0)
            corpus = 'écrit'
        except Exception as e:
            corpus = f"échec : {type(e).__name__}: {e}"

    return {'model': model_key, 'applied': bool(apply), 'posed': posed,
            'projected': plan, 'corpus': corpus}


def record_after_install(spec: dict, appeared_keys) -> dict:
    """
    Après installation + sync : pose l'identité sur les modèles qui viennent d'APPARAÎTRE.

    `cles_apparues` vient de `SyncResult.added_keys` — c'est le sync qui sait ce qu'il a créé.
    La clé d'un modèle est FABRIQUÉE par la découverte (`{source}:{…}`) à partir de ce qu'elle
    trouve sur le disque : elle n'est pas prévisible depuis le descripteur d'installation, et
    la re-dériver par une photo avant/après serait à la fois redondant et sujet aux courses.

    Repli quand rien n'apparaît (réinstallation, ou modèle déjà catalogué) : on vise la ligne
    qui porte déjà cette identité de plateforme, pour que relancer l'installation reste utile.
    """
    from wama.model_manager.models import AIModel

    identity = identity_for_spec(spec)
    if not identity:
        return {'identity': None, 'models': [],
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
    # identité sur les trois lignes — corpus avec hf_id/author croisés. On ne pose l'identité
    # que sur une ligne qui la revendique déjà (hf_id posé par la découverte) ou qui n'en a pas.
    expected_hf = (identity.get('hf_id') or '').lower()
    if expected_hf:
        discarded = [c for c in targets
                    if (AIModel.objects.filter(model_key=c)
                        .values_list('hf_id', flat=True).first() or '').lower()
                    not in ('', expected_hf)]
        if discarded:
            logger.info("[provenance] %d ligne(s) écartée(s) (hf_id étranger — install "
                        "concurrente probable) : %s", len(discarded), discarded)
            targets = [c for c in targets if c not in discarded]

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
    posed = [set_identity(c, identity, capabilities=declared, engine=card.get('engine'))
             for c in targets]
    return {'identity': identity, 'models': posed, **({'task': task} if task else {})}
