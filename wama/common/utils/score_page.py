"""La PAGE porte-t-elle une partition ? — compter ses PORTÉES (2026-11-08).

Demande de Fabien (lecture de partition du Reader) : *« une détection automatique avec switch
automatique, mais qui peut rester un choix de l'utilisateur »*. La décision « texte ou partition »
se PROPOSE d'après le fichier (`Param.default_from`, propriété `has_staves` de la sonde commune,
`media_probe.INPUT_PROPERTIES`) ; elle ne se tranche pas ici.

Une portée, c'est CINQ lignes horizontales LONGUES (elles barrent la page d'une marge à l'autre)
et RÉGULIÈREMENT espacées. Une ligne de texte n'encre qu'une petite part de sa rangée de pixels ;
un filet de tableau isolé n'a pas ses quatre voisins à intervalle égal. Rien n'est appris, aucun
modèle n'est chargé : une rangée de pixels se mesure par sa part d'encre.

⚠ Ce que la règle ne voit pas : une photo de travers (une ligne inclinée ne remplit plus aucune
rangée), un manuscrit sans portée imprimée. La proposition se trompe alors en le disant, et
l'utilisateur la change — c'est le contrat de `default_from`.
"""
from __future__ import annotations

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


def _gray_pages(path: str):
    """Les pages d'une image ou des premières pages d'un PDF, en tableaux de gris."""
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
    with Image.open(path) as image:
        image = image.convert('L')
        if image.width > MAX_WIDTH:
            image = image.resize((MAX_WIDTH, round(image.height * MAX_WIDTH / image.width)),
                                 Image.BOX)
        yield np.asarray(image)


def page_staves(path: str):
    """Le plus grand nombre de portées sur une page de `path` (image, ou les `PDF_PAGES`
    premières d'un PDF) — None pour un fichier illisible."""
    try:
        return max((count_staves(gray) for gray in _gray_pages(path)), default=0)
    except Exception:
        return None
