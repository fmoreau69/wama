"""
Les COMMANDES de l'assistant — `/concile`, `/effort`, `/modele`… — déclarées UNE fois pour toutes
ses surfaces (2026-11-06, demande de Fabien : « gère-t-on bien les commandes qui permettent
d'expliciter l'usage des skills ou fonctionnalités de l'assistant comme le concile ? »).

Jusque-là seule la passerelle en avait (`!modele`, `!oublier`, `!code`, écrites dans
`gateway/core.py`) : le web transmettait `/concile` au modèle comme une phrase, et l'API n'avait
que des routes. `WAMA_LLM §A` comptait « commandes (Discord seul) » parmi les divergences entre
surfaces à résorber par le commun. Elles s'exécutent désormais dans `conversation_turn`, le point
commun du web (synchrone et en flux), de l'API et des canaux — après la garde d'accès, avant que
le fil ne s'ouvre.

UNE COMMANDE N'AJOUTE AUCUN MÉCANISME : elle rend EXPLICITE un geste qui existe déjà.
  - un RÉGLAGE durable de l'assistant (`/modele`, `/effort`) : la même écriture que le sélecteur
    et le curseur du volet (`set_chat_model`, `user_settings`), valable pour toutes les surfaces ;
  - un tour AMORCÉ (`/competence`, `/concile`) : le `domain` que le web et l'API savaient déjà
    passer, l'outil `delegate` ouvert pour CE message — le geste manuel du triptyque « auto +
    curseur + manuel ». Le modèle COMPOSE toujours le concile (« pas un council figé », décision
    de Fabien du 29/10) : la commande dit l'intention, elle ne choisit pas les agents ;
  - un geste du fil ou du compte (`/oublier`, `/code`) : `conversation_store.clear_thread`,
    `tool_api.ask_claude_code`.

Préfixe : `/` ou `!`, partout. Une réponse reprend celui que la personne a TAPÉ ; l'aide du web
montre `/`, celle d'un canal `!` (son habitude depuis le 21/08 — sur Discord, `/` ouvre le
sélecteur des commandes NATIVES, que `ROADMAP §19` prévoit de générer). Un mot inconnu n'est pas
une commande : le message part au modèle tel quel, comme avant.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from wama.common.utils.text_fold import fold
from wama.model_manager.services.model_selector import QUALITY_PRESETS

#: Les positions NOMMÉES du curseur, telles qu'on les tape (celles du sélecteur, repliées).
_EFFORT_NAMES = tuple(fold(label) for _, label, _ in QUALITY_PRESETS)
#: Son usage, celui de l'aide et de la réponse : un passage de code, donc sans accent grave dedans.
_EFFORT_USAGE = f"[{'|'.join(_EFFORT_NAMES)}|0-100]"

#: Les préfixes d'une commande ; le premier est celui de l'aide d'une surface sans préférence.
PREFIXES = ('/', '!')
#: Un préfixe collé au mot (`/concile`, pas `/ concile` ni un chemin `/media/…`, qu'aucun espace
#: ne suit), puis le reste — sur plusieurs lignes au besoin.
_COMMAND_HEAD = re.compile(
    r'([' + re.escape(''.join(PREFIXES)) + r'])(\w+)(?:\s+(.*))?$', re.S)


@dataclass(frozen=True)
class CommandContext:
    """Où la commande a été tapée : la surface et son fil (ce que `/oublier` efface), et le
    préfixe employé (celui que la réponse reprend)."""
    surface: str
    thread_key: str = ''
    prefix: str = PREFIXES[0]


@dataclass(frozen=True)
class Command:
    """Une commande de l'assistant. `run(user, args, ctx)` rend :
      - `{'reply': texte, …}` — la commande répond seule, sans tour de modèle ni trace au fil ;
        les autres clés vont à la surface (`cleared`, `settings`) ;
      - `{'turn': {'message', 'domain'?, 'delegate'?}}` — un tour amorcé, que
        `conversation_turn` mène comme les autres (et enregistre)."""
    name: str
    help: str
    run: Callable
    usage: str = ''
    aliases: tuple = field(default_factory=tuple)


def parse_command(text: str):
    """`(préfixe, mot, reste)` d'un message qui commence par un préfixe de commande, sinon None.
    Le mot est replié (`fold`). Lu aussi par la passerelle pour SES gestes de canal
    (appariement), qui précèdent l'identité."""
    match = _COMMAND_HEAD.match((text or '').strip())
    if match is None:
        return None
    return match.group(1), fold(match.group(2)), (match.group(3) or '').strip()


