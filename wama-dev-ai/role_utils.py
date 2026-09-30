"""
Briques COMMUNES des pilotes de rôle (librarian, scout, integrator) — extraites de
run_librarian.py le 2026-08-27 au moment d'écrire les deux rôles frères (zéro duplication,
même règle que wama/common/ côté produit).

Tout est BORNÉ (leçons wama-dev-ai) : un appel Ollama one-shot, sorties dans outputs/ avec
PENDING_HUMAN_VALIDATION, jamais d'auto-application.
"""
import json
import os
import re
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = Path(__file__).resolve().parent / 'outputs'
PROMPTS = Path(__file__).resolve().parent / 'prompts'

# Ollama (gateway) SANS proxy — le proxy UGE avalerait 172.x ; le web AVEC proxy (défaut env).
_OPENER_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ollama_host():
    """Adresse d'Ollama — DÉLÈGUE à la brique commune (2026-09-07).

    Ce fichier en portait une copie. Elle n'était pas « une variante » : la brique commune
    `common/utils/ollama_host.py` a justement été EXTRAITE de `run_librarian.py` le
    2026-08-02 comme « seule implémentation correcte du repo » — et sa source ne l'a jamais
    adoptée. *Une brique qu'on extrait sans que son origine l'adopte laisse deux vérités
    derrière elle.*

    Les deux résolvaient la même adresse aujourd'hui (mesuré : `http://172.21.96.1:11434`
    des deux côtés), mais la copie était en retard sur TROIS points, tous latents :
      • elle lisait `os.environ` BRUT au lieu du registre `external_sources` — le jour où
        l'adresse est posée par réglage Django et non par l'environnement, elle vise encore
        la boucle locale, avec le symptôme trompeur que la brique commune documente
        (« Ollama ne répond pas » alors qu'il tourne) ;
      • son `subprocess` n'avait AUCUN timeout — un `ip route` qui pend gèle le rôle ;
      • passerelle introuvable = retour silencieux sur la boucle locale, sans avertissement.

    Import PARESSEUX : `role_utils` reste importable sans Django, et Django n'est exigé qu'à
    l'appel — les 5 rôles font tous `django.setup()` avant d'importer ce module (vérifié).
    Pas de repli « si Django manque » : ce serait exactement le second chemin qu'on retire.
    """
    from wama.common.utils.ollama_host import ollama_base
    return ollama_base()


def model_vocabularies() -> str:
    """Vocabulaires FERMÉS d'un manifeste `model`, SERVIS par le code (l'agent choisit dedans,
    il n'invente pas) — accesseur UNIQUE des rôles qui écrivent un manifeste `model`.

    Vivait dans `run_model_manifest.py` (`vocabulaires`). Remonté ici le 2026-09-30 : le rôle
    frère `scout` écrit le MÊME manifeste et ne recevait AUCUN de ces vocabulaires. Vécu au
    1er passage réel des avatars (qwen3.8, LongCat-Video-Avatar-1.5) : `inputs_required
    ['audio']`, `inputs_optional ['image']` — manifeste invalide, exactement le défaut que
    `e750fa74` avait corrigé pour le seul rôle `model`. *Une garde se pose avec ses jumeaux.*

    Import PARESSEUX, comme `ollama_host` : Django n'est exigé qu'à l'appel.
    """
    from wama.common.backends.manager import known_engines
    from wama.common.utils.app_modes import INPUT_TYPES
    from wama.common.utils.model_capabilities import CANONICAL_CAPABILITIES
    from wama.model_manager.models import ModelSource, ModelTask, ModelType

    engines = sorted(known_engines())
    return (
        f"capabilities.task — valeurs autorisées : {', '.join(sorted(ModelTask.values))}\n"
        # Servi depuis le 2026-09-29 : sans lui, gpt-oss-120b a déclaré `seed, steps, cfg`
        # (des réglages) comme entrées d'un modèle texte→image.
        f"capabilities.inputs_required / inputs_optional — ids d'ENTRÉES (données fournies, "
        f"jamais des réglages) : {', '.join(sorted(INPUT_TYPES))}\n"
        f"identity.model_type — valeurs autorisées : {', '.join(sorted(ModelType.values))}\n"
        f"identity.source — valeurs autorisées : {', '.join(sorted(ModelSource.values))}\n"
        f"clés canoniques de `capabilities` : {', '.join(sorted(CANONICAL_CAPABILITIES))}\n"
        f"composition.runtime.engine — moteurs DÉJÀ SERVIS par un backend : "
        f"{', '.join(engines) or '(aucun)'}\n"
    )


