"""
Appel de Claude Code en mode headless, SUR L'ABONNEMENT du titulaire.

CE QUE CE MODULE EST, ET N'EST PAS. Ce n'est **pas** un fournisseur LLM de plus : il ne
passe ni par LiteLLM, ni par `llm_chat()`, et il ne consomme **pas** `ANTHROPIC_API_KEY`.
C'est un OUTIL qui délègue une tâche de développement à Claude Code — lequel apporte ses
propres capacités (lecture du dépôt, recherche, exécution) que WAMA n'a pas. D'où sa place
dans `services/` et son exposition par `tool_api`, et non dans `llm_utils`.

  • provider « claude » de l'assistant  →  API Anthropic via LiteLLM, facturée à la requête
  • CE module                            →  abonnement Claude, crédit mensuel inclus

⚠⚠ LE PIÈGE CENTRAL — `ANTHROPIC_API_KEY` DOIT ÊTRE RETIRÉE DE L'ENVIRONNEMENT.
Claude Code résout son authentification dans cet ordre : `ANTHROPIC_API_KEY`, puis
`apiKeyHelper`, puis `CLAUDE_CODE_OAUTH_TOKEN`, puis les identifiants d'abonnement. Or WAMA
renseigne `ANTHROPIC_API_KEY` dans son `.env` (pour LiteLLM). Hériter de l'environnement du
process Django ferait donc **facturer l'API** en croyant utiliser l'abonnement — un
sur-coût silencieux, jamais signalé nulle part. L'environnement du sous-processus est pour
cette raison construit **explicitement**, jamais hérité.

⚠ CONTRAINTE D'INFRASTRUCTURE MESURÉE (2026-08-21). Django tourne dans WSL2 ; le CLI, lui,
est un binaire **Windows** (`~/.local/bin/claude.exe`, PE32+). L'interop WSL sait le lancer,
mais **seulement avec un environnement propre** : en héritant de l'environnement complet,
l'appel échoue sur `C:/Program: No such file or directory`. La construction explicite de
l'environnement résout donc le piège de facturation ET cette panne — c'est la même ligne.

⚠ Bug amont connu : le rafraîchissement du jeton OAuth échoue en mode non-interactif
(~10-15 min). D'où des invocations COURTES et bornées par un délai, jamais une session
longue.

⚠⚠ CE QUI GOUVERNE LE COÛT : LE CACHE, PAS LA REPRISE DE SESSION — MESURÉ le 2026-08-31.

La note précédente (21/08) affirmait « ~0,99 $ par invocation, le contexte est rechargé à
chaque fois » et en tirait qu'une question triviale coûte presque autant qu'une vraie.
**C'est le cas FROID, pas le cas courant.** Trois appels identiques (« réponds uniquement
par le mot OK »), même dépôt, à la suite :

    A. appel frais, cache FROID   0,538 $   (création du cache)
    B. appel `--resume A`         0,392 $   (RE-création : 38 457 tokens ephemeral_1h)
    C. appel frais, cache CHAUD   0,033 $   (LECTURE de 53 143 tokens) ← 6 % de A

Trois conséquences, dont deux contre-intuitives :
  • **le cache de prompt (TTL 1 h) traverse les invocations** : deux appels rapprochés
    partagent le préfixe, et le second coûte ~6 % du premier. Le coût réel d'un usage
    conversationnel est donc de l'ordre de 0,03 $, pas de 0,99 $ ;
  • **`--resume` est le MAUVAIS levier** — testé précisément pour ça, et réfuté : la
    session reprise construit un préfixe DIFFÉRENT (elle inclut le tour précédent), donc
    elle rate le cache partagé et recrée le sien. Elle coûte 73 % d'un appel froid, soit
    **douze fois** un appel frais à cache chaud. Ne pas l'implémenter en croyant amortir ;
  • ce qui coûte, c'est le PREMIER appel après une heure de silence. Espacer les questions
    est plus cher que les enchaîner — l'inverse de l'intuition.

`total_cost_usd` est l'équivalent API rapporté par le CLI ; sur abonnement la dépense est
imputée au crédit mensuel inclus, pas facturée à la requête. Il reste le bon indicateur
RELATIF, et il est remonté à l'appelant pour ça.

⚠ La garde admin (`subscription_allowed`) reste justifiée — mais par l'ACCÈS AU DÉPÔT et le
crédit partagé, pas par un « 1 $ le message » qui n'est vrai qu'à froid.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

#: Délai maximal d'une invocation, en secondes. Borné par intention (cf. le bug OAuth
#: ci-dessus) : mieux vaut plusieurs tâches courtes qu'une session qui meurt sans rien rendre.
DELAI_DEFAUT = 300
DELAI_MAX = 900

#: Outils autorisés par défaut : LECTURE SEULE. Un appel déclenché depuis une conversation
#: (Discord, assistant) ne doit pas pouvoir modifier le dépôt sans une intention explicite.
#: Les outils absents de cette liste provoquent une demande de permission, qui en mode
#: non-interactif se solde par un refus — c'est exactement le comportement voulu.
OUTILS_LECTURE = ('Read', 'Grep', 'Glob')

#: Emplacements où chercher le CLI, dans l'ordre. Le `.exe` Windows est cité parce que
#: c'est la configuration réelle de cet hôte ; une installation WSL native le supplanterait.
_CANDIDATS = (
    'claude',                                              # PATH (installation WSL native)
    '/mnt/c/Users/fmoreau/.local/bin/claude.exe',           # binaire Windows, via interop
)


class ClaudeCodeIndisponible(RuntimeError):
    """Le CLI est absent ou inexploitable — message destiné à l'utilisateur."""


