# Construit la page WAMA du rapport « pipeline d'analyse du cam_analyzer » appliqué aux données ENA (menu
# « Présentations & annexes » › Rapports, `wama.views.REPORTS`). Les FAITS viennent des registres et de la
# base, jamais recopiés à la main : les passes et leurs dépendances (`pass_tracking.PASSES`), ce que fait
# chacune (`READER` ci-dessous, en repli le `FunctionSpec` du catalogue), les bascules (`features.FEATURES`), la session (profil, caméras,
# volumes, indicateurs du dernier tracking). Le texte qui les relie est écrit ici.
#
# Usage (racine du dépôt) — lit la base, n'écrit que le gabarit :
#     python manage.py shell < scripts/reports/build_cam_analyzer_report.py
# La capture du Studio (`wama/static/presentation/rapports/cam_analyzer_studio.png`) se refait à la main
# (pipeline déclaré `cam_analyzer` ouvert dans le Studio) quand le pipeline change.
import datetime as dt
import html
import sys
from collections import Counter, defaultdict
from pathlib import Path

from wama.common.catalog import function_catalog as fc
from wama_lab.cam_analyzer.models import (AnalysisSession, ConflictEvent, DetectionFrame, LaneEvent,
                                          TemporalSegment)
from wama_lab.cam_analyzer.utils.features import FEATURES, effective
from wama_lab.cam_analyzer.utils.pass_tracking import PASSES

HERE = Path('scripts/reports')
sys.path.insert(0, str(HERE))
from shell_page import fill_shell  # noqa: E402

OUT = Path('wama/templates/includes/wama_rapport_cam_analyzer.html')
SESSION_NAME = 'ENA_CASA_P97_20220404_124000_seg'
IMG = '/static/presentation/rapports/cam_analyzer_studio.png'
esc = lambda s: html.escape(str(s), quote=False)  # noqa: E731

fc.load_all()
s = AnalysisSession.objects.get(name=SESSION_NAME)
prof = s.profile
rs = s.results_summary or {}
eff = effective(s)
today = dt.date.today()
MONTHS = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre',
          'novembre', 'décembre')
date_fr = f'{today.day} {MONTHS[today.month - 1]} {today.year}'


def first_sentence(text):
    t = (text or '').strip()
    for stop in ('. ', ' — '):
        if stop in t:
            return t.split(stop)[0].rstrip('.') + '.'
    return t


def nb(n):
    return f'{n:,}'.replace(',', ' ')


# ── Les données ─────────────────────────────────────────────────────────────────────────────
cams = list(s.cameras.all().order_by('position'))
LABEL = {'front': 'avant', 'rear': 'arrière', 'left': 'gauche', 'right': 'droite'}
duration_s = max((c.duration or 0) for c in cams) if cams else 0
cam_rows = ''.join(
    f'<tr><td>{LABEL.get(c.position, c.position)}</td><td>{c.width} × {c.height}</td><td>{c.fps:g}</td>'
    f'<td>{nb(DetectionFrame.objects.filter(camera=c).count())}</td></tr>' for c in cams)
inters = (prof.intersections if prof else []) or []
windows = s.intersection_windows or []
passes_per_inter = Counter(w.get('name') for w in windows)
inter_rows = ''.join(f'<tr><td>{esc(i.get("name"))}</td><td>{i.get("radius_m")} m</td>'
                     f'<td>{passes_per_inter.get(i.get("name"), 0)}</td></tr>' for i in inters)

# ── Le pipeline : tableau et diagramme tirés du registre ────────────────────────────────────
by_key = {p.key: p for p in PASSES}


