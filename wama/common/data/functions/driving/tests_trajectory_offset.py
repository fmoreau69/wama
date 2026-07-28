"""Tests des fonctions pures de `trajectory_offset` (aucune dépendance Django/GPU).

Lancement : `python3 wama/common/data/functions/driving/tests_trajectory_offset.py`
Le module est chargé par chemin, sans passer par le paquet : importer
`wama.common.data.functions` déclencherait l'auto-déclaration des FunctionSpec, donc Django.
"""
import importlib.util
import math
import sys
from pathlib import Path

MOD = Path(__file__).resolve().parent / "trajectory_offset.py"
# Racine du dépôt : le module déclare ses FunctionSpec, donc importe `wama.common.data.*`
# (pur Python, sans Django). On charge quand même le module PAR CHEMIN pour éviter le
# `__init__` du paquet, qui lui tirerait tout le domaine driving.
sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
spec = importlib.util.spec_from_file_location("trajectory_offset_under_test", MOD)
oa = importlib.util.module_from_spec(spec)
sys.modules["trajectory_offset_under_test"] = oa
spec.loader.exec_module(oa)

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        fail += 1
        print(f"  FAIL {label} {detail}")


print("== 1. Décomposition global/local ==")
rec = {
    "global": {"de_m": 3.0, "dn_m": -1.0, "n": 30},
    "per_window": {
        "0": {"de_m": 3.0, "dn_m": -1.0, "n": 10},   # pile la médiane -> local nul
        "1": {"de_m": 8.0, "dn_m": -1.0, "n": 12},   # +5 m est en local
        "2": {"de_m": 1.0, "dn_m": 1.0, "n": 8},     # -2 est / +2 nord
    },
}
d = oa.decompose(rec)
check("biais caméra = médiane globale", d["camera"] == {"de_m": 3.0, "dn_m": -1.0}, d["camera"])
check("fenêtre à la médiane -> local nul", d["gps_local"]["0"] == {"de_m": 0.0, "dn_m": 0.0, "n": 10})
check("fenêtre 1 -> +5 m est", abs(d["gps_local"]["1"]["de_m"] - 5.0) < 1e-9)
check("fenêtre 2 -> -2 est / +2 nord",
      abs(d["gps_local"]["2"]["de_m"] + 2.0) < 1e-9 and abs(d["gps_local"]["2"]["dn_m"] - 2.0) < 1e-9)

print("== 2. Ancres et rétraction par masquage ==")
wins = [
    {"lat": 45.75, "lon": 4.83, "t_enter": 10.0, "t_exit": 20.0},
    {"lat": 45.76, "lon": 4.84, "t_enter": 110.0, "t_exit": 130.0},
    {"lat": 45.77, "lon": 4.85, "t_enter": 210.0, "t_exit": 230.0},
]
a_nomask = oa.build_anchors(wins, d)
check("3 ancres", len(a_nomask) == 3, len(a_nomask))
check("ts = milieu de traversée", a_nomask[0]["ts"] == 15.0 and a_nomask[1]["ts"] == 120.0)
check("triées par temps", [x["ts"] for x in a_nomask] == sorted(x["ts"] for x in a_nomask))
check("sans masque -> alpha 1", all(x["alpha"] == 1.0 for x in a_nomask))

# Ciel dégagé sur la fenêtre 1 -> correction rétractée ; canyon sur la 2 -> pleine.
a_mask = oa.build_anchors(wins, d, mask_by_key={"0": 0.0, "1": 0.0, "2": 24.0})
w1 = [x for x in a_mask if x["ts"] == 120.0][0]
w2 = [x for x in a_mask if x["ts"] == 220.0][0]
check("ciel dégagé -> correction annulée", w1["de_m"] == 0.0 and w1["alpha"] == 0.0, w1)
check("canyon profond -> alpha plafonné à 1", w2["alpha"] == 1.0, w2)

print("== 3. Interpolation et bornes ==")
anchors = [{"ts": 0.0, "de_m": 0.0, "dn_m": 0.0, "n": 10, "alpha": 1.0},
           {"ts": 100.0, "de_m": 10.0, "dn_m": -4.0, "n": 10, "alpha": 1.0}]