def diffusers_class_known(class_name) -> bool:
    """Vrai si `class_name` est exporté par le `diffusers` INSTALLÉ.

    `dir()` d'un module paresseux (`_LazyModule`) liste ses noms SANS importer les sous-modules :
    `hasattr` les importerait (mesuré : TensorFlow et xformers chargés, plusieurs minutes).
    """
    if not class_name:
        return False
    import diffusers
    return str(class_name) in dir(diffusers)


def diffusers_pipeline_class(hf_id):
    """(`_class_name` du `model_index.json` racine, ou None ; raison lisible) — fait MÉCANIQUE."""
    import json as _json
    from huggingface_hub import hf_hub_download
    try:
        path = hf_hub_download(hf_id, 'model_index.json')
    except Exception:
        return None, "aucun model_index.json à la racine du dépôt"
    with open(path, encoding='utf-8') as f:
        class_name = (_json.load(f) or {}).get('_class_name')
    if not class_name:
        return None, "model_index.json sans _class_name"
    return class_name, f"model_index.json nomme {class_name!r}"


def transformers_class_known(class_name) -> bool:
    """Vrai si `class_name` est exporté par le `transformers` INSTALLÉ (même lecture paresseuse
    que `diffusers_class_known` : `dir()` d'un `_LazyModule` n'importe aucun sous-module)."""
    if not class_name:
        return False
    import transformers
    return str(class_name) in dir(transformers)


def transformers_architectures(hf_id):
    """(`architectures` du `config.json` racine, ou [] ; raison lisible) — fait MÉCANIQUE.

    `auto_map` y est signalé : un modèle à code DISTANT ne s'exécute pas par les classes de
    `transformers`, mais par le moteur `transformers-remote-code`."""
    import json as _json
    from huggingface_hub import hf_hub_download
    try:
        path = hf_hub_download(hf_id, 'config.json')
    except Exception:
        return [], "aucun config.json à la racine du dépôt"
    with open(path, encoding='utf-8') as f:
        config = _json.load(f) or {}
    architectures = [a for a in (config.get('architectures') or []) if a]
    if not architectures:
        return [], "config.json sans architectures"
    reason = f"config.json nomme {architectures}"
    if config.get('auto_map'):
        reason += " (code DISTANT déclaré par auto_map)"
    return architectures, reason


#: Moteurs dont le dépôt PROUVE l'exécutabilité : lecteur du fait, test contre la lib installée,
#: libellé de l'échec. Un moteur absent de cette table n'est pas jugé ici — le fait manque.
ENGINE_PROOFS = {
    'diffusers': (diffusers_pipeline_class, diffusers_class_known, 'classe inconnue de diffusers'),
    'transformers': (transformers_architectures, transformers_class_known,
                     'aucune de ces classes dans le transformers installé'),
}


def repo_files(hf_id) -> list:
    """Chemins des fichiers du dépôt HF ([] s'il est illisible — réseau, dépôt restreint)."""
    try:
        from huggingface_hub import HfApi
        return list(HfApi().list_repo_files(hf_id))
    except Exception:
        return []


def signal_weight_formats(hf_id, concerns, lister=repo_files):
    """Signale les FORMATS de poids du dépôt quand il en porte plusieurs.

    Vécu le 2026-09-30 (LinTO FastConformer) : le rôle a proposé `transformers` sur la foi d'un
    `config.json`, alors que le `.nemo` du MÊME dépôt s'exécute par NeMo. Le rôle ne voyait pas
    l'alternative ; le validateur humain non plus. Les extensions sont celles que la prospection
    reconnaît déjà comme des poids (`prospector._WEIGHT_EXTS`) — aucune liste de plus."""
    from wama.model_manager.services.prospector import _WEIGHT_EXTS
    by_ext = {}
    for path in lister(hf_id):
        ext = next((e for e in _WEIGHT_EXTS if path.lower().endswith(e)), None)
        if ext:
            by_ext.setdefault(ext, []).append(path)
    if len(by_ext) > 1:
        detail = ' ; '.join(f"{ext} ({', '.join(sorted(paths)[:2])}"
                            f"{', …' if len(paths) > 2 else ''})"
                            for ext, paths in sorted(by_ext.items()))
        concerns.append(f"le dépôt porte PLUSIEURS formats de poids — {detail} : le moteur doit "
                        f"être celui du format retenu")
    return by_ext


