"""
Divergence inter-systèmes — un signal de qualité qui est un FAIT, pas un avis.

LE PRINCIPE. Deux systèmes indépendants ne se trompent pas de la même façon, mais ils entendent
(ou voient) la même chose. Donc :
  • **divergence**  ⇒ forte probabilité d'erreur réelle → c'est là qu'il faut envoyer l'humain ;
  • **convergence**, même sur une sortie qui « semble » mauvaise ⇒ c'est probablement juste.

POURQUOI CE SIGNAL PLUTÔT QU'UN JUGE. Décidé dans `TRANSCRIBER_CORRECTION.md` §8.3, sur un
constat ancré dans le code : `analyze_segments_coherence` ne reçoit **que du texte, jamais
l'audio**. Elle ne peut donc pas, même en principe, distinguer « l'ASR a halluciné » de « la
personne a réellement dit ça maladroitement ». Elle mesure la FLUIDITÉ et s'en sert comme proxy
de la FIDÉLITÉ — or les deux sont **anticorrélées** sur de l'entretien : plus le texte est
fidèle, plus il paraît incohérent. Le défaut est STRUCTUREL ; reformuler le prompt le déplace.

Enjeu SHS : sur un entretien de recherche, hésitations, autocorrections et répétitions **sont des
données**. Un LLM qui les lisse en silence est un problème d'intégrité méthodologique.

La divergence, elle, est **objective et ancrée sur la source** sans réécoute, et ne demande aucun
avis de modèle. C'est ce qui la place AVANT la confiance et TRÈS avant la cohérence dans l'ordre
de priorité (§8.3), et ce qui en fait la deuxième marche de la boucle qualité (ROADMAP §16.7),
après les faits de `run_outcome` et avant tout juge automatique.

CE QUE CE MODULE FAIT — et ne fait pas.
  • Il compare deux sorties du MÊME travail et rend un désaccord chiffré, par zone et global.
  • Il ne dit JAMAIS laquelle a raison. Deux systèmes peuvent diverger parce que l'un se trompe,
    ou parce que le passage est objectivement difficile. C'est un signal d'ATTENTION, pas un
    verdict — même précaution que `run_outcome`, qui enregistre un fait sans le juger.

PROCHAIN CONSOMMATEUR ATTENDU : la vision (anonymizer, cam_analyzer) — deux détecteurs sur la
même image, désaccord par IoU. Non implémenté ici : on ne construit pas un mécanisme pour un
besoin qu'on n'a pas encore mesuré.
"""
from __future__ import annotations

import difflib
import logging
import re

logger = logging.getLogger(__name__)

#: En dessous de ce recouvrement temporel, deux segments ne parlent pas du même moment.
RECOUVREMENT_MINIMAL = 0.30

#: Seuils de lecture du désaccord. Bornes INDICATIVES, à recalibrer sur le jeu de test à
#: 4 fichiers (§8.5) — elles ne sont pas des vérités, elles servent à colorer une bande.
SEUILS = ((0.15, 'accord'), (0.40, 'attention'), (1.01, 'divergence'))


def _mots(texte: str) -> list:
    """
    Tokens comparables : minuscules, sans ponctuation, **apostrophe traitée en séparateur**.

    La ponctuation est une DÉCISION de transcription, pas un désaccord d'écoute — la compter
    ferait diverger deux systèmes qui ont entendu la même chose.

    ⚠ L'apostrophe mérite sa propre règle, et la première version s'y est trompée : en gardant
    `aujourd'hui` comme UN token, « aujourd'hui » vs « aujourd hui » sortait à 33 % de divergence
    alors que les deux systèmes ont entendu la même chose (mesuré à l'écriture des tests). On la
    coupe donc : les deux graphies rendent `['aujourd', 'hui']`. Même effet sur « m'appelle » vs
    « m appelle », et sur les élisions que les ASR écrivent différemment (« l'on » / « l on »).
    """
    return re.findall(r'\w+', re.sub(r"['’]", ' ', (texte or '').lower()))


def divergence_texte(a: str, b: str) -> float:
    """
    Désaccord entre deux transcriptions d'un même passage : 0.0 = identiques, 1.0 = tout diffère.

    Mesuré sur les MOTS et non les caractères : « m'appelle » vs « m appelle » est une différence
    de tokenisation, pas d'écoute, et une distance caractère la surévaluerait.
    """
    ma, mb = _mots(a), _mots(b)
    if not ma and not mb:
        return 0.0
    if not ma or not mb:
        return 1.0
    commun = sum(bloc.size for bloc in difflib.SequenceMatcher(None, ma, mb).get_matching_blocks())
    return round(1.0 - (2.0 * commun) / (len(ma) + len(mb)), 4)


def _recouvrement(s1, s2) -> float:
    """Part de recouvrement temporel de deux segments, rapportée au plus court (0..1)."""
    d1, f1 = float(s1.get('start_time') or 0), float(s1.get('end_time') or 0)
    d2, f2 = float(s2.get('start_time') or 0), float(s2.get('end_time') or 0)
    inter = min(f1, f2) - max(d1, d2)
    if inter <= 0:
        return 0.0
    plus_court = min(f1 - d1, f2 - d2)
    return inter / plus_court if plus_court > 0 else 0.0