# ── Les commandes ───────────────────────────────────────────────────────────────

def _help(user, args, ctx) -> dict:
    return {'reply': help_text(ctx.prefix)}


def _model(user, args, ctx) -> dict:
    """Le réglage durable `assistant.model` — le même que le sélecteur du web. Le fil n'est pas
    touché : le moteur résout son modèle à chaque tour (`set_chat_model`)."""
    from wama.common.services.assistant_engine import assistant_settings, set_chat_model
    if not args:
        return {'reply': (f"Modèle actuel : `{assistant_settings(user).get('model')}`\n"
                          f"Usage : `{ctx.prefix}modele <clé du catalogue>` ou "
                          f"`{ctx.prefix}modele auto`.")}
    outcome = set_chat_model(user, args)
    if 'error' in outcome:
        return {'reply': f"⛔ {outcome['error']}"}
    return {'reply': f"✅ Modèle : `{outcome['model']}`. La conversation continue, rien n'est effacé.",
            'settings': {'model': outcome['model']}}


def _effort(user, args, ctx) -> dict:
    """Le curseur Rapide ↔ Qualité (`quality_intent`) : ses positions NOMMÉES sont celles du
    sélecteur (`QUALITY_PRESETS`), un nombre de 0 à 100 vaut tel quel (`read_quality_intent`)."""
    from wama.common.services.assistant_engine import assistant_settings
    from wama.common.utils.auto_model import preset_key_for_intent, read_quality_intent
    from wama.common.utils.user_settings import save_user_app_settings

    def said(value) -> str:
        key = preset_key_for_intent(value)
        return f"**{next(label for k, label, _ in QUALITY_PRESETS if k == key)}** ({value})"

    names = ' | '.join(f"`{name}`" for name in _EFFORT_NAMES)
    if not args:
        current = read_quality_intent(assistant_settings(user).get('quality_intent'))
        return {'reply': f"Curseur Rapide ↔ Qualité : {said(current)}.\n"
                         f"Usage : `{ctx.prefix}effort {_EFFORT_USAGE}`."}
    wanted = fold(args.split()[0])
    value = next((position for key, label, position in QUALITY_PRESETS
                  if wanted in (key, fold(label))), None)
    if value is None and wanted.isdigit():
        value = read_quality_intent(wanted)
    if value is None:
        return {'reply': f"⛔ « {args.split()[0]} » n'est pas une position du curseur : {names}, "
                         "ou un nombre de 0 à 100."}
    save_user_app_settings(user, 'assistant', {'quality_intent': value})
    return {'reply': (f"✅ Curseur : {said(value)}. Il vaut pour les prochains tours — modèle, "
                      "réflexion, sous-agents en « auto » — et pour les tâches que je lance."),
            'settings': {'quality_intent': value}}


def _competence(user, args, ctx) -> dict:
    """Un tour amorcé dans un DOMAINE du registre (`assistant_skills.DOMAINES`) — le `domain` que
    le web et l'API savaient passer. Sans commande, c'est l'assistant qui charge la compétence
    (`charger_competence`) ; la commande est le choix MANUEL de l'utilisateur, jamais celui d'une
    surface (l'arbitrage du 21/08 vise l'adaptateur qui DEVINERAIT un domaine)."""
    from wama.common.utils.assistant_skills import DOMAINES
    key, _, question = (args or '').partition(' ')
    domain = next((d for d in DOMAINES if d.key == fold(key)), None)
    if domain is None:
        listed = '\n'.join(f"• `{d.key}` — {d.label} : {d.help_text}" for d in DOMAINES)
        head = f"⛔ Compétence inconnue : « {key} ».\n" if key else ''
        return {'reply': f"{head}Usage : `{ctx.prefix}competence <clé> <votre question>`. "
                         f"Compétences :\n{listed}"}
    if not question.strip():
        return {'reply': f"Usage : `{ctx.prefix}competence {domain.key} <votre question>`."}
    return {'turn': {'message': question.strip(), 'domain': domain.key}}


#: Ce que reçoit le modèle d'un `/concile` : l'INTENTION de l'utilisateur, en clair. La manière de
#: le réunir est la règle de délégation du prompt d'outils (`assistant_engine._DELEGATION_RULE`),
#: annoncée au tour puisque la commande ouvre `delegate` ; le modèle compose les agents.
COUNCIL_REQUEST = ("Réunis un concile sur cette question (la même tâche à plusieurs agents de "
                   "compétences différentes, conclusion par relecture croisée), puis rends-moi "
                   "sa réponse :\n{question}")


