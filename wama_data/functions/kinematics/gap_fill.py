"""Combler le TROU d'une trajectoire entre deux observations — courbe d'Hermite.

Domicile unique depuis le 2026-10-05 (question de Fabien : réutiliser les trajectoires du
cam_analyzer pour l'interpolation de l'anonymizer). Né au cam_analyzer (`multicam_tracker.
hermite_ghost`, ⚑ ghost_hermite) pour reposer les positions fantômes d'un véhicule perdu de vue ;
l'anonymizer l'emploie pour les trous de détection d'un visage ou d'une plaque. Seules les
UNITÉS changent (mètres et secondes là-bas, pixels et images ici) : les seuils sont donc des
paramètres, leurs défauts sont ceux du cam_analyzer.
"""
import math


def hermite_gap(p0, v0, p1, v1, span, a, *, min_bulge=2.0, bulge_share=0.25,
                overshoot_margin=4.0, min_speed_share=None):
    """Position à la fraction `a` (0 → 1) d'un trou de durée `span` entre `p0` (vitesse `v0`) et
    `p1` (vitesse `v1`), en 2D. La courbe part dans la direction et à l'allure de l'arrivée et
    rejoint la sortie de même, là où la ligne droite casse la direction aux deux bords.

    Repli LINÉAIRE — un détour inventé est pire qu'une droite :
      • sans l'une des deux vitesses ;
      • quand la courbe s'écarterait de la corde de plus de max(`min_bulge`, `bulge_share` × corde) ;
      • quand les allures ne collent pas à la distance à couvrir (la courbe dépasserait ses
        extrémités : vitesse × durée > 2 × corde + `overshoot_margin`) ;
      • et, si `min_speed_share` est donné, quand elles sont trop LENTES pour l'expliquer : les
        deux vitesses × durée < `min_speed_share` × corde (la courbe inventerait un départ lent,
        une pointe, une arrivée lente). Absent par défaut : le cam_analyzer ne le demande pas ;
        l'anonymizer, si — mesuré sur la card #1026, des visages reliés à 198 px en 6 images
        avec des allures de 1 et 11 px/image aux bords.
    Les vitesses sont dans l'unité de `span` (m/s et s, ou px/image et images)."""
    linear = (p0[0] + a * (p1[0] - p0[0]), p0[1] + a * (p1[1] - p0[1]))
    if v0 is None or v1 is None:
        return linear
    chord = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    bulge = span * math.hypot(v0[0] - v1[0], v0[1] - v1[1]) / 8.0     # écart au milieu de la corde
    if bulge > max(min_bulge, bulge_share * chord):
        return linear
    fastest = max(math.hypot(*v0), math.hypot(*v1)) * span
    if fastest > 2.0 * chord + overshoot_margin:
        return linear
    if min_speed_share is not None and fastest < min_speed_share * chord:
        return linear
    h00, h10 = 2 * a ** 3 - 3 * a ** 2 + 1, a ** 3 - 2 * a ** 2 + a
    h01, h11 = -2 * a ** 3 + 3 * a ** 2, a ** 3 - a ** 2
    return (h00 * p0[0] + h10 * span * v0[0] + h01 * p1[0] + h11 * span * v1[0],
            h00 * p0[1] + h10 * span * v0[1] + h01 * p1[1] + h11 * span * v1[1])
