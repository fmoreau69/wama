"""
Détecteur DÉTERMINISTE de mises à jour de modèles — sans LLM, sans scraping de registre.

Deux signaux, via les API OFFICIELLES uniquement :
  • Ollama : API LOCALE `/api/tags` → date d'installation (`modified_at`) → heuristique d'âge
             (`review_candidate`). La vraie comparaison de version distante est DÉLÉGUÉE à la
             couche prospection (agents), pas à du scraping du registre Ollama.
  • HF     : `huggingface_hub.HfApi().model_info(hf_id).last_modified` comparé au mtime local
             → `update_available` si l'amont est plus récent que les fichiers téléchargés.

Produit un rapport. Persiste optionnellement les drapeaux dans `AIModel.extra_info['update_check']`
(clé « collante » préservée par `model_sync`). Toute MAJ reste soumise à acceptation admin.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_ISO_RE = re.compile(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})')


def _parse_dt(s):
    """Parse tolérante d'un préfixe ISO (ignore fraction/timezone) → datetime UTC, ou None."""
    if not s:
        return None
    m = _ISO_RE.search(str(s))
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _ollama_tags(timeout=5):
    """API LOCALE Ollama `/api/tags` → {name: modified_at}. Best-effort, local uniquement."""
    from django.conf import settings
    import requests
    base = getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')
    r = requests.get(f"{base}/api/tags", timeout=timeout)
    r.raise_for_status()
    return {m['name']: m.get('modified_at', '') for m in r.json().get('models', [])}


def _local_mtime(path):
    """mtime le plus récent sous un fichier/dossier → datetime UTC, ou None."""
    if not path or not os.path.exists(path):
        return None
    newest = 0.0
    if os.path.isfile(path):
        newest = os.path.getmtime(path)
    else:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(root, f)))
                except OSError:
                    pass
    if newest <= 0:
        return None
    return datetime.fromtimestamp(newest, tz=timezone.utc)


def check_updates(age_days_threshold=120, hf_grace_days=7, do_hf=True):
    """
    Calcule les signaux de MAJ pour les modèles du catalogue. Retourne un rapport (dict).
    Ne persiste RIEN (utiliser `apply_flags`).
    """
    from wama.model_manager.models import AIModel

    now = datetime.now(timezone.utc)
    results = []

    # ── Ollama : âge d'installation (API locale, déterministe) ──
    tags = {}
    try:
        tags = _ollama_tags()
    except Exception as e:
        logger.info(f"[update_checker] Ollama /api/tags indisponible: {e}")

    for m in AIModel.objects.filter(source='ollama').exclude(is_proposed=True):
        # model_key = "ollama:<name>" ; le name (avec tag) est après le 1er ':'
        name = m.model_key.split(':', 1)[1] if ':' in m.model_key else m.name
        installed = _parse_dt(tags.get(name))
        age_days = (now - installed).days if installed else None
        review = age_days is not None and age_days > age_days_threshold
        results.append({
            'model_key': m.model_key,
            'source': 'ollama',
            'installed_at': installed.isoformat() if installed else None,
            'age_days': age_days,
            'review_candidate': review,
            'update_available': None,
            'reason': (
                f"installé il y a {age_days} j (> {age_days_threshold})" if review
                else ("absent de /api/tags" if installed is None else f"récent ({age_days} j)")
            ),
        })

    # ── HF : last_modified amont vs mtime local (API officielle) ──
    if do_hf:
        api = None
        try:
            from huggingface_hub import HfApi
            api = HfApi()
        except Exception as e:
            logger.info(f"[update_checker] huggingface_hub indisponible: {e}")
        if api is not None:
            qs = AIModel.objects.exclude(source='ollama').filter(is_downloaded=True).exclude(hf_id='')
            for m in qs:
                local_dt = _local_mtime(m.local_path)
                remote_dt = None
                try:
                    info = api.model_info(m.hf_id, timeout=8)
                    remote_dt = getattr(info, 'last_modified', None)
                    if remote_dt and remote_dt.tzinfo is None:
                        remote_dt = remote_dt.replace(tzinfo=timezone.utc)
                except Exception as e:
                    logger.debug(f"[update_checker] HF model_info {m.hf_id}: {e}")
                upd, reason = None, ''
                if remote_dt and local_dt:
                    delta = (remote_dt - local_dt).days
                    upd = delta > hf_grace_days
                    reason = f"amont +{delta} j vs local" if upd else "local à jour"
                elif remote_dt and not local_dt:
                    reason = "mtime local inconnu"
                else:
                    reason = "amont inaccessible"
                results.append({
                    'model_key': m.model_key,
                    'source': m.source,
                    'hf_id': m.hf_id,
                    'local_mtime': local_dt.isoformat() if local_dt else None,
                    'remote_last_modified': remote_dt.isoformat() if remote_dt else None,
                    'update_available': upd,
                    'review_candidate': None,
                    'reason': reason,
                })

    return {
        'checked_at': now.isoformat(),
        'total': len(results),
        'ollama_review': [r for r in results if r.get('review_candidate')],
        'hf_updates': [r for r in results if r.get('update_available')],
        'results': results,
    }


def apply_flags(report):
    """Persiste les drapeaux dans `AIModel.extra_info['update_check']` (clé préservée par model_sync)."""
    from wama.model_manager.models import AIModel
    n = 0
    for r in report.get('results', []):
        obj = AIModel.objects.filter(model_key=r['model_key']).first()
        if not obj:
            continue
        info = dict(obj.extra_info or {})
        info['update_check'] = {
            'checked_at': report['checked_at'],
            'update_available': r.get('update_available'),
            'review_candidate': r.get('review_candidate'),
            'reason': r.get('reason', ''),
        }
        obj.extra_info = info
        obj.save(update_fields=['extra_info'])
        n += 1
    return n
