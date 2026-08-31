"""
Générateur de QR codes — brique COMMUNE (aucune logique d'app ici).

POURQUOI UNE BRIQUE ET PAS UNE APP : un QR est déterministe (zéro modèle, zéro GPU) et
sert des surfaces de natures différentes — l'appariement de canal (passerelle, ROADMAP
§19.1 : le bot joint un QR qui ouvre la page de profil avec le code prérempli), demain
l'enrôlement TOTP (`otpauth://`) et un domaine `qrcode` de l'Imager (QR artistique via
ControlNet, où le QR déterministe devient le conditionnement). Le loger dans une app
forcerait les autres surfaces à l'importer d'un domicile qui n'est pas le sien.

⚠ CE QU'UN QR N'EST PAS ICI : un canal d'authentification. Un QR ENCODE, il ne PROUVE
rien — celui d'appariement ne fait qu'éviter la retape du code, et c'est toujours la
session WAMA authentifiée qui scelle la liaison (« le canal propose, WAMA dispose »,
`gateway/models.py`). Ne jamais encoder un jeton qui connecterait le scanneur : ce
serait inverser ce modèle (détournement type QRLjacking).

`segno` (pur Python, BSD-3-Clause — licence lue AU TEXTE le 2026-08-31, zéro dépendance)
est importé TARDIVEMENT : le module se laisse importer sans lui, seuls les appels échouent
avec un message d'installation — même patron que `discord.py` dans l'adaptateur.
"""
from __future__ import annotations

import io


def _segno():
    try:
        import segno
    except ImportError as e:  # pragma: no cover — dépend de l'environnement
        raise RuntimeError(
            "segno n'est pas installé. `pip install 'segno>=1.6'` "
            "(déclaré dans requirements.txt)."
        ) from e
    return segno


def _make(data: str):
    """⚠ `make_qr`, jamais `make` : pour une donnée courte, `make` choisit un MICRO QR,
    que beaucoup de lecteurs de smartphone (et OpenCV) ne décodent pas. Un QR que le
    téléphone ne lit pas est pire que pas de QR — l'utilisateur accuse le service."""
    return _segno().make_qr(data)


def qr_png(data: str, *, scale: int = 6, border: int = 4) -> bytes:
    """Le QR en PNG (octets, en mémoire) — la forme qui se JOINT (message Discord, mail).

    `scale` : pixels par module (6 ≈ 250 px pour une URL courte, confortable au scan
    d'écran). `border` : zone de silence en modules (4 = minimum de la norme)."""
    buffer = io.BytesIO()
    _make(data).save(buffer, kind='png', scale=scale, border=border)
    return buffer.getvalue()


def qr_svg(data: str, *, scale: int = 6, border: int = 4) -> str:
    """Le QR en SVG (texte) — la forme qui s'EMBARQUE dans une page (enrôlement TOTP à
    venir) : vectoriel, net à toute taille, plus léger qu'un PNG."""
    buffer = io.BytesIO()
    _make(data).save(buffer, kind='svg', scale=scale, border=border)
    return buffer.getvalue().decode('utf-8')