def enforce_engine_facts(manifest, hf_id, concerns, reader=None, lister=repo_files):
    """Retire `composition.runtime.engine` quand le dépôt ne le PROUVE pas, et dit ce qu'il porte.

    Vécu le 2026-09-30 (qwen3.8, avatars) : LongCat-Video-Avatar-1.5 et SoulX-FlashHead portent
    un `model_index.json` et des fichiers `diffusion_pytorch_model.safetensors`, et le rôle a
    déclaré `diffusers` — alors que leur `_class_name` (absent, `WanModelAudioProject`) n'existe
    pas dans `diffusers`, et que sa PROPRE remarque disait « pas un pipeline diffusers standard ».
    La consigne alignée n'a rien changé au run suivant : *une consigne de prompt n'est pas un
    contrôle*. Un moteur faux ne grise pas le modèle (le backend existe) : il le rend proposable
    puis fait échouer le chargement. Retirer le moteur le laisse GRISÉ avec sa raison, ce qui est
    le comportement voulu tant qu'aucun backend ne l'exécute.
    Même défaut le même jour sur `transformers` (LinTO FastConformer, `ParakeetForRNNT` absente
    du transformers installé) : la preuve est désormais une TABLE par moteur (`ENGINE_PROOFS`).
    Un moteur qu'AUCUN backend ne sert (`known_engines`) n'est pas retiré — c'est peut-être le
    backend à écrire — mais il est DIT : le modèle restera grisé jusque-là.
    Les faits mécaniques priment sur le jugement du LLM, comme la licence ou la taille.
    `reader` remplace le lecteur du fait (tests) ; `lister`, l'inventaire du dépôt.
    """
    signal_weight_formats(hf_id, concerns, lister=lister)
    runtime = (((manifest.get('body') or {}).get('composition') or {}).get('runtime') or {})
    engine = runtime.get('engine')
    if not engine:
        return manifest
    proof = ENGINE_PROOFS.get(engine)
    if proof is None:
        from wama.common.backends.manager import known_engines
        if engine not in known_engines():
            concerns.append(f"engine {engine!r} servi par AUCUN backend — le modèle restera "
                            f"grisé jusqu'à ce qu'un backend le serve")
        return manifest
    read, known, failure = proof
    names, reason = (reader or read)(hf_id)
    names = [names] if isinstance(names, str) else list(names or [])
    if any(known(n) for n in names):
        return manifest
    runtime.pop('engine', None)
    if not runtime:
        manifest['body']['composition'].pop('runtime', None)
    concerns.append(f"engine {engine!r} RETIRÉ (fait mécanique) : {reason}, "
                    f"{failure} — un backend dédié reste à écrire")
    return manifest


#: Fichiers qui font d'un dépôt un PAQUET que pip sait installer (`pip install .`).
PACKAGING_FILES = ('pyproject.toml', 'setup.py', 'setup.cfg')


def vendor_engine_name(repo: str) -> str:
    """Nom de moteur dérivé du dépôt (`TMElyralab/MuseTalk` → `musetalk`) — la forme exigée par
    `vendor_spec_error` ; c'est aussi la clé du manifeste et le dossier sous le vendor."""
    name = re.sub(r'[^a-z0-9]+', '_', repo.rsplit('/', 1)[-1].lower()).strip('_')
    return name if re.match(r'^[a-z]', name) else f'engine_{name}'


def github_head_sha(repo: str, branch: str, fetcher=None) -> str:
    """SHA complet de la tête de `branch` — MESURÉ par l'API GitHub (source déclarée `github_api`)."""
    from wama.common.external_sources import base_url
    raw = (fetcher or fetch)(f"{base_url('github_api')}/repos/{repo}/commits/{branch}")
    return json.loads(raw)['sha']