# Ce que fait chaque passe, dit pour le LECTEUR du rapport : la description du catalogue est écrite pour le
# développeur (noms de passes, de briques, de champs). La LISTE des passes, leurs dépendances et leur matériel
# restent tirés du registre ; une passe sans phrase ici retombe sur le catalogue, et le script le signale.
READER = {
    'extraction': "Lit l'enregistrement de la navette : une vidéo par caméra, la trace GPS (position, cap, "
                  "vitesse) et l'accéléromètre, et synchronise le GPS avec les vidéos.",
    'intersection_windows': "Découpe le trajet en fenêtres de temps autour de chaque intersection déclarée : "
                            "c'est ce que regardent les passes suivantes.",
    'yolo_detect': "Détecte et segmente les usagers (voitures, camions, deux-roues, piétons) sur chaque image de "
                   "chaque caméra, et les suit d'une image à l'autre.",
    'yolopv2_lanes': "Segmente la chaussée praticable et les lignes de voie sur la caméra avant.",
    'sam3_markings': "Segmente les marquages au sol des intersections : passages piétons, lignes d'arrêt.",
    'depth': "Estime la profondeur de chaque pixel sur des images échantillonnées et la stocke : une mesure de "
             "distance indépendante de la géométrie des caméras.",
    'ortho_recalage': "Repère les passages piétons sur l'orthophoto IGN et mesure leur écart avec ceux que voit "
                      "la caméra avant : de quoi corriger la position GPS.",
    'lane_events': "Attribue une voie à chaque usager et relève ses changements de voie.",
    'temporal_segments': "Découpe le parcours de chaque usager en épisodes : approche, suivi, traversée, "
                         "insertion devant la navette, attente à l'intersection.",
    'distance': "Calcule la distance de chaque usager à la navette, sa vitesse et un premier temps à "
                "collision (TTC).",
    'depth_calc': "Tire de la profondeur stockée le plan du sol de la caméra avant et une distance de contrôle "
                  "pour chaque usager.",
    'lane_map_recalage': "Cale la position latérale et le cap de la navette en superposant les lignes de voie "
                         "vues à l'avant au réseau routier de l'IGN.",
    'camera_intrinsics': "Mesure le champ de vue réel et l'orientation de montage de chaque caméra, à partir "
                         "des virages de la navette et des lignes droites de la scène.",
    'visual_yaw': "Mesure la rotation de la navette dans la vidéo avant : une seconde source de cap, "
                  "indépendante du GPS.",
    'ortho_correction': "Transforme l'écart mesuré sur les passages piétons en corrections de la trace GPS, "
                        "passage par passage.",
    'global_tracking': "Relie les identifiants d'une caméra à l'autre (un véhicule, un identifiant), place "
                       "chaque usager au sol, reconnaît les véhicules garés et lisse les trajectoires.",
    'indicators': "Prédit la trajectoire de chaque usager et de la navette, et en tire le temps à collision "
                  "(TTC) et le temps post-empiètement (PET).",
    'conflicts': "Repère les situations de conflit (approche frontale, suivi rapproché, dépassement) et leur "
                 "donne une gravité.",
}
unwritten = [p.key for p in PASSES if p.key not in READER]
if unwritten:
    print('⚠ passes sans phrase pour le lecteur (repli sur le catalogue) :', ', '.join(unwritten))


def describe(p):
    if p.key in READER:
        return READER[p.key]
    spec = fc.get(p.function_key)
    return first_sentence(spec.description) if spec else ''


def stage_rows(stage):
    out = []
    for p in PASSES:
        if p.stage != stage:
            continue
        deps = ', '.join(by_key[d].label for d in p.depends_on if d in by_key) or '—'
        out.append(f'<tr><td><strong>{esc(p.label)}</strong></td><td>{esc(describe(p))}</td>'
                   f'<td>{esc(deps)}</td><td>{"GPU" if p.gpu else "processeur"}</td></tr>')
    return ''.join(out)


def depth_of(key, memo={}):
    if key not in memo:
        p = by_key[key]
        memo[key] = 1 + max((depth_of(d) for d in p.depends_on if d in by_key), default=-1)
    return memo[key]


def wrap(label, width=21, lines=2):
    """Le libellé en `lines` lignes d'au plus `width` caractères, coupé aux mots."""
    out, cur = [], ''
    for word in label.split():
        if cur and len(cur) + 1 + len(word) > width:
            out.append(cur)
            cur = word
        else:
            cur = f'{cur} {word}'.strip()
    out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][:width - 1] + '…'
    return out


