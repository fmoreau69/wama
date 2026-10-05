"""
Registre des bascules cam_analyzer — comparer AVEC/SANS chaque amélioration.

Mécanisme générique : `wama/common/utils/feature_flags.py`. Surcharges stockées dans
`AnalysisSession.config['features']` (endpoint `set_features`, panneau ⚑ Modes de la
vue de dessus). Un flag absent de la config retombe sur son défaut.

Règle : toute amélioration COMPARABLE du positionnement/cap/distances passe par une
bascule déclarée ici (jamais de if ad hoc dispersé) — voir CAM_ANALYZER_CHANGELOG.md.
"""
from wama.common.utils.feature_flags import (Feature, resolve, is_enabled as _is_enabled,
                                             describe as _describe, sanitize_overrides)

FEATURES = [
    Feature('fov_dist_correction', 'Correction FOV distances',
            "Corrige les distances annotées avec un ancien FOV V supposé "
            "(caméras latérales : ×3,6 trop courtes). OFF = distances brutes stockées.",
            default=True, scope='live'),
    Feature('mount_lever_arm', 'Bras de levier caméras',
            "Positions de montage réelles des caméras (antenne GPS à l'arrière, caméra "
            "avant +4,5 m). OFF = toutes les caméras supposées à l'antenne.",
            default=True, scope='live'),
    Feature('heading_ratio', 'Cap par ratio de bbox',
            "Cap des lents/stationnés estimé par le ratio largeur/hauteur de bbox, fondu "
            "avec la trajectoire selon la vitesse. OFF = trajectoire seule (cap figé à "
            "l'arrêt).",
            default=True, scope='live'),
    Feature('server_heading', 'Cap = trajectoire lissée (serveur)',
            "Le cap d'un véhicule qui roule (≥ 0,5 m/s) vient de la vitesse LISSÉE de TOUTE sa "
            "trajectoire (Kalman + RTS du tracking 360°), et non des quelques images que la page "
            "vient d'afficher : un saut dans la vidéo ne le fait plus retomber sur le cap de la "
            "navette, et il n'est plus bruité. OFF = cap tiré de la trace affichée (historique). "
            "Exige un « Tracking 360° » postérieur au 2026-10-02.",
            default=True, scope='live'),
    Feature('antenna_lever', "Levier d'antenne GPS",
            "Le point GPS est l'ANTENNE (coin arrière droit sur le rig ENA), pas le centre "
            "du véhicule : tout le repère est ramené au centre arrière via le levier déclaré "
            "(config gps_antenna). Corrige un biais systématique ~1 m vers la droite.",
            default=True, scope='compute'),
    Feature('artifact_filter', 'Filtre reflets/artefacts',
            "Masque les détections collées à l'image (reflets de vitrage : bbox immobile "
            "pendant que la navette avance). Le marquage/exclusion du tracking s'applique "
            "au prochain calcul des indicateurs ; le masquage à l'affichage est immédiat.",
            default=True, scope='live'),
    Feature('anchor_heading', 'Cap serveur des stationnés',
            "Cap des véhicules garés = consensus axial du ratio de bbox sur TOUTE la vie "
            "du track (calculé par le tracking 360°), au lieu de l'estimation frame par "
            "frame au rendu.",
            default=True, scope='live'),
    Feature('auto_ground_calib', 'Calibration sol auto (pitch)',
            "Position des objets par PROJECTION SOL (angle caméra estimé automatiquement "
            "depuis le mouvement + véhicules stationnés) au lieu du pinhole (hauteur de "
            "bbox). Étape 2a : corrige l'angle (gain ×5 mesuré) ; l'échelle absolue viendra "
            "des marquages ortho. Recalcule la calib au tracking si absente.",
            default=False, scope='compute'),
    Feature('ortho_correction', 'Recalage GPS par marquages ortho',
            "Applique à la trajectoire l'offset mesuré à l'étape 2b (passages piétons de "
            "l'orthophoto IGN vs caméra) — l'ÉCHELLE/POSITION absolue que 2a ne peut pas "
            "donner. La médiane globale est tenue pour un biais de PROJECTION caméra et "
            "n'est PAS appliquée ; seul l'écart LOCAL par intersection corrige le GPS, "
            "interpolé entre intersections et atténué là où le ciel est dégagé (hauteurs "
            "BD TOPO). Calculé par la passe « Correction de trajectoire ortho » ; la bascule "
            "choisit de l'appliquer, au tracking comme à l'affichage. OFF = trajectoire "
            "brute, l'offset restant mesuré et rapporté.",
            default=False, scope='compute'),
    Feature('marking_axis_snap', 'Passages piétons calés sur le corridor',
            "Un passage piéton agrégé en monde (SAM3, toutes caméras, tous passages) prend "
            "l'orientation la plus proche de la rue de la navette ou de sa perpendiculaire, et une "
            "longueur bornée à une chaussée — l'axe du nuage de points dérivait (diagonales, "
            "traits étirés le long de la rue). OFF = axe principal du nuage. Sert l'affichage ET "
            "le recalage ortho, qui mesure sur ces marquages.",
            default=True, scope='compute'),
    Feature('gps_bias_kalman', 'Biais GPS lissé (Kalman)',
            "Le recalage voie + carte estime le BIAIS du GPS (est, nord) comme un état lent, "
            "observé par chaque ancre dans la seule direction perpendiculaire à la route : des "
            "routes d'orientations différentes (virage, giratoire) rendent les deux composantes "
            "observables, et la correction est portée dans les zones SANS ancre (boucle de "
            "retournement, carrefour) tant que son incertitude reste faible. OFF = correction "
            "interpolée entre ancres proches, nulle loin d'elles. Relancer la passe « Recalage "
            "voie + carte ».",
            default=True, scope='compute'),
    Feature('same_camera_exclusion', "Une boîte par véhicule et par image (tracking)",
            "Dans une même image d'une même caméra, deux détections sont deux objets : le tracking "
            "360° ne les fond plus dans le même véhicule (la fusion de doublons reste permise ENTRE "
            "caméras). OFF = une file de voitures garées proches pouvait porter un seul numéro.",
            default=True, scope='compute'),
    Feature('chain_lock_priority', 'Tracking : les objets déjà suivis d\'abord',
            "Dans chaque image, les détections d'une trajectoire DÉJÀ suivie récupèrent leur numéro "
            "avant que les nouvelles ne cherchent le véhicule le plus proche. Sans cet ordre, une "
            "nouvelle détection traitée en premier pouvait prendre le numéro d'un véhicule suivi, qui "
            "devait alors en changer : un même véhicule éclaté sur plusieurs numéros. A/B : "
            "« Continuité du suivi » en console (chaînes éclatées, doublons, recollement). "
            "Mesuré sur ENA_CASA (2026-10-01) : chaînes éclatées 867 → 724, sans fusion abusive.",
            default=True, scope='compute'),
    Feature('birth_same_camera_guard', 'Tracking : un véhicule déjà vu par la caméra ne s\'absorbe pas',
            "Une NOUVELLE trajectoire d'une caméra ne peut pas rejoindre un véhicule que cette même "
            "caméra voit déjà par une autre trajectoire (vue il y a moins de 0,5 s) : c'est un autre "
            "objet. Sans cette garde, une trajectoire née pendant une détection manquée du voisin s'y "
            "fondait, puis les deux se disputaient le numéro. Une boîte qui recouvre la dernière de "
            "l'autre trajectoire reste permise (le détecteur a changé de numéro pour le même véhicule). "
            "Mesuré sur ENA_CASA avec la précédente (2026-10-01) : chaînes éclatées 867 → 597, doublons "
            "28 → 25, relais ratés 39 → 38, aucune fusion abusive. A/B : « Continuité du suivi ».",
            default=True, scope='compute'),
    Feature('class_family_gate', 'Porte de famille de classe (tracking)',
            "Le tracking 360° ne relie jamais un deux-roues (moto, vélo) à un quatre-roues "
            "(voiture, camion, bus) ni à un piéton : ni au rattachement d'une nouvelle chaîne, "
            "ni au recollement de tracklets. La famille comparée est la DOMINANTE du track "
            "(votes pondérés, établie seulement au-delà d'un seuil) — une image mal classée "
            "ne ferme rien. OFF = association sur la seule position (motos fondues dans une "
            "voiture voisine et affichées « car »).",
            default=True, scope='compute'),
    Feature('ghost_on_smoothed', 'Fantômes sur la trajectoire lissée',
            "Les fantômes (positions reconstituées dans un trou de détection) sont interpolés "
            "entre les deux points LISSÉS qui encadrent le trou — ceux-là mêmes que "
            "l'affichage dessine — au lieu des positions brutes : l'objet ne saute plus à "
            "l'entrée et à la sortie du fantôme. OFF = interpolation entre positions brutes "
            "(saut mesuré p90 2,25 m, p99 9,1 m). Les fantômes tombés dans l'emprise de la "
            "navette sont retirés dans les deux cas (physiquement impossibles).",
            default=True, scope='compute'),
    Feature('map_buildings', 'Bâtiments sur la carte',
            "Dessine les emprises des bâtiments BD TOPO autour de la navette sur la vue de "
            "dessus (IGN, chargées par zone). Ce sont eux qui dévient le GPS en canyon urbain "
            "et qui fondent le masquage satellite de la correction ortho : les voir aide à "
            "juger une trace. Affichage seul.",
            default=False, scope='live'),
    Feature('visual_heading', 'Cap visuel (rotation vue par la caméra avant)',
            "Sous 1 m/s le cap GPS ne vaut rien et le filtre navette le TENAIT. Avec cette bascule, "
            "il est propagé par la rotation VUE par la caméra avant (passe « Cap visuel ») tant que "
            "la navette roule — arrêtée, elle ne tourne pas. Mesuré sur 115 segments : erreur de "
            "cap p90 30,5° → 16,9°, vrais virages 30° → 14°. Exige la focale mesurée (passe "
            "« Champ des caméras »). Appliqué au prochain calcul du filtre (« Indicateurs »).",
            default=False, scope='compute'),
    Feature('measured_camera_fov', 'Champ des caméras MESURÉ',
            "Utilise le champ de vue des caméras avant/arrière MESURÉ sur la session (passe "
            "« Champ des caméras » : rotation vue dans l'image contre cap GPS en virage) au lieu "
            "de la fiche technique (110° pour la caméra avant, mesurée ~75°). Change le latéral des "
            "objets, les largeurs de voie vues, le cap par ratio et la projection sol : "
            "calibration sol, recalage voie + carte et calculs sont à rejouer après bascule.",
            default=False, scope='compute'),
    Feature('cut_box_inner_edge', 'Boîtes coupées par le bord INTÉRIEUR',
            "Une boîte coupée par le bord de l'image était placée au centre de sa partie VISIBLE, trop vers "
            "l'intérieur. On part de son bord intérieur (non coupé) et on prolonge de la demi-étendue "
            "apparente du véhicule. Constat du 2026-10-03, 519 s : une voiture coupée au bord de l'avant "
            "était placée à 8,7 m de la mesure de la latérale qui la voyait entière — le passage de relais "
            "ratait (G449 / G473).",
            default=False, scope='compute'),
    Feature('lens_distortion', 'Distorsion des objectifs',
            "Applique la distorsion radiale de chaque caméra (session : `camera_distortion`) à la "
            "projection sol, à la calibration et au placement pinhole. Mesuré le 2026-10-03 : sans elle, "
            "une voiture GARÉE qui traverse l'image d'une latérale « avance » de 17 % (gauche) à 22 % "
            "(droite) du trajet de la navette — elle semble la suivre ; les bords de l'image, là où se font "
            "les passages avant ↔ latérales, sont les plus faux. Calculs à rejouer après bascule.",
            default=False, scope='compute'),
    Feature('vehicle_center_placement', 'Véhicules placés par leur CENTRE',
            "Une caméra place un véhicule par le bas de sa boîte : le contact au sol de la face qu'elle "
            "VOIT. Vu de profil il était placé une demi-largeur trop près (≈ 0,9 m), vu de dos une "
            "demi-longueur (≈ 2,25 m) — et dessiné centré sur ce point, donc à moitié sur la voie pour "
            "un garé vu par une latérale, qui n'était alors jamais reconnu garé. Le point est repoussé "
            "le long de la ligne de visée jusqu'au centre (axe : vitesse du véhicule s'il roule, sinon "
            "parallèle à la navette). Change tous les placements : calculs à rejouer après bascule.",
            default=False, scope='compute'),
    Feature('stitch_one_to_one', 'Recollement un pour un',
            "Le recollement des morceaux de trajectoire (un objet coupé en deux, par exemple en "
            "zone aveugle) ne prolonge une fin de trajectoire qu'UNE fois, et jamais vers un groupe "
            "dont un membre est présent au même moment. Sans cela, des recollements en chaîne "
            "fusionnaient des dizaines de véhicules en un seul (mesuré le 2026-10-03 : 93 000 "
            "allers-retours entre objets distincts sous un même numéro, 581 avec la bascule ; doublons "
            "et relais ratés inchangés). ON par défaut : c'est la correction d'un défaut, pas une option.",
            default=True, scope='compute'),
    Feature('duplicate_chain_merge', 'Doublons de détection fondus',
            "Le détecteur suit parfois UNE voiture par deux chaînes (deux boîtes superposées dans la même "
            "image) : la seconde recevait son propre numéro de véhicule, puis le recollement pouvait la "
            "prolonger vers une autre voiture, et le comblement traçait entre les deux une trajectoire "
            "inventée. Constat du 2026-10-04, 525,1 s : G459, « un fantôme qui ne correspond à aucun "
            "véhicule » — deux images collées à G449, recollées 5,7 s plus tard à une voiture de l'arrière. "
            "Un numéro COURT (au plus ~1 s d'observations) qui n'est qu'un doublon (boîtes superposées, "
            "moins de 2 m) est fondu dans l'autre AVANT le recollement ; deux numéros vus une seule fois "
            "séparés dans une même image ne le sont jamais. Tracking à rejouer après bascule.",
            default=False, scope='compute'),
    Feature('stitch_bidirectional', 'Recollement dans les DEUX sens',
            "Deux morceaux de trajectoire sont jugés comme UNE trajectoire : en plus de prolonger la fin "
            "de A jusqu'au début de B, on ramène B en arrière (sa vitesse estimée sur ses premières "
            "secondes) jusqu'à la fin de A, et le meilleur raccord compte — entre deux morceaux qui "
            "ROULENT (≥ 3 m/s), et jamais s'ils vont en sens opposés ; les morceaux lents gardent la "
            "règle d'avant. Constat du 2026-10-05 : la Twingo G1588 (1780 s) qui ACCÉLÈRE pour doubler "
            "(~3 puis 6,5 m/s à l'arrière, 11 m/s à l'avant) — A prolongé la manquait de 9,4 m. "
            "Tracking à rejouer après bascule.",
            default=False, scope='compute'),
    Feature('range_correction', 'Distances corrigées par la portée (mesure automatique)',
            "À chaque calcul du tracking, la justesse des distances est MESURÉE automatiquement, par "
            "caméra et par méthode (projection sol, hauteur de boîte), sur les voitures garées : une "
            "garée ne bouge pas — sa position fixe vient de ses vues proches, et l'on compare la "
            "distance mesurée de loin à la distance vraie, par tranche (4-10 … 30-40 m). La bascule "
            "corrige les distances avec la courbe du calcul PRÉCÉDENT (plausibilité vérifiée) ; la "
            "courbe d'après correction s'affiche en console (contrôle : ~1,00). Mesuré le 2026-10-05 : "
            "projection sol arrière 0,60 à 30-40 m, avant 0,78 au-delà de 20 m. Universel : rien à "
            "saisir pour une nouvelle vue caméra. Tracking à rejouer (deux fois la 1ʳᵉ fois).",
            default=False, scope='compute'),
    Feature('offset_pitch_calib', "Inclinaison des caméras par l'écartement des garés (mesure automatique)",
            "Une voiture garée ne bouge pas : sa distance à la trajectoire de la navette ne doit pas "
            "dépendre de la caméra qui la voit. À chaque calcul du tracking, on cherche pour chaque caméra "
            "l'inclinaison (tangage) qui ANNULE cet écart avec la caméra de référence — celle dont la "
            "projection sol et la hauteur de boîte s'accordent. La bascule applique l'inclinaison du calcul "
            "PRÉCÉDENT (si elle réduit l'écart, sur au moins 20 garés, à ±5°). Constat du 2026-10-05 : les "
            "latérales écartaient les garés de +1,3 à +1,5 m de plus que l'avant — les trajectoires droites "
            "s'incurvaient autour de la navette. Universel : rien à régler pour une nouvelle vue caméra. "
            "Tracking à rejouer (deux fois la 1ʳᵉ fois).",
            default=False, scope='compute'),
    Feature('ghost_hermite', 'Trous comblés en COURBE',
            "Un trou de suivi (≤ 6 s) était comblé par une ligne droite entre ses deux bords : le cap "
            "cassait à l'entrée et à la sortie, et la ligne pouvait couper une file de garés. La courbe "
            "part dans la direction et à l'allure de l'arrivée et rejoint la sortie de même (vitesses "
            "lissées) ; repli sur la droite si les vitesses ne sont pas cohérentes avec la distance. "
            "Tracking à rejouer après bascule.",
            default=False, scope='compute'),
    Feature('measured_camera_yaw', 'Orientation des latérales MESURÉE',
            "Utilise l'orientation de montage des caméras latérales MESURÉE sur la session (passe "
            "« Champ des caméras » : le mouvement de la navette, tiré de la trace, contraint les "
            "points suivis dans l'image) au lieu de l'angle saisi (±75° par défaut ; mesuré ~67,5° à "
            "droite et ~−77,5° à gauche le 2026-10-02). Refusée si la caméra avant, contrôle de la "
            "méthode, ne retrouve pas ~0°. Change le placement de tout ce que voient les latérales "
            "et les jonctions avec l'avant : calibration sol et calculs sont à rejouer après bascule.",
            default=False, scope='compute'),
    Feature('parked_off_road', 'Garés = hors des voies',
            "Un véhicule est GARÉ si sa position médiane est HORS de l'emprise de chaussée IGN "
            "(à plus de 0,5 m du bord) : un immobile SUR la chaussée — à un feu, dans une file, à un "
            "carrefour — peut repartir et n'est jamais garé ; piétons exclus, et un track qui "
            "AVANCE franchement (déplacement net / chemin > 0,8) aussi. Remplace les seuils "
            "d'étalement en mètres, qui mesuraient le bruit de placement plus que le mouvement. "
            "OFF = règle historique. Emprise indisponible : règle historique, dite en console. "
            "Près d'une intersection, jamais garé (règle d'origine du filtre, rétablie le 2026-10-01).",
            default=True, scope='compute'),
    Feature('parked_motion_guard', 'Garés : trajectoire immobile exigée',
            "Sous « Garés = hors des voies », un track ne peut être garé que s'il ne SE DÉPLACE pas : "
            "position médiane du premier tiers contre celle du dernier tiers (le bruit de placement "
            "s'y moyenne, un vrai déplacement reste) — à partir de 5 m ET 0,5 m/s, c'est un véhicule "
            "qui roule. Demande de Fabien (2026-10-01) : un véhicule de l'intersection figé en garé "
            "est une interaction PERDUE ; mieux vaut un garé affiché mobile. Seuil non validé contre "
            "une vérité terrain — compté en console. OFF = sans cette garde.",
            default=True, scope='compute'),
    Feature('sam3_label_arbitration', 'SAM3 : un marquage, un seul label',
            "Les prompts SAM3 sont interrogés séparément : un même marquage pouvait sortir sous "
            "deux labels (une rangée de triangles vue comme « triangles » ET « passage piéton »). "
            "Deux masques de labels différents qui se recouvrent à plus de 50 % du plus petit sont "
            "le même objet : seul le plus confiant est gardé. Compté en console. Agit à la passe "
            "SAM3 (à relancer).",
            default=True, scope='compute'),
    Feature('map_road_zones', 'Chaussée IGN sur la carte',
            "Dessine l'emprise de la CHAUSSÉE autour de la navette : axes BD TOPO élargis de leur "
            "largeur puis unis — bords de voie, carrefours et giratoires ouverts. Remplace les "
            "bandes violettes des intersections (branche apprise ou bande symétrique), qui disaient "
            "qu'une route croisait sans dire où était la chaussée. OFF = les bandes violettes. "
            "Affichage seul.",
            default=True, scope='live'),
    Feature('shuttle_filter', 'Filtre de trajectoire navette (Kalman+RTS)',
            "Position et cap de la NAVETTE lissés par Kalman vitesse-constante + lisseur RTS "
            "(sans retard de phase) ; cap dérivé de la vitesse lissée, tenu à l'arrêt. Appliqué "
            "au point d'ingestion UNIQUE de la trace, côté serveur ET affichage : tout le "
            "positionnement (tracking 360°, ancres, TTC/PET, calibration sol) en hérite. OFF = "
            "GPS brut, cap = bearing entre fixes (±10-25° à basse vitesse — la source d'erreur "
            "angulaire dominante, §[2]). Premier levier qui touche la pose navette (inventaire "
            "2026-09-05 : aucun avant lui). Rapport A/B chiffré en console au recalcul.",
            default=False, scope='compute'),
    Feature('prediction_ground', "Projection sol dans le TTC/PET",
            "Place les objets du calcul TTC/PET par PROJECTION SOL (calib `ground_calib`) au "
            "lieu du pinhole. 🔴 **OFF par DÉCISION, pas par prudence** : la projection sol "
            "avait été retirée du TTC parce que le résultat était très mauvais avec "
            "l'homographie — or la calib sol de cette chaîne en DÉRIVE. À rebrancher quand "
            "l'homographie sera améliorée. Mesuré le 2026-09-12 sur la session de référence : "
            "ON ferait passer 51 % des placements du TTC par le sol et récupérerait 61 068 "
            "détections que le pinhole refuse (bbox coupées au bord) — un gain de COUVERTURE "
            "réel, sur une PRÉCISION encore mauvaise. ⚠ Distincte de ⚑ `auto_ground_calib`, "
            "qui vaut pour le TRACKER : deux placements, une différence VOULUE.",
            default=False, scope='compute'),
    Feature('prediction_causal_smoothing', "Lissage CAUSAL en entrée de la prédiction",
            "La trajectoire objet servie au TTC/PET est lissée par une fenêtre TRAÎNANTE "
            "(le point courant et ses prédécesseurs) au lieu de la fenêtre CENTRÉE "
            "historique, qui moyenne aussi ±2 points POSTÉRIEURS (~0,17 s). ⚠ Pourquoi ça "
            "compte : la méthode calcule le TTC sur des trajectoires PRÉDITES à chaque pas, "
            "et l'écart prédit/réel s'interprète comme un comportement de CORRECTION "
            "(`CHAINE §F`) — tout ce qui informe l'entrée du futur réduit cet écart "
            "artificiellement. La fenêtre centrée regarde bien moins loin que le lissage RTS "
            "de `world_en` (tout le track), mais elle regarde quand même : différence de "
            "DEGRÉ, pas de nature. OFF = fenêtre centrée, comportement historique.",
            default=False, scope='compute'),
    Feature('prediction_kalman', "Extrapolation Kalman pour le TTC/PET",
            "Les trajectoires navette et objet sont extrapolées par un filtre de Kalman à "
            "accélération constante au lieu de « vitesse + accélération constantes ». ⚠ Les "
            "DEUX existent depuis l'origine et la seconde est le PORTAGE du script MATLAB "
            "d'origine (`ExtrTraj_WithSpeedAndAccel.m`) ; la variante Kalman a été écrite "
            "parce que le Kalman MATLAB était incomplet — et elle est restée INATTEIGNABLE, "
            "aucun appelant ne posant le paramètre `method` (mesuré 2026-09-11, `CHAINE "
            "§D.5 ④`). ⚠ Extrapolation CAUSALE dans les deux cas (historique jusqu'à t0) : "
            "rien à voir avec le lissage RTS, qui voit le futur. OFF = le script d'origine, "
            "comportement historique.",
            default=False, scope='compute'),
    Feature('lane_map_recalage', "Recalage voie + carte (latéral + cap navette)",
            "Corrige la position LATÉRALE et le CAP de la navette par la voie vue (lignes YOLOPv2 "
            "projetées au sol, caméra avant) et l'axe routier IGN BD TOPO (largeur, nombre de "
            "voies, sens), rattachés en continu (Viterbi). Le longitudinal reste au GPS et au "
            "recalage ortho. Calcul stocké par la passe « Recalage voie + carte » ; appliqué au "
            "point d'ingestion UNIQUE de la pose, après ⚑ shuttle_filter. Mesure fondatrice : "
            "GPS ≈ 2 m trop à droite et cap figé à −5,9° à Roumanille-Poincaré (2026-09-28). "
            "OFF = pose GPS (filtrée ou brute), comportement historique.",
            default=False, scope='compute'),
    Feature('imu_command', "Accéléromètre en commande du filtre navette",
            "Le filtre de trajectoire navette (⚑ `shuttle_filter`) cesse de supposer "
            "« accélération inconnue ±0,8 m/s² » et prend l'accélération MESURÉE par "
            "l'accéléromètre embarqué, à son résidu près (±0,25 m/s² — mesuré 4× plus fin, "
            "`CHAINE §D.4 ⑤`). L'axe avant est `ax`, identifié par trois discriminants "
            "indépendants sur données réelles ; le biais de pose est réestimé À L'ARRÊT. "
            "N'a d'effet qu'au RECALCUL, et seulement si ⚑ `shuttle_filter` sert la trace. "
            "Ne corrige PAS le cap : ça demande un gyroscope (§D.4 ⑥). OFF = modèle à "
            "accélération inconnue, comportement historique.",
            default=False, scope='compute'),
    Feature('sam3_homography', 'Homographie sol par passage piéton (DLT)',
            "Utilise l'homographie calibrée sur un passage piéton (SAM3 ou clics, "
            "`camera.ground_homography`) là où elle est consommée : distances géométriques à "
            "l'analyse, projection des MARQUAGES en monde, largeur de voie auto. Voie PROUVÉE "
            "BIAISÉE sur les données réelles (#546 inversion de signe, #537 profondeur non "
            "monotone) mais restée active sans bascule jusqu'au 2026-09-05 (§INVENTAIRE D.2). "
            "OFF = projection paramétrique (FOV réels, hauteur 2,4 m, pitch 0) pour les marquages, "
            "aucune distance géométrique à l'analyse. Défaut ON = comportement historique.",
            default=True, scope='compute'),
    Feature('display_ema', "Lissage EMA d'affichage (repli par frame)",
            "En repli ③ (détection sans ancre ni world_en : frames postérieures au dernier calcul, "
            "ou véhicule non qualifié stationné), la distance et le latéral affichés sont lissés "
            "par EMA α=0,3. Une EMA échange du jitter contre un RETARD DE PHASE : hypothèse "
            "§INVENTAIRE D.3 pour les garés qui « suivent la navette puis se décrochent ». OFF = "
            "position brute par frame (jitter visible, aucun retard) — bascule LIVE : le test D.3 "
            "se fait à l'œil ET au chiffre sans recalcul. Défaut ON = comportement historique.",
            default=True, scope='live'),
    Feature('world_markings', 'Marquages SAM3 en monde',
            "Les stop_line/passages piétons segmentés par SAM3 sont projetés au sol et "
            "agrégés multi-passages : bornes réelles d'intersection sur la mini-map, et "
            "axe de la branche croisante même sans trafic observé.",
            default=True, scope='compute'),
    Feature('sam3_interp', 'Interpolation des marquages SAM3',
            "Les marquages (passages piétons…) ne sont segmentés qu'aux keyframes "
            "(sam3_fps du profil) : l'affichage interpole entre deux keyframes "
            "(translation+échelle) pour un rendu continu, avec fondu aux extrémités.",
            default=True, scope='live'),
    Feature('learned_branches', 'Branches apprises du trafic',
            "Les voies croisantes aux intersections sont apprises des trajectoires monde "
            "des véhicules suivis (côté, azimut, étendue et largeur observés) au lieu "
            "d'une bande perpendiculaire symétrique aveugle.",
            default=True, scope='compute'),
    Feature('heading_cluster', 'Prior de cluster (cap des garés)',
            "Les garés voisins (< 15 m) partagent souvent leur axe (rangée, épi) : mélange "
            "axial pondéré du cap individuel avec celui des voisins.",
            default=True, scope='compute'),
    Feature('track_speed_unified', 'Vitesse/distance unifiées par track',
            "Une seule vitesse/distance monde par véhicule (tracker 360°) servie à toutes "
            "les vues, au lieu de valeurs indépendantes par caméra. (Pas encore implémenté "
            "— déclaré pour le chantier d'unification.)",
            default=False, scope='compute'),
    Feature('depth_estimation', 'Profondeur monoculaire (1ère passe)',
            "Profondeur par image (ZoeDepth KITTI, MIT, par défaut depuis le 2026-09-28 ; Depth Pro "
            "au choix via config['depth_model']). Chaîne en 3 ÉTAGES DÉCOUPLÉS (« analyse d'abord, "
            "calculs ensuite ») : ÉTAGE 1 ANALYSE = la passe `depth` du volet (session-wide, 4 caméras) "
            "infère et STOCKE la donnée brute (cartes → DepthFrame, profondeur de contact "
            "`depth_distance_m`) — indépendante de ce flag ; ÉTAGE 2 CALCULS (CPU, re-jouable) relit "
            "la db → plan de sol (RANSAC sur la zone roulable YOLOPv2, focales fx/fy du rig), pitch "
            "indépendant de l'échelle, échelle ANCRÉE sur la hauteur de caméra quand le modèle ne rend "
            "pas de mètres, et cross-check distance. CE FLAG = ÉTAGE 3 : quand ON, la projection "
            "CONSOMME le plan profondeur au lieu de la recherche homographique (tranché sur "
            "`placement_spread`) ; l'overlay de profondeur viendra plus tard. Voir "
            "CAM_ANALYZER_CHAINE_TRAITEMENT.md §[E].",
            default=False, scope='compute'),
]


def enabled(session, key):
    return _is_enabled(FEATURES, getattr(session, 'config', None), key)


def effective(session):
    return resolve(FEATURES, getattr(session, 'config', None))


def compute_snapshot(session):
    """Bascules de CALCUL (`scope='compute'`) en vigueur : ce qu'un calcul stocké a vu. Une bascule
    d'affichage (`live`) n'invalide aucun calcul, elle n'y figure donc pas."""
    eff = effective(session)
    return {f.key: eff[f.key] for f in FEATURES if f.scope == 'compute'}


def catalog(session):
    return _describe(FEATURES, getattr(session, 'config', None))


def clean_overrides(raw):
    return sanitize_overrides(FEATURES, raw)