def enforce_install_channel(manifest, repo, packaging, sha, notes):
    """Pose le CANAL d'installation d'après les FAITS du dépôt, jamais d'après le LLM.

    Route `library` (ROADMAP D-a, 2026-09-30) : pip est la norme ; un dépôt sans fichier de
    paquet (`PACKAGING_FILES`) n'est pas installable par pip et se VENDORISE — dépôt épinglé au
    commit MESURÉ. Avant ce contrôle, le rôle écrivait `install.pip` pour MuseTalk ou TripoSR,
    et le manifeste mourait au verrou (`nom==version` introuvable sur PyPI) : la chaîne
    scout → install apportait manifeste et poids, jamais le moteur.
    `packaging` = les fichiers de paquet trouvés à la racine ; `sha` = tête mesurée (ou None).
    """
    body = manifest.setdefault('body', {})
    install = body.get('install') if isinstance(body.get('install'), dict) else {}
    if packaging:
        if install.pop('vendor', None) is not None:
            notes.append(f"install.vendor RETIRÉ : le dépôt est un paquet ({', '.join(packaging)}) "
                         "— la norme est pip")
        body['install'] = install
        return manifest
    if not sha:
        notes.append("dépôt SANS fichier de paquet mais tête non mesurée : install.vendor à "
                     "compléter à la main (commit exact)")
        return manifest
    engine = vendor_engine_name(repo)
    if install.get('pip'):
        notes.append(f"install.pip {install['pip']!r} RETIRÉ (fait mécanique) : aucun "
                     f"{'/'.join(PACKAGING_FILES)} à la racine — pip ne sait pas l'installer")
    body['install'] = {'vendor': {'repo': repo, 'commit': sha, 'engine': engine}}
    identity = body.setdefault('identity', {})
    identity['version'] = sha[:12]
    identity['repository'] = f'https://github.com/{repo}'
    manifest['key'] = engine
    manifest['source'] = {'type': 'authored', 'ref': f'github:{repo}@{sha}'}
    notes.append(f"voie VENDOR : commit {sha[:12]} mesuré, moteur {engine!r} — à aligner sur "
                 "l'ENGINE du backend qui l'exécutera ; correctif local éventuel sous patches/")
    return manifest


#: Clés qui, dans un fichier de config à la RACINE du dépôt, disent la taille de travail d'un
#: modèle image (`pipeline_config.json` de Supra2-IMG : `image_size: 256`). Un entier = côté
#: d'une image carrée. Liste DÉCLARÉE, à étendre au premier dépôt qui en porte une autre.
RESOLUTION_KEYS = ('image_size',)


def root_config_values(hf_id, keys, lister=repo_files, loader=None) -> dict:
    """`{fichier: {clé: valeur}}` des clés `keys` trouvées dans les .json à la RACINE du dépôt."""
    import json as _json

    def _load(name):
        from huggingface_hub import hf_hub_download
        with open(hf_hub_download(hf_id, name), encoding='utf-8') as f:
            return _json.load(f)

    out = {}
    for name in lister(hf_id):
        if '/' in name or not name.endswith('.json'):
            continue
        try:
            data = (loader or _load)(name)
        except Exception:
            continue
        found = {k: data[k] for k in keys if isinstance(data, dict) and k in data}
        if found:
            out[name] = found
    return out


def enforce_resolution_facts(manifest, hf_id, concerns, lister=repo_files, loader=None):
    """Pose `capabilities.native_resolution` quand un fichier de config du dépôt la DIT.

    Vécu le 2026-09-30 : Supra2-IMG génère en 256×256 FIXE — `pipeline_config.json` le dit —,
    mais aucun manifeste ne le portait, et l'imager lui proposait 896×512 (taille ignorée par le
    backend, image de 256 px). Le fait mécanique prime sur le jugement du LLM, comme le moteur :
    une valeur absente est posée, une valeur contraire est CORRIGÉE — et c'est dit. Le caractère
    FIXE (`min_resolution` = `max_resolution`) reste à déclarer : un `image_size` dit la taille
    de travail, pas qu'aucune autre n'est possible."""
    values = root_config_values(hf_id, RESOLUTION_KEYS, lister=lister, loader=loader)
    sizes = {int(v) for found in values.values() for v in found.values()
             if isinstance(v, int) and not isinstance(v, bool) and v > 0}
    if len(sizes) != 1:
        if len(sizes) > 1:
            concerns.append(f"tailles contradictoires dans les configs du dépôt : {values}")
        return manifest
    n = sizes.pop()
    fact = f'{n}x{n}'
    body = manifest.setdefault('body', {})
    caps = body.setdefault('capabilities', {})
    declared = str(caps.get('native_resolution') or '').lower()
    if declared == fact:
        return manifest
    caps['native_resolution'] = fact
    source = ', '.join(sorted(values))
    concerns.append(f"native_resolution {'CORRIGÉE ' + repr(declared) + ' → ' if declared else 'POSÉE à '}"
                    f"{fact!r} (fait mécanique : {source})")
    return manifest


