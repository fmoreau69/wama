"""
Bascule SCOPÉE du cache HuggingFace — LA brique anti-fuite (extraite le 2026-08-12).

Deux implémentations locales du même geste coexistaient (règle des 2 occurrences) :
  - `wama/views.py::_get_kokoro` — save/restore de l'env seul ;
  - `wama/anonymizer/core/sam3_processor.py` — env + constantes (version corrigée du jour,
    après la fuite inter-apps : la mutation PERMANENTE routait les artefacts HF — refs/
    locks/xet — des backends suivants du même worker vers vision/sam/, squelette olmOCR
    vide constaté).
Les deux ont été portées ici.

QUAND l'utiliser : uniquement pour une lib qui N'ACCEPTE PAS de `cache_dir=` et lit
l'env/les constantes au chargement (kokoro, sam3). Les backends qui passent `cache_dir=`
à `from_pretrained()` gardent le pattern CLAUDE.md (env posé avant import + cache_dir
explicite) — et `settings.py` pose déjà le défaut global UNE fois au démarrage
(`HF_DEFAULT_CACHE`). La cible long-terme reste ROADMAP §5b : `cache_dir=` partout, zéro
mutation d'env par modèle — cette brique est le pont sûr, JAMAIS un permis de muter.

Pourquoi les CONSTANTES en plus de l'env : huggingface_hub fige ces valeurs à l'import
dans `huggingface_hub.constants` — dans un process où le hub est déjà importé (Django,
worker Celery), muter l'env seul ne suffit pas, et muter les constantes sans les
restaurer contamine tous les chargements suivants du process.
"""
import os
from contextlib import contextmanager

_CLES = ('HF_HOME', 'HF_HUB_CACHE', 'HUGGINGFACE_HUB_CACHE')


@contextmanager
def hf_cache_scope(cache_dir):
    """Pose env + constantes huggingface_hub sur `cache_dir` LE TEMPS du bloc, puis
    restaure TOUT (try/finally) — y compris l'absence (clé non posée avant = retirée)."""
    cache_str = str(cache_dir)
    prev_env = {k: os.environ.get(k) for k in _CLES}
    try:
        import huggingface_hub.constants as hf_constants
    except ImportError:
        hf_constants = None
    prev_const = {k: getattr(hf_constants, k, None) for k in _CLES} if hf_constants else {}
    for k in _CLES:
        os.environ[k] = cache_str
        if hf_constants is not None:
            setattr(hf_constants, k, cache_str)
    try:
        yield
    finally:
        for k in _CLES:
            if prev_env[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev_env[k]
            if hf_constants is not None:
                setattr(hf_constants, k, prev_const[k])
