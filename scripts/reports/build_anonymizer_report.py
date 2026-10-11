# Construit la page WAMA du rapport d'évaluation des détecteurs de l'Anonymizer (menu « Présentations &
# annexes » › Rapports, `wama.views.REPORTS`). Les CHIFFRES viennent de la base, jamais recopiés : les mesures
# rangées par le banc (`ResultEvaluation`, `bench --task detect-boxes|detect-recall --record`), les fiches du
# catalogue (`AIModel` : nom, licence, source) et le choix automatique de l'Anonymizer, recalculé par sa propre
# fonction (`select_best_models_by_precision`). Le texte qui les relie est écrit ici ; une phrase qui cite un
# chiffre le tire des mesures.
#
# Usage (racine du dépôt, venv_linux) — lit la base, n'écrit que le gabarit :
#     python manage.py shell < scripts/reports/build_anonymizer_report.py
# Relancer après chaque campagne de banc : le classement, les tableaux et les recommandations suivent.
import datetime as dt
import html
import json
import sys
from pathlib import Path

from wama.anonymizer.utils.model_config import RECALL_FLOOR
from wama.anonymizer.utils.model_selector import select_best_models_by_precision
from wama.common.models import ResultEvaluation
from wama.model_manager.models import AIModel
from wama.model_manager.services import bench
from wama.model_manager.services.eta_estimator import learned_speed

HERE = Path('scripts/reports')
sys.path.insert(0, str(HERE))
from shell_page import fill_shell  # noqa: E402

OUT = Path('wama/templates/includes/wama_rapport_anonymizer.html')
FACES = 'faces_wider_val_v1'
esc = lambda s: html.escape(str(s), quote=False)  # noqa: E731
MONTHS = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre',
          'novembre', 'décembre')


def date_fr(d):
    return f'{d.day} {MONTHS[d.month - 1]} {d.year}'


def pct(v, digits=1):
    return '—' if v is None else f'{100 * v:.{digits}f}'.replace('.', ',') + ' %'


def nb(n):
    return f'{n:,}'.replace(',', ' ')


# D'où vient chaque famille de détecteurs : ce que ni le catalogue ni la mesure ne disent. Écrit pour le
# lecteur ; une famille absente d'ici est signalée par le script (et affichée « non renseigné »).
FAMILIES = [
    ('lindevs', 'lindevs/yolov9-face', 'WIDER FACE (partie entraînement)'),
    ('yolo26', 'akanametov/yolo-face', 'WIDER FACE (partie entraînement)'),
    ('yolov11l-face', 'akanametov/yolo-face', 'WIDER FACE (partie entraînement)'),
    ('yolov12l-face', 'akanametov/yolo-face', 'non dit par l\'auteur (WIDER FACE probable)'),
    ('egoblur', 'Meta (EgoBlur)', 'données propres à Meta, vidéo à la première personne'),
    ('face_plate_signs', 'Panoramax', 'images de rue (visages, plaques, panneaux)'),
    ('face_plate', 'non renseigné', 'non renseigné'),
    ('rtdetr', 'justjuu (Hugging Face)', 'plaques d\'immatriculation'),
    ('license-plate-finetune', 'non renseigné', 'plaques d\'immatriculation'),
]
# Licence quand le catalogue n'en porte pas (lue sur la page de la source, vérifiée le 2026-10-11).
LICENSES = {'lindevs': 'MIT', 'akanametov': 'GPL-3.0', 'egoblur': 'Apache-2.0', 'rtdetr': 'Apache-2.0'}


def family_of(key):
    for token, author, data in FAMILIES:
        if token in key:
            return author, data
    print('⚠ famille non renseignée :', key)
    return 'non renseigné', 'non renseigné'


def label_of(key, models):
    m = models.get(key)
    name = (m.name if m else key.rsplit(':', 1)[-1])
    return name[:-3] if name.endswith('.pt') else name


def license_of(key, models):
    m = models.get(key)
    if m and m.license:
        return m.license
    for token, lic in LICENSES.items():
        if token in key:
            return lic
    return '—'


# ── Les mesures ─────────────────────────────────────────────────────────────────────────────
faces = list(ResultEvaluation.objects.filter(app=bench.RECALL_APP, object_type=bench.BOXES_OBJECT,
                                             protocol=bench.BOXES_PROTOCOL, reference_name=FACES))
plates = list(ResultEvaluation.objects.filter(app=bench.RECALL_APP, object_type=bench.RECALL_OBJECT,
                                              protocol=bench.RECALL_PROTOCOL))
