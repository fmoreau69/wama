"""
Les DESCRIPTIONS du catalogue, comblées depuis les sources externes (2026-10-29, demande de
Fabien : « à l'installation des modèles on a pas forcément les descriptions courtes et longues »,
puis « l'exploration de sources externes (même web) peut permettre de combler les trous de
description à minima »).

Mesuré ce jour sur 666 lignes : 27 descriptions génériques du balayage (« Snapshot HF … »,
« Version GitHub … »), 14 « Ollama LLM (x Go) », ~488 distants réduits à « <fournisseur> — modèle
distant (<type>) ». Trois remèdes, chacun à son domicile :
  • la synchronisation n'écrase plus une vraie description par un texte de remplissage, et marque
    celui qu'elle écrit (`ModelInfo.description_placeholder`, `model_sync._sync_model`) ;
  • le fournisseur qui publie une description la donne (OpenRouter, `cloud_models`) ;
  • ICI, pour les lignes marquées : la FICHE du modèle (README du Hub — le dépôt, ou le modèle
    d'origine d'une quantification), sinon une recherche WEB (`search_engines`), RÉSUMÉE en
    français par le LLM local par défaut — sans rien ajouter à la source (consigne), la source
    tracée sur la ligne (`DESCRIPTION_SOURCE_KEY`, collante à la synchronisation).
Un modèle sans fiche ni résultat garde son remplissage : on ne devine pas.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Ce que la consigne laisse lire d'une fiche — l'essentiel d'une carte tient dans ses premiers
#: paragraphes ; au-delà, des tableaux et du code d'usage qui n'aident pas à décrire.
CARD_CHARS = 8000

#: Longueur maximale de la description COURTE (l'aide sous un sélecteur, une ligne).
SHORT_CHARS = 160

PROMPT = (
    "Tu rédiges la fiche d'un modèle d'IA pour le catalogue d'une plateforme de laboratoire. "
    "À partir UNIQUEMENT du texte source ci-dessous (fiche officielle ou résultats de recherche), "
    "écris en français :\n"
    "- \"short\" : une ligne (au plus {short} caractères) qui dit ce que fait le modèle ;\n"
    "- \"long\" : 2 à 4 phrases : ce qu'il fait, ses entrées et sorties, ses points forts ou "
    "limites que la source énonce (langues, taille, licence si dite).\n"
    "N'invente rien : ce que la source ne dit pas ne s'écrit pas. Si la source ne parle pas de "
    "ce modèle ({name}), rends {{}}. Réponds par un objet JSON seul, sans texte autour.\n\n"
    "SOURCE ({origin}) :\n{text}"
)


def rows_to_describe(keys=None):
    """Les lignes à décrire : celles que `keys` NOMME (le choix de l'opérateur — une description
    fausse ou imprécise se refait ainsi), sinon celles dont la description n'est qu'un remplissage
    marqué, ou vide. Jamais une proposition."""
    from django.db.models import Q

    from ..models import DESCRIPTION_PLACEHOLDER_KEY, AIModel
    qs = AIModel.objects.filter(is_proposed=False)
    if keys:
        qs = qs.filter(model_key__in=list(keys))
    else:
        qs = qs.filter(Q(extra_info__has_key=DESCRIPTION_PLACEHOLDER_KEY)
                       | (Q(description='') & Q(description_short='')))
    return list(qs.order_by('model_key'))


def card_repo(row) -> str:
    """Le dépôt du Hub dont la fiche décrit la ligne : le sien, sinon le modèle d'origine d'une
    quantification (un GGUF est ce modèle), '' sinon."""
    return row.hf_repo or row.quantized_base or ''


def card_text(repo: str) -> str:
    """La fiche (README) d'un dépôt du Hub, sans son en-tête YAML, tronquée — '' si illisible
    (dépôt à accès contrôlé, absent). Lue par l'adresse `raw`, comme le texte d'une licence :
    rien dans le cache."""
    import requests
    try:
        from huggingface_hub import hf_hub_url
        response = requests.get(hf_hub_url(repo, 'README.md'), timeout=(5, 30))
    except Exception:
        return ''
    if response.status_code != 200:
        return ''
    from wama.common.utils.front_matter import split_front_matter
    _header, body = split_front_matter(response.text)
    return (body or '').strip()[:CARD_CHARS]


def web_text(row, user=None) -> tuple[str, list]:
    """`(texte, adresses)` d'une recherche web sur le modèle (`search_engines.engine_for`, le
    moteur que le compte a choisi), '' si aucun moteur n'est utilisable ou rien n'est trouvé."""
    from wama.common.search_engines.base import SearchEngineUnavailable
    from wama.common.search_engines.registry import engine_for
    try:
        hits = engine_for(user).search(f'"{row.name}" AI model', max_results=5)
    except SearchEngineUnavailable as e:
        logger.info("[descriptions] recherche web indisponible : %s", e)
        return '', []
    except Exception as e:
        logger.info("[descriptions] recherche web en échec pour %s : %s", row.model_key, e)
        return '', []
    lines = [f"- {h.title} ({h.url}) : {h.snippet}" for h in hits if h.snippet]
    return '\n'.join(lines)[:CARD_CHARS], [h.url for h in hits]


def summarize(name: str, text: str, origin: str) -> tuple[dict | None, str]:
    """`({'short', 'long'} | None, modèle employé)` — le résumé en français de `text` par le LLM
    local par défaut (`llm_utils.modele_par_defaut`), validé : deux textes non vides, la ligne
    courte bornée. None si le modèle ne rend rien d'exploitable ou dit que la source ne parle pas
    de ce modèle."""
    from wama.common.utils.llm_utils import (STEADY_TEMPERATURE, extract_json_from_llm, llm_chat,
                                             modele_par_defaut)
    model = modele_par_defaut()
    prompt = PROMPT.format(short=SHORT_CHARS, name=name, origin=origin, text=text)
    answer, error = llm_chat([{'role': 'user', 'content': prompt}], model=model, think=False,
                             temperature=STEADY_TEMPERATURE, num_predict=600)
    if error or not answer:
        logger.info("[descriptions] %s : pas de résumé (%s)", name, error or 'réponse vide')
        return None, model
    data = extract_json_from_llm(answer) or {}
    short = ' '.join(str(data.get('short') or '').split())
    long_ = ' '.join(str(data.get('long') or '').split())
    if not short or not long_:
        return None, model
    if len(short) > SHORT_CHARS:
        short = short[:SHORT_CHARS - 1].rstrip() + '…'
    return {'short': short, 'long': long_}, model


def describe(row, *, apply: bool = False, user=None, web: bool = True) -> dict:
    """Comble la description d'UNE ligne : la fiche du Hub d'abord, le web sinon. Rend
    `{key, origin, ref, short, long}` ou `{key, skipped: motif}` ; écrit seulement si `apply`."""
    from django.utils import timezone

    from ..models import DESCRIPTION_PLACEHOLDER_KEY, DESCRIPTION_SOURCE_KEY, AIModel
    repo = card_repo(row)
    text, origin, refs = '', '', []
    if repo:
        from wama.common.external_sources import hf_platform_ref, model_page_url
        text = card_text(repo)
        origin, refs = (('fiche', [model_page_url(hf_platform_ref(repo)) or repo]) if text
                        else ('', []))
    if not text and web:
        text, refs = web_text(row, user=user)
        origin = 'web' if text else ''
    if not text:
        return {'key': row.model_key, 'skipped': 'ni fiche lisible ni résultat web'}
    found, model = summarize(row.name or row.model_key, text, origin)
    if not found:
        return {'key': row.model_key, 'skipped': f'résumé inexploitable ({origin})'}
    result = {'key': row.model_key, 'origin': origin, 'ref': refs[:3], 'model': model, **found}
    if apply:
        info = dict(row.extra_info or {})
        info.pop(DESCRIPTION_PLACEHOLDER_KEY, None)
        info[DESCRIPTION_SOURCE_KEY] = {'origin': origin, 'ref': refs[:3], 'model': model,
                                        'date': timezone.now().date().isoformat()}
        AIModel.objects.filter(pk=row.pk).update(description=found['long'],
                                                 description_short=found['short'],
                                                 extra_info=info)
    return result


def describe_rows(keys=None, *, apply: bool = False, limit: int | None = None, user=None,
                  web: bool = True) -> list:
    """`describe` sur chaque ligne à combler (`rows_to_describe`), au plus `limit`."""
    rows = rows_to_describe(keys)
    if limit:
        rows = rows[:limit]
    return [describe(row, apply=apply, user=user, web=web) for row in rows]