def subscription_allowed(user) -> bool:
    """
    Qui a le droit de consommer l'abonnement du titulaire — DOMICILE UNIQUE de la règle.

    Extraite du corps de `tool_api.ask_claude_code` le 2026-08-31, quand un DEUXIÈME
    appelant est apparu (le fournisseur « abonnement » de l'assistant, puis le geste
    `!code` de la passerelle). Trois copies de ce prédicat auraient dérivé : c'est
    exactement le cas que la règle « zéro duplication » vise, et une garde de sécurité
    qui dérive s'ouvre du côté qu'on a oublié de mettre à jour.

    ⚠ DEUX VOCABULAIRES DE RÔLE COEXISTENT dans WAMA (mesuré le 2026-08-21) : les GROUPES
    Django (`dev`, `admin` — ce que lit `is_dev()`) et les TIERS de profil (`developpeur`,
    `admin` — ce que lit `permissions.BYPASS_TIERS`). Et un groupe `developpeur` existe
    AUSSI en base, homonyme du tier mais invisible pour `is_dev()`. S'en remettre à un seul
    vocabulaire produirait un refus incompréhensible pour un compte légitimement
    développeur. On accepte donc les deux — et ce commentaire vit ici, pas en trois copies.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return False

    from wama.accounts.views import is_admin, is_dev

    return bool(
        is_dev(user) or is_admin(user)
        or user.groups.filter(name='developpeur').exists()
        or getattr(getattr(user, 'profile', None), 'tier', '') in ('developpeur', 'admin')
    )


def chemin_cli() -> str:
    """Chemin du CLI Claude Code, ou lève une erreur explicite."""
    force = os.environ.get('WAMA_CLAUDE_CLI') or getattr(settings, 'WAMA_CLAUDE_CLI', '')
    if force:
        if not Path(force).exists():
            raise ClaudeCodeIndisponible(f"WAMA_CLAUDE_CLI pointe sur un fichier absent : {force}")
        return force

    for candidat in _CANDIDATS:
        trouve = shutil.which(candidat) if '/' not in candidat else (
            candidat if Path(candidat).exists() else None)
        if trouve:
            return trouve

    raise ClaudeCodeIndisponible(
        "Claude Code est introuvable. Installez-le côté WSL2 (`npm i -g @anthropic-ai/claude-code`) "
        "ou renseignez WAMA_CLAUDE_CLI avec le chemin du binaire."
    )


def _environnement() -> dict:
    """
    Environnement MINIMAL et EXPLICITE du sous-processus.

    Deux raisons, également impératives (cf. l'en-tête du module) :
      1. `ANTHROPIC_API_KEY` ne doit PAS être transmise, sinon l'API est facturée au lieu de
         l'abonnement — silencieusement ;
      2. l'interop WSL→Windows échoue avec l'environnement complet hérité.

    `CLAUDE_CODE_OAUTH_TOKEN` est transmis s'il existe (jeton `claude setup-token`) ; sinon
    le CLI retombe sur les identifiants d'abonnement déjà présents sur la machine.
    """
    env = {
        'PATH': os.environ.get('PATH_CLAUDE_CODE', '/usr/local/bin:/usr/bin:/bin'),
        'HOME': os.environ.get('HOME', '/root'),
        'LANG': 'C.UTF-8',
    }
    jeton = os.environ.get('CLAUDE_CODE_OAUTH_TOKEN')
    if jeton:
        env['CLAUDE_CODE_OAUTH_TOKEN'] = jeton
    # ⚠ NE JAMAIS ajouter ANTHROPIC_API_KEY ici. Voir l'en-tête du module.
    return env


def demander(prompt: str, *, cwd: str | None = None, delai: int = DELAI_DEFAUT,
             outils=OUTILS_LECTURE, ecriture: bool = False) -> dict:
    """
    Soumet UNE tâche à Claude Code et rend son résultat.

    Args:
        prompt:   la tâche, en clair.
        cwd:      répertoire de travail (défaut : la racine du dépôt WAMA).
        delai:    délai maximal en secondes (borné par `DELAI_MAX`).
        outils:   outils autorisés ; par défaut LECTURE SEULE.
        ecriture: True lève la restriction d'outils. ⚠ À n'accorder que sur une intention
                  explicite : Claude Code peut alors modifier le dépôt.

    Returns:
        {'success': True, 'texte': str, 'cout_usd': float|None, 'duree_ms': int|None}
        {'success': False, 'error': str}
    """
    cli = chemin_cli()
    racine = str(cwd or settings.BASE_DIR)
    delai = max(10, min(int(delai or DELAI_DEFAUT), DELAI_MAX))

    commande = [cli, '-p', prompt, '--output-format', 'json']
    if not ecriture:
        # Restriction de surface : les outils non listés déclenchent une demande de
        # permission, qui en non-interactif équivaut à un refus.
        commande += ['--allowedTools', *outils]

    logger.info("[claude_code] tâche soumise (%d caractères, %s, délai %ds)",
                len(prompt or ''), 'écriture' if ecriture else 'lecture seule', delai)

    try:
        acheve = subprocess.run(
            commande, cwd=racine, env=_environnement(),
            capture_output=True, text=True, timeout=delai,
        )
    except subprocess.TimeoutExpired:
        return {'success': False,
                'error': f"Claude Code n'a pas répondu en {delai}s. Découpez la tâche : le "
                         f"rafraîchissement du jeton échoue sur les sessions longues."}
    except Exception as e:
        logger.exception("[claude_code] invocation impossible")
        return {'success': False, 'error': f"Invocation impossible : {e}"}

    if acheve.returncode != 0:
        detail = (acheve.stderr or acheve.stdout or '').strip()[:500] or 'aucun détail'
        return {'success': False, 'error': f"Claude Code a échoué (code {acheve.returncode}) : {detail}"}

    return _lire_sortie(acheve.stdout)


def _lire_sortie(brut: str) -> dict:
    """
    Interprète la sortie `--output-format json`.

    Tolérante par construction : le format de sortie appartient à un outil tiers et peut
    changer. Si le JSON n'est pas celui attendu, on rend le texte brut plutôt que de
    prétendre à l'échec — la réponse a été payée, elle doit parvenir à l'utilisateur.
    """
    brut = (brut or '').strip()
    if not brut:
        return {'success': False, 'error': "Claude Code n'a rien renvoyé."}

    try:
        charge = json.loads(brut)
    except json.JSONDecodeError:
        return {'success': True, 'texte': brut, 'cout_usd': None, 'duree_ms': None}

    if isinstance(charge, list):        # flux d'événements : le dernier porte le résultat
        charge = charge[-1] if charge else {}
    if not isinstance(charge, dict):
        return {'success': True, 'texte': str(charge), 'cout_usd': None, 'duree_ms': None}

    if charge.get('is_error'):
        return {'success': False,
                'error': str(charge.get('result') or charge.get('error') or 'erreur inconnue')}

    return {
        'success': True,
        'texte': str(charge.get('result') or charge.get('text') or brut),
        'cout_usd': charge.get('total_cost_usd'),
        'duree_ms': charge.get('duration_ms'),
    }