def consigne_role(nom):
    """Consigne système d'un RÔLE de wama-dev-ai (`prompts/<nom>.txt`) — accesseur UNIQUE.

    Il y avait QUATRE chemins vers ce dossier avant le 2026-09-09 : `cli.py::_load_prompt`,
    `run_audit.py` (via `config.PROMPTS_DIR`), un chemin ÉCRIT EN DUR dans `run_codegen.py`,
    et cette constante `PROMPTS` — jamais lue, donc morte. Quatre lectures d'un même dossier,
    c'est quatre endroits où une convention de nommage peut diverger sans que rien ne plante.

    `nom` s'écrit SANS extension (`'audit'`, `'codegen'`). Lève si le fichier manque : une
    consigne absente donnerait un rôle sans posture, ce qui rend une sortie plausible et
    fausse — exactement ce que la validation humaine doit attraper, mais trop tard.
    """
    chemin = PROMPTS / f"{nom}.txt"
    if not chemin.is_file():
        connues = sorted(p.stem for p in PROMPTS.glob('*.txt'))
        raise FileNotFoundError(f"consigne de rôle introuvable : {chemin} (connues : {connues})")
    return chemin.read_text(encoding='utf-8')


def skill_wama(app=None, domain=None, kind='generative'):
    """Skill de prompt WAMA le plus spécifique pour (app, domain, kind) → `(nom, texte)`.

    LE PONT, enfin construit (2026-09-09). Il était ANNONCÉ depuis le 2026-07-08 par trois
    fichiers — `config.py::PROMPT_SKILLS_DIR`, ce README, et la docstring de `prompt_skills.py`
    (« réutilisable depuis TOUTES les sources d'appel : … wama-dev-ai ») — et il n'existait
    dans AUCUN. Les trois descendaient de la MÊME phrase de décision, recopiée : ce n'étaient
    pas trois vérifications, c'était une intention comptée comme faite parce que le chemin
    avait été déclaré. La constante est retirée en même temps que ce pont est posé : un chemin
    déclaré sans lecteur est précisément ce qui a fait croire au pont pendant 14 mois.

    Import PARESSEUX et SANS REPLI, comme `ollama_host()` — mêmes raisons, même précédent.
    ⚠ Aucun `django.setup()` n'est requis : `prompt_skills` n'importe que `pathlib`/`re`/
    `logging`. VÉRIFIÉ empiriquement le 2026-09-09, `DJANGO_SETTINGS_MODULE` non défini —
    la promesse « importable sans Django » de sa docstring tient réellement, elle. Comme pour
    l'audit, aucun `INSTALLED_APPS` n'est chargé : un import cassé dans une app ne peut pas
    empêcher un rôle de tourner.

    ⚠ CE QUE ÇA N'EST PAS : les skills de `prompt_skills/` traitent le prompt d'un
    UTILISATEUR pour un modèle qui ne sait pas choisir (diffusion, SAM3, TTS) — ils sont
    résolus PAR LE CODE. Les consignes de DÉVELOPPEMENT sont d'une autre famille et d'un autre
    format (`.claude/skills/`, `SKILL.md` à frontmatter, choisi par l'agent) : ne pas les
    confondre, `WAMA_LLM §0bis 🔒` trace la frontière.
    """
    from wama.common.utils.prompt_skills import resolve_skill
    return resolve_skill(app=app, domain=domain, kind=kind)


def catalogue_skills():
    """`{nom: texte}` de tous les skills de prompt WAMA — pour un rôle qui explore le corpus."""
    from wama.common.utils.prompt_skills import skills_catalog
    return skills_catalog()


def fetch(url, user_agent='wama-dev-ai'):
    """GET texte via le proxy d'environnement (GitHub/HF passent par le proxy UGE)."""
    req = urllib.request.Request(url, headers={'User-Agent': user_agent})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'replace')


