"""
Capture des signaux d'exécution — la brique `RunOutcome` de la ROADMAP §16.7.

CE QU'ELLE FAIT : record, en une ligne d'appel, un FAIT observé sur un résultat produit.
CE QU'ELLE NE FAIT PAS : juger. Aucune note n'entre ici (cf. le docstring de `RunOutcome`).

RÈGLE D'INTÉGRATION — best-effort ABSOLU. Un signal manqué est un signal manqué ; une exception
levée ici casserait un téléchargement, une suppression ou une tâche qui, eux, ont réussi.
Toute fonction d'écriture avale donc ses erreurs et se contente de les journaliser. C'est la
même précaution que `record_run`/`notify_job` dans le squelette de tâche.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Gestes déjà faits par l'utilisateur, dont on se contente (§16.7 : jamais de geste ajouté).
SIGNAUX = ('produit', 'echec', 'telecharge', 'corrige', 'relance', 'supprime')


def record(app: str, item, signal: str, *, model_keys=None, detail=None, user=None):
    """
    Consigne un signal sur `item`. Retourne la ligne créée, ou None si rien n'a pu être écrit.

    `item` est l'objet Django concerné (Media, Transcription, ImageGeneration…) : on en tire le
    type et la clé primaire, plus le propriétaire à défaut de `user` explicite.
    """
    if signal not in SIGNAUX:
        logger.warning("[run_outcome] signal inconnu %r — ignoré (connus : %s)",
                       signal, ', '.join(SIGNAUX))
        return None
    try:
        from wama.common.models import RunOutcome

        return RunOutcome.objects.create(
            app=app or '',
            object_type=type(item).__name__,
            object_id=getattr(item, 'pk', None) or 0,
            user=user if user is not None else getattr(item, 'user', None),
            signal=signal,
            model_keys=[str(k) for k in (model_keys or []) if k],
            detail=detail or {},
        )
    except Exception as exc:
        # Best-effort : on ne casse jamais l'action de l'utilisateur pour un journal.
        logger.debug("[run_outcome] signal %s non enregistré (%s: %s)",
                     signal, type(exc).__name__, exc)
        return None


def correction_magnitude(avant, apres) -> dict:
    """
    Mesure une correction humaine sans l'interpréter : combien de segments, quelle distance.

    Sert le gisement le plus riche de WAMA — les corrections manuelles du Transcriber sont des
    paires (sortie IA → vérité humaine), c'est-à-dire la SEULE vérité terrain du dépôt. C'est
    aussi ce qui permettra de CALIBRER un juge automatique : un juge qui ne retrouve pas le
    verdict humain là où la vérité existe n'a pas à juger là où elle n'existe pas.

    Rend `{}` si la comparaison n'a pas de sens — on préfère ne rien dire qu'estimer à faux.
    """
    def _texts(segments):
        if not isinstance(segments, (list, tuple)):
            return []
        out = []
        for s in segments:
            if isinstance(s, dict):
                out.append(str(s.get('text') or '').strip())
            elif isinstance(s, str):
                out.append(s.strip())
        return out

    t_avant, t_apres = _texts(avant), _texts(apres)
    if not t_avant or not t_apres:
        return {}

    modifies = sum(1 for a, b in zip(t_avant, t_apres) if a != b)
    modifies += abs(len(t_avant) - len(t_apres))     # segments ajoutés ou retirés

    car_avant = sum(len(t) for t in t_avant)
    car_apres = sum(len(t) for t in t_apres)

    import difflib
    similarite = difflib.SequenceMatcher(None, ' '.join(t_avant), ' '.join(t_apres)).ratio()

    return {
        'segments_avant': len(t_avant),
        'segments_apres': len(t_apres),
        'segments_modifies': modifies,
        # Rapportée au plus GRAND des deux découpages, et bornée à 1. La première version
        # divisait par le nombre de segments AVANT : sur le Transcript #48 (5 segments ASR
        # cassés, réécrits en 2 395 à la main) elle rendait `479.0`, ce qui n'est pas une part.
        'part_modifiee': round(min(1.0, modifies / max(len(t_avant), len(t_apres), 1)), 3),
        'caracteres_avant': car_avant,
        'caracteres_apres': car_apres,
        # 1.0 = texte identique. C'est une DISTANCE, pas une note de qualité : une transcription
        # très corrigée peut l'avoir été pour du style, pas pour des erreurs.
        'similarite': round(similarite, 4),
    }


def is_real_correction(mesure: dict) -> bool:
    """
    La correction a-t-elle CHANGÉ quelque chose ? Garde-fou du signal `corrige`.

    ⚠ Pourquoi c'est indispensable : `corrected_segments_json` est écrit par l'auto-save de
    l'éditeur **même quand l'utilisateur n'a rien modifié**. Sur les 6 transcripts corrigés du
    dépôt, **trois** (#46, #134, #142) portent un texte strictement identique à la sortie ASR
    (mesuré le 2026-08-13). Enregistrer `corrige` pour ceux-là polluerait le gisement le plus
    précieux de WAMA avec des non-événements, et ferait croire à une correction humaine là où
    l'utilisateur n'a fait qu'ouvrir l'éditeur.
    """
    if not mesure:
        return False
    return bool(mesure.get('segments_modifies')) or (mesure.get('similarite') or 1.0) < 1.0


# ── Lecture (agrégation) ──────────────────────────────────────────────────────────────────
# Volontairement SÉPARÉE de l'écriture, et volontairement pauvre pour l'instant : on capte
# d'abord, on interprète ensuite. « métrique d'abord, boucle ensuite, autonomie en dernier »
# (§16.7-4) — un agent qui réécrit ses réglages sans métrique mesurée dérive au lieu de
# s'améliorer.

def count_signals(app: str = '', depuis=None) -> dict:
    """Répartition brute des signaux, éventuellement filtrée. Sans interprétation."""
    from django.db.models import Count

    from wama.common.models import RunOutcome

    qs = RunOutcome.objects.all()
    if app:
        qs = qs.filter(app=app)
    if depuis is not None:
        qs = qs.filter(occurred_at__gte=depuis)
    return {r['signal']: r['n']
            for r in qs.values('signal').annotate(n=Count('id')).order_by('-n')}


def by_model(signal: str = '', app: str = '', modele_unique: bool = True) -> dict:
    """
    `{model_key: {signal: n}}` — de quoi ORDONNER des modèles quand le volume le permettra.

    `modele_unique=True` (défaut) n'agrège que les exécutions à UN SEUL modèle : sur une
    exécution multi-modèles, un signal ne dit pas lequel a démérité, et répartir le crédit à
    parts égales inventerait une information. On préfère un échantillon plus petit et honnête.
    """
    from collections import defaultdict

    from wama.common.models import RunOutcome

    qs = RunOutcome.objects.exclude(model_keys=[])
    if app:
        qs = qs.filter(app=app)
    if signal:
        qs = qs.filter(signal=signal)

    resultat = defaultdict(lambda: defaultdict(int))
    for cles, sig in qs.values_list('model_keys', 'signal'):
        if modele_unique and len(cles or []) != 1:
            continue
        for cle in (cles or []):
            resultat[cle][sig] += 1
    return {k: dict(v) for k, v in resultat.items()}
