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
    `{license, author, platform_ref, hf_id}` lu sur la carte du dépôt, ou None si injoignable.

    L'auteur et la licence viennent de la MÊME requête : les séparer coûterait un aller-retour
    par modèle pour deux faits posés sur la même table.
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

    licence = ''
    try:
        carte = info.card_data
        licence = (carte.to_dict().get('license') if carte else None) or ''
    except Exception:
        licence = ''
    # À défaut du champ `author`, le namespace du dépôt : sur HuggingFace, `org/repo` EST
    # l'éditeur — ce n'est pas une déduction, c'est la façon dont la plateforme nomme.
    auteur = (getattr(info, 'author', '') or hf_id.partition('/')[0] or '')

    return {
        'license': str(licence)[:64],
        'author': str(auteur)[:200],
        'platform_ref': f"huggingface:{hf_id}",
        'hf_id': hf_id,
    }


def ollama_identity(nom: str) -> Optional[dict]:
    """
    Identité d'un modèle Ollama. La plateforme n'expose ni licence ni auteur exploitables par
    l'API locale : on ne pose que ce qui est vrai — l'identité de plateforme.
    """
    famille = (nom or '').split(':', 1)[0].strip()
    if not famille:
        return None
    return {'platform_ref': f"ollama:{famille}"}


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


def set_identity(model_key: str, identite: dict, *, apply: bool = True,
                   exporter: bool = True) -> dict:
    """
    Pose l'identité sur un modèle DU CATALOGUE, en passant par son manifeste.

    Retourne un compte rendu : `{model, applique, projete, corpus, erreur?}`.
    Ne lève pas — une provenance manquée ne doit pas faire échouer une installation réussie.
    """
    # API PUBLIQUE de la couche manifeste (`ingest`), pas le builtin du kind : c'est elle qui
    # porte le contrat extract → validate → write_back, et qui dispatche par kind.
    from wama.common.manifests.ingest import extract, validate, write_back

    if not identite:
        return {'model': model_key, 'applique': False, 'erreur': 'aucune identité à poser'}

    try:
        manifeste = extract('model', model_key)
    except Exception as e:
        return {'model': model_key, 'applique': False,
                'erreur': f"extraction impossible : {type(e).__name__}: {e}"}
    if not manifeste:
        return {'model': model_key, 'applique': False,
                'erreur': "aucun AIModel de cette clé — lancer sync_models d'abord"}

    # Superposition : l'identité de l'éditeur COMPLÈTE l'extraction, elle ne l'écrase pas quand
    # elle n'a rien à dire (une valeur vide ne doit pas effacer une valeur déjà établie).
    # `author` va plus loin : il ne s'écrase JAMAIS — la carte HF rend un slug d'organisation
    # (parfois l'org miroir), toujours plus pauvre qu'un auteur curé. Il ne fait que remplir
    # un champ vide (défaut vécu le 2026-08-27 : 6 auteurs curés écrasés par un backfill).
    ident = manifeste.setdefault('body', {}).setdefault('identity', {})
    poses = []
    for champ in ('license', 'author', 'platform_ref', 'hf_id'):
        valeur = (identite.get(champ) or '').strip()
        if champ == 'author' and ident.get('author'):
            continue
        if valeur and ident.get(champ) != valeur:
            ident[champ] = valeur
            poses.append(champ)

    # On VALIDE avant de projeter : un `platform_ref` mal formé ou une plateforme inconnue est
    # refusé par le kind (`validate_model_body`), et il vaut mieux le voir ici qu'écrire une
    # identité que le corpus rejettera ensuite.
    erreurs = validate(manifeste)
    if erreurs:
        return {'model': model_key, 'applique': False,
                'erreur': f"manifeste invalide : {'; '.join(erreurs[:3])}"}

    try:
        plan = write_back(manifeste, apply=apply)
    except Exception as e:
        return {'model': model_key, 'applique': False,
                'erreur': f"projection impossible : {type(e).__name__}: {e}"}

    corpus = None
    if apply and exporter:
        try:
            from django.core.management import call_command
            # On passe par la commande plutôt que de réécrire la règle de nommage du corpus
            # (`_nom_fichier`, qui assainit le `:` des clés modèle) : une seconde graphie
            # rendrait le glob inverse faux.
            call_command('manifest_export', model_key, kind='model', verbosity=0)
            corpus = 'écrit'
        except Exception as e:
            corpus = f"échec : {type(e).__name__}: {e}"

    return {'model': model_key, 'applique': bool(apply), 'poses': poses,
            'projete': plan, 'corpus': corpus}


def record_after_install(spec: dict, cles_apparues) -> dict:
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

    identite = identity_for_spec(spec)
    if not identite:
        return {'identite': None, 'modeles': [],
                'note': f"aucune identité déductible pour kind={spec.get('kind')!r}"}

    cibles = sorted(cles_apparues or ())
    if not cibles:
        # ⚠ `is_proposed=False` OBLIGATOIRE (2026-08-31) : pendant `install_candidate`, la ligne
        # CANDIDATE existe encore (elle n'est supprimée qu'après) et porte le même platform_ref —
        # sans ce filtre, l'identité se posait aussi sur elle et son manifeste partait au corpus,
        # orphelin dès la suppression du candidat (2 fichiers `proposed__*` constatés).
        ref = identite.get('platform_ref') or ''
        cibles = sorted(AIModel.objects.filter(platform_ref=ref, is_proposed=False)
                        .values_list('model_key', flat=True)) if ref else []

    # ⚠ GARDE DE CONCORDANCE (2026-08-31) : `added_keys` liste ce que LE SYNC vient de créer —
    # pas ce que CETTE installation a installé. Trois installs HF concurrentes l'ont prouvé :
    # la première finie (Kokoro-ONNX) a synchronisé pendant que les deux autres téléchargeaient,
    # son sync a découvert LEURS snapshots partiels (added_keys = les 3), et elle a posé SON
    # identité sur les trois lignes — corpus avec hf_id/author croisés. On ne pose l'identité
    # que sur une ligne qui la revendique déjà (hf_id posé par la découverte) ou qui n'en a pas.
    hf_attendu = (identite.get('hf_id') or '').lower()
    if hf_attendu:
        ecartees = [c for c in cibles
                    if (AIModel.objects.filter(model_key=c)
                        .values_list('hf_id', flat=True).first() or '').lower()
                    not in ('', hf_attendu)]
        if ecartees:
            logger.info("[provenance] %d ligne(s) écartée(s) (hf_id étranger — install "
                        "concurrente probable) : %s", len(ecartees), ecartees)
            cibles = [c for c in cibles if c not in ecartees]

    return {'identite': identite, 'modeles': [set_identity(c, identite) for c in cibles]}
