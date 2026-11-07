"""
Garde des URL SORTANTES — WAMA ne doit pas devenir une sonde vers son propre réseau.

POURQUOI. Plusieurs chemins font TÉLÉCHARGER le serveur à la demande d'un utilisateur : import
par URL de la card d'entrée, fichier de lot contenant des URL, ingest déclaratif (`WAMA_INGEST`).
Aucun ne validait la cible (relevé le 2026-08-22) : ni schéma, ni liste blanche, ni blocage des
adresses privées. Une URL comme `http://10.0.0.5/`, `http://localhost:8001/` (le service TTS) ou
`http://169.254.169.254/` (métadonnées d'instance) faisait donc interroger l'intérieur du réseau
UGE PAR le serveur, avec ses droits réseau à lui. C'est une SSRF, et elle ne demande aucun
fichier malveillant — juste un champ de saisie.

Vaut pour les comptes AUTHENTIFIÉS aussi : ce n'est pas une question d'ouverture au public mais
de surface de sortie. D'où une garde commune, appelée aux points d'entrée, plutôt qu'un contrôle
par app qui manquerait le prochain appelant.

CE QUE LA GARDE COUVRE, ET CE QU'ELLE NE COUVRE PAS.
  ✓ schéma autre que http/https (file://, gopher://, ftp://…) ;
  ✓ identifiants dans l'URL (`http://user:pass@…`) — exfiltration d'identifiants par redirection ;
  ✓ hôte résolvant vers une adresse PRIVÉE, de bouclage, lien-local, réservée ou multicast —
    en IPv4 comme en IPv6, y compris les formes littérales (`http://[::1]/`, `http://0177.0.0.1/`
    que `ipaddress` normalise) ;
  ✗ **rebinding DNS** : entre la résolution ici et la connexion réelle, un DNS hostile peut
    changer sa réponse. S'en prémunir exige d'épingler l'IP résolue jusqu'à la socket (adaptateur
    HTTP dédié), ce que `yt_dlp` ne permet pas simplement. La garde arrête l'attaque directe et
    évidente, pas un adversaire déterminé — le dire ici plutôt que laisser croire à une immunité ;
  ✓ **redirections** : une cible publique peut rediriger vers une adresse interne. Un appelant
    qui suit des redirections passe par `guarded_request`, qui juge chaque saut AVANT de
    l'envoyer (2026-11-06 ; `verifier_redirections`, qui relisait l'historique d'une réponse déjà
    obtenue — la requête interne était partie —, est retiré : `REMOVAL_LEDGER R223`).

Un environnement de dev peut avoir besoin de cibles locales : `WAMA_URL_GUARD_ALLOW_PRIVATE=1`
lève le blocage des adresses privées. Jamais en production.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

SCHEMAS_AUTORISES = ('http', 'https')


class UrlRefusee(ValueError):
    """URL rejetée par la garde de sortie. Message destiné à l'utilisateur."""


def _autorise_prive() -> bool:
    return os.environ.get('WAMA_URL_GUARD_ALLOW_PRIVATE', '') in ('1', 'true', 'True')


def _adresse_interdite(ip: str) -> str:
    """Motif de refus d'une IP, ou '' si elle est acceptable."""
    try:
        adr = ipaddress.ip_address(ip)
    except ValueError:
        return ''                                   # pas une IP littérale : rien à dire ici
    if adr.is_loopback:
        return 'adresse de bouclage'
    if adr.is_private:
        return 'adresse privée (réseau interne)'
    if adr.is_link_local:
        return 'adresse lien-local'
    if adr.is_reserved or adr.is_multicast or adr.is_unspecified:
        return 'adresse réservée'
    return ''


def verifier_url(url: str) -> str:
    """Valide une URL sortante. Rend l'URL normalisée, ou lève `UrlRefusee`.

    À appeler AVANT toute requête réseau déclenchée par une saisie utilisateur.
    """
    brut = (url or '').strip()
    if not brut:
        raise UrlRefusee("URL vide.")

    decoupe = urlparse(brut)
    if decoupe.scheme.lower() not in SCHEMAS_AUTORISES:
        raise UrlRefusee(
            f"Schéma « {decoupe.scheme or '?'} » refusé — seuls http et https sont acceptés.")
    if decoupe.username or decoupe.password:
        raise UrlRefusee("Les identifiants dans l'URL ne sont pas acceptés.")
    hote = decoupe.hostname
    if not hote:
        raise UrlRefusee("URL sans nom d'hôte.")

    if _autorise_prive():
        return brut

    # Hôte littéral (http://10.0.0.5/, http://[::1]/) : refus immédiat, sans résolution.
    motif = _adresse_interdite(hote)
    if motif:
        raise UrlRefusee(f"Cible interdite ({motif}) : {hote}")

    # Nom d'hôte : refuser si UNE de ses adresses est interne. Un nom peut en résoudre
    # plusieurs (A + AAAA) et il suffit d'une interne pour que la cible soit atteignable.
    try:
        infos = socket.getaddrinfo(hote, None)
    except socket.gaierror as e:
        raise UrlRefusee(f"Hôte introuvable : {hote} ({e.strerror or e})")
    for famille, *_reste, adresse in infos:
        ip = adresse[0]
        motif = _adresse_interdite(ip)
        if motif:
            raise UrlRefusee(f"Cible interdite ({motif}) : {hote} → {ip}")
    return brut


#: Sauts de redirection suivis au plus par `guarded_request`.
MAX_REDIRECTS = 5


def guarded_request(method: str, url: str, **kwargs):
    """Une requête `requests` dont CHAQUE saut est jugé AVANT d'être envoyé (2026-11-06, audit de
    sécurité). `verifier_redirections` relisait l'historique d'une réponse déjà obtenue : la
    requête vers l'adresse interne était PARTIE — SSRF aveugle, mais réelle contre tout service
    interne qui agit en GET. Ici les redirections ne sont jamais suivies par `requests`
    (`allow_redirects=False`) : on lit `Location`, on juge, puis on envoie.

    Rend la réponse finale (mêmes arguments que `requests.request`, `stream` compris) ; lève
    `UrlRefusee` sur un saut interdit ou au-delà de `MAX_REDIRECTS`."""
    import requests
    from urllib.parse import urljoin
    kwargs.pop('allow_redirects', None)
    method = method.upper()
    current = verifier_url(url)
    for _hop in range(MAX_REDIRECTS + 1):
        send = requests.head if method == 'HEAD' else requests.get if method == 'GET' else (
            lambda u, **kw: requests.request(method, u, **kw))
        response = send(current, allow_redirects=False, **kwargs)
        if not getattr(response, 'is_redirect', False):
            return response
        target = urljoin(current, response.headers.get('Location', ''))
        response.close()
        current = verifier_url(target)
        if response.status_code == 303 and method != 'HEAD':
            method = 'GET'
    raise UrlRefusee(f"Trop de redirections (plus de {MAX_REDIRECTS}) : {url}")