def _council(user, args, ctx) -> dict:
    if not args:
        return {'reply': f"Usage : `{ctx.prefix}concile <votre question>` — plusieurs agents la "
                         "traitent, relisent leurs avis, puis un arbitre tranche."}
    return {'turn': {'message': COUNCIL_REQUEST.format(question=args), 'delegate': True}}


def _forget(user, args, ctx) -> dict:
    """Le « Effacer » du chat web, pour toute surface : CE fil seul (`clear_thread`), jamais les
    autres fils de la personne ni ceux d'autrui."""
    from wama.common.services import conversation_store
    if conversation_store.clear_thread(user, surface=ctx.surface, thread_key=ctx.thread_key):
        return {'reply': "🧹 Conversation effacée : je repars de zéro.", 'cleared': True}
    return {'reply': "Il n'y avait rien à effacer dans ce fil.", 'cleared': True}


def _code(user, args, ctx) -> dict:
    """La délégation au dépôt via Claude Code — un geste EXPLICITE (chantier §19.3) : sur un canal
    le tour part souvent sur un modèle local, et ce serait à lui de décider d'appeler l'outil.
    La garde reste celle de l'outil (`subscription_allowed`) : appelée, jamais recopiée."""
    if not args:
        return {'reply': f"Usage : `{ctx.prefix}code <votre question sur le dépôt>`\n"
                         f"_Exemple : `{ctx.prefix}code où est décidé le nom d'un fichier de "
                         "sortie ?`_"}
    from wama.tool_api import ask_claude_code
    result = ask_claude_code(user, args)
    if 'error' in result:
        return {'reply': f"⛔ {result.get('detail') or result['error']}"}
    cost = result.get('cost_usd')
    # Le coût est AFFICHÉ : ce chemin n'est pas gratuit en crédit mensuel, et un chemin dont on ne
    # voit jamais le prix finit par être pris pour du bavardage.
    footer = (f"\n\n_~{cost:.3f} $ d'équivalent-API imputés à l'abonnement "
              f"(cache chaud ≈ 0,03 $, froid ≈ 0,5 $)._") if cost else ''
    return {'reply': f"{result.get('response') or '(réponse vide)'}{footer}"}


#: LES COMMANDES — domicile unique. L'ordre fait celui de l'aide.
COMMANDS = (
    Command('concile', "réunir un concile sur une question : plusieurs agents, une relecture "
                       "croisée, un arbitre", _council, usage='<question>', aliases=('council',)),
    Command('competence', "répondre avec une compétence précise (seule, la commande les liste)",
            _competence, usage='<clé> <question>', aliases=('skill',)),
    Command('effort', "voir ou régler le curseur Rapide ↔ Qualité", _effort,
            usage=_EFFORT_USAGE),
    Command('modele', "voir ou changer le modèle de réflexion, sans perdre la conversation",
            _model, usage='[clé|auto]', aliases=('model',)),
    Command('oublier', "effacer la conversation de ce fil et repartir de zéro", _forget,
            aliases=('forget',)),
    Command('code', "déléguer une question SUR LE DÉPÔT à Claude Code (développeurs/admins ; "
                    "consomme l'abonnement)", _code, usage='<question>'),
    Command('aide', "ce message", _help, aliases=('help',)),
)

_BY_WORD = {word: c for c in COMMANDS for word in (c.name, *c.aliases)}


def help_lines(prefix: str = PREFIXES[0]) -> list:
    """Une ligne par commande, dans l'ordre déclaré — l'aide du web, de l'API et des canaux."""
    return [f"• `{prefix}{c.name}{' ' + c.usage if c.usage else ''}` — {c.help}" for c in COMMANDS]


def help_text(prefix: str = PREFIXES[0]) -> str:
    other = next(p for p in PREFIXES if p != prefix)
    return (f"**Commandes de l'assistant** (`{other}` marche aussi) :\n"
            + '\n'.join(help_lines(prefix)) + "\nSinon, écrivez simplement ce que vous voulez faire.")


def run_command(user, text: str, *, surface: str, thread_key: str = ''):
    """Exécute la commande que porte `text`, ou rend None si ce n'est pas une commande connue —
    le message part alors au modèle tel quel. Voir `Command` pour la forme du résultat, qui porte
    aussi `command` (le nom canonique)."""
    parsed = parse_command(text)
    command = _BY_WORD.get(parsed[1]) if parsed else None
    if command is None:
        return None
    ctx = CommandContext(surface=surface, thread_key=thread_key, prefix=parsed[0])
    return {**command.run(user, parsed[2], ctx), 'command': command.name}