faces.sort(key=lambda r: r.value)
plates.sort(key=lambda r: r.value)
models = {m.model_key: m for m in AIModel.objects.filter(model_key__in=[r.model_key for r in faces + plates])}
ref_path = bench.benchmark_reference(FACES)
with open(ref_path, encoding='utf-8') as f:
    faces_ref = json.load(f)
last = max(r.measured_at for r in faces + plates)


def speed(r):
    """Temps par image (ms) APPRIS pour ce détecteur sur cette carte — la boucle d'ETA commune, que le
    banc calibre et que le curseur lit (`eta_estimator.comparable_speeds`) ; None s'il n'y est pas, ou
    dans une autre unité. Le temps « mur » des campagnes de rappel mesurait surtout le partage réseau."""
    learned = learned_speed(r.model_key)
    return 1000 * learned[1] if learned and learned[0] == bench.IMAGE_UNIT else None


face_speeds = {r.model_key: speed(r) for r in faces}
plate_speeds = {r.model_key: speed(r) for r in plates}
untimed = [label_of(r.model_key, models) for r in faces + plates if speed(r) is None]
if untimed:
    print('⚠ sans temps propre :', ', '.join(untimed))
f0 = faces[0]
p0 = plates[0]
truth_faces = f0.detail['reference_length']
images_faces = f0.detail['images']


def chart_two_bars(rows, title, sub, note, *, first='Rappel', second='Précision', second_of):
    """Une ligne par modèle : rappel et seconde mesure en barres, le meilleur en couleur."""
    out = [f'<div class="br head"><span></span><span>{first}</span><span>{second}</span></div>']
    for i, r in enumerate(rows):
        recall, other = 1 - r.value, second_of(r)
        cls = ' best' if i == 0 else ''
        lab = label_of(r.model_key, models)
        bar2 = (f'<span class="bar"><i style="width:{100 * other:.1f}%"></i><b>{pct(other)}</b></span>'
                if other is not None else '<span class="bar"><b>—</b></span>')
        out.append(f'<div class="br{cls}" title="{html.escape(lab)}"><span class="lab">{esc(lab)}</span>'
                   f'<span class="cell"><span class="cnd">{first}</span><span class="bar">'
                   f'<i style="width:{100 * recall:.1f}%"></i><b>{pct(recall)}</b></span></span>'
                   f'<span class="cell"><span class="cnd">{second}</span>{bar2}</span></div>')
    return (f'<figure class="chart wide"><figcaption><strong>{esc(title)}</strong><span>{esc(sub)}</span>'
            f'</figcaption>{"".join(out)}<p class="note">{esc(note)}</p></figure>')


# Les noms de détecteurs sont plus longs que ceux des moteurs de transcription : colonne des libellés élargie,
# repliée sur téléphone comme dans l'enveloppe commune.
STYLE = ('<style>.wide .br{grid-template-columns:minmax(150px,230px) 1fr 1fr}'
         '@media (max-width:720px){.wide .br{grid-template-columns:1fr}}</style>')


TINY = bench.SIZE_BUCKETS[0][0]
SIZES = [('large', 'grands'), ('medium', 'moyens'), ('small', 'petits'), ('tiny', f'&lt; {TINY} px')]


def ms(v):
    return '—' if v is None else nb(round(v))


