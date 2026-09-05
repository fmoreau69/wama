"""
Lissage de trajectoire 2D — filtre de Kalman (vitesse constante) + lisseur RTS.

⚠ Depuis le 2026-09-05 ce module DÉLÈGUE : la mécanique vit dans
`wama_data.functions.kinematics.rts_smoother.kalman_rts_cv` (brique commune, même code).
Raison : la même mécanique devait servir la NAVETTE (`driving.ego_trajectory_filter`) alors
qu'elle n'était écrite ici que pour les OBJETS — la règle « toute logique pure et réutilisable
va dans wama_data » l'a fait remonter. Non-régression attestée par
`tests_trajectory_smoother.py` (empreinte numérique enregistrée AVANT le déplacement).

Brique GÉNÉRIQUE : entrée = série temporelle de positions bruitées [(t, x, y)],
sortie = positions ET vitesses lissées aux mêmes instants. Le passage ARRIÈRE
(Rauch-Tung-Striebel) utilise le futur ET le passé de chaque point — contrairement
à une EMA, le lissage est optimal sans retard de phase : le jitter de mesure
(pinhole ±20 %, gisement) est absorbé sans déformer la manœuvre réelle.

Consommateur : la trajectoire monde par `global_track_id` du cam_analyzer
(fusion multi-caméras d'un même véhicule sur toute la durée d'une manœuvre).
"""
from wama_data.functions.kinematics.rts_smoother import kalman_rts_cv


def smooth_track(points, sigma_a=2.5, sigma_m=1.5):
    """
    points : liste [(t, x, y)] triée par t (doublons de t tolérés — moyennés).
    Retourne une liste [(t, x, y, vx, vy)] lissée (mêmes t, dédoublonnés).
    Moins de 3 points : renvoie l'entrée avec vitesses nulles (rien à lisser).
    """
    return kalman_rts_cv(points, sigma_a=sigma_a, sigma_m=sigma_m)
