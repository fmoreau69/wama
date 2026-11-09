"""La PAGE porte-t-elle une partition ? — compter ses PORTÉES (2026-11-08).

Demande de Fabien (lecture de partition du Reader) : *« une détection automatique avec switch
automatique, mais qui peut rester un choix de l'utilisateur »*. La décision « texte ou partition »
se PROPOSE d'après le fichier (`Param.default_from`, propriété `has_staves` de la sonde commune,
`media_probe.INPUT_PROPERTIES`) ; elle ne se tranche pas ici.

Une portée, c'est CINQ lignes horizontales LONGUES (elles barrent la page d'une marge à l'autre)
et RÉGULIÈREMENT espacées. Une ligne de texte n'encre qu'une petite part de sa rangée de pixels ;
un filet de tableau isolé n'a pas ses quatre voisins à intervalle égal. Rien n'est appris, aucun
modèle n'est chargé : une rangée de pixels se mesure par sa part d'encre.

⚠ Ce que la règle ne voit pas : un manuscrit sans portée imprimée. La proposition se trompe alors
en le disant, et l'utilisateur la change — c'est le contrat de `default_from`.

UNE PHOTO SE REMET D'APLOMB AVANT D'ÊTRE MESURÉE (2026-11-08, mesuré sur six photos de partitions
de batterie de Fabien) : la sonde disait « aucune portée » sur les six. Trois causes, chacune vue :
  • l'étiquette EXIF d'orientation n'était pas appliquée — une photo de téléphone se lisait couchée,
    ses portées verticales ;
  • une photo « droite » penche d'un ou deux degrés : sur 1 500 pixels de portée, 1,8° décalent la
    ligne de 47 rangées, aucune ne se remplit ;
  • la feuille n'occupe qu'une part de la photo (le bureau autour) : une ligne de portée n'y remplit
    plus 30 % de la LARGEUR DE LA PHOTO.
D'où `level_gray` : l'EXIF, puis l'ANGLE des lignes longues (`page_angle`, celui qui rend le profil
horizontal de l'encre le plus contrasté — les portées, les lignes de texte), puis la FEUILLE
(`paper_box`, la plus grande zone claire). La même mise d'aplomb sert la lecture (`level_page`) :
copisteria ne redresse rien, une page penchée de 22° n'y donnait qu'une mesure. Les quarts de tour
restent au classifieur d'orientation (`ocr_base.upright_image`), appelé avant.
"""
from __future__ import annotations

import re

#: Lignes d'une portée.
STAFF_LINES = 5
#: Part minimale d'encre d'une rangée de pixels pour qu'elle soit une LIGNE de portée : une portée
#: barre la page d'une marge à l'autre (≈ 70 % de la largeur sur une page imprimée), une ligne de
#: texte en encre 5 à 20 %.
LINE_FILL = 0.3
#: Écart toléré entre le plus grand et le plus petit intervalle des cinq lignes.
MAX_GAP_RATIO = 1.35
#: Intervalle le plus grand, en part de la largeur : au-delà, des filets de tableau, pas une portée.
MAX_GAP_SHARE = 0.03
#: Épaisseur la plus grande d'une ligne, en part de la hauteur (au moins 4 pixels).
MAX_LINE_SHARE = 0.005
#: Un pixel est de l'encre sous ce gris (seuil d'Otsu plafonné : un papier jauni reste du papier).
INK_CEILING = 200
#: Les pages d'un PDF regardées (une partition commence à la première), et leur résolution.
PDF_PAGES = 2
PDF_DPI = 150
#: Largeur au-delà de laquelle une image est réduite avant la mesure (le coût, pas la précision).
MAX_WIDTH = 2500
#: L'inclinaison la plus forte cherchée, en degrés, de part et d'autre : au-delà, un quart de tour,
#: que le classifieur d'orientation rattrape.
MAX_TILT = 45.0
#: En deçà de cette inclinaison, la page reste telle quelle (rien n'est réécrit pour un rien).
MIN_TILT = 0.3
#: Largeur de l'image où l'angle et la feuille se cherchent (le coût, pas la précision : l'angle est
#: affiné au dixième de degré).
SEARCH_WIDTH = 800
#: La feuille se recadre quand elle laisse au moins cette part de la photo autour d'elle.
PAPER_MARGIN_SHARE = 0.1