def diagram():
    """Les passes en RANGÉES par profondeur de dépendance (la source en haut), colorées par étage, reliées
    par leurs dépendances déclarées — le même graphe que le Studio, sans la mise en page à la main."""
    rows = defaultdict(list)
    for p in PASSES:
        rows[depth_of(p.key)].append(p)
    W, H, gx, gy, pad = 156, 46, 14, 40, 12
    widest = max(len(v) for v in rows.values())
    width = pad * 2 + widest * (W + gx) - gx
    pos = {}
    for r, ps in sorted(rows.items()):
        x_start = (width - (len(ps) * (W + gx) - gx)) / 2
        for c, p in enumerate(ps):
            pos[p.key] = (x_start + c * (W + gx), pad + r * (H + gy))
    height = pad * 2 + (max(rows) + 1) * (H + gy) - gy
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Pipeline du cam_analyzer" '
             f'style="width:100%;height:auto;font-family:var(--sans)">']
    for p in PASSES:
        x1, y1 = pos[p.key]
        for d in p.depends_on:
            if d in pos:
                xa, ya = pos[d]
                parts.append(f'<path d="M{xa + W / 2:.1f} {ya + H} C{xa + W / 2:.1f} {ya + H + gy / 2} '
                             f'{x1 + W / 2:.1f} {y1 - gy / 2} {x1 + W / 2:.1f} {y1}" '
                             f'style="fill:none;stroke:var(--muted-bar);stroke-width:1.4"/>')
    for p in PASSES:
        x, y = pos[p.key]
        fill = 'var(--accent-soft)' if p.stage == 'analyse' else 'var(--card-2)'
        stroke = 'var(--accent)' if p.stage == 'analyse' else 'var(--line)'
        lines = wrap(p.label)
        top = y + H / 2 - (len(lines) - 1) * 8 + 5
        spans = ''.join(f'<tspan x="{x + W / 2:.1f}" y="{top + i * 16:.1f}">{esc(line)}</tspan>'
                        for i, line in enumerate(lines))
        parts.append(f'<g><title>{esc(p.label)}</title><rect x="{x:.1f}" y="{y}" width="{W}" height="{H}" '
                     f'rx="8" style="fill:{fill};stroke:{stroke};stroke-width:1.2"/>'
                     f'<text text-anchor="middle" style="fill:var(--ink);font-size:13.5px">{spans}</text></g>')
    parts.append('</svg>')
    return ''.join(parts)


# ── Qualité mesurée sans vérité terrain (dernier tracking) ──────────────────────────────────
ct = rs.get('tracking_continuity') or {}
anchors = rs.get('stationary_anchors') or {}
quality_rows = [
    ('Véhicules garés reconnus', nb(len(anchors)),
     'hors des voies de circulation, immobiles ; position et cap fixes'),
    ('Doublons', ct.get('cross_camera_close_pairs'),
     'deux identifiants restés proches que jamais une caméra n\'a vus ensemble'),
    ('Relais ratés', ct.get('relay_breaks'), 'un véhicule qui change d\'identifiant en passant d\'une caméra à '
                                             'l\'autre'),
    ('Allers-retours', ct.get('switchbacks'), 'un identifiant qui passe d\'un véhicule à un autre puis revient'),
    ('Trajectoires coupées', ct.get('chain_splits'), 'un véhicule suivi par une caméra, porté par plusieurs '
                                                     'identifiants'),
]
quality_html = ''.join(f'<tr><td>{esc(a)}</td><td>{esc(b if b is not None else "—")}</td><td>{esc(c)}</td></tr>'
                       for a, b, c in quality_rows)
compute_flags = [f for f in FEATURES if f.scope == 'compute']
flags_on = [f for f in compute_flags if eff.get(f.key)]
flags_off = [f for f in compute_flags if not eff.get(f.key)]
flag_items = ''.join(f'<li>{esc(f.label)}</li>' for f in flags_on)
flags_off_text = ', '.join(f'« {esc(f.label)} »' for f in flags_off) or 'aucune'

# ── Les intersections : ce que la base contient aujourd'hui ─────────────────────────────────
conf = ConflictEvent.objects.filter(session=s)
sev = Counter(conf.values_list('severity', flat=True))
seg_types = Counter(TemporalSegment.objects.filter(session=s).values_list('segment_type', flat=True))
lane_in = LaneEvent.objects.filter(camera__session=s).exclude(intersection_window_idx=-1).count()

