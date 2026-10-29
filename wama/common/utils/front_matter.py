"""
L'EN-TÊTE d'un texte (« front matter ») : le bloc `---` … `---` qui ouvre un SKILL.md, et la réponse
d'olmOCR-2 (langue, rotation, tableau, schéma). Une lecture, trois lecteurs (2026-10-29) : le
catalogue des skills et `check_skills` la recopiaient chacun, l'OCR allait en faire une troisième.

Sans PyYAML, volontairement : les lecteurs ne veulent que des clés PLATES, et une page d'affichage
ne dépend pas d'un format tiers pour ça.
"""


def split_front_matter(text: str) -> tuple[str, str]:
    """`(en-tête, corps)` — l'en-tête sans ses lignes `---` ; `('', text)` sans en-tête complet.
    Le corps commence juste après le `---` de fermeture (son saut de ligne compris)."""
    text = text or ''
    if not text.startswith('---'):
        return '', text
    end = text.find('\n---', 3)
    if end == -1:
        return '', text
    return text[3:end], text[end + len('\n---'):]


def flat_keys(header: str, keep=None) -> dict:
    """Les clés plates `clé: valeur` d'un en-tête (valeurs en texte, espaces de bord retirés) —
    toutes, ou seulement celles de `keep`."""
    out = {}
    for line in (header or '').splitlines():
        key, sep, value = line.partition(':')
        key = key.strip()
        if sep and (keep is None or key in keep):
            out[key] = value.strip()
    return out