def divergence_segments(reference, comparaison) -> dict:
    """
    Compare deux découpages en segments du même média et rend le désaccord PAR SEGMENT.

    L'appariement se fait sur le TEMPS, pas sur l'ordre : deux ASR ne segmentent pas pareil, et
    apparier le i-ᵉ avec le i-ᵉ produirait un désaccord artificiel dès le premier décalage. Un
    segment de la référence peut donc recouvrir plusieurs segments de la comparaison — on
    concatène alors ces derniers avant de comparer.

    Retourne :
        {'segments': [{'index', 'start_time', 'end_time', 'divergence', 'niveau',
                       'texte_reference', 'texte_comparaison'}],
         'divergence_globale': 0..1,      # pondérée par la durée : un long passage compte plus
         'segments_sans_vis_a_vis': int,  # rien en face — souvent un silence ou une coupure
         'couverture': 0..1}              # part de la référence réellement comparée
    """
    reference = [s for s in (reference or []) if isinstance(s, dict)]
    comparaison = [s for s in (comparaison or []) if isinstance(s, dict)]
    if not reference or not comparaison:
        return {'segments': [], 'divergence_globale': None, 'granularite': None,
                'segments_sans_vis_a_vis': len(reference), 'couverture': 0.0}

    # ⚠ GRANULARITÉ — le côté le plus FIN doit être la comparaison, jamais la référence.
    # Sinon chaque segment fin est confronté au gros segment qui le contient, dont le texte
    # est bien plus long : on mesure alors un écart de DÉCOUPAGE et on l'annonce comme un
    # désaccord d'écoute. Constaté sur le Transcript #172 — 748 segments ASR contre 106
    # segments regroupés à la main : 72 % de « divergence » pour un texte identique.
    # On échange donc les rôles au besoin, et on le DIT dans le résultat.
    granularite = round(len(reference) / len(comparaison), 2)
    echange = len(reference) > 2 * len(comparaison)
    if echange:
        reference, comparaison = comparaison, reference

    lignes, orphelins = [], 0
    duree_totale, somme_ponderee = 0.0, 0.0

    for i, seg in enumerate(reference):
        en_face = [c for c in comparaison if _recouvrement(seg, c) >= RECOUVREMENT_MINIMAL]
        duree = max(0.0, float(seg.get('end_time') or 0) - float(seg.get('start_time') or 0))

        if not en_face:
            orphelins += 1
            # ⚠ COMPTÉ COMME DIVERGENCE TOTALE dans la moyenne. La première version les
            # excluait, et le chiffre global mentait : un système qui raterait la moitié de
            # l'audio aurait affiché une divergence BASSE, puisque seuls les passages qu'il
            # avait entendus étaient comparés. Un passage sans vis-à-vis est le désaccord
            # maximal — l'un l'a entendu, l'autre pas.
            duree_totale += duree
            somme_ponderee += 1.0 * duree
            lignes.append({
                'index': i,
                'start_time': seg.get('start_time'), 'end_time': seg.get('end_time'),
                'divergence': None, 'niveau': 'sans_vis_a_vis',
                'texte_reference': seg.get('text') or '', 'texte_comparaison': '',
            })
            continue

        texte_b = ' '.join((c.get('text') or '').strip() for c in en_face).strip()
        d = divergence_texte(seg.get('text') or '', texte_b)
        niveau = next(nom for borne, nom in SEUILS if d < borne)

        duree_totale += duree
        somme_ponderee += d * duree
        lignes.append({
            'index': i,
            'start_time': seg.get('start_time'), 'end_time': seg.get('end_time'),
            'divergence': d, 'niveau': niveau,
            'texte_reference': seg.get('text') or '', 'texte_comparaison': texte_b,
        })

    compares = len(reference) - orphelins
    return {
        'segments': lignes,
        #: reference/comparaison en nombre de segments. Loin de 1 = les deux systèmes ne
        #: découpent pas pareil ; `reference_echangee` dit qu'on a inversé les rôles pour que
        #: la mesure reste un désaccord de CONTENU et non de découpage.
        'granularite': granularite,
        'reference_echangee': echange,
        # Pondérée par la DURÉE et non par le nombre de segments : un désaccord sur trente
        # secondes de parole ne pèse pas comme un désaccord sur un « oui » d'une demi-seconde.
        'divergence_globale': round(somme_ponderee / duree_totale, 4) if duree_totale else None,
        'segments_sans_vis_a_vis': orphelins,
        'couverture': round(compares / len(reference), 4) if reference else 0.0,
    }


def zones_a_verifier(resultat: dict, niveau_minimal: str = 'attention') -> list:
    """
    Les segments à montrer à l'humain en priorité — c'est l'usage final du signal.

    `sans_vis_a_vis` est TOUJOURS retenu : un passage qu'un seul système a entendu est au moins
    aussi suspect qu'un passage sur lequel les deux se contredisent.
    """
    ordre = {'accord': 0, 'attention': 1, 'divergence': 2, 'sans_vis_a_vis': 3}
    seuil = ordre.get(niveau_minimal, 1)
    retenus = [s for s in (resultat.get('segments') or [])
               if ordre.get(s.get('niveau'), 0) >= seuil]
    return sorted(retenus, key=lambda s: (-(s.get('divergence') or 1.0),
                                          s.get('start_time') or 0))
