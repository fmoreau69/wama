"""
Prospection de modèles — version DÉTERMINISTE (sans LLM, sans scraping).

Interroge l'API officielle `huggingface_hub` pour lister les modèles notables d'une tâche
(triés par téléchargements) et signale ceux que WAMA possède déjà. C'est le socle factuel :
la couche multi-agents (lecture de benchmarks, confrontation d'avis, score de confiance)
viendra PAR-DESSUS ce signal, et toute intégration reste soumise à acceptation admin.

Mapping app WAMA → tâche HF dans `APP_TASKS`.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Tâche HuggingFace par défaut pour chaque app WAMA (point de départ de la prospection).
APP_TASKS = {
    'imager':       'text-to-image',
    'video':        'text-to-video',
    'transcriber':  'automatic-speech-recognition',
    'synthesizer':  'text-to-speech',
    'describer':    'image-text-to-text',
    'anonymizer':   'object-detection',
    'enhancer':     'image-to-image',
}

# Tâche HF → ModelType valide (cf. models.ModelType).
_TASK_MODEL_TYPE = {
    'text-to-image':                 'diffusion',
    'text-to-video':                 'diffusion',
    'image-to-video':                'diffusion',
    'image-to-image':                'upscaling',
    'automatic-speech-recognition':  'speech',
    'text-to-speech':                'speech',
    'text-to-audio':                 'music',
    'image-text-to-text':            'vlm',
    'image-to-text':                 'ocr',
    'object-detection':              'vision',
}


def _metrique_declaree(card_data):
    """
    Metrique d'evaluation auto-declaree dans le `model-index` de la carte HF, ou None.

    C'est le seul signal de QUALITE que la plateforme expose ; tout le reste (telechargements,
    likes) mesure la popularite. Mais elle est auto-declaree, non verifiee, et calculee sur le
    jeu de validation de l'AUTEUR : deux modeles a 0.98 et 0.95 ne sont pas comparables s'ils
    n'ont pas ete evalues sur le meme jeu. On rend donc le jeu et le drapeau `verifie` avec la
    valeur -- de quoi trier des candidats, pas de quoi conclure.
    """
    if not card_data:
        return None
    try:
        donnees = card_data.to_dict() if hasattr(card_data, 'to_dict') else dict(card_data)
    except Exception:
        return None
    index = donnees.get('model-index') or donnees.get('model_index') or []
    for entree in index:
        for resultat in (entree.get('results') or []):
            jeu = ((resultat.get('dataset') or {}).get('name')) or ''
            for metrique in (resultat.get('metrics') or []):
                valeur = metrique.get('value')
                if isinstance(valeur, (int, float)):
                    return {
                        'nom': metrique.get('name') or metrique.get('type') or 'metrique',
                        'valeur': float(valeur),
                        'jeu': jeu,
                        'verifie': bool(metrique.get('verified')),
                    }
    return None


def prospect_hf(task: str, limit: int = 15, library: str | None = None, min_downloads: int = 0,
                search: str | None = None, sort: str = 'downloads'):
    """
    Top modèles HF d'une `task` (par téléchargements), avec flag « déjà dans WAMA ».
    Retourne {'ok': True, 'task': str, 'candidates': [...]} ou {'ok': False, 'error': str}.

    `search` restreint aux modèles dont le nom contient les termes donnés. Sans lui, une tâche
    large ne rend que les modèles les plus téléchargés — pour `object-detection`, des détecteurs
    COCO génériques, jamais les spécialisés qu'on cherche (visage, plaque). Constaté le
    2026-08-04 en cherchant à remplacer les modèles visage/plaque de l'anonymizer.
    """
    try:
        from huggingface_hub import HfApi
    except ImportError:
        return {'ok': False, 'error': "huggingface_hub non installé (pip install huggingface_hub)"}

    from wama.model_manager.models import AIModel
    # « Déjà chez nous » s'indexe sur les DEUX identités de plateforme, pas sur `hf_id` seul :
    # les modèles découverts par scan disque n'ont pas de `hf_id`, mais peuvent porter un
    # `platform_ref` posé par la provenance vérifiée (backfill_platform_refs / manifeste).
    # Sans ça, morsetechlab/yolov11-license-plate-detection ressortait « ★ NOUVEAU » alors que
    # ses 5 fichiers sont installés — la veille proposait de télécharger l'existant (2026-08-12).
    have = {(m.hf_id or '').lower() for m in AIModel.objects.exclude(hf_id='')}
    have |= {ref.partition(':')[2].lower()
             for ref in AIModel.objects.filter(platform_ref__startswith='huggingface:')
                                       .values_list('platform_ref', flat=True)}
    have.discard('')

    api = HfApi()
    # huggingface_hub 1.x : filtrage par tâche = `pipeline_tag` (pas `task`), librairie via `filter`.
    # `sort` : 'downloads' (éprouvé) ou 'trendingScore' (ce qui MONTE — seul tri qui fait
    # sortir une famille fraîchement publiée avant qu'elle domine les téléchargements ;
    # vérifié 2026-08-18 : le top downloads text-to-video ignorait les sorties de la semaine).
    kwargs = {'pipeline_tag': task, 'sort': sort, 'limit': limit,
              'expand': ['downloads', 'likes', 'lastModified', 'pipeline_tag', 'cardData']}
    if library:
        kwargs['filter'] = library
    if search:
        kwargs['search'] = search
    try:
        models = list(api.list_models(**kwargs))
    except Exception as e:
        # Repli si `expand` non supporté/incompatible avec ce filtre.
        kwargs.pop('expand', None)
        try:
            models = list(api.list_models(**kwargs))
        except Exception as e2:
            return {'ok': False, 'error': f"{type(e2).__name__}: {e2}"}
    # Garantir l'ordre décroissant par téléchargements quel que soit le défaut de l'API.
    models.sort(key=lambda m: getattr(m, 'downloads', 0) or 0, reverse=True)

    candidates = []
    for m in models:
        dl = getattr(m, 'downloads', 0) or 0
        if dl < min_downloads:
            continue
        lm = getattr(m, 'last_modified', None)
        carte = getattr(m, 'card_data', None)
        licence = None
        if carte is not None:
            try:
                licence = (carte.to_dict() if hasattr(carte, 'to_dict') else dict(carte)).get('license')
            except Exception:
                licence = None
        candidates.append({
            'hf_id': m.id,
            'downloads': dl,
            'likes': getattr(m, 'likes', 0) or 0,
            'pipeline_tag': getattr(m, 'pipeline_tag', None) or task,
            'last_modified': lm.isoformat() if hasattr(lm, 'isoformat') else (lm or None),
            'have': m.id.lower() in have,
            'metrique': _metrique_declaree(carte),
            'license': licence,
            'url': f"https://huggingface.co/{m.id}",
        })
    return {'ok': True, 'task': task, 'candidates': candidates}


# ── Balayage HF → candidats `is_proposed` (cards UI) ───────────────────────────────
# Tâches HF balayées : catégorie d'installation (= valeur ModelType, cf. model_locations),
# plancher de poids (un modèle SOUS ce poids est un LoRA/config pour la génération, mais un
# YOLO légitime pèse 13 Mo — d'où le plancher PAR TÂCHE), plafond de candidats (une liste
# que personne ne lit ne vaut pas mieux qu'une liste vide — même règle que MAX_PAR_ROLE).
# Déclaratif : élargir la prospection = ajouter une entrée, pas du code.
#
# Volontairement ABSENTS : `image-text-to-text` (VLM — doublon du rôle Ollama `vlm`, qui
# couvre déjà describer/reader avec des modèles réellement branchés) ; `lipsync` (aucun
# pipeline_tag HF ; la prospection avatars est un chantier séparé — PROSPECTION_AVATARS).
HF_TASKS = {
    # Génération (imager / vidéo) — étendu le 2026-08-18
    'text-to-image':  {'category': 'diffusion', 'poids_min_go': 1.0,   'max': 5},
    'text-to-video':  {'category': 'diffusion', 'poids_min_go': 1.0,   'max': 5},
    'image-to-video': {'category': 'diffusion', 'poids_min_go': 1.0,   'max': 5},
    # Parole (transcriber / synthesizer) — ⚠ TTS : vérifier la LICENCE sur la card (souvent NC)
    'automatic-speech-recognition': {'category': 'speech', 'poids_min_go': 0.05, 'max': 3},
    'text-to-speech':               {'category': 'speech', 'poids_min_go': 0.05, 'max': 3},
    # Image → image (enhancer)
    'image-to-image': {'category': 'upscaling', 'poids_min_go': 0.05, 'max': 3},
    # Détection (anonymizer…) — top downloads = COCO génériques ; les spécialisés
    # (visage/plaque) exigent `search`, cf. docstring prospect_hf (leçon 2026-08-04)
    'object-detection': {'category': 'vision', 'poids_min_go': 0.005, 'max': 3},
    # Musique (composer)
    'text-to-audio': {'category': 'music', 'poids_min_go': 0.05, 'max': 3},
    # OCR / documents (reader)
    'image-to-text': {'category': 'ocr', 'poids_min_go': 0.05, 'max': 3},
}

#: Un dépôt de génération sous ce poids est un LoRA/config, pas un modèle installable seul.
_POIDS_MIN_GO = 1.0

#: Motifs de BRUIT dans l'id d'un dépôt de génération : dérivés (LoRA, quantifs, repacks
#: d'outils tiers) qui noient les modèles canoniques — mesuré 2026-08-18 : le trending
#: text-to-video était aux 3/4 des LoRA MiniMax-H3 de particuliers.
_MOTIFS_BRUIT = ('lora', 'gguf', 'comfyui', 'repackaged', 'fp8', 'bnb',
                 'int4', 'int8', 'fp4', 'nvfp4', '4bit',
                 'coreml', 'mlx')   # formats Apple : non chargeables sur l'hôte CUDA


def _poids_depot_go(hf_id: str):
    """Poids total d'un dépôt HF en Go (somme des fichiers), ou None si indéterminable.
    Un appel HTTP par dépôt : à réserver aux candidats RETENUS, pas au listing."""
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(hf_id, files_metadata=True)
        total = sum((s.size or 0) for s in (info.siblings or []))
        return round(total / 1024 ** 3, 1) if total else None
    except Exception as e:
        logger.debug("[prospect_hf_seed] poids de %s indéterminable : %s", hf_id, e)
        return None


#: Marqueurs de QUANTISATION/repack dans l'id d'un dépôt dérivé. Sous-ensemble de
#: `_MOTIFS_BRUIT` (moins `lora` — un adaptateur n'est pas une variante du modèle — et moins
#: `coreml`/`mlx`, inchargeables sur l'hôte CUDA), plus les schémas absents du bruit
#: (`awq`, `gptq`…). `comfy` couvre les repacks Comfy-Org/ComfyUI : single-file + variantes
#: fp8 SANS marqueur dans l'id du dépôt (mesuré 2026-08-26 : le repack le plus téléchargé
#: de MiniMax-Music3, 551 k, était invisible sans lui).
_MOTIFS_QUANT = ('gguf', 'fp8', 'bnb', 'int4', 'int8', 'fp4', 'nvfp4',
                 '4bit', '8bit', 'awq', 'gptq', 'quant', 'comfy')


def variantes_quantisees(hf_id: str, limit: int = 5) -> list[dict]:
    """
    Dépôts HF dérivés QUANTISÉS d'un modèle (GGUF/FP8/4-8bit/AWQ…), triés par téléchargements.

    Ce qui est du BRUIT pour le listing des canoniques (`_MOTIFS_BRUIT` les écarte du seeding)
    est l'INFORMATION du juge de confiance : un gros modèle se juge sur sa meilleure variante,
    pas sur ses poids pleins. Vécu 2026-08-26 : MiniMax-Music3 rejeté à 10 % « 53 Go > 24 Go »
    alors que son repack single-file dominait les téléchargements de la famille.

    Recherche LARGE (radical sans le numéro de version final — « MiniMax-Music » retrouve
    « MiniMax-Music-3 », tiret inséré par le repackageur), filtre STRICT (le nom complet
    normalisé alphanumérique
    doit apparaître dans l'id candidat + un marqueur de quantisation). Réseau : 2 requêtes.
    """
    import re
    try:
        from huggingface_hub import HfApi
    except ImportError:
        return []

    nom_court = hf_id.split('/')[-1]
    normaliser = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())  # noqa: E731
    cible = normaliser(nom_court)
    radical = re.sub(r'[-_ ]?\d+(\.\d+)?$', '', nom_court) or nom_court

    vus, variantes = {hf_id.lower()}, []
    api = HfApi()
    for terme in dict.fromkeys((nom_court, radical)):        # dédupliqué, ordre stable
        try:
            depots = api.list_models(search=terme, sort='downloads', limit=100,
                                     expand=['downloads', 'likes'])
        except Exception as e:
            logger.debug("[variantes_quantisees] recherche « %s » en échec : %s", terme, e)
            continue
        for d in depots:
            did = d.id.lower()
            if did in vus or cible not in normaliser(d.id):
                continue
            if not any(m in did for m in _MOTIFS_QUANT):
                continue
            vus.add(did)
            variantes.append({'hf_id': d.id,
                              'downloads': getattr(d, 'downloads', 0) or 0,
                              'likes': getattr(d, 'likes', 0) or 0})
    variantes.sort(key=lambda v: v['downloads'], reverse=True)
    return variantes[:limit]


#: Extensions de fichiers de POIDS (pour le détail par fichier des dépôts quantisés).
_EXT_POIDS = ('.gguf', '.safetensors', '.bin', '.pt', '.pth')


def _fichiers_poids(hf_id: str) -> list[tuple[str, int]]:
    """`[(nom, taille_octets)]` des fichiers de poids d'un dépôt (metadata, 1 requête)."""
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(hf_id, files_metadata=True)
        return [(s.rfilename, s.size or 0) for s in (info.siblings or [])
                if s.rfilename.lower().endswith(_EXT_POIDS)]
    except Exception as e:
        logger.debug("[options_install] fichiers de %s indéterminables : %s", hf_id, e)
        return []


def options_installation(cand) -> dict:
    """
    Options d'installation EXPLICITES d'un candidat HF : poids pleins + variantes quantisées,
    chacune avec son poids disque — l'information à montrer AVANT d'installer, pour que
    l'utilisateur choisisse en connaissance de cause (demande Fabien 2026-08-27 : le juge
    évaluait la faisabilité sur les variantes quantisées, mais l'installation tirait les
    poids pleins du dépôt canonique — 54 Go inexploitables sur 24 Go de VRAM).

    Un dépôt GGUF porte souvent PLUSIEURS niveaux de quantisation : l'option descend alors au
    FICHIER (une ligne par .gguf, la taille du fichier ≈ la VRAM nécessaire), et l'installation
    se fera par `allow_patterns` — jamais le dépôt entier. Les relevés (1 requête réseau par
    variante) sont PERSISTÉS dans `extra_info['prospect']['quant_variants']` : payés une fois.

    Retourne {'choice': bool, 'options': [{ref, file, label, disk_gb, vram_note, downloads,
    kind}]} — liste plate, prête pour l'UI.
    """
    prospect = dict((cand.extra_info or {}).get('prospect') or {})
    if (prospect.get('spec') or {}).get('kind') != 'hf':
        return {'choice': False, 'options': []}

    variants = prospect.get('quant_variants')
    a_persister = variants is None
    if variants is None:
        variants = variantes_quantisees(cand.hf_id)
    enrichies = []
    for v in variants:
        v = dict(v)
        if v.get('disk_gb') is None:
            v['disk_gb'] = _poids_depot_go(v['hf_id'])
            a_persister = True
        if 'files' not in v:
            v['files'] = [{'file': nom, 'gb': round(taille / 1024 ** 3, 1)}
                          for nom, taille in _fichiers_poids(v['hf_id'])]
            a_persister = True
        enrichies.append(v)
    if a_persister:
        prospect['quant_variants'] = enrichies
        info = dict(cand.extra_info or {})
        info['prospect'] = prospect
        cand.extra_info = info
        cand.save(update_fields=['extra_info'])

    options = [{
        'ref': cand.hf_id, 'file': None,
        'label': f"Poids pleins — {cand.hf_id}",
        'disk_gb': cand.disk_gb or None,
        'vram_note': "ne tient pas en VRAM sans quantisation/offload"
                     if (cand.disk_gb or 0) > 24 else "",
        'downloads': None, 'kind': 'full',
    }]
    for v in enrichies:
        ggufs = [f for f in (v.get('files') or []) if f['file'].lower().endswith('.gguf')]
        if ggufs:
            # Une ligne PAR fichier gguf : c'est le fichier qu'on installe, pas le dépôt.
            for f in sorted(ggufs, key=lambda x: x['gb'], reverse=True):
                options.append({
                    'ref': v['hf_id'], 'file': f['file'],
                    'label': f"{v['hf_id']} — {f['file']}",
                    'disk_gb': f['gb'],
                    'vram_note': f"VRAM ≈ {f['gb']:.1f} Go (+ marge de contexte)",
                    'downloads': v.get('downloads'), 'kind': 'variant_file',
                })
        else:
            options.append({
                'ref': v['hf_id'], 'file': None,
                'label': v['hf_id'],
                'disk_gb': v.get('disk_gb'),
                'vram_note': "",
                'downloads': v.get('downloads'), 'kind': 'variant',
            })
    return {'choice': len(options) > 1, 'options': options}


def spec_pour_choix(cand, variant_ref: str, variant_file: str | None) -> dict | None:
    """
    Le SPEC d'installation qui respecte le choix validé par l'utilisateur, ou None si le choix
    ne correspond à aucune option connue (on n'installe jamais un dépôt non proposé).

    La famille de dossier reste celle du modèle CANONIQUE (`cand.name`) : les poids d'une
    variante vivent sous `models/<cat>/<famille>/models--org--variante/` — regroupés avec les
    poids pleins qu'ils remplacent, désinstallables l'un comme l'autre.
    """
    prospect = (cand.extra_info or {}).get('prospect') or {}
    base = prospect.get('spec') or {}
    if base.get('kind') != 'hf' or not variant_ref:
        return None
    if variant_ref == cand.hf_id and not variant_file:
        return dict(base)                      # poids pleins : le spec d'origine, inchangé
    variantes = {v['hf_id']: v for v in (prospect.get('quant_variants') or [])}
    v = variantes.get(variant_ref)
    if v is None:
        return None
    if variant_file and variant_file not in {f['file'] for f in (v.get('files') or [])}:
        return None
    spec = dict(base)
    spec['ref'] = variant_ref
    spec['family'] = cand.name
    if variant_file:
        # Le fichier choisi + les petits fichiers de bord (config/tokenizer) — jamais les
        # autres niveaux de quantisation du dépôt.
        spec['allow_patterns'] = [variant_file, '*.json', '*.txt', 'tokenizer*']
    spec['note'] = (f"variante quantisée choisie par l'utilisateur : {variant_ref}"
                    + (f" / {variant_file}" if variant_file else ""))
    return spec


def seed_hf_candidates(limit: int = 12, min_downloads: int = 1000, tasks=None) -> dict:
    """
    Candidats `is_proposed` depuis la bibliothèque HuggingFace — pendant HF de la découverte
    par rôles de `prospect_ollama`. Né « génération image/vidéo » (2026-08-18, demande
    Fabien : « que Wan3 sorte ») puis étendu le même jour à TOUTE la table `HF_TASKS`
    (parole, détection, upscaling, musique, OCR).

    Réutilise : `prospect_hf` (découverte + flag « déjà chez nous » + licence),
    `ecrire_candidat` (writer unique, garde de préservation des évaluations comprise),
    `AIModel.meilleurs_installes` (référentiel `concurrence` affiché sur la card),
    `_poids_depot_go` (garde d'espace). Chaque candidat porte son **spec d'installation**
    (`install_from_spec`) — c'était le RESTE (3) du pipeline (« spec attaché »).

    Purge CIBLÉE comme dans prospect_ollama : uniquement le périmètre des tâches dont le
    balayage a ABOUTI (une panne réseau HF ne vide pas la liste).
    """
    from wama.model_manager.models import AIModel
    from .prospect_ollama import PROPOSED_PREFIX, ecrire_candidat

    crees = maj = 0
    vus: set = set()
    taches_ok: list = []
    refs_type: dict = {}
    table = {t: HF_TASKS[t] for t in (tasks or HF_TASKS) if t in HF_TASKS}

    for tache, regle in table.items():
        # Deux tris complémentaires : `downloads` = l'éprouvé, `trendingScore` = ce qui
        # MONTE (une famille publiée cette semaine — c'est LE tri qui la fait sortir avant
        # qu'elle domine les téléchargements). Dédupliqués via `vus`.
        candidats, ok_tache = [], False
        for tri in ('downloads', 'trendingScore'):
            res = prospect_hf(tache, limit=limit, min_downloads=(min_downloads
                              if tri == 'downloads' else 0), sort=tri)
            if res.get('ok'):
                ok_tache = True
                candidats.extend(res['candidates'])
            else:
                logger.warning("[prospect_hf_seed] %s (%s) indisponible : %s",
                               tache, tri, res.get('error'))
        if not ok_tache:
            continue
        taches_ok.append(tache)
        model_type = _TASK_MODEL_TYPE.get(tache, 'diffusion')
        if model_type not in refs_type:
            # Identité courte : `name` du catalogue porte parfois un descriptif après « — ».
            refs_type[model_type] = [
                (m.name or '').split('—')[0].strip()
                for m in AIModel.meilleurs_installes(model_type)]
        retenus = 0
        for c in candidats:
            if retenus >= regle['max']:
                break
            hf_id = c['hf_id']
            cand_key = PROPOSED_PREFIX + f"hf:{hf_id}"
            if c['have'] or cand_key in vus:
                continue
            if any(motif in hf_id.lower() for motif in _MOTIFS_BRUIT):
                continue    # dérivé (LoRA/quantif/repack), pas un modèle canonique
            poids = _poids_depot_go(hf_id)   # un appel HTTP — candidats retenus seulement
            if poids is not None and poids < regle['poids_min_go']:
                continue    # sous le plancher de la tâche : LoRA/config, pas un modèle
            vus.add(cand_key)
            retenus += 1
            cree = ecrire_candidat(
                cand_key, nom=hf_id.split('/')[-1], model_type=model_type,
                source='huggingface',
                description=(f"[{tache}] {c['downloads']} téléchargements, "
                             f"{c['likes']} ♥ — proposé par la bibliothèque HuggingFace."),
                kind='new', confidence=None,
                extra={'kind': 'new', 'role': f"hf:{tache}", 'name': hf_id,
                       'reason': f"tâche {tache} — non installé",
                       'concurrence': refs_type[model_type],
                       'downloads': c['downloads'], 'likes': c['likes'],
                       'metrique': c.get('metrique'),
                       'spec': {'kind': 'hf', 'ref': hf_id, 'category': regle['category'],
                                'note': f"prospection HF {tache}"}},
                hf_id=hf_id, license=str(c.get('license') or '')[:64],
                platform_ref=f"huggingface:{hf_id}",
                disk_gb=poids or 0.0,     # 0.0 = inconnu → la garde d'espace refusera (forçable)
            )
            crees += int(cree)
            maj += int(not cree)

    supprimes = preserves = 0
    # Transition : les candidats du 18/08 portaient `generation:<t>` avant le passage au
    # préfixe générique `hf:<t>` — on purge les deux graphies du même périmètre.
    roles_ok = {f"hf:{t}" for t in taches_ok} | {f"generation:{t}" for t in taches_ok}
    if roles_ok:
        perimetre = AIModel.objects.filter(
            is_proposed=True, source='huggingface', proposal_kind='new',
            model_key__startswith=PROPOSED_PREFIX + 'hf:',
        ).exclude(model_key__in=vus)
        for m in perimetre:
            # Ne purger que le périmètre des tâches qui ont réellement abouti : un candidat
            # d'une tâche en échec réseau reste en place (même règle que prospect_ollama).
            pr = m.extra_info.get('prospect', {})
            if (pr.get('role') or '') not in roles_ok:
                continue
            # ⚠ NE JAMAIS PURGER UN CANDIDAT ÉVALUÉ (2026-08-19). Le tri « tendance » de HF
            # bouge en continu : d'un run à l'autre la liste retenue change presque
            # entièrement (mesuré : 32 créés / 32 purgés). Sans cette garde, chaque clic
            # « Prospecter » DÉTRUISAIT les évaluations LLM déjà payées (13 perdues au test)
            # et le badge de confiance disparaissait. Un candidat évalué reste jusqu'à ce
            # qu'un humain le rejette — c'est la même règle que `ecrire_candidat`, qui
            # préserve déjà l'évaluation à l'écriture.
            if pr.get('assess'):
                preserves += 1
                continue
            m.delete()
            supprimes += 1

    resume = {'created': crees, 'updated': maj, 'removed': supprimes,
              'preserved': preserves,      # évalués, sortis de la tendance : conservés
              'total': len(vus), 'tasks_ok': taches_ok}
    logger.info("[prospect_hf_seed] %s", resume)
    return resume


def apply_recommendations(candidates, source: str, task: str):
    """
    Crée/maj des entrées `recommended` dans le catalogue pour les candidats NOUVEAUX (pas déjà
    dans WAMA). Non téléchargées, non disponibles, préfixe model_id `rec-` (distinctes des
    modèles découverts). Le flag `extra_info['recommended']` est préservé par le sync. Retourne
    le nombre d'entrées écrites. L'installation effective reste une action admin (HF à venir).
    """
    import re
    from datetime import datetime, timezone
    from wama.model_manager.models import AIModel

    mt = _TASK_MODEL_TYPE.get(task, 'llm')
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for c in candidates:
        if c.get('have'):
            continue
        hf_id = c['hf_id']
        model_id = 'rec-' + re.sub(r'[^a-z0-9.-]+', '-', hf_id.lower()).strip('-')
        AIModel.objects.update_or_create(
            model_key=f"{source}:{model_id}",
            defaults={
                'name': hf_id.split('/')[-1],
                'source': source,
                'model_type': mt,
                'hf_id': hf_id,
                # La prospection LIT déjà la licence sur la carte HF (prospect_hf) : la jeter ici
                # obligeait à repasser par backfill_platform_refs --licences pour la retrouver.
                # `platform_ref` se dérive du même fait, sans requête supplémentaire.
                'license': str(c.get('license') or '')[:64],
                'platform_ref': f"huggingface:{hf_id}",
                'description': f"(Recommandé · prospection) {task} — {c['downloads']} téléchargements, {c['likes']} ♥",
                'is_downloaded': False,
                'is_available': False,
                'extra_info': {'recommended': {
                    'task': task,
                    'downloads': c['downloads'],
                    'likes': c['likes'],
                    'pipeline_tag': c.get('pipeline_tag'),
                    'prospected_at': now,
                }},
            },
        )
        n += 1
    return n