body = f'''
<p>WAMA Lab Cam Analyzer analyse les vidéos d'une <strong>navette autonome</strong> (projet ENA) pour mesurer
ses <strong>interactions avec les autres usagers de la route aux intersections</strong> : qui s'insère devant la
navette, dans quelle voie, à quelle distance et à quelle vitesse, et avec quelle marge de temps (TTC, PET). Ce
rapport présente la chaîne complète, de la vidéo aux indicateurs, sur la session <strong>{esc(s.name)}</strong>.
Il est généré depuis les registres de WAMA et la base : la liste des passes, leurs dépendances, les bascules
et tous les chiffres viennent de leurs déclarations et des mesures, pas d'un texte recopié.</p>

<h2>Les données</h2>
<p>Quatre caméras montées sur la navette, filmées pendant <strong>{f'{duration_s / 3600:.1f}'.replace('.', ',')} h</strong>
({nb(round(duration_s))} s), avec la trace GPS du véhicule. Deux intersections sont déclarées dans le profil
d'analyse « {esc(prof.name if prof else '—')} » ; la navette les traverse plusieurs fois.</p>
<div class="tbl"><table><thead><tr><th>Caméra</th><th>Image</th><th>Images/s</th><th>Images analysées</th></tr>
</thead><tbody>{cam_rows}</tbody></table></div>
<div class="tbl"><table><thead><tr><th>Intersection</th><th>Rayon d'analyse</th><th>Passages de la navette</th>
</tr></thead><tbody>{inter_rows}</tbody></table></div>

<h2>Le pipeline</h2>
<p>La chaîne se lit en deux étages. L'étage <strong>analyse</strong> regarde les images, une fois, sur la
carte graphique : détection et suivi des véhicules, chaussée et voies, marquages au sol, profondeur. L'étage
<strong>calcul</strong> ne fait que dériver des données stockées, sur le processeur : il se rejoue à volonté
quand une méthode change, sans repasser sur les images. Une passe dont une entrée a changé est marquée
périmée, et seules les passes en aval sont à refaire.</p>
<figure class="chart"><figcaption><strong>Le pipeline dans le Studio de WAMA</strong>
<span>Le même pipeline, déclaré par l'application, ouvert dans le Studio : chaque nœud est une passe, chaque
câble une donnée qui passe de l'une à l'autre.</span></figcaption>
<img src="{IMG}" alt="Pipeline du cam_analyzer dans le Studio de WAMA" style="width:100%;height:auto;border-radius:8px"></figure>
<figure class="chart"><figcaption><strong>Les passes, rangées par dépendance</strong>
<span>Bleu : étage analyse (carte graphique). Gris : étage calcul (processeur). Tiré du registre des passes.</span>
</figcaption>{diagram()}</figure>
<div class="tbl"><table><thead><tr><th>Passe</th><th>Ce qu'elle fait</th><th>Dépend de</th><th>Matériel</th></tr>
</thead><tbody><tr><th colspan="4">Étage analyse</th></tr>{stage_rows("analyse")}
<tr><th colspan="4">Étage calcul</th></tr>{stage_rows("calcul")}</tbody></table></div>

<h2>Les outils</h2>
<div class="tbl"><table><thead><tr><th>Outil</th><th>Rôle dans la chaîne</th></tr></thead><tbody>
<tr><td>YOLO ({esc(Path(prof.model_path).name if prof and prof.model_path else '—')}), suivi
{esc((prof.tracker if prof else '') or '—').upper()}</td><td>détecter et suivre véhicules, deux-roues et
piétons sur chaque caméra</td></tr>
<tr><td>YOLOPv2</td><td>chaussée praticable et lignes de voie (caméra avant) : la voie de chaque usager</td></tr>
<tr><td>SAM3</td><td>marquages au sol aux intersections (lignes d'arrêt, passages piétons, dents de requin)</td></tr>
<tr><td>Profondeur monoculaire (ZoeDepth)</td><td>plan du sol de la caméra avant</td></tr>
<tr><td>IGN : BD TOPO et orthophotos (Géoplateforme)</td><td>emprise des routes, bâtiments, recalage
absolu sur les passages piétons vus du ciel</td></tr>
<tr><td>OpenCV</td><td>lecture des vidéos, flux optique (champ et orientation des caméras mesurés), lignes
droites (distorsion des objectifs mesurée)</td></tr>
<tr><td>Fonctions de WAMA Data</td><td>géométrie (projection au sol, métriques de placement), cinématique
(lissage de Kalman, trous comblés), indicateurs TTC/PET</td></tr>
</tbody></table></div>

<h2>La qualité, mesurée sans vérité terrain</h2>
<p>Il n'y a pas de vérité terrain : la qualité se mesure par la <strong>cohérence</strong>. Un véhicule garé ne
bouge pas ; un même véhicule vu par deux caméras doit être placé au même endroit ; un identifiant ne doit
porter qu'un véhicule. Chaque calcul de suivi le mesure et l'affiche. Dernier calcul :</p>
<div class="tbl"><table><thead><tr><th>Indicateur</th><th>Valeur</th><th>Ce qu'il compte</th></tr></thead>
<tbody>{quality_html}</tbody></table></div>
<p>Chaque amélioration de méthode est une <strong>bascule</strong> qu'on active session par session, et qu'on
ne garde qu'après une comparaison chiffrée. {len(flags_on)} des {len(compute_flags)} bascules de calcul sont
actives sur cette session. Désactivées : {flags_off_text}. Actives :</p>
<ul style="columns:2 260px;column-gap:32px">{flag_items}</ul>

<h2>Les intersections : où en est le rapport</h2>
<p>Le profil vise les <strong>insertions aux intersections</strong>. La base contient aujourd'hui
{nb(conf.count())} situations de conflit en voie de la navette pendant un passage d'intersection
(critiques : {sev.get("critical", 0)}, à surveiller : {sev.get("warn", 0)}, informatives : {sev.get("info", 0)}),
{nb(seg_types.get("insertion_front", 0))} insertions devant la navette et
{nb(seg_types.get("intersection_stop", 0))} attentes détectées par la caméra avant, et {nb(lane_in)} présences
de véhicules dans une voie pendant un passage.</p>
<p>Le rapport centré sur les véhicules présents aux intersections — s'insèrent-ils avant la navette, dans
quelle voie, avec quel niveau de criticité selon le TTC et le PET, à quelle distance et à quelle vitesse — est
<strong>en préparation</strong>. Plusieurs pièces existent déjà mais ne sont pas encore reliées entre elles, et
quatre points sont à corriger avant de s'y fier :</p>
<ul>
<li>le PET est calculé pour chaque véhicule suivi, mais n'entre encore dans aucune sortie ;</li>
<li>l'information « la navette est passée en premier » est enregistrée avec le sens inversé ;</li>
<li>la détection des insertions compare des instants qui ne sont pas sur la même base de temps (GPS et
vidéo) — décalage à mesurer ;</li>
<li>le rayon d'intérêt d'une intersection, distinct de son rayon d'analyse, n'est encore appliqué à aucun
rapport.</li>
</ul>
'''

page = fill_shell(
    title="Analyse vidéo d'une navette autonome aux intersections",
    kicker='Analyse · navette autonome · WAMA Lab',
    sub=f'Pipeline du cam_analyzer appliqué aux données ENA · généré le {date_fr}',
    comment=("  Rapport « pipeline du cam_analyzer » sur les données ENA — GÉNÉRÉ par\n"
             "  `scripts/reports/build_cam_analyzer_report.py` depuis les registres (passes, fonctions,\n"
             "  bascules) et la base (session, profil, indicateurs). Ne pas l'éditer à la main : relancer le\n"
             "  script. Même enveloppe que le rapport de transcription (`report_shell.html`).\n"),
    foot=("Généré depuis les registres de WAMA et la base de la session : passes et dépendances "
          "(pass_tracking), fonctions déclarées (catalogue), bascules (features). La chaîne est décrite "
          "dans CAM_ANALYZER_CHAINE_TRAITEMENT, ses changements dans CAM_ANALYZER_CHANGELOG."),
    body=body.replace('<table>', '<table>'))
OUT.write_text(page, encoding='utf-8')
print('written', OUT, len(page), 'bytes')