de, dn = oa.offset_at(anchors, 50.0)
check("milieu (poids n égaux) -> moitié", abs(de - 5.0) < 1e-6 and abs(dn + 2.0) < 1e-6, (de, dn))
check("avant la 1re ancre -> maintien", oa.offset_at(anchors, -999.0) == (0.0, 0.0))
check("après la dernière -> maintien", oa.offset_at(anchors, 9999.0) == (10.0, -4.0))
check("aucune ancre -> offset nul", oa.offset_at([], 42.0) == (0.0, 0.0))

print("== 4. SIGNE (le point critique) ==")
# Le passage vu par la caméra est projeté 5 m à l'EST du vrai (ortho) :
#   de = ortho - camera = -5  ->  la position supposée était 5 m trop à l'est
#   -> la correction doit ramener le véhicule vers l'OUEST (longitude qui diminue).
anch = [{"ts": 0.0, "de_m": -5.0, "dn_m": 0.0, "n": 5, "alpha": 1.0}]
track = [{"ts": 0.0, "lat": 45.75, "lon": 4.83}]
corr = oa.correct_track(track, anch)
check("offset est négatif -> longitude diminue (vers l'ouest)", corr[0]["lon"] < 4.83, corr[0]["lon"])
shift_m = (corr[0]["lon"] - 4.83) * 111320.0 * math.cos(math.radians(45.75))
check("amplitude = 5 m", abs(shift_m + 5.0) < 0.01, f"{shift_m:.3f} m")
check("original préservé", corr[0]["lat_raw"] == 45.75 and corr[0]["lon_raw"] == 4.83)
check("traçabilité présente", corr[0]["corr_de_m"] == -5.0)

# Nord : dn positif -> latitude augmente
anch_n = [{"ts": 0.0, "de_m": 0.0, "dn_m": 8.0, "n": 5, "alpha": 1.0}]
c2 = oa.correct_track([{"ts": 0.0, "lat": 45.75, "lon": 4.83}], anch_n)
check("dn positif -> latitude augmente", c2[0]["lat"] > 45.75)
check("amplitude nord = 8 m", abs((c2[0]["lat"] - 45.75) * 111320.0 - 8.0) < 0.01)

print("== 5. Robustesse ==")
check("trace vide", oa.correct_track([], anchors) == [])
check("sans ancre -> trace inchangée", oa.correct_track(track, []) == track)
check("point sans coordonnées toléré",
      oa.correct_track([{"ts": 1.0}], anchors)[0].get("lat") is None)
check("rec vide", oa.decompose({}) == {"camera": {"de_m": 0.0, "dn_m": 0.0}, "gps_local": {}})
check("fenêtre hors index ignorée",
      oa.build_anchors([], {"gps_local": {"7": {"de_m": 1, "dn_m": 1, "n": 1}}}) == [])
rep = oa.correction_report(a_nomask)
check("rapport cohérent", rep["n_anchors"] == 3 and rep["max_shift_m"] > 0, rep)

print("== 6. Masque ABSENT ≠ ciel dégagé (panne BD TOPO) ==")
# Fenêtre "1" absente du dict = réseau indisponible -> ne doit PAS rétracter,
# sinon une panne BD TOPO annulerait toute la correction en silence.
a_part = oa.build_anchors(wins, d, mask_by_key={"2": 24.0})
w1p = [x for x in a_part if x["ts"] == 120.0][0]
check("masque absent -> alpha 1 (correction préservée)", w1p["alpha"] == 1.0, w1p)
check("masque absent -> offset local intact", abs(w1p["de_m"] - 5.0) < 1e-9, w1p)
# Masque explicitement nul = ciel réellement dégagé -> rétraction totale
a_zero = oa.build_anchors(wins, d, mask_by_key={"1": 0.0})
w1z = [x for x in a_zero if x["ts"] == 120.0][0]
check("masque explicite 0 -> alpha 0 (rétraction)", w1z["alpha"] == 0.0, w1z)

print(f"\n=== {ok} OK, {fail} FAIL ===")
sys.exit(1 if fail else 0)
