"""
Pipeline accept→download→register — installation de modèles dans WAMA.

Étape 2 du système d'auto-maintenance : une fois un modèle ACCEPTÉ (par l'admin, ou plus tard
par la prospection validée), on le télécharge AU BON ENDROIT puis on l'enregistre dans le
catalogue `AIModel` pour qu'il devienne visible/sélectionnable.

Ollama d'abord : `POST /api/pull` sur le démon LOCAL = API officielle (le démon parle au
registre, pas nous → aucun scraping). HF viendra ensuite (règle CLAUDE.md : path→env→import).
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def pull_ollama_model(name: str, timeout: int = 1800, progress=None):
    """
    Télécharge un modèle Ollama via le démon LOCAL (`POST /api/pull`, stream).

    `progress` : callback optionnel(status:str) pour remonter l'avancement.
    Retourne {'ok': bool, 'status': str} ou {'ok': False, 'error': str}.
    """
    import requests
    from wama.common.utils.ollama_host import ollama_base, ollama_kwargs

    base = ollama_base()
    last = None
    try:
        with requests.post(f"{base}/api/pull", json={"name": name, "stream": True},
                           stream=True, **ollama_kwargs(timeout=timeout)) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if data.get('error'):
                    return {'ok': False, 'error': data['error']}
                status = data.get('status')
                # Le flux porte `completed`/`total` par couche : un POURCENTAGE dans le
                # statut (2026-08-18, install asynchrone) — le callback garde sa signature
                # (str) et n'est appelé qu'au changement, donc ~100 appels par couche max.
                total, fait = data.get('total'), data.get('completed')
                if status and total and fait is not None:
                    status = f"{status} {int(fait * 100 / total)}%"
                if status and status != last:
                    last = status
                    if progress:
                        progress(status)
        return {'ok': True, 'status': last or 'success'}
    except Exception as e:
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}


def delete_ollama_model(name: str, timeout: int = 60) -> dict:
    """
    Désinstalle un modèle Ollama (`DELETE /api/delete`) — libère sa place sur le volume.

    Sert le REMPLACEMENT : quand un candidat succède à un modèle installé, l'espace du nouveau
    n'est disponible qu'après retrait de l'ancien (D: est à 96 %). Ollama ne supprime que les
    blobs devenus orphelins : les couches partagées avec un autre tag restent en place, donc
    l'espace réellement rendu peut être inférieur à la taille annoncée.

    Envoie `model` ET `name` : la clé du corps a changé selon les versions du démon, et accepter
    les deux évite un échec silencieux sur une machine au démon plus ancien.
    """
    import requests
    from wama.common.utils.ollama_host import ollama_base, ollama_kwargs
    try:
        r = requests.delete(f"{ollama_base()}/api/delete",
                            json={"model": name, "name": name},
                            **ollama_kwargs(timeout=timeout))
        if r.status_code in (200, 204):
            return {'ok': True}
        return {'ok': False, 'error': f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}


# ModelType (catalogue) → catégorie de dossier (model_locations.model_dir).
_TYPE_CATEGORY = {
    'diffusion': 'diffusion',
    'speech':    'speech',
    'vlm':       'vlm',
    'vision':    'detect',
    'upscaling': 'enhance',
    'ocr':       'ocr',
    'music':     'music',
    'llm':       'llm',
}


def pull_hf_model(hf_id: str, category: str, family: str | None = None,
                  dry_run: bool = False, allow_patterns=None, progress=None):
    """
    Télécharge un modèle HuggingFace DANS LE BON DOSSIER (catégorie WAMA) via l'API officielle
    `snapshot_download(cache_dir=…)` — on catégorise par `cache_dir`, SANS muter `HF_HUB_CACHE`
    global (cause de dispersion/doublons quand plusieurs threads le mutent en concurrence).

    `dry_run` : ne télécharge pas, retourne juste le dossier cible (valide la logique de chemin).
    Retourne {'ok': bool, 'path'|'target'|'error': …}.

    NB : « téléchargé + catalogué » ≠ « utilisable dans l'app » — l'usage requiert un backend qui
    sache charger ce modèle (problème du chargeur générique, séparé).
    """
    import os
    try:
        from wama.common.utils.model_locations import model_dir
        target = str(model_dir(category, family or hf_id.split('/')[-1]))
    except Exception as e:
        return {'ok': False, 'error': f"résolution dossier: {type(e).__name__}: {e}"}

    if dry_run:
        return {'ok': True, 'target': target, 'dry_run': True}

    os.makedirs(target, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
        path = snapshot_download(repo_id=hf_id, cache_dir=target, allow_patterns=allow_patterns)
        return {'ok': True, 'path': path, 'target': target}
    except Exception as e:
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}


# Suffixe de nom de poids → sous-dossier de tâche YOLO (AI-models/models/vision/yolo/<task>/).
_YOLO_TASK_DIRS = {'-seg': 'segment', '-obb': 'obb', '-pose': 'pose', '-cls': 'classify'}


def pull_yolo_weights(name: str, timeout: int = 600, dry_run: bool = False):
    """
    Télécharge des poids YOLO OFFICIELS (assets GitHub Ultralytics, URL stable
    `releases/latest/download/<name>.pt`) DANS LE BON DOSSIER :
    `AI-models/models/vision/yolo/<task>/<name>.pt` — le sous-dossier de tâche est déduit
    du suffixe du nom (-seg/-obb/-pose/-cls, sinon detect), exactement l'arborescence que
    `model_registry` découvre au sync. Ouvre l'installation VISION du model_manager
    (l'endpoint prospect/install n'était qu'Ollama — phase 1).

    `dry_run` : ne télécharge pas, retourne la cible (valide la logique de chemin).
    Retourne {'ok': bool, 'path'|'target'|'error': …}. Idempotent : fichier déjà présent → ok.
    """
    import os
    import re
    import requests
    from django.conf import settings

    base = name[:-3] if name.endswith('.pt') else name
    # Noms officiels uniquement (yolo11s-seg, yolo26x, yolov12n-seg…) — pas d'URL arbitraire.
    if not re.fullmatch(r'yolo[a-z0-9._\-]+', base, re.IGNORECASE):
        return {'ok': False, 'error': f"nom de poids YOLO invalide: {name!r}"}
    task = next((d for suf, d in _YOLO_TASK_DIRS.items() if base.endswith(suf)), 'detect')
    target_dir = os.path.join(str(settings.AI_MODELS_DIR), 'models', 'vision', 'yolo', task)
    target = os.path.join(target_dir, f"{base}.pt")
    if dry_run:
        return {'ok': True, 'target': target, 'dry_run': True}
    if os.path.exists(target):
        return {'ok': True, 'path': target, 'already': True}

    os.makedirs(target_dir, exist_ok=True)
    url = f"https://github.com/ultralytics/assets/releases/latest/download/{base}.pt"
    tmp = target + '.part'
    try:
        with requests.get(url, stream=True, timeout=timeout, allow_redirects=True) as r:
            r.raise_for_status()
            with open(tmp, 'wb') as fh:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
        # Garde-fou : une page d'erreur HTML ferait un .pt de quelques Ko.
        if os.path.getsize(tmp) < 1_000_000:
            os.remove(tmp)
            return {'ok': False, 'error': f"téléchargement suspect (<1 Mo) — poids inexistant ? {url}"}
        os.replace(tmp, target)
        return {'ok': True, 'path': target, 'url': url}
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}


def register_after_install():
    """
    Re-synchronise le catalogue `AIModel` pour que le modèle fraîchement installé apparaisse.
    Réutilise `full_sync` (clean=False : ne touche pas aux autres sources). Retourne le résumé.
    """
    from .model_sync import ModelSyncService
    return ModelSyncService().full_sync()


def replaced_model(cand):
    """
    (nom Ollama de l'ancien modèle, espace qu'il rendra en Go) pour un candidat successeur,
    sinon (None, 0.0).

    La prospection écrit l'origine dans `extra_info['prospect']['origin_key']` quand elle a
    identifié une famille supérieure — c'est ce lien qui rend le remplacement possible sans
    demander à l'utilisateur de désigner lui-même ce qu'il faut retirer.
    (Migré depuis views.py le 2026-08-18 : la tâche Celery d'install en a besoin autant
    que la garde d'espace de la vue.)
    """
    from ..models import AIModel
    prospect = (cand.extra_info or {}).get('prospect', {})
    origine, cible = prospect.get('origin_key'), prospect.get('cible')
    if not origine or not cible or cand.proposal_kind != 'update':
        return None, 0.0
    ancien = AIModel.objects.filter(model_key=origine, is_proposed=False).first()
    if ancien is None:
        return None, 0.0
    nom = origine.split(':', 1)[1] if ':' in origine else ancien.name
    # Garde-fou : sans `cible`, un candidat « âge seul » porte le nom du modèle EXISTANT, et la
    # séquence retirerait puis re-tirerait le même modèle — churn pur, avec la fenêtre de risque
    # d'une restauration. On ne remplace que si la cible est réellement un AUTRE modèle.
    if nom == cand.name:
        return None, 0.0
    return nom, float(ancien.disk_gb or 0)


def install_candidate(cand, progress=None) -> dict:
    """
    Séquence d'installation d'un CANDIDAT de prospection Ollama — corps unique, appelé par
    la tâche Celery (`install_proposed_task`, chemin normal depuis le 2026-08-18) et
    réutilisable en synchrone. La GARDE D'ESPACE DISQUE reste chez l'appelant : elle doit
    répondre AVANT d'engager quoi que ce soit (le 507/forçage est un dialogue utilisateur).

    Retourne {'ok': True, 'installed': nom} ou {'ok': False, 'error': …[, 'restored',
    'replaced']}. `progress(status:str)` : avancement du pull (avec pourcentage).
    """
    from ..models import AIModel

    # ── Candidat porteur d'un SPEC non-Ollama (génération HF…) : le driver est
    # `install_from_spec` (pull au bon dossier + sync + provenance — RÉUTILISÉ, pas
    # réécrit). Pas de séquence de remplacement ici : un candidat HF est toujours
    # `kind='new'` (la MAJ des installés HF relève d'update_checker).
    spec = (cand.extra_info or {}).get('prospect', {}).get('spec')
    if spec and spec.get('kind') and spec['kind'] != 'ollama':
        if progress:
            progress(f"téléchargement {spec.get('ref')} (HuggingFace)…")
        res = install_from_spec(spec)
        if not res.get('ok'):
            return {'ok': False, 'error': res.get('error', 'installation échouée')}
        installed_name = cand.name
        cand.delete()
        return {'ok': True, 'installed': installed_name, 'path': res.get('path')}

    rollback = None
    remplace, _ = replaced_model(cand)
    origine_key = (cand.extra_info or {}).get('prospect', {}).get('origin_key')
    if remplace:
        # REMPLACEMENT : l'espace du nouveau n'est disponible qu'APRÈS retrait de l'ancien —
        # séquence désinstallation → installation (décision 2026-08-04, PROSPECTION_PIPELINE.md).
        if progress:
            progress(f"retrait de {remplace}…")
        sup = delete_ollama_model(remplace)
        if not sup.get('ok'):
            return {'ok': False,
                    'error': f"Retrait de « {remplace} » impossible : {sup.get('error')}. "
                             f"Installation annulée (l'espace n'aurait pas suffi)."}
        rollback = remplace      # à re-tirer si l'installation échoue

    res = pull_ollama_model(cand.name, progress=progress)
    if not res.get('ok') and rollback:
        # L'ancien a été retiré et le nouveau n'est pas venu : on restaure. C'est possible
        # sans sauvegarde précisément parce que `ollama pull` EST le chemin de restauration
        # (décision 2026-08-04, PROSPECTION_PIPELINE.md).
        reprise = pull_ollama_model(rollback)
        return {'ok': False,
                'error': (f"Installation de « {cand.name} » échouée : {res.get('error')}. "
                          + (f"« {rollback} » a été restauré." if reprise.get('ok')
                             else f"⚠ ÉCHEC DE LA RESTAURATION de « {rollback} » : "
                                  f"{reprise.get('error')} — à réinstaller à la main.")),
                'restored': bool(reprise.get('ok')), 'replaced': rollback}
    if not res.get('ok'):
        return {'ok': False, 'error': res.get('error', 'pull échoué')}

    # Re-synchronise pour que le modèle réel apparaisse, puis retire le candidat.
    if progress:
        progress("enregistrement au catalogue…")
    try:
        register_after_install()
    except Exception:
        logger.warning("register_after_install a échoué (le sync périodique rattrapera)",
                       exc_info=True)

    # RÉCONCILIER LE REMPLACÉ. `register_after_install()` → `full_sync()` n'enlève rien :
    # c'est voulu (une indisponibilité passagère ne doit pas purger le catalogue), mais ici
    # la suppression était DÉLIBÉRÉE — sans ce recalage, l'ancien modèle restait
    # `is_downloaded=True, is_available=True` alors qu'Ollama ne l'avait plus, et
    # `select_model()` pouvait désigner un modèle inexistant (constaté au test réel du
    # 2026-08-04 : `ollama:qwen3.5:35b-a3b` fantôme après son remplacement par qwen3.6:35b).
    # On MARQUE au lieu de supprimer : la ligne porte l'historique (statistiques de runtime,
    # ETA appris) qu'un `delete()` détruirait. `downloaded_only=True` suffit à l'écarter
    # de la sélection.
    if remplace and origine_key:
        maj = AIModel.objects.filter(model_key=origine_key).update(
            is_downloaded=False, is_available=False, is_loaded=False)
        logger.info("[prospect_install] %s remplacé par %s — %d ligne(s) recalée(s)",
                    origine_key, cand.name, maj)

    installed_name = cand.name
    cand.delete()
    return {'ok': True, 'installed': installed_name}


def uninstall_model(model_key: str) -> dict:
    """
    DÉSINSTALLE un modèle du catalogue : retrait des POIDS uniquement, jamais du backend
    (léger et réutilisable — décision Fabien 2026-08-27), et recalage du catalogue dans le
    même geste. Miroir de `install_from_spec` : dispatch par nature du stockage.

      • ollama       → `DELETE /api/delete` (driver existant `delete_ollama_model`) ;
      • snapshot HF  → suppression du dossier `models--org--nom` + ses verrous `.locks` ;
      • autre        → refus explicite (un fichier de poids d'app déclarée se retire par
                       l'app, pas par un rm générique).

    La ligne de catalogue est MARQUÉE (`is_downloaded=False`), jamais supprimée : elle porte
    l'historique (statistiques de runtime, ETA appris, identité/licence) — même doctrine que
    le remplacement de `install_candidate`. Un modèle déclaré par une app revient d'ailleurs
    au prochain sync (non téléchargé) ; un snapshot générique reste en mémoire de catalogue.

    Retourne {'ok': True, 'freed_gb': X, 'kind': …} ou {'ok': False, 'error': …}.
    """
    import shutil

    from django.utils import timezone

    from ..models import AIModel

    model = AIModel.objects.filter(model_key=model_key).first()
    if model is None:
        return {'ok': False, 'error': f"modèle inconnu du catalogue : {model_key!r}"}
    if model.is_proposed:
        return {'ok': False, 'error': "un candidat de prospection ne se désinstalle pas — "
                                      "il se rejette (bouton Rejeter)."}
    if model.is_loaded:
        return {'ok': False, 'error': f"« {model.name} » est chargé en mémoire — "
                                      "le décharger avant de le désinstaller."}
    if not model.is_downloaded:
        return {'ok': False, 'error': f"« {model.name} » n'a pas de poids sur cette machine."}

    freed_gb = float(model.disk_gb or 0)

    if model.source == 'ollama':
        nom = model.model_key.split(':', 1)[1] if ':' in model.model_key else model.name
        res = delete_ollama_model(nom)
        if not res.get('ok'):
            return {'ok': False, 'error': f"retrait Ollama impossible : {res.get('error')}"}
        kind = 'ollama'
    else:
        # Snapshot HF : le chemin vient du catalogue (posé par la découverte). GARDE-FOUS
        # avant tout rm -rf : le dossier doit être un `models--*` SOUS la racine canonique —
        # jamais de suppression hors de `AI-models/models/`, quoi que dise la base.
        from wama.common.utils.model_locations import models_root
        chemin = Path(model.local_path or (model.extra_info or {}).get('path') or '')
        if not chemin.name.startswith('models--'):
            return {'ok': False,
                    'error': f"stockage non pris en charge ({model.source}) : seuls les "
                             "snapshots HuggingFace et les modèles Ollama se désinstallent "
                             "d'ici — retrait manuel pour le reste."}
        try:
            racine = models_root().resolve()
            cible = chemin.resolve()
            cible.relative_to(racine)          # ValueError si hors racine
        except (ValueError, OSError):
            return {'ok': False, 'error': f"chemin hors de la racine des modèles : {chemin}"}
        if not cible.is_dir():
            return {'ok': False, 'error': f"dossier de poids introuvable : {cible}"}

        if not freed_gb:
            try:
                freed_gb = sum(f.stat().st_size for f in cible.rglob('*')
                               if f.is_file()) / (1024 ** 3)
            except OSError:
                freed_gb = 0.0
        shutil.rmtree(cible)
        verrous = cible.parent / '.locks' / cible.name
        if verrous.is_dir():
            shutil.rmtree(verrous, ignore_errors=True)
        kind = 'hf_snapshot'

    # Recalage IMMÉDIAT du catalogue (le sync ne re-mesure ces lignes qu'à sa prochaine
    # passe, et un snapshot générique disparu n'est simplement plus re-découvert).
    info = dict(model.extra_info or {})
    info['uninstalled_at'] = timezone.now().isoformat()
    AIModel.objects.filter(pk=model.pk).update(
        is_downloaded=False, is_loaded=False, extra_info=info)
    logger.info("[uninstall] %s (%s) — %.1f Go rendus", model_key, kind, freed_gb)
    return {'ok': True, 'freed_gb': round(freed_gb, 1), 'kind': kind, 'name': model.name}


def spec_for_catalog_row(model) -> dict | None:
    """
    Spec d'installation DÉRIVÉ d'une ligne de catalogue non téléchargée — le geste « Installer »
    des modèles d'app (2026-08-27, cas musicgen-melody : affiché « Not downloaded » sans aucun
    bouton ; l'affichage est voulu — découvrabilité —, le geste manquait).

    Conditions : un `hf_id` (la référence à tirer) ET un `extra_info['install_dir']` déclaré
    par la DÉCOUVERTE de l'app (le registre ne connaît pas ses producteurs : c'est l'app qui
    dit où ses poids vivent). `category`/`family` se dérivent du chemin relatif à la racine
    canonique. La `composition` déclarée voyage dans le spec (jeu cohérent). None si la ligne
    n'est pas installable ainsi — l'appelant le DIT, il n'invente pas d'emplacement.
    """
    from wama.common.utils.model_locations import models_root

    hf_id = (model.hf_id or '').strip()
    install_dir = ((model.extra_info or {}).get('install_dir') or '').strip()
    if not hf_id or not install_dir:
        return None
    try:
        rel = Path(install_dir).resolve().relative_to(models_root().resolve())
    except (ValueError, OSError):
        return None                      # hors racine canonique : pas installable d'ici
    parts = rel.parts
    if not parts:
        return None
    spec = {
        'kind': 'hf', 'ref': hf_id,
        'category': parts[0],
        **({'family': parts[1]} if len(parts) > 1 else {}),
        'note': f"installation explicite depuis le catalogue ({model.model_key})",
    }
    if getattr(model, 'composition', None):
        spec['composition'] = model.composition
    return spec


#: Fichiers de bord tirés avec tout jeu de composants (config/tokenizer/licence — légers).
_PATTERNS_DE_BORD = ['*.json', '*.txt', 'tokenizer*', '*.md']


def patterns_from_composition(composition) -> list | None:
    """
    `allow_patterns` DÉRIVÉS d'une `composition` déclarée (manifeste `model`,
    `body.composition.components`), ou None si rien n'est déclaré (→ dépôt entier, cas
    général mono-modèle). C'est la moitié « installation » du contrat : le manifeste déclare
    l'anatomie UNE fois, l'installation tire le jeu COHÉRENT — jamais le dépôt entier d'un
    repack multi-quantisations, jamais un composant isolé qui ne serait pas un modèle.
    """
    comps = (composition or {}).get('components') or []
    patterns = [c['pattern'] for c in comps if isinstance(c, dict) and c.get('pattern')]
    return patterns + _PATTERNS_DE_BORD if patterns else None


def install_from_spec(spec: dict) -> dict:
    """
    Point d'entrée UNIQUE d'installation — DESCRIPTEUR déclaratif au lieu de mécanismes
    hardcodés par type. Le spec peut être construit par l'UI, par la prospection, ou par
    l'ASSISTANT IA (pipeline cible : besoin utilisateur → modèle → librairie → app →
    install ; voir PROSPECTION_PIPELINE.md). Les `pull_*` existants deviennent les
    drivers derrière ce dispatcher.

    spec = {
      'kind': 'ollama' | 'hf' | 'yolo',        # driver d'installation
      'ref':  'bge-m3' | 'org/model' | 'yolo26s-seg',
      'category': 'diffusion' | 'speech' | …,  # hf : catégorie de dossier (model_locations)
      'family': 'qwen-image',                  # hf : sous-dossier famille (optionnel)
      'allow_patterns': ['*.safetensors'],     # hf : restreindre les fichiers (optionnel)
      'composition': {'components': […]},      # hf : anatomie déclarée (manifeste model) —
                                               #   allow_patterns DÉRIVÉS des patterns de
                                               #   composants si non fournis explicitement
      'pip_dependencies': ['lib>=x'],          # optionnel — VALIDATION HUMAINE OBLIGATOIRE
      'human_validated': True,                 # requis si pip_dependencies non vide
      'note': 'pourquoi ce modèle',            # traçabilité (journalisée)
    }
    Retourne {'ok': bool, …} (mêmes clés que les drivers, + 'pip' si dépendances).
    """
    spec = spec or {}
    kind = spec.get('kind')
    ref = (spec.get('ref') or '').strip()
    if not ref:
        return {'ok': False, 'error': 'spec.ref requis'}
    deps = [d for d in (spec.get('pip_dependencies') or []) if d]
    # ⚠ Installer des paquets = surface de risque (cf. pip_install_packages) : le spec
    # doit porter la preuve d'une validation humaine explicite, jamais d'auto.
    if deps and not spec.get('human_validated'):
        return {'ok': False,
                'error': "pip_dependencies exige une validation humaine explicite "
                         "(spec.human_validated=true)"}
    if spec.get('note'):
        logger.info("install_from_spec %s:%s — %s", kind, ref, spec['note'])

    if kind == 'ollama':
        res = pull_ollama_model(ref)
    elif kind == 'yolo':
        res = pull_yolo_weights(ref)
    elif kind == 'hf':
        if not spec.get('category'):
            return {'ok': False, 'error': "spec.category requis pour kind='hf'"}
        res = pull_hf_model(ref, spec['category'], spec.get('family'),
                            allow_patterns=(spec.get('allow_patterns')
                                            or patterns_from_composition(spec.get('composition'))))
    else:
        return {'ok': False, 'error': f"spec.kind inconnu: {kind!r} (ollama|hf|yolo)"}

    if res.get('ok') and deps:
        res['pip'] = pip_install_packages(deps)
        if not res['pip'].get('ok'):
            res['ok'] = False
            res['error'] = "modèle téléchargé mais dépendances pip en échec (voir 'pip')"
    if res.get('ok'):
        sync = None
        try:
            sync = register_after_install()
        except Exception:
            logger.warning("register_after_install a échoué (le sync périodique rattrapera)",
                           exc_info=True)
        if sync is not None:
            # Le sync ne pose QUE les faits de découverte (chemin, format, classes, taille) : il
            # ne sait rien de la licence ni de l'auteur. Sans cette étape, un modèle ajouté par
            # URL depuis l'assistant arrivait au catalogue aussi anonyme que ceux trouvés par
            # scan disque — et le corpus déclaratif n'en portait aucune trace.
            # `added_keys` vient du sync lui-même : c'est LUI qui sait ce qu'il vient de créer.
            # Best-effort : une provenance manquée (réseau, dépôt privé) ne doit jamais faire
            # échouer une installation qui, elle, a réussi.
            try:
                from .provenance import record_after_install
                res['provenance'] = record_after_install(
                    spec, getattr(sync, 'added_keys', None) or [])
            except Exception as e:
                logger.warning("provenance non enregistrée après installation : %s", e,
                               exc_info=True)
                res['provenance'] = {'erreur': f"{type(e).__name__}: {e}"}
    return res


#: Verrous d'installation pip (ROADMAP §16.7, transposés d'Hermes — câblés le 2026-08-31,
#: ils n'étaient jusque-là que doctrine) : PyPI par NOM seul (extras tolérés), PIN EXACT
#: `==` obligatoire — URL, `git+`, `file:`, options (`--index-url`, `-e`), chemins et
#: contraintes lâches (`>=`) sont refusés AVANT de toucher pip. L'allowlist par librairie
#: est `Library.is_allowed` (décision humaine, jamais posée par une projection) ; le kill
#: switch coupe tout sans redéploiement.
_PIP_SPEC_RE = re.compile(
    r'^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?'   # nom de distribution (PEP 508)
    r'(\[[A-Za-z0-9._,-]+\])?'                      # extras optionnels
    r'==[A-Za-z0-9.!+]+$'                           # pin exact (PEP 440)
)
PIP_KILL_SWITCH_ENV = 'WAMA_PIP_KILL_SWITCH'


def pip_spec_error(spec: str):
    """Motif de refus d'un spécificateur pip, ou None s'il passe les verrous syntaxiques."""
    s = (spec or '').strip()
    if not s:
        return "spécificateur vide"
    if not _PIP_SPEC_RE.match(s):
        return (f"spécificateur refusé : {s!r} — forme exigée « nom==version » "
                "(PyPI par nom seul, pin exact ; pas d'URL, git+, option ni contrainte lâche)")
    return None


def pip_install_packages(packages, timeout: int = 1800) -> dict:
    """
    Installe des paquets pip dans le venv courant — pour rendre un backend disponible quand un
    nouveau modèle exige de nouvelles libs (jonction avec le contrat BaseModelBackend).

    ⚠️ Installer des paquets arbitraires est une surface de risque → à déclencher sur VALIDATION
    HUMAINE uniquement, jamais en auto — et depuis le 2026-08-31 les verrous syntaxiques
    (`pip_spec_error` : pin exact, PyPI par nom) + kill switch s'appliquent à TOUS les
    appelants, y compris `ensure_backend_deps`. Retourne {ok, installed, error}.
    """
    import subprocess
    import sys

    pkgs = [p for p in (packages or []) if p]
    if not pkgs:
        return {'ok': True, 'installed': []}
    if os.environ.get(PIP_KILL_SWITCH_ENV):
        return {'ok': False, 'installed': [],
                'error': f"installations pip désactivées ({PIP_KILL_SWITCH_ENV} posé)"}
    refus = [e for e in (pip_spec_error(p) for p in pkgs) if e]
    if refus:
        return {'ok': False, 'installed': [], 'error': ' ; '.join(refus)}
    try:
        proc = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', *pkgs],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode == 0:
            return {'ok': True, 'installed': pkgs}
        return {'ok': False, 'installed': [], 'error': (proc.stderr or '')[-2000:]}
    except Exception as e:
        return {'ok': False, 'installed': [], 'error': f"{type(e).__name__}: {e}"}


def ensure_backend_deps(backend_cls, timeout: int = 1800) -> dict:
    """
    Installe les paquets manquants d'un backend (classe `BaseModelBackend`) si nécessaire.
    Lit `missing_packages()` (import) et `pip_install_spec()` (noms pip). No-op si déjà dispo.
    À appeler sur validation humaine (cf. pip_install_packages). Retourne {ok, installed, already}.
    """
    missing = backend_cls.missing_packages()
    if not missing:
        return {'ok': True, 'installed': [], 'already': True}
    res = pip_install_packages(backend_cls.pip_install_spec(), timeout=timeout)
    res['already'] = False
    return res


def _replay_patches() -> dict:
    """
    Rejoue `patches/apply_patches.py` — post-étape OBLIGATOIRE après tout pip install
    (contrat `WAMA_MANIFEST_ARCHITECTURE §7`) : pip écrase les patches venv en silence,
    et un patch perdu ne se signale pas (règle « ce qui ne plante pas ne se signale pas »).
    """
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[3] / 'patches' / 'apply_patches.py'
    if not script.exists():
        return {'ok': False, 'error': f"script introuvable : {script}"}
    try:
        proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                              text=True, timeout=600, cwd=str(script.parents[1]))
        return {'ok': proc.returncode == 0,
                'tail': (proc.stdout or proc.stderr or '').strip()[-500:]}
    except Exception as e:
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}


def install_library(key: str, apply: bool = False) -> dict:
    """
    Installe UNE librairie depuis son registre (`common.models.Library`) — la JONCTION
    manifeste→pip qui manquait (2026-08-31) : le kind `library` projetait le registre
    (`write_back_library`), mais rien ne reliait `pip_spec`/`is_allowed` aux exécuteurs.

    Contrat (WAMA_MANIFEST_ARCHITECTURE §7 + ROADMAP §16.7) :
      • `apply=False` (défaut) = PLAN sans aucun effet ;
      • `is_allowed` (décision humaine, jamais posée par une projection) obligatoire ;
      • verrous syntaxiques (`pip_spec_error` : nom PyPI + pin exact) + kill switch ;
      • post-étape : `patches/apply_patches.py` rejoué après toute installation réelle ;
      • version CONSTATÉE après coup (importlib.metadata) — un « pip ok » ne suffit pas ;
      • ⚠ n'installe QUE dans le venv COURANT : `venv_win` reste un geste manuel (règle
        « requirements s'installe dans LES DEUX venvs ») — signalé, jamais silencieux.
    """
    import importlib.metadata as im
    import sys

    from wama.common.models import Library

    lib = Library.objects.filter(key=key).first()
    if lib is None:
        return {'ok': False, 'library': key,
                'error': "librairie absente du registre — ingérer son manifeste d'abord "
                         "(write_back_library)"}
    spec = (lib.pip_spec or '').strip()
    err = pip_spec_error(spec)
    if err:
        return {'ok': False, 'library': key, 'error': err}

    nom_dist, _, version_cible = spec.partition('==')
    nom_dist = nom_dist.split('[', 1)[0]
    try:
        constat = im.version(nom_dist)
    except im.PackageNotFoundError:
        constat = None
    plan = {'library': key, 'spec': spec, 'installed_version': constat,
            'already_satisfied': constat == version_cible,
            'allowed': lib.is_allowed,
            'venv': sys.executable,
            'venv_win': "NON traité — geste manuel (règle des deux venvs)",
            'post_step': "patches/apply_patches.py rejoué après installation réelle"}

    if not apply:
        # Le PLAN est visible sans allowlist — le verrou ne gate que l'EXÉCUTION.
        return {'ok': True, 'plan': plan, 'would_install': constat != version_cible}

    if not lib.is_allowed:
        return {'ok': False, 'library': key, 'plan': plan,
                'error': "is_allowed=False — l'installation exige une décision humaine "
                         "explicite (allowlist, ROADMAP §16.7) : manage.py install_library "
                         f"{key} --allow --apply"}

    patches = None
    if constat != version_cible:
        res = pip_install_packages([spec])
        if not res.get('ok'):
            return {'ok': False, 'library': key, 'error': res.get('error'), 'plan': plan}
        patches = _replay_patches()
        try:
            constat = im.version(nom_dist)
        except im.PackageNotFoundError:
            constat = None
        if constat != version_cible:
            return {'ok': False, 'library': key, 'plan': plan, 'patches': patches,
                    'error': f"pip a répondu ok mais la version constatée est {constat!r} "
                             f"(attendu {version_cible!r})"}

    lib.is_installed = True
    lib.installed_version = version_cible
    lib.save(update_fields=['is_installed', 'installed_version'])
    return {'ok': True, 'library': key, 'installed': patches is not None,
            'version': version_cible, 'patches': patches, 'plan': plan}


def install_requirements(app_key: str, apply: bool = False) -> dict:
    """
    Le MARCHEUR d'app (« application = modèles + librairies », reste ③ de la route
    PROSPECTION_PIPELINE — câblé le 2026-08-31) : lit les `requires` du manifeste d'app AU
    CORPUS (`manifests/apps/<app>.json` — la déclaration validée, qui porte les jambes
    `library` semées) et DISPATCHE chaque référence vers son driver EXISTANT :

      • kind=library → `install_library` (plan/apply — allowlist `is_allowed` par lib) ;
      • kind=model   → état du catalogue + `install_catalog_task` (Celery) si un spec est
        dérivable (`spec_for_catalog_row`) ; sans spec dérivable, le modèle reste au
        « téléchargement au premier usage » — signalé, jamais silencieux.

    Le marcheur n'invente RIEN : il n'installe que ce que les drivers savent installer,
    sous leurs propres gardes. `apply=False` (défaut) = plan complet sans effet.
    """
    from wama.model_manager.models import AIModel

    chemin = Path(__file__).resolve().parents[3] / 'manifests' / 'apps' / f'{app_key}.json'
    if not chemin.exists():
        return {'ok': False, 'app': app_key,
                'error': f"manifeste d'app absent du corpus : {chemin.name} "
                         "(manifest_export --kind app d'abord)"}
    try:
        manifeste = json.loads(chemin.read_text(encoding='utf-8'))
    except Exception as e:
        return {'ok': False, 'app': app_key, 'error': f"manifeste illisible : {e}"}

    libraries, models, autres = [], [], []
    for ref in (manifeste.get('requires') or []):
        kind, key = ref.get('kind'), ref.get('key')
        if kind == 'library':
            libraries.append({'key': key, **install_library(key, apply=apply)})
        elif kind == 'model':
            row = AIModel.objects.filter(model_key=key, is_proposed=False).first()
            if row is None:
                models.append({'key': key, 'state': 'ABSENT du catalogue — sync_models ?'})
            elif row.is_downloaded:
                models.append({'key': key, 'state': 'téléchargé'})
            else:
                spec = spec_for_catalog_row(row)
                if spec is None:
                    models.append({'key': key,
                                   'state': "non téléchargé — pas de spec dérivable "
                                            "(téléchargement au premier usage)"})
                elif not apply:
                    models.append({'key': key, 'state': 'non téléchargé',
                                   'would_install': spec.get('ref')})
                else:
                    from ..tasks import install_catalog_task
                    started = install_catalog_task.delay(key)
                    models.append({'key': key, 'state': 'installation enfilée (Celery)',
                                   'task_id': started.id})
        else:
            autres.append(ref)   # function/dataset… : hors périmètre du marcheur, signalés

    ok = all(r.get('ok', True) for r in libraries)
    return {'ok': ok, 'app': app_key, 'apply': apply,
            'libraries': libraries, 'models': models,
            **({'ignored': autres} if autres else {})}