def call_ollama(model, system, user_msg, num_ctx=16384, keep_alive=None,
                temperature=0.1, timeout=600):
    """Appel Ollama one-shot. `keep_alive='0'` décharge le modèle SITÔT la réponse rendue
    (au lieu des ~5 min de résidence par défaut) — c'est la parade du mode dépannage GPU,
    à passer depuis `resource_governor.pipeline_keep_alive()`. None = défaut Ollama.

    ⚠ `temperature` et `timeout` sont PARAMÈTRES depuis le 2026-09-07, et les défauts ici
    sont EXACTEMENT ceux d'avant (0.1 / 600 s) : les quatre rôles qui appellent sans les
    citer sont donc inchangés au bit près. Ils existent parce que `run_codegen` portait un
    DOUBLON de cette fonction avec trois valeurs différentes (0.2 / 32768 / 900 s) —
    remplacer sans les offrir aurait TRONQUÉ sa matière (jusqu'à 60 000 caractères servis,
    illisibles à num_ctx=16384) et raccourci son délai. *Avant de supprimer un doublon, on
    compare ; s'il diverge, on FUSIONNE — sinon la déduplication perd une capacité.*
    """
    payload = {
        'model': model,
        'messages': [{'role': 'system', 'content': system},
                     {'role': 'user', 'content': user_msg}],
        'stream': False,
        'options': {'temperature': temperature, 'num_ctx': num_ctx},
    }
    if keep_alive is not None:
        payload['keep_alive'] = keep_alive
    req = urllib.request.Request(
        f'{ollama_host()}/api/chat', data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    with _OPENER_DIRECT.open(req, timeout=timeout) as r:
        return json.loads(r.read())['message']['content']


#: Variable d'environnement qui choisit le fournisseur de TOUS les rôles quand la ligne de
#: commande n'en impose aucun. Absente = `ollama`, le comportement d'avant à l'octet.
PROVIDER_ENV = 'WAMA_DEV_AI_PROVIDER'


def add_llm_arguments(parser, role='dev'):
    """Options `--provider` et `--model` des rôles — UNE définition pour les cinq pilotes.

    Posée le 2026-09-15 avec Albert API : chaque pilote déclarait à la main son `--model`
    « Modèle Ollama ». Ajouter un fournisseur aurait voulu dire l'ajouter cinq fois.
    """
    parser.add_argument(
        '--provider', default=os.environ.get(PROVIDER_ENV) or 'ollama',
        help=f"ollama (local) ou un fournisseur de llm_chat : albert, anthropic… "
             f"(défaut : ${PROVIDER_ENV}, sinon ollama)")
    parser.add_argument(
        '--model', default=None,
        help=f"Modèle (défaut : chaîne du rôle {role} en local, modèle par défaut du "
             f"fournisseur sinon)")


def resolve_model(provider, role, model=None):
    """Modèle effectif d'un rôle.

    Local : chaîne de repli RAM-aware de `config.py`. Distant : modèle par défaut du
    fournisseur (`llm_utils.default_cloud_model`) — la VRAM de l'hôte ne dit rien d'un modèle
    qui tourne ailleurs. Résolu ICI plutôt que laissé à `llm_chat` pour que le rapport de
    sortie nomme le modèle réellement employé.
    """
    if model:
        return model
    if provider == 'ollama':
        # BRIDAGE « niveau développement » (Fabien, 2026-09-22 — global à wama-dev-ai) : le
        # tirage passe par le domicile commun `development_models` (plancher sur le score coding
        # du banc, curseur 100, jamais de repli sur un petit modèle). La chaîne de `config.py`
        # finissait sur `fast`/`ultra_fast` dès que la VRAM manquait : c'est exactement le
        # modèle qui invente des imports. Sans catalogue (première installation), la chaîne
        # historique reste le dernier recours — et le dit.
        try:
            from wama.common.services.development_models import (
                development_model, development_refusal)
            key = development_model(None)
        except Exception as e:      # catalogue injoignable : pas une raison de bloquer un rôle
            print(f"[role_utils] catalogue indisponible ({e}) — chaîne de repli de config.py")
            from config import select_model_for_role
            return select_model_for_role(role)[1].ollama_id
        if not key:
            raise RuntimeError(development_refusal(None))
        return key.split(':', 1)[1]
    from wama.common.utils.llm_utils import default_cloud_model
    return default_cloud_model(provider)


def call_llm(provider, model, system, user_msg, num_ctx=16384, keep_alive=None,
             temperature=0.1, timeout=600):
    """Appel one-shot d'un rôle, quel que soit le fournisseur.

    `ollama` → `call_ollama` inchangé (keep_alive et num_ctx compris). Tout autre fournisseur
    → `llm_chat`, la passerelle LiteLLM commune à l'assistant : un seul endroit sait router
    vers Albert. `num_ctx` et `keep_alive` n'y ont pas de sens (fenêtre et résidence sont
    gérées par le fournisseur) ; `num_predict=None` ne plafonne pas la réponse, comme Ollama.

    Lève `RuntimeError` en cas d'échec, comme `call_ollama` lève sur une erreur HTTP : les
    pilotes n'ont pas à distinguer les deux chemins.
    """
    if provider == 'ollama':
        return call_ollama(model, system, user_msg, num_ctx=num_ctx, keep_alive=keep_alive,
                           temperature=temperature, timeout=timeout)
    from wama.common.utils.llm_utils import llm_chat
    text, error = llm_chat(
        [{'role': 'system', 'content': system}, {'role': 'user', 'content': user_msg}],
        model=model or None, provider=provider, num_predict=None,
        temperature=temperature, timeout=timeout)
    if text is None:
        raise RuntimeError(f'{provider} : {error}')
    return text


def extract_json(text):
    """Premier objet JSON équilibré du texte (les modèles emballent parfois en ```json)."""
    text = re.sub(r'^```(?:json)?|```$', '', text.strip(), flags=re.M)
    start = text.find('{')
    if start < 0:
        raise ValueError('aucun JSON dans la réponse')
    depth = 0
    for i, c in enumerate(text[start:], start):
        depth += (c == '{') - (c == '}')
        if depth == 0:
            return json.loads(text[start:i + 1])
    raise ValueError('JSON non équilibré')


def write_output(role, slug, payload):
    """Rapport horodaté dans outputs/ — TOUJOURS PENDING_HUMAN_VALIDATION."""
    from datetime import datetime
    OUTPUTS.mkdir(exist_ok=True)
    horodatage = datetime.now().strftime('%Y-%m-%d_%H-%M')
    sortie = OUTPUTS / f"{role}_{slug.replace('/', '_')}_{horodatage}.json"
    sortie.write_text(json.dumps({'status': 'PENDING_HUMAN_VALIDATION', 'role': role,
                                  **payload}, ensure_ascii=False, indent=2), encoding='utf-8')
    return sortie


def manifest_examples(dossier, *, prefer_source='', want_composed=None, limit=2) -> str:
    """
    Exemples du corpus choisis PAR NATURE — le few-shot d'un rôle, pas le premier fichier venu.

    Pourquoi (2026-09-19) : `run_scout.py` prenait `sorted(glob)[:1]`, c'est-à-dire le premier
    par ORDRE ALPHABÉTIQUE — `albert__bge-m3.json`, un modèle CLOUD servi par une API, comme
    unique exemple pour traduire un dépôt HuggingFace LOCAL. Un exemple hors nature enseigne
    la mauvaise forme : il n'a ni poids, ni composition, ni moteur. `run_model_manifest.py`
    faisait déjà le choix par nature (un COMPOSÉ + un simple) : ce corps est le sien, déplacé
    ici pour que les deux rôles le partagent au lieu de le dupliquer.

    `prefer_source` : préfixe de nom de fichier privilégié (`huggingface__`, `ollama__`…) — le
    corpus assainit `:` en `__`, donc la source d'une clé est son préfixe.
    `want_composed` : True = privilégier ceux qui déclarent `composition.runtime`, False =
    l'éviter, None = prendre un de chaque (le défaut, qui montre les deux formes).
    """
    fichiers = sorted(Path(dossier).glob('*.json'))
    if prefer_source:
        meme_nature = [f for f in fichiers if f.name.startswith(prefer_source)]
        fichiers = meme_nature + [f for f in fichiers if f not in meme_nature]

    composes, simples = [], []
    for f in fichiers:
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        cible = composes if ((d.get('body') or {}).get('composition') or {}).get('runtime') else simples
        cible.append(f)

    if want_composed is True:
        choisis = (composes + simples)[:limit]
    elif want_composed is False:
        choisis = (simples + composes)[:limit]
    else:                      # un de chaque forme, dans l'ordre de préférence de nature
        choisis = [x for x in (composes[:1] + simples[:1]) if x][:limit]
    return '\n\n'.join(f.read_text(encoding='utf-8') for f in choisis)