def _ink_threshold(gray) -> int:
    """Le seuil d'Otsu de l'histogramme de `gray`, plafonné à `INK_CEILING`."""
    import numpy as np
    hist = np.bincount(gray.ravel(), minlength=256).astype(float)
    total = hist.sum()
    if not total:
        return INK_CEILING
    weights = np.cumsum(hist)
    means = np.cumsum(hist * np.arange(256))
    between = (means[-1] * weights - means * total) ** 2 / np.maximum(weights * (total - weights), 1)
    return int(min(int(np.argmax(between)), INK_CEILING))


def count_staves(gray) -> int:
    """Le nombre de PORTÉES d'une page en niveaux de gris (tableau numpy 2-D, 0 = noir)."""
    import numpy as np
    height, width = gray.shape
    if not height or not width:
        return 0
    # `<=` : le seuil d'Otsu est la dernière valeur de la classe sombre — sur une page parfaitement
    # noire et blanche (0 et 255), il vaut 0, et `<` n'y aurait vu aucune encre.
    fill = (gray <= _ink_threshold(gray)).mean(axis=1)
    rows = np.flatnonzero(fill >= LINE_FILL)
    thick = max(4, int(height * MAX_LINE_SHARE))
    centers, start = [], None
    for index, row in enumerate(rows):
        if start is None:
            start = row
        if index + 1 == len(rows) or rows[index + 1] != row + 1:
            if row - start + 1 <= thick:          # une ligne mince ; un aplat n'est pas une ligne
                centers.append((start + row) / 2)
            start = None
    staves, i = 0, 0
    while i + STAFF_LINES <= len(centers):
        gaps = np.diff(centers[i:i + STAFF_LINES])
        if (gaps.min() >= 2 and gaps.max() <= MAX_GAP_RATIO * gaps.min()
                and gaps.max() <= MAX_GAP_SHARE * width):
            staves += 1
            i += STAFF_LINES
        else:
            i += 1
    return staves


# ── Mettre une photo d'aplomb ────────────────────────────────────────────────────────────────

def _shrunk(gray):
    """`gray` réduit à `SEARCH_WIDTH` de large, et le facteur appliqué."""
    import cv2
    height, width = gray.shape
    if width <= SEARCH_WIDTH:
        return gray, 1.0
    factor = SEARCH_WIDTH / width
    return cv2.resize(gray, (SEARCH_WIDTH, max(1, round(height * factor))),
                      interpolation=cv2.INTER_AREA), factor