def faces_table():
    head = ''.join(f'<th>{lab}</th>' for _, lab in SIZES)
    rows = []
    for r in faces:
        d = r.detail
        sizes = ''.join(f'<td>{pct((d["by_size"].get(k) or {}).get("recall"), 0)}</td>' for k, _ in SIZES)
        rows.append(f'<tr><td><strong>{esc(label_of(r.model_key, models))}</strong></td><td>{pct(1 - r.value)}</td>'
                    f'<td>{pct(d.get("precision"))}</td>{sizes}<td>{ms(speed(r))}</td></tr>')
    return (f'<div class="tbl"><table><thead><tr><th>Modèle</th><th>Rappel</th><th>Précision</th>{head}'
            f'<th>ms / image</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def provenance_table(rows):
    """D'où viennent les détecteurs : une ligne par famille (auteur), les modèles mesurés listés."""
    # Une famille peut porter deux licences : celle que l'auteur déclare et celle que le catalogue a posée à
    # la découverte (poids dérivés d'Ultralytics) — les deux se montrent, aucune n'est tranchée ici.
    groups = {}
    for r in rows:
        g = groups.setdefault(family_of(r.model_key), ([], []))
        g[0].append(label_of(r.model_key, models))
        lic = license_of(r.model_key, models)
        if lic not in g[1]:
            g[1].append(lic)
    body_rows = ''.join(f'<tr><td>{esc(author)}</td><td>{esc(", ".join(names))}</td><td>{esc(data)}</td>'
                        f'<td>{esc(" / ".join(lics))}</td></tr>' for (author, data), (names, lics) in groups.items())
    return ('<div class="tbl"><table><thead><tr><th>Auteur</th><th>Modèles</th><th>Entraînés sur</th>'
            f'<th>Licence</th></tr></thead><tbody>{body_rows}</tbody></table></div>')


def plates_table():
    rows = []
    for r in plates:
        d = r.detail
        inside = d['inside'] / d['detections'] if d.get('detections') else None
        rows.append(f'<tr><td><strong>{esc(label_of(r.model_key, models))}</strong></td><td>{pct(1 - r.value)}</td>'
                    f'<td>{pct(inside)}</td><td>{ms(speed(r))}</td></tr>')
    return ('<div class="tbl"><table><thead><tr><th>Modèle</th><th>Plaques trouvées</th><th>Détections sur un '
            'véhicule</th><th>ms / image</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


# ── Le choix automatique, recalculé par la fonction de l'Anonymizer ─────────────────────────
CRANS = [(20, 'Rapide'), (50, 'Équilibré'), (90, 'Précis')]


def selection_rows():
    """Une ligne par cran : les détecteurs retenus et le temps de traitement d'une image — la SOMME de leurs
    temps propres, l'Anonymizer les passant l'un après l'autre."""
    out = []
    for level, name in CRANS:
        cells = []
        for classes, speeds, unit in ((['face'], face_speeds, 'photo'),
                                      (['license_plate'], plate_speeds, 'image de vidéo')):
            chosen = select_best_models_by_precision(classes, precision_level=level)['models_to_use']
            names = ', '.join(esc(m['name'][:-3] if m['name'].endswith('.pt') else m['name'])
                              for m in chosen) or '—'
            times = [speeds.get(m['model_key']) for m in chosen]
            total = (f'<br><small>≈ {ms(sum(times))} ms par {unit}</small>'
                     if chosen and None not in times else '')
            cells.append(names + total)
        out.append(f'<tr><td><strong>{name}</strong> ({level})</td><td>{cells[0]}</td><td>{cells[1]}</td></tr>')
    return ''.join(out)


tiny_best = max(faces, key=lambda r: (r.detail['by_size'].get('tiny') or {}).get('recall') or 0)
ego_face = next((r for r in faces if 'egoblur' in r.model_key), None)
ego_text = (f'EgoBlur visages, conçu par Meta pour anonymiser, trouve {pct(1 - ego_face.value)} des visages : il '
            'est pénalisé par les foules (il rend au plus 100 visages par image) et par les très petits visages. ')\
    if ego_face else ''

body = STYLE + f'''
<p>Pour les <strong>visages</strong>, le meilleur détecteur installé est
<strong>{esc(label_of(f0.model_key, models))}</strong> : il retrouve <strong>{pct(1 - f0.value)}</strong> des
{nb(truth_faces)} visages du banc WIDER FACE, et {pct(f0.detail.get("precision"))} de ses détections sont de vrais
visages. Pour les <strong>plaques d'immatriculation</strong> filmées par une caméra embarquée, c'est
<strong>{esc(label_of(p0.model_key, models))}</strong> : {pct(1 - p0.value)} des plaques des véhicules proches.
Aucun détecteur ne voit tout : l'Anonymizer en combine plusieurs par classe, d'autant plus que le réglage de
précision est haut, et une page de correction permet d'ajouter à la main ce qui a été manqué.</p>
<p>Mesuré dans WAMA, par le même chemin de détection que l'Anonymizer (deux tailles d'image pour une photo),
sur {nb(images_faces)} photos annotées à la main pour les visages et {nb(p0.detail["reference_length"])} plaques
pour les plaques. Dernière mesure le {date_fr(last)}.</p>

<h2>Quel réglage choisir</h2>
<p>Le curseur Rapide ↔ Qualité de l'Anonymizer choisit les détecteurs tout seul, à partir des mesures de ce
rapport : il pèse ce que chaque détecteur trouve contre le temps qu'il prend par image. Tout à gauche il
prend le plus rapide, tout à droite celui qui trouve le plus, et entre les deux un compromis — c'est la
même règle que le curseur de toutes les applications de WAMA, et le temps est celui que WAMA apprend pour
estimer la durée d'un traitement. La vitesse ne départage que les détecteurs qui trouvent au moins
{nb(round(100 * RECALL_FLOOR))} % de ce que trouve le meilleur : un détecteur rapide qui laisse passer les
visages n'est pas un réglage rapide, c'est une fuite. Plus haut sur le curseur, il ajoute d'autres détecteurs, rangés par ce
qu'ils trouvent, pour rattraper ce que le premier manque. Voici ce qu'il retient aujourd'hui, avec le
temps de traitement d'une image.</p>
<div class="tbl"><table><thead><tr><th>Réglage</th><th>Visages</th><th>Plaques</th></tr></thead>
<tbody>{selection_rows()}</tbody></table></div>
<p>Pour une photo de foule ou une scène où l'on ne veut rien laisser passer, choisir <strong>Précis</strong>
puis relire le résultat sur la page de correction (bouton ✎ de la carte) : un visage manqué s'y ajoute d'un
cadre, et le floutage se refait seul.</p>

<h2>Visages : le banc WIDER FACE</h2>
<p>WIDER FACE est le banc de référence de la détection de visages : des photos de la vie courante (défilés,
manifestations, sport, réunions…) où chaque visage a été encadré à la main. WAMA utilise sa partie
<strong>validation</strong> : {nb(images_faces)} images, {nb(truth_faces)} visages à trouver. Un visage compte
comme trouvé quand un cadre du détecteur le recouvre à au moins {pct(faces_ref.get("iou", 0.5), 0)}. Les visages que
le jeu marque lui-même comme inexploitables ne comptent ni comme oubli ni comme fausse alerte.</p>
{chart_two_bars(faces, f"{label_of(f0.model_key, models)} trouve {pct(1 - f0.value)} des visages",
                f"{nb(images_faces)} photos, {nb(truth_faces)} visages · rappel : part des visages trouvés · "
                "précision : part des détections qui sont des visages",
                "Plus long = mieux. Seuil de confiance " + str(f0.detail.get("threshold")).replace(".", ",") + ".",
                second_of=lambda r: r.detail.get("precision"))}
<p>Le rappel dépend surtout de la <strong>taille</strong> du visage. Les grands visages sont presque tous
trouvés ; les visages de moins de {TINY} pixels de haut, nombreux dans les foules, restent le point faible de
tous les détecteurs — le meilleur sur eux, {esc(label_of(tiny_best.model_key, models))}, en trouve
{pct((tiny_best.detail["by_size"].get("tiny") or {}).get("recall"))}. {ego_text}</p>
{faces_table()}
<p>Tailles, en hauteur du visage : petits de {bench.SIZE_BUCKETS[0][0]} à {bench.SIZE_BUCKETS[1][0]} pixels,
moyens de {bench.SIZE_BUCKETS[1][0]} à {bench.SIZE_BUCKETS[2][0]}, grands au-delà. Le temps par image est
le temps de traitement d'une photo par l'Anonymizer — la lire, l'analyser à ses deux tailles, rendre les
cadres —, mesuré sur une copie locale de l'image, le modèle déjà chargé et une première image de chauffe
écartée, sur un échantillon régulier de {nb(bench.SPEED_SAMPLE)} photos du banc et sur la carte graphique
du serveur WAMA.</p>
<p>D'où viennent ces détecteurs :</p>
{provenance_table(faces)}

<h2>Plaques : caméra embarquée</h2>
<p>Les plaques ont été mesurées sur une vidéo de caméra embarquée en basse résolution, le cas le plus
difficile. Il n'existe pas encore de cadres de plaques tracés à la main pour ces images : le banc compte
comme trouvée une plaque détectée <strong>sur un véhicule proche</strong> suivi par WAMA, et comme manquée un
véhicule proche sans plaque détectée. C'est une mesure de rappel ; la colonne « détections sur un véhicule »
dit quelle part des détections tombe bien sur un véhicule.</p>
{chart_two_bars(plates, f"{label_of(p0.model_key, models)} trouve {pct(1 - p0.value)} des plaques",
                f"{nb(p0.detail['reference_length'])} véhicules proches · rappel : véhicules dont la plaque est "
                "détectée · seconde barre : détections tombées sur un véhicule",
                "Plus long = mieux.", second='Sur un véhicule',
                second_of=lambda r: (r.detail['inside'] / r.detail['detections']) if r.detail.get('detections')
                else None)}
{plates_table()}
{provenance_table(plates)}
<p>EgoBlur et RT-DETR ne se trompent pas sur les mêmes plaques : réunis par l'Anonymizer, ils en trouvent
plus que chacun seul — c'est ce que fait le choix automatique dès qu'il garde plus d'un détecteur par
classe.</p>

<h2>Ce que ces chiffres ne disent pas</h2>
<ul>
<li><strong>Un détecteur qui encadre la tête</strong> plutôt que le visage (les modèles « visages et plaques »)
est pénalisé par la règle de recouvrement : son cadre couvrirait le visage au floutage, mais il compte comme
un oubli et une fausse alerte. Ces modèles restent loin derrière même quand on corrige cet effet : ils
manquent réellement la plupart des visages de foule.</li>
<li><strong>Plusieurs détecteurs ont appris sur la partie entraînement de WIDER FACE</strong> (colonne
« Entraîné sur ») : ils jouent à domicile. Le banc utilise la partie validation, jamais vue à
l'entraînement, comme le font leurs auteurs ; mais sur des images très différentes (caméra embarquée,
vidéo de surveillance), l'écart avec EgoBlur peut se réduire. Un banc sur nos propres images, à partir des
corrections faites dans l'Anonymizer, le dira.</li>
<li>Le rappel des plaques est mesuré sur <strong>une</strong> vidéo, en basse résolution : il classe les
détecteurs entre eux, il ne promet pas un taux sur d'autres images.</li>
</ul>

<h2>Méthode</h2>
<p>Chaque détecteur passe par le chemin de détection de l'Anonymizer, chargé une seule fois pour tout le
banc. Les cadres trouvés deux fois (une photo est analysée à deux tailles) sont fusionnés avant de compter.
Chaque mesure est rangée en base avec le modèle, la version du protocole et l'empreinte de la référence ;
le choix automatique des détecteurs la lit, et ce rapport se régénère depuis elle. Le temps par image se
mesure à part du rappel (il dépend de la machine, pas des images annotées) : chaque image est d'abord copiée
sur le disque local, hors chronomètre, pour que la lecture du partage réseau des jeux de données n'entre pas
dans la mesure ; pour les plaques, la vidéo entière est traitée et le temps divisé par son nombre
d'images. Ce temps est rangé là où WAMA apprend la durée de ses traitements, par modèle et par carte
graphique : le curseur le lit, et un changement de carte le fait réapprendre. Un détecteur passé sur les
deux bancs (les modèles visages + plaques) garde un seul temps par image, moyenne glissante de ses
mesures.</p>
<div class="tbl"><table><thead><tr><th>Banc</th><th>Données</th><th>Ce qui compte comme trouvé</th>
<th>Protocole</th></tr></thead><tbody>
<tr><td>Visages</td><td>WIDER FACE, validation : {nb(images_faces)} images, {nb(truth_faces)} visages</td>
<td>cadre recouvrant le visage à {pct(faces_ref.get("iou", 0.5), 0)} ou plus</td><td>{esc(bench.BOXES_PROTOCOL)}</td></tr>
<tr><td>Plaques</td><td>vidéo de caméra embarquée, {nb(p0.detail["reference_length"])} véhicules proches</td>
<td>plaque détectée sur le véhicule</td><td>{esc(bench.RECALL_PROTOCOL)}</td></tr>
</tbody></table></div>

<h2>À venir</h2>
<ul>
<li><strong>Vitesse</strong> : la conversion des détecteurs en TensorRT est à mesurer ; elle entrera dans ce
banc comme un détecteur de plus, avec son temps et son rappel.</li>
<li><strong>Nouveaux détecteurs</strong> : Ultralytics annonce YOLO-Face (détection et analyse de visages,
attendu en 2027) ; il entrera dans ce banc à sa sortie.</li>
<li><strong>Un banc sur nos images</strong>, à partir des corrections saisies dans l'Anonymizer, et des cadres
de plaques tracés à la main pour remplacer la mesure par véhicule.</li>
</ul>
'''

page = fill_shell(
    title="Évaluation des détecteurs de l'Anonymizer",
    kicker='Évaluation · anonymisation',
    sub=f'Visages et plaques, mesurés dans WAMA contre une vérité tracée à la main · généré le {date_fr(dt.date.today())}',
    comment=("  Rapport d'évaluation des détecteurs de l'Anonymizer — GÉNÉRÉ par\n"
             "  `scripts/reports/build_anonymizer_report.py` depuis les mesures du banc (`ResultEvaluation`),\n"
             "  le catalogue (`AIModel`) et le choix automatique de l'Anonymizer. Ne pas l'éditer à la main :\n"
             "  relancer le script après une campagne de banc. Même enveloppe que les autres rapports.\n"),
    foot=("Généré depuis les mesures du banc de WAMA (bench --task detect-boxes / detect-recall --record) et le "
          "catalogue des modèles. Méthode et lecture des mesures : WAMA_QUALITE ; campagnes : "
          "PROSPECTION_PIPELINE."),
    body=body)
OUT.write_text(page, encoding='utf-8')
print('written', OUT, len(page), 'bytes')