def _local_ink(gray):
    """L'encre : un pixel plus sombre que son VOISINAGE (seuil adaptatif). Le bureau noir autour
    d'une feuille photographiée n'en est pas — un seuil global l'y compterait tout entier."""
    import cv2
    block = max(15, (min(gray.shape) // 40) | 1)
    return cv2.adaptiveThreshold(gray, 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV,
                                 block, 15)


def _rotated(image, angle: float, fill: int, expand: bool = True):
    """`image` tournée de `angle` degrés (sens trigonométrique, celui d'OpenCV), agrandie pour n'en
    rien couper quand `expand`, le fond rempli de `fill`."""
    import cv2
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    size = (width, height)
    if expand:
        cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
        size = (int(height * sin + width * cos), int(height * cos + width * sin))
        matrix[0, 2] += size[0] / 2 - width / 2
        matrix[1, 2] += size[1] / 2 - height / 2
    return cv2.warpAffine(image, matrix, size, flags=cv2.INTER_LINEAR, borderValue=fill)


def page_angle(gray, span: float = MAX_TILT) -> float:
    """L'angle (degrés) qui met d'aplomb les lignes longues d'une page en gris : celui qui rend le
    profil horizontal de son encre le plus CONTRASTÉ (somme des carrés des parts d'encre par rangée)
    — une ligne de portée ou de texte remplit alors une rangée au lieu d'en effleurer cent. Cherché
    au degré sur ±`span`, puis au dixième autour du meilleur."""
    import numpy as np
    small, _ = _shrunk(gray)
    ink = _local_ink(small)

    def contrast(angle):
        profile = _rotated(ink, angle, 0, expand=False).mean(axis=1)
        return float((profile ** 2).sum())

    best = max(np.arange(-span, span + 0.01, 1.0), key=contrast)
    return round(float(max(np.arange(best - 1, best + 1.01, 0.1), key=contrast)), 1)


def paper_box(gray):
    """La FEUILLE dans une photo en gris : la boîte `(x0, y0, x1, y1)` de la plus grande zone claire,
    ou None quand elle couvre (presque) toute l'image — un scan, une page déjà recadrée."""
    import cv2
    small, factor = _shrunk(gray)
    blurred = cv2.GaussianBlur(small, (9, 9), 0)
    _, bright = cv2.threshold(blurred, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    count, _, stats, _ = cv2.connectedComponentsWithStats(bright, connectivity=4)
    if count < 2:
        return None
    label = 1 + int(stats[1:, cv2.CC_STAT_AREA].argmax())
    x, y, w, h = (int(v) for v in stats[label, :4])
    height, width = small.shape
    if w * h >= (1 - PAPER_MARGIN_SHARE) * width * height:
        return None
    return (round(x / factor), round(y / factor), round((x + w) / factor), round((y + h) / factor))


def _level(gray):
    """`(page, changée)` : la page en gris mise d'APLOMB (`page_angle`) puis recadrée sur sa feuille
    (`paper_box`), et si l'un des deux gestes a eu lieu."""
    angle = page_angle(gray)
    tilted = abs(angle) >= MIN_TILT
    if tilted:
        # Le fond ajouté est NOIR pour chercher la feuille (il n'en fait pas partie), BLANC pour la
        # page rendue (il ne doit rien encrer).
        box = paper_box(_rotated(gray, angle, 0))
        gray = _rotated(gray, angle, 255)
    else:
        box = paper_box(gray)
    if box:
        x0, y0, x1, y1 = box
        gray = gray[y0:y1, x0:x1]
    return gray, bool(tilted or box)


def level_gray(gray):
    """La page en gris mise d'aplomb et recadrée sur sa feuille (`_level`)."""
    return _level(gray)[0]


def _upright_gray(path: str):
    """L'image `path` en gris, son étiquette EXIF d'orientation appliquée (une photo de téléphone
    est rangée couchée), en tableau numpy."""
    import numpy as np
    from PIL import Image, ImageOps
    with Image.open(path) as image:
        return np.asarray(ImageOps.exif_transpose(image).convert('L'))


def level_page(path: str, folder: str) -> str:
    """Le chemin de la page `path` (une IMAGE) mise d'aplomb et recadrée sur sa feuille, écrite en
    PNG dans `folder` — ou `path` lui-même quand elle est déjà droite et sans bord à retirer.
    L'original n'est jamais modifié."""
    from pathlib import Path

    from PIL import Image
    leveled, changed = _level(_upright_gray(path))
    if not changed:
        return path
    target = Path(folder) / f"{Path(path).stem}_level.png"
    Image.fromarray(leveled).save(target)
    return str(target)


def _gray_pages(path: str):
    """Les pages d'une image ou des premières pages d'un PDF, en tableaux de gris — une image mise
    d'aplomb et recadrée sur sa feuille (`level_gray`)."""
    from pathlib import Path

    import numpy as np
    from PIL import Image
    if Path(path).suffix.lower() == '.pdf':
        import fitz
        with fitz.open(path) as doc:
            for page in list(doc)[:PDF_PAGES]:
                pix = page.get_pixmap(dpi=PDF_DPI, colorspace=fitz.csGRAY, alpha=False)
                yield np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
        return
    gray = _upright_gray(path)
    if gray.shape[1] > MAX_WIDTH:
        image = Image.fromarray(gray)
        gray = np.asarray(image.resize((MAX_WIDTH, round(image.height * MAX_WIDTH / image.width)),
                                       Image.BOX))
    yield level_gray(gray)


# ── Le texte d'une page de partition ─────────────────────────────────────────────────────────
# Une partition porte du TEXTE à des places convenues : le titre en tête, en grand ; le compositeur
# en tête, à droite ; le numéro de page en tête ou au pied ; les mentions au fil des portées (« x3 »,
# « 58 second »). Le moteur de lecture le sait en partie — copisteria lit un titre et des mots si on
# lui donne les boîtes de texte AVEC LEUR RÔLE ; il n'a pas d'OCR. Ces rôles se donnent ici, à partir
# des lignes d'un OCR qui rend la place du texte (`OCRBackend.read_lines`), par leur seule PLACE et
# leur TAILLE : rien n'est appris.

#: Les rôles qu'une ligne de texte reçoit (`page_texts` du contrat `ScoreReadingBackend`).
TEXT_ROLES = ('title', 'composer', 'subtitle', 'page_number', 'footer', 'repeat_count', 'words')
#: La tête de page : la part haute où se cherchent titre, compositeur et numéro.
HEAD_SHARE = 0.15
#: Le pied de page : la part basse (copyright, numéro).
FOOT_SHARE = 0.07
#: La confiance d'OCR sous laquelle une ligne n'est pas retenue (les têtes de notes lues « X »…).
MIN_TEXT_CONF = 0.5
#: Lettres d'un titre, d'un nom : en deçà, un sigle ou du bruit.
MIN_NAME_LETTERS = 3
#: Un compositeur est à droite : le centre de sa ligne au-delà de cette part de la largeur.
COMPOSER_X_SHARE = 0.6


def _letters(text: str) -> int:
    return sum(ch.isalpha() for ch in text)


def text_roles(page: dict) -> dict:
    """La page `page` (forme de `OCRBackend.read_lines` : `width`, `height`, `lines`) dont chaque
    ligne retenue porte son `role` (`TEXT_ROLES`) — et `times` pour un nombre de passages, `number`
    pour un numéro de page. Une ligne de confiance trop faible est écartée."""
    from wama.common.utils.musicxml_score import repeat_count
    width, height = float(page.get('width') or 1), float(page.get('height') or 1)
    lines = []
    for line in page.get('lines') or []:
        text = ' '.join(str(line.get('text') or '').split())
        if not text or float(line.get('conf', 1.0)) < MIN_TEXT_CONF:
            continue
        lines.append(dict(line, text=text))
    head, rest = [], []
    for line in lines:
        x0, y0, x1, y1 = line['bbox']
        times = repeat_count(line['text'])
        in_head, in_foot = y1 <= HEAD_SHARE * height, y0 >= (1 - FOOT_SHARE) * height
        if times:
            line.update(role='repeat_count', times=times)
        elif line['text'].isdigit() and len(line['text']) <= 3 and (in_head or in_foot):
            line.update(role='page_number', number=int(line['text']))
        elif in_head and _letters(line['text']) >= MIN_NAME_LETTERS:
            head.append(line)
            continue
        else:
            line['role'] = 'footer' if in_foot else 'words'
        rest.append(line)
    if head:
        title = max(head, key=lambda l: (l['bbox'][3] - l['bbox'][1], l.get('conf', 0)))
        # Le compositeur et le numéro de page sont dans la BANDE du titre (à sa hauteur, ou
        # au-dessus) : sous elle, la tête de page porte déjà de la musique — mesuré le 2026-11-08,
        # les légendes d'une « clé de batterie » (« Tom Toms », « Crash Cymbal ») prises pour des
        # compositeurs, le « 2 » d'une reprise de deux mesures pris pour un numéro de page.
        band = title['bbox'][3]
        for line in head:
            centre = (line['bbox'][0] + line['bbox'][2]) / 2
            line['role'] = ('title' if line is title else
                            'composer' if centre > COMPOSER_X_SHARE * width and line['bbox'][1] < band
                            else 'subtitle')
        for line in rest:
            if line.get('role') == 'page_number' and line['bbox'][1] < HEAD_SHARE * height \
                    and line['bbox'][1] >= band:
                line['role'] = 'words'
                line.pop('number', None)
    return dict(page, lines=sorted(head + rest, key=lambda l: (l['bbox'][1], l['bbox'][0])))


def page_identity(page: dict) -> dict:
    """`{'title', 'composer', 'page_number'}` d'une page aux rôles donnés (`text_roles`) — '' / None
    pour ce qu'elle ne porte pas."""
    def first(role):
        return next((l for l in page.get('lines') or [] if l.get('role') == role), None)
    title, composer, number = first('title'), first('composer'), first('page_number')
    return {'title': title['text'] if title else '', 'composer': composer['text'] if composer else '',
            'page_number': number['number'] if number else None}


def text_quality(page: dict) -> float:
    """Ce que vaut la lecture du texte d'une page : la somme, sur ses lignes, de la confiance par le
    nombre de lettres. Une page lue à l'envers rend du bruit peu sûr — c'est ce qui départage les
    deux sens d'une page (`ocr_base.upright_image` peut retourner une partition : son classifieur
    d'orientation a appris sur du texte ; mesuré le 2026-11-08 sur une page de batterie droite)."""
    return sum(float(l.get('conf', 0)) * _letters(str(l.get('text') or ''))
               for l in page.get('lines') or [] if _letters(str(l.get('text') or '')) >= MIN_NAME_LETTERS)


def half_turned(path: str, folder: str) -> str:
    """La page `path` tournée d'un demi-tour, écrite en PNG dans `folder`."""
    from pathlib import Path

    from PIL import Image
    target = Path(folder) / f"{Path(path).stem}_turned.png"
    with Image.open(path) as image:
        image.rotate(180, expand=True).save(target)
    return str(target)


# ── La légende d'une partition de batterie (« Drum Key ») ─────────────────────────────────────

#: Le mot qui annonce une légende, à gauche de sa portée (« Drum Key », « Legend », « Légende »).
KEY_WORDS = re.compile(r'\b(key|legend|l[ée]gende)\b', re.I)
#: La bande sous la portée où se lisent ses étiquettes, en interlignes de la portée.
LABEL_DEPTH = 5.0


def _centre(box) -> float:
    return (box[0] + box[2]) / 2


def drum_key(lines: list, staves: list):
    """La LÉGENDE de batterie d'une page (demande de Fabien, 2026-11-09 : « lire la légende de la
    page ») — `{'staff', 'system', 'entries': [{'pos', 'name', 'sound'}], 'ambiguous': [pos]}`, ou
    None quand aucune portée n'en porte.

    `lines` : les lignes de texte de la page (`{'text', 'bbox'}`) ; `staves` : ses portées
    (`{'index', 'system', 'box', 'space', 'notes': [{'x', 'pos'}]}`), lignes et portées dans la même
    unité. `pos` est la place d'une tête sur la portée, en demi-interlignes (0 = ligne du milieu).

    Une portée est une légende quand un mot-clé (`KEY_WORDS`) est écrit à sa gauche, à sa hauteur.
    Chaque note reçoit l'étiquette la plus proche en largeur sous la portée ; une seconde rangée
    d'étiquettes nomme une FAMILLE (« Snare Drum » sous « Normal » et « Crosstick » : deux têtes de
    la même caisse, que la lecture ne distingue pas). Une place que la légende donne à deux
    instruments ne reçoit aucun nom (`ambiguous`) : un nom faux est pire qu'aucun. Une famille qui
    couvre plusieurs places (« Tom-Toms ») les numérote de la plus haute à la plus basse."""
    from wama.common.utils.midi_score import TOM_SOUNDS, drum_sound
    for staff in staves:
        x0, y0, x1, y1 = staff['box']
        space = float(staff.get('space') or (y1 - y0) / 4 or 1)
        # La boîte d'une portée lue peut ne couvrir qu'une part de ses notes (mesuré le 2026-11-09 :
        # la mesure d'une légende finissait au deuxième tom, celle d'une autre photo commençait au
        # charleston) : la largeur couvre aussi les notes.
        xs = [note['x'] for note in staff.get('notes') or ()]
        x0, x1 = min([x0] + xs), max([x1] + xs)
        keyed = [l for l in lines if KEY_WORDS.search(l['text'])
                 and l['bbox'][2] <= x0 + space and l['bbox'][1] < y1 + 2 * space
                 and l['bbox'][3] > y0 - 2 * space]
        if not keyed or not staff.get('notes'):
            continue
        labels = [l for l in lines if l not in keyed and _letters(l['text']) >= 2
                  and x0 - space <= _centre(l['bbox']) <= x1 + space
                  and y1 - space <= l['bbox'][1] <= y1 + LABEL_DEPTH * space]
        if not labels:
            continue
        top = min(l['bbox'][1] for l in labels)
        height = sorted(l['bbox'][3] - l['bbox'][1] for l in labels)[len(labels) // 2]
        first = [l for l in labels if l['bbox'][1] <= top + height / 2]
        second = [l for l in labels if l not in first]
        family = {}
        for label in first:
            for below in second:
                if below['bbox'][0] < label['bbox'][2] and label['bbox'][0] < below['bbox'][2]:
                    family[id(label)] = below['text']
        names = {}                                       # place → noms lus
        for note in staff['notes']:
            label = min(first, key=lambda l: abs(_centre(l['bbox']) - note['x']))
            names.setdefault(note['pos'], set()).add(drum_sound(family.get(id(label), label['text'])))
        ambiguous = sorted(pos for pos, found in names.items() if len(found) > 1)
        by_name = {}
        for pos, found in names.items():
            if pos not in ambiguous:
                by_name.setdefault(next(iter(found)), []).append(pos)
        entries = []
        for (name, sound), places in by_name.items():
            places.sort(reverse=True)
            for rank, pos in enumerate(places):
                own_sound = sound
                if len(places) > 1 and sound in TOM_SOUNDS:
                    own_sound = TOM_SOUNDS[round(rank * (len(TOM_SOUNDS) - 1) / (len(places) - 1))]
                entries.append({'pos': pos, 'name': f'{name} {rank + 1}' if len(places) > 1 else name,
                                'sound': own_sound})
        if entries:
            return {'staff': staff['index'], 'system': staff.get('system'),
                    'entries': sorted(entries, key=lambda e: e['pos']), 'ambiguous': ambiguous}
    return None


def page_staves(path: str):
    """Le plus grand nombre de portées sur une page de `path` (image, ou les `PDF_PAGES`
    premières d'un PDF) — None pour un fichier illisible. Une page qui n'en montre aucune est
    regardée aussi d'un quart de tour : une photo prise de côté, sans étiquette EXIF."""
    import numpy as np
    try:
        best = 0
        for gray in _gray_pages(path):
            best = max(best, count_staves(gray))
            if not best:
                best = count_staves(level_gray(np.ascontiguousarray(np.rot90(gray))))
        return best
    except Exception:
        return None
