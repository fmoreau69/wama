"""external_sources — registre DÉCLARATIF des sources externes joignables par WAMA.

Ajouter une plateforme = **une entrée ici**. Avant le 2026-09-01, chaque source vivait dans le
fichier qui la consommait ; personne ne pouvait répondre à « à quoi WAMA se connecte-t-il ? »
autrement qu'en fouillant le dépôt. Idée de Fabien (01/09), les trois étapes livrées le jour même
(déclaration commune, migration des consommateurs, registre catalogué + page).

⚠ CE QUI SE DÉCLARE ICI : l'identité, l'adresse de base, le réglage qui la surcharge, la
variable portant la clé d'API, la PORTÉE (service local ou Internet — donc le traitement du
proxy), l'attribution quand une licence l'oblige.

⚠ CE QUI NE SE DÉCLARE PAS : le CLIENT. Chaque plateforme a sa forme — Artificial Analysis rend
du JSON authentifié, l'Arena un parquet HuggingFace, Ollama du HTML scrapé. Un « chargeur
générique paramétré depuis l'écran » serait à la fois fragile et une surface de requête
arbitraire côté serveur. Le parseur reste chez le consommateur ; seule son ADRESSE vient d'ici.
C'est la ligne écrite dans `benchmark_sync.SOURCES` (registre SŒUR, cf. plus bas) — elle vaut ici.

L'étape 3 (le registre catalogué `sources_externes`, nature `mesure`) vit en bas de ce module :
`probe_all()` SONDE chaque source — clé posée ? service joignable ? — et écrit son rapport dans
`logs/external_sources_report.json`. La valeur de la page est dans la sonde : un inventaire pur
n'aurait aucun bouton, la doctrine des registres le refuse.

── Ce que la mesure du 2026-09-01 a trouvé, et qui motive la brique ────────────────────────

Le handoff annonçait « 9 sources dans 7 fichiers ». Le relevé exhaustif en donne **une
vingtaine**, et surtout le défaut n'était pas seulement la dispersion, c'était la DUPLICATION :

  • `http://127.0.0.1:11434` écrit **10 fois**, dont 8 sous la forme
    `getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434')` — or `settings.py` pose
    TOUJOURS cet attribut : ces 8 replis sont MORTS. Un repli qui ne se déclenche jamais est
    une fausse sécurité, et le jour où il se déclencherait il divergerait du réglage.
  • `_LJ_BASE` (échantillons ljspeech) recopié **3 fois** à l'identique.
  • `TTS_SERVICE_URL` et `WAMA_UI_SMOKE_BASE` : défaut redéclaré chez chaque appelant.

── PÉRIMÈTRE : toute source que WAMA appelle — la CLÉ peut être de l'instance OU de chacun ─────

✅ **DÉCISION de Fabien, 2026-09-22 : les connecteurs de la médiathèque (wikimedia, pixabay,
pexels, openverse, jamendo, freesound) sont des SOURCES COMMUNES de ce registre — mais chacun y
pose SA propre clé, exactement comme pour les fournisseurs LLM distants.** Ils y sont déclarés
en famille `media`, avec `user_key=True` : l'adresse, la portée (donc le proxy) et la sonde
viennent d'ici ; la clé reste celle de l'utilisateur, saisie au profil.

L'historique, gardé parce qu'il dit pourquoi la frontière a bougé :
  • 2026-09-01 — exclusion écrite ici : « ce registre couvre les sources dont la configuration
    appartient à l'installation » ; la clé d'un connecteur étant « une donnée par utilisateur,
    stockée en base », les y rapatrier aurait été « uniformiser ce qui n'est pas pareil ».
  • 2026-09-15 — le CONSTAT qui fondait l'exclusion cesse d'être vrai : les fournisseurs `llm`
    (Albert, API Anthropic, abonnement Claude Code) entrent ici alors que leur clé est PAR
    UTILISATEUR, stockée en base (`accounts/api_keys.py`), et rendue au profil par le MÊME code
    que les clés de la médiathèque (`api_keys.listing`). Le registre porte donc déjà des sources à
    clé d'utilisateur — relevé le 2026-09-21, décision rouverte, tranchée le 22/09.
  ⭐ Ce qui sépare vraiment les deux cas n'est pas la SOURCE mais le DÉTENTEUR DE LA CLÉ : c'est
    ce que dit `user_key`, pas une frontière entre registres.

⚠ Décision OUVERTE, nommée (non faite) : les clés d'utilisateur vivent dans DEUX tables —
`accounts.UserApiKey` (fournisseurs `llm`) et `media_library.UserProviderConfig` (connecteurs,
chiffrée). Les unifier, c'est migrer des secrets : une décision à part, pas un effet de bord.

── Registres VOISINS, volontairement distincts ──────────────────────────────────────────────

  • `benchmark_sync.SOURCES` déclare comment LIRE un banc (priorité, échelle, méta). Il parle
    de mesure, pas de connectivité — il devient CONSOMMATEUR d'ici pour ses adresses.
  • `http_proxy` reste la plomberie du proxy ; `proxies_for()` ci-dessous ne fait que choisir
    entre ses deux gestes d'après la portée déclarée, au lieu de laisser chaque appelant deviner.
  • `ollama_host.ollama_base()` reste le résolveur SPÉCIALISÉ d'Ollama : il porte en plus la
    réécriture WSL2 → passerelle Windows, que rien de générique ne saurait faire.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

#: Hébergement d'un fournisseur LLM (champ `hosting`) → libellé court affiché aux utilisateurs.
HOSTING = {'private': 'privé', 'sovereign': 'souverain', 'third_party': 'hébergeur tiers'}

#: L'ÉCHELLE des hébergements distants, du plus proche au plus lointain — les anneaux de la
#: présentation de WAMA (`includes/wama_presentation.html`, « La souveraineté, à plusieurs
#: niveaux ») : Local · Cloud privé · Clouds souverains · Clouds commerciaux. « Local » n'y
#: figure PAS : ce n'est pas l'hébergement d'une source distante, c'est l'exécution sur site
#: (`AIModel.execution == 'local'`), réglée par `UserProfile.cloud_policy`.
#:   • `private`     — infrastructure de l'ÉTABLISSEMENT (un serveur de l'université) : la
#:                     donnée quitte le poste, pas l'institution. ⏳ Aucune source ne le déclare
#:                     encore (2026-10-03) : la valeur existe pour que le plafond du profil et
#:                     la présentation disent la même chose le jour où une source arrive ;
#:   • `sovereign`   — hébergement public ou qualifié en France (Albert de la DINUM, ILaaS de
#:                     l'ESR, SecNumCloud) ;
#:   • `third_party` — hébergeur commercial, qui ne garde pas les requêtes et n'entraîne pas
#:                     dessus quand le fournisseur sait le demander (OpenRouter :
#:                     `no_reuse_request_body`) ;
#:   • `third_party_all` — le même, y COMPRIS les hébergeurs qui conservent les requêtes ou
#:                     s'en servent pour entraîner leurs modèles : souvent la condition des
#:                     modèles GRATUITS (servis par leur seul éditeur). Cran de PLAFOND seulement —
#:                     aucune source ne le déclare comme hébergement. Décision de Fabien,
#:                     2026-10-12 : la règle de collecte suit le choix de l'utilisateur.
#: C'est l'ORDRE qui fait la règle : un profil plafonné à un niveau admet ce niveau et tous
#: ceux qui le précèdent (`hosting_within`). Décision de Fabien, 2026-10-03.
HOSTING_SCALE = ('private', 'sovereign', 'third_party', 'third_party_all')

#: Le cran du plafond à partir duquel l'utilisateur accepte que ses requêtes soient gardées ou
#: servent à entraîner un modèle (`data_reuse_accepted`).
DATA_REUSE_CEILING = 'third_party_all'

#: Comment on DIT à l'utilisateur où tourne un modèle distant (aide sous un sélecteur de modèle,
#: `AIModel.origin_label`) — un libellé par niveau de l'échelle.
CLOUD_ORIGIN_LABELS = {
    'private': 'Cloud privé',
    'sovereign': 'Cloud souverain',
    'third_party': 'Cloud commercial',
}

#: Comment on dit qu'un modèle tourne SUR SITE (poids sur cette machine, Ollama compris) — le
#: premier anneau de la présentation, celui dont rien ne sort.
LOCAL_ORIGIN_LABEL = 'WAMA local'

#: Clé de l'origine locale dans un regroupement d'options (les distantes portent leur source).
LOCAL_ORIGIN_KEY = 'local'

#: Ce que COÛTE un modèle distant — vocabulaire UNIQUE (2026-10-10) : les choix du champ
#: `AIModel.cost_tier` en dérivent (`model_manager.models.COST_TIER_CHOICES`), et les libellés
#: d'origine ci-dessous le lisent. Une source déclare son coût (`ExternalSource.cost_tier`) ; un
#: modèle peut s'en écarter (les modèles gratuits d'OpenRouter, fournisseur facturé).
COST_TIERS = (('free', 'Gratuit (quota)'), ('metered', "Facturé à l'usage"),
              ('subscription', 'Abonnement'))


def cost_label(tier: str) -> str:
    """« gratuit (quota) », « facturé à l'usage », « abonnement » — '' pour un coût inconnu."""
    label = dict(COST_TIERS).get(tier or '', '')
    return label[:1].lower() + label[1:]


def remote_origin_label(source: str, cost_tier: str = '') -> str:
    """LE libellé d'un modèle distant, calculé de ce qui est DÉCLARÉ : hébergement · fournisseur ·
    coût — « Cloud souverain · Albert API (DINUM) · gratuit (quota) ».

    Demande de Fabien (2026-10-10) : on distinguait local / distant / souverain, jamais gratuit /
    payant, sauf par accident (« Claude Code (abonnement) » le disait dans son NOM). Un mot écrit à
    la main dans un nom vieillit ; ici chaque partie vient d'un champ — `hosting` et `label` de la
    source, le coût du MODÈLE s'il en déclare un, sinon celui de la source. Lu par les intitulés de
    groupe des sélecteurs (`model_origin`), l'aide sous le sélecteur (`AIModel.origin_label`) et le
    profil (`source_origin_label`).
    """
    declared = by_key().get(source)
    if declared is None:
        return 'Cloud'
    parts = [CLOUD_ORIGIN_LABELS.get(declared.hosting, 'Cloud'), declared.label]
    cost = cost_label(cost_tier or declared.cost_tier)
    if cost:
        parts.append(cost)
    return ' · '.join(parts)


def source_origin_label(source: str) -> str:
    """Où partent les données d'un FOURNISSEUR et ce qu'il coûte, sans son nom (que l'écran
    affiche déjà) — « Cloud souverain · gratuit (quota) ». '' pour une source qui n'est pas un
    fournisseur distant."""
    declared = by_key().get(source)
    if declared is None or declared.kind != 'llm':
        return ''
    parts = [CLOUD_ORIGIN_LABELS.get(declared.hosting, 'Cloud'), cost_label(declared.cost_tier)]
    return ' · '.join(p for p in parts if p)


def model_origin(model_key: str, execution: str = '', cost_tier: str = '') -> tuple:
    """`(clé, libellé, rang)` de l'ORIGINE d'un modèle — où son inférence a lieu.

    Un modèle exécuté sur site rend `('local', 'WAMA local', 0)`. Un modèle distant rend la
    clé de sa SOURCE déclarée et le libellé calculé `remote_origin_label` — « Cloud souverain ·
    Albert API (DINUM) · gratuit (quota) » ; `cost_tier` est celui du MODÈLE (un fournisseur
    facturé peut servir des modèles gratuits). Son rang suit l'échelle des hébergements — privé,
    souverain, commercial — pour que le plus proche soit proposé d'abord.
    C'est ce que les sélecteurs de modèle affichent en INTITULÉ de groupe (demande de Fabien,
    2026-10-05 : « on ne sait pas si on choisit un modèle local ou distant » ; le coût s'y ajoute
    le 2026-10-10).
    """
    if execution != 'cloud':
        return LOCAL_ORIGIN_KEY, LOCAL_ORIGIN_LABEL, 0
    source = (model_key or '').partition(':')[0]
    declared = by_key().get(source)
    if declared is None:
        return source or 'cloud', 'Cloud', len(HOSTING_SCALE) + 1
    rank = (HOSTING_SCALE.index(declared.hosting) + 1 if declared.hosting in HOSTING_SCALE
            else len(HOSTING_SCALE) + 1)
    return declared.key, remote_origin_label(source, cost_tier), rank


#: Plafond par défaut d'un profil : les clouds commerciaux « seulement si on les choisit,
#: jamais par défaut » (même diapositive).
HOSTING_CEILING_DEFAULT = 'sovereign'

#: Libellés du PLAFOND au profil (une formulation par niveau, dans l'ordre de l'échelle).
HOSTING_CEILING_LABELS = {
    'private': "Cloud privé seulement (serveurs de l'établissement)",
    # Ce que le niveau EST, jamais un fournisseur nommé (2026-10-13, Fabien : « Albert en dur…
    # pas homogène avec les autres choix ») — ILaaS est souverain lui aussi, et la liste s'allonge.
    'sovereign': "Jusqu'aux clouds souverains (hébergés et opérés en France)",
    'third_party': "Jusqu'aux clouds commerciaux, sans conservation de mes données",
    'third_party_all': "Jusqu'aux clouds commerciaux, même s'ils gardent ou réutilisent mes données",
}

#: Ce que l'utilisateur doit SAVOIR avant de choisir le dernier cran — affiché sous le plafond, au
#: profil (2026-10-12).
DATA_REUSE_WARNING = (
    "Au dernier niveau, un hébergeur commercial peut conserver vos requêtes (textes, documents "
    "envoyés) et s'en servir pour entraîner ses modèles. C'est souvent la condition des modèles "
    "gratuits. N'y envoyez rien de confidentiel ni de personnel.")


def hosting_within(hosting: str, ceiling: str) -> bool:
    """`hosting` est-il admis par un profil plafonné à `ceiling` ?

    Un hébergement INCONNU ou vide n'est admis par aucun plafond : une source qui ne dit pas où
    partent les données ne passe pas au bénéfice du doute. Un plafond inconnu vaut le défaut.
    """
    if hosting not in HOSTING_SCALE:
        return False
    if ceiling not in HOSTING_SCALE:
        ceiling = HOSTING_CEILING_DEFAULT
    return HOSTING_SCALE.index(hosting) <= HOSTING_SCALE.index(ceiling)


def data_reuse_accepted(ceiling: str) -> bool:
    """Un profil plafonné à `ceiling` accepte-t-il qu'un hébergeur garde ou réutilise ses
    requêtes ? Seulement au dernier cran ; un plafond inconnu vaut le défaut, donc non."""
    return ceiling == DATA_REUSE_CEILING

#: Portées. `LOCAL` = service tournant sur la machine (ou l'hôte) : le proxy doit être
#: NEUTRALISÉ, sans quoi il répond sa page d'erreur HTML à la place du service (incident
#: mesuré le 2026-08-31 sur le TTS : 90 s de repli en-process et de la VRAM prise côté web,
#: alors que le service répondait parfaitement). `OUTBOUND` = Internet, à travers le proxy UGE.
LOCAL = 'local'
OUTBOUND = 'outbound'

#: TYPES de source — ce à quoi elle SERT. Jusqu'au 2026-09-02 cette famille n'existait que
#: dans les commentaires de séparation de `SOURCES` (« Services locaux », « Bancs de
#: performance »…) : la page ne pouvait donc filtrer que par PORTÉE (locale/sortante), un axe
#: technique qui ne dit rien de l'usage. Une famille lisible uniquement dans le code est une
#: facette perdue pour l'écran. Clé = valeur de `data-f-type` ; libellé = option du select.
KINDS = {
    'service':   'Service local',
    'llm':       'Fournisseur LLM',
    'catalogue': 'Catalogue de modèles',
    'banc':      'Banc de performance',
    'poids':     'Outillage et poids',
    'audit':     'Audit de sécurité',
    'recherche': 'Recherche web',
    'media':     'Banque de médias',
    #: Jeux de données dont WAMA tire de la MATIÈRE (voix de référence, corpus) — distinct de
    #: `catalogue`, qui référence des MODÈLES. Ouvert le 2026-09-27 avec Mozilla Data
    #: Collective : y ranger un corpus de voix sous « Catalogue de modèles » aurait fait mentir
    #: la facette de la page des sources, que cette table remplit.
    'corpus':    'Corpus de données',
    #: Nuages de FICHIERS montés au filemanager comme un dossier (Nextcloud, WebDAV — rclone,
    #: 2026-10-10, `filemanager/remote_mounts.py`). L'adresse et les identifiants sont ceux que
    #: l'utilisateur saisit en connectant le dossier, et le secret vit sur le MONTAGE (chiffré),
    #: pas au profil : un même compte peut connecter plusieurs nuages.
    'stockage':  'Stockage de fichiers',
    #: Service d'embeddings et de RAG DISTANT dont la clé se pose AVANT que WAMA ne s'en serve
    #: (2026-10-13, ILaaS) : famille à part de `llm` exprès — une source `llm` fait lire ses
    #: modèles dès que sa clé est posée (`api_keys.store_key`) et ses modèles de chat entrent au
    #: tirage de l'assistant. L'usage (embeddings de la mémoire, fournisseur cloud) se tranche
    #: avec le routage des modèles cloud (`ROADMAP §8d`, sélection automatique, étape 7).
    'rag':       'Embeddings et RAG',
}


@dataclass(frozen=True)
class Quota:
    """Une limite de débit DÉCLARÉE sur une source (`ExternalSource.quotas`) — lue par la brique
    commune `common/services/source_quota.py`, qui compte et apprend le reste (2026-10-14).

    `count` par `window_s` secondes, en `unit` ('requests' ou 'tokens'). `models` : préfixe ou
    suffixe des modèles visés ('' = tous ; ':free' = ceux qui finissent ainsi). `per_model` :
    chaque modèle a son propre compteur ; sinon les modèles visés en partagent UN — c'est ce qui
    distingue la limite par modèle (Albert, Claude) du quota d'un groupe (les gratuits
    d'OpenRouter). Ne déclarer qu'une limite DOCUMENTÉE ou MESURÉE : celle qu'on ignore
    s'apprend au premier refus réel.
    """
    count: int
    window_s: int
    unit: str = 'requests'
    models: str = ''
    per_model: bool = False

    def applies_to(self, model: str) -> bool:
        if not self.models:
            return True
        model = model or ''
        return model.startswith(self.models) or model.endswith(self.models)

    def bucket(self, model: str) -> str:
        """Le compteur que ce plafond lit : celui du modèle, ou celui du groupe qu'il vise."""
        if self.per_model:
            return f'm:{model or ""}'
        return f'g:{self.models or "*"}'


@dataclass(frozen=True)
class ExternalSource:
    """Une source externe : ce qu'elle est et comment on l'adresse — jamais comment on la lit."""

    key: str
    #: Nom lisible — sert aux écrans et aux attributions.
    label: str
    #: Adresse de base par DÉFAUT. Surchargée par `setting` puis `env` (cf. `base_url`).
    base: str
    #: Une ligne : à quoi elle sert dans WAMA.
    usage: str
    #: Clé de `KINDS` — la famille d'USAGE (facette « Type » de la page).
    kind: str = 'poids'
    #: `LOCAL` ou `OUTBOUND` — décide du traitement du proxy, jamais laissé à l'appelant.
    scope: str = OUTBOUND
    #: Réglage Django qui surcharge `base` (prioritaire sur `env`).
    setting: str = ''
    #: Variable d'environnement qui surcharge `base` quand aucun réglage Django ne la porte.
    env: str = ''
    #: Variable d'environnement portant la clé d'API. '' = source anonyme.
    api_key_env: str = ''
    #: Page où l'on obtient une clé — affichée à côté du champ de saisie du profil.
    api_key_help_url: str = ''
    #: La clé de l'instance est FACULTATIVE (2026-10-12, décision de Fabien) : la source répond
    #: sans elle, la clé ne fait que relever un quota (API GitHub : 60 appels/h anonymes, 5000
    #: avec un jeton). Sans ce drapeau, déclarer `api_key_env` rendait la source « non
    #: configurée » tant que personne ne posait de clé — ce qui la gardait hors du registre.
    api_key_optional: bool = False
    #: Fournisseur LLM : où partent les données — une valeur de `HOSTING_SCALE` ('private',
    #: 'sovereign' — hébergement de l'État —, 'third_party'). Une clé d'API suffit à faire d'une
    #: source un service DISTANT (Fabien, 15/09).
    hosting: str = ''
    #: Fournisseur LLM : coût de ses modèles (valeurs de `AIModel.cost_tier`).
    cost_tier: str = ''
    #: Fournisseur LLM : protocole de sa liste de modèles — 'openai' (Albert), 'anthropic' (API
    #: Anthropic, clé `x-api-key`), 'claude_cli' (jeton OAuth d'abonnement).
    protocol: str = ''
    #: Type des modèles quand le fournisseur ne le dit pas (tag de tâche HuggingFace).
    default_remote_type: str = ''
    #: PLATEFORME de modèles (2026-10-22) : chemin de la FICHE publique d'un modèle, relatif à
    #: l'adresse de la source — `{id}` = l'identifiant que porte `AIModel.platform_ref`
    #: (`huggingface:org/repo` → `org/repo`). '' = la source ne publie pas de fiches de modèles.
    #: C'est ce qui fait d'une source une plateforme au sens de `platform_ref` (`model_platforms`) :
    #: la table plateforme → gabarit d'adresse et les noms des plateformes vivaient en double dans
    #: `AIModel` (`_URL_PAR_PLATEFORME`, `platform_label`), sous d'autres libellés.
    model_page: str = ''
    #: Le préfixe de `platform_ref` qui désigne cette source quand il n'est pas sa clé : une fiche
    #: `ollama:<famille>` est celle du SITE (`ollama_site`), pas du moteur local (`ollama`).
    platform_ref_prefix: str = ''
    #: Fournisseur LLM : modèle appelé quand l'appelant n'en nomme aucun (`llm_utils.
    #: default_cloud_model`, 2026-10-07 — ex-entrée de `CLOUD_DEFAULT_MODELS`, chantier 5 de
    #: `WAMA_HARNESS.md`). ⚠ Un nom de modèle vieillit : le fournisseur le retire.
    default_model: str = ''
    #: Libellé du champ de saisie au profil ('' = « Clé d'API »).
    api_key_label: str = ''
    #: Début de toute clé que délivre ce fournisseur ('' = forme inconnue, rien n'est contrôlé).
    #: Une clé saisie qui ne commence pas ainsi est refusée au dépôt (`api_keys.key_shape_error`) :
    #: c'est une copie TRONQUÉE. Vécu le 2026-10-26 : le jeton d'abonnement Claude d'un profil,
    #: collé le 15/09, n'avait pas son début (92 caractères, sans `sk-ant-oat01-`) — refusé par
    #: l'API (401) dès qu'il a enfin atteint le CLI. N'y écrire qu'un préfixe MESURÉ sur des clés
    #: réelles, et le plus court qui les distingue (la version qui suit peut changer).
    api_key_prefix: str = ''
    #: La clé est posée par CHAQUE UTILISATEUR, au profil (2026-09-22). Indépendant de
    #: `api_key_env`, qui dit la clé de l'INSTANCE : une source `llm` porte les deux (l'instance
    #: ne sert qu'aux usages sans utilisateur), un connecteur de la médiathèque seulement la
    #: sienne. Sans ce champ, une source sans `api_key_env` passait pour ANONYME — donc
    #: « configurée » — alors qu'elle attend la clé de chacun.
    user_key: bool = False
    #: La clé d'INSTANCE peut être PARTAGÉE avec tous les comptes (2026-10-07) : l'admin la pose
    #: sur la page « Sources externes » et coche « partager » (`accounts.InstanceApiKey.shared`) ;
    #: un compte qui a posé SA clé garde la sienne. Réservé aux fournisseurs qui délivrent des
    #: clés d'APPLICATION (ILaaS) — jamais à ceux dont le quota est par personne (Albert, 15/09).
    shareable: bool = False
    #: L'ADRESSE se pose sur la page « Sources externes » par un admin (2026-10-10, demande de
    #: Fabien), et y prime sur le réglage et le `.env` (`accounts.InstanceApiKey.base_url`).
    #: ⚠ Ne le déclarer que pour une source dont TOUS les consommateurs passent par `base_url()`
    #: et dont l'adresse est un CHOIX (quel fournisseur, quelle instance) : relevé du jour —
    #: Ollama est lu par l'environnement d'abord (`assistant_engine`) et réécrit pour WSL2
    #: (`ollama_host`), et l'adresse d'un service local (TTS, MCP) est celle où le script de
    #: démarrage le LANCE. La page y afficherait une adresse que rien n'emploierait.
    address_editable: bool = False
    #: Le défaut déclaré n'est qu'un EXEMPLE (adresse propre à chaque établissement, absente d'un
    #: dépôt public) : tant qu'aucune adresse n'est posée, la source n'est pas configurée.
    address_required: bool = False
    #: Réservé aux développeurs (abonnement Claude Code : accès au dépôt).
    developer_only: bool = False
    #: La source SERT des modèles de PLUSIEURS tâches sous un même moteur, hors du processus WAMA
    #: (2026-10-07) : Ollama héberge chat, embeddings et OCR (`glm-ocr`) comme Albert héberge
    #: chat, embeddings, OCR et parole. Lu par la résolution des backends
    #: (`backend_inventory.resolve_entry`) : un backend lié au contrat d'UNE tâche n'y exécute
    #: que celle-là — sans quoi il deviendrait « le seul backend du moteur » pour les modèles de
    #: TOUTES ses tâches. Un fournisseur LLM (`kind='llm'`) l'est par nature (`serves_many_tasks`).
    multi_task: bool = False
    #: Fournisseur LLM SANS liste de modèles (protocole `claude_cli`) : les modèles qu'il sert,
    #: DÉCLARÉS ici — `(id, nom, description)`. `cloud_models.declared_listing` en fait les
    #: lignes du catalogue (2026-09-16 : « l'abonnement = ligne DÉCLARÉE »). Vide = une seule
    #: ligne `default`. ⚠ N'y écrire que des identifiants que le fournisseur ACCEPTE, vérifiés
    #: sur lui : ils partent tels quels dans son appel.
    declared_models: tuple = ()
    #: Fournisseur LLM : champs AJOUTÉS au corps d'une requête de conversation pour qu'aucun
    #: hébergeur ne garde ni n'entraîne sur les données (OpenRouter, 2026-10-10), lus par
    #: `llm_utils.llm_chat`. Envoyés SAUF si l'utilisateur a accepté cette réutilisation au
    #: plafond de son profil (`data_reuse_accepted`, 2026-10-12) ; toujours envoyés sans
    #: utilisateur (clé d'instance). Chaîne JSON (et non dict) : la source est figée, donc hachable.
    no_reuse_request_body: str = ''
    #: Fournisseur LLM : ses modèles GRATUITS ne sont servis qu'à qui accepte que ses requêtes
    #: servent à entraîner (OpenRouter, mesuré le 2026-10-12 : sous `no_reuse_request_body`, un
    #: modèle `:free` répond 404 « No endpoints found matching your data policy (Free model
    #: training) »). Le tirage automatique ne les retient donc qu'au dernier cran du plafond
    #: (`cloud_models.allowed_cloud_keys`) — sinon il tirerait un modèle voué à l'échec.
    free_models_need_data_reuse: bool = False
    #: Fournisseur LLM : attente, en secondes, après un refus de débit (HTTP 429) qui ne dit pas
    #: quand recommencer (`Retry-After`) — MESURÉE sur le fournisseur ; 0 = l'attente commune
    #: (`llm_utils.RATE_LIMIT_WAIT_S`). Chantier 5 ③ de `WAMA_HARNESS.md` (2026-10-11) : la
    #: reprise est le seul profil qui diffère d'un fournisseur à l'autre ; le DÉLAI, lui, reste
    #: celui de l'appelant (un tour interactif n'attend pas comme une tâche).
    rate_limit_wait_s: float = 0.0
    #: Limites de débit DOCUMENTÉES ou MESURÉES (`Quota`) — la source les porte par défaut, un
    #: `Quota` peut ne viser que certains modèles. Vide = rien d'annoncé : le compte commun
    #: (`source_quota`) n'écarte alors la source qu'après un premier refus réel, dont il apprend
    #: le plafond (`ROADMAP §8d` étape 3, 2026-10-14).
    quotas: tuple = ()
    #: Fournisseur LLM : les outils de l'assistant lui sont DÉCLARÉS au format standard
    #: (`tools=`, appels rendus nommés dans `tool_calls`) en plus de la liste du prompt
    #: (2026-10-11). Mesuré sur Albert/gpt-oss : sans déclaration, son appel d'outil natif
    #: arrivait sans nom, rangé dans le raisonnement — réponse vide environ 2 fois sur 3 ; déclarés,
    #: 81 outils acceptés et l'appel rendu nommé. Ne le poser que MESURÉ sur le fournisseur.
    #: ⚠ PAR MODÈLE, jamais pour toute la source (2026-10-11, le soir même) : posé pour Albert
    #: entier, il a rendu l'assistant MUET sur les deux autres modèles mesurés — deepseek-v4-flash
    #: (tiré en « auto ») annonçait « je vais chercher le fichier » puis s'arrêtait sans appel,
    #: gemma-4-31b rendait vide ; 0 appel sur 3 chacun, contre 3 sur 3 par la liste du prompt.
    #: D'où un tuple d'identifiants de modèles MESURÉS (sans préfixe de protocole).
    #: La mesure a son outil depuis le 2026-10-23 : `manage.py llm_gateway_check --provider <source>
    #: --model <id> --tools --user <compte> --repeat 3` (la liste même que l'assistant envoie, la clé
    #: et le profil du compte) — elle rejoue le cas deepseek (muet) et gpt-oss (nommé).
    native_tools: tuple = ()
    #: Attribution EXIGÉE par la licence de la source. Une obligation, pas une politesse.
    attribution: str = ''
    #: Document portant l'intention, quand elle est écrite quelque part.
    doc: str = ''

    def catalogue_model_id(self, model: str) -> str:
        """L'identifiant d'un modèle de cette source tel que le CATALOGUE le porte — `model` sans
        le préfixe de PROTOCOLE que LiteLLM lui ajoute (`openai/gpt-oss-120b` → `gpt-oss-120b`,
        l'inverse exact de `llm_chat`). Jamais tout ce qui précède un « / » : il fait partie d'un
        identifiant OpenRouter (`qwen/qwen3…`) — la coupe au dernier « / » ne reconnaissait aucun
        d'eux dans `native_tools` (2026-10-23)."""
        prefix = f'{self.protocol}/'
        model = model or ''
        return model[len(prefix):] if self.protocol and model.startswith(prefix) else model


#: ⚠ ORDRE : par famille, pour la lecture. Aucun code ne dépend de l'ordre.
SOURCES: tuple[ExternalSource, ...] = (
    # ── Services LOCAUX ─────────────────────────────────────────────────────────────────
    ExternalSource(
        'ollama', 'Ollama (hôte)', 'http://127.0.0.1:11434',
        "Moteur LLM local — assistant, describer, reader, prospection de modèles",
        kind='service', scope=LOCAL, setting='OLLAMA_HOST', env='OLLAMA_HOST', multi_task=True,
        doc='docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md'),
    ExternalSource(
        'tts_service', 'Service TTS WAMA', 'http://localhost:8001',
        "Vocalisation hors du process web (évite de charger un modèle dans gunicorn)",
        kind='service', scope=LOCAL, setting='TTS_SERVICE_URL', env='TTS_SERVICE_URL'),
    ExternalSource(
        'vector_service', 'Service de vectorisation WAMA', 'http://127.0.0.1:8002',
        "Embeddings texte et médias hors des process web et workers (RAG, recherche par contenu)",
        kind='service', scope=LOCAL, setting='VECTOR_SERVICE_URL', env='VECTOR_SERVICE_URL',
        doc='docs/construction/ia/WAMA_MEMORY.md'),
    ExternalSource(
        'wama_self', 'WAMA (cette instance)', 'http://127.0.0.1:8000',
        "WAMA s'interroge lui-même : smoke navigateur, matrice de droits",
        kind='service', scope=LOCAL, env='WAMA_UI_SMOKE_BASE'),
    # 2026-09-15 : WAMA SERVEUR d'outils MCP (ROADMAP §8d Phase 3). Process à part
    # (`manage.py run_mcp_server`), comme le service TTS : son adresse vit ici, pas chez ses
    # clients (Claude Code, IDE, moteur de l'assistant).
    ExternalSource(
        'wama_mcp', 'Serveur MCP WAMA', 'http://127.0.0.1:8770',
        "Les outils tool_api exposés en MCP — même contrat pour tout client (Claude Code, IDE, "
        "assistant)", kind='service', scope=LOCAL, env='WAMA_MCP_URL',
        doc='docs/construction/suivi/ROADMAP.md'),
    # Serveur des outils de DÉVELOPPEMENT : un AUTRE process (ROADMAP §16 — jamais chargé dans
    # le process de prod), donc une autre adresse.
    ExternalSource(
        'wama_mcp_dev', 'Serveur MCP WAMA — développement', 'http://127.0.0.1:8771',
        "Outils de développement (rôles wama-dev-ai, bac à sable d'apps) — process séparé, "
        "réservé aux développeurs", kind='service', scope=LOCAL, env='WAMA_MCP_DEV_URL',
        doc='docs/construction/suivi/ROADMAP.md'),

    # ── Fournisseurs LLM distants ───────────────────────────────────────────────────────
    # 2026-09-15 : Albert API (DINUM) parle le protocole OpenAI depuis sa propre adresse.
    # `llm_utils.llm_chat(provider='albert')` lit ICI son adresse et sa clé. Hébergement
    # SecNumCloud sans conservation des conversations (doc DINUM) — ce qui n'en fait PAS un
    # service local : le traitement des données sensibles reste à trancher (ROADMAP §8d ③).
    ExternalSource(
        'albert', 'Albert API (DINUM)', 'https://albert.api.etalab.gouv.fr/v1',
        "LLM de l'État compatible OpenAI — assistant et rôles wama-dev-ai (manifestes, "
        "codegen) via llm_chat", kind='llm', env='ALBERT_API_BASE', address_editable=True,
        api_key_env='ALBERT_API_KEY', user_key=True,
        api_key_help_url='https://ia.numerique.gouv.fr/outils-ia/albert-api/',
        hosting='sovereign', cost_tier='free', protocol='openai',
        default_model='openai/gpt-oss-120b', native_tools=('gpt-oss-120b',),
        # 10 requêtes par minute et par clé, sans `Retry-After` : une fenêtre ENTIÈRE (mesuré le
        # 2026-10-10 — trois essais à 20 s d'écart tous refusés).
        rate_limit_wait_s=60.0,
        doc='docs/construction/ia/WAMA_LLM.md'),
    # 2026-10-07 : ILaaS, fédération d'inférence de l'ESR (MESRE, CINES ; datacenters labellisés
    # ESR), protocole OpenAI. Il délivre des clés d'APPLICATION (une par service, validée par
    # un admin ILaaS) : d'où `shareable` — l'admin WAMA la pose sur la page Sources externes et
    # la partage ; un compte qui a sa clé individuelle ILaaS la pose au profil, elle prime.
    # ⚠ `default_remote_type` : MESURÉ le 2026-10-12 avec la vraie clé, leur `/models` ne porte
    # que `id`, `object`, `owned_by` — aucune tâche. `text-generation` vaut donc pour les 6
    # modèles : il sous-déclare la vision éventuelle de certains plutôt que de la prêter à ceux
    # qui ne l'ont pas. La même liste répond VIDE à ~1 lecture sur 2 (`cloud_models.LISTING_ATTEMPTS`).
    # Embeddings : service à part, `ilaas_rag` ci-dessous. Transcription (adresse remise avec la
    # clé) : non branchée.
    ExternalSource(
        'ilaas', 'ILaaS (ESR)', 'https://llm.ilaas.fr/v1',
        "Inférence LLM mutualisée de l'enseignement supérieur et de la recherche, compatible "
        "OpenAI — assistant, apps et rôles wama-dev-ai via llm_chat", kind='llm',
        env='ILAAS_API_BASE', api_key_env='ILAAS_API_KEY', user_key=True, shareable=True,
        address_editable=True,
        api_key_help_url='https://www.ilaas.fr/demande-de-cles-ilaas/',
        hosting='sovereign', cost_tier='free', protocol='openai',
        default_remote_type='text-generation',
        # Identifiant SERVI, mesuré le 2026-10-12 (`llm_gateway_check --provider ilaas`).
        default_model='mistral-small-4-119b',
        # Outils déclarés nativement (décision de Fabien, 2026-10-26) : les CINQ modèles qui ont
        # nommé l'outil 3 fois sur 3 à la sortie de maintenance (`llm_gateway_check --provider
        # ilaas --model <id> --tools --user … --repeat 3`, les 90 outils du serveur MCP). La
        # mesure du 2026-10-23, faite PENDANT la maintenance, ne valait pas preuve.
        # `mistral-medium-latest` n'y est PAS : 503 « busy » à 6 essais sur 7, donc non mesuré —
        # la liste du prompt reste sa voie jusqu'à une série complète.
        native_tools=('gemma-4-31b', 'llama-3.1-8b', 'mistral-small-4-119b',
                      'qwen-3.6-35b-instruct', 'qwen-3.8-27b'),
        doc='docs/construction/ia/WAMA_LLM.md'),
    # 2026-10-13 (demande de Fabien : « que je puisse poser la clé ») : le service RAG d'ILaaS,
    # jeton À PART de celui du chat. Lu sans clé le même jour sur son `/openapi.json` public :
    # c'est OpenGateLLM, la passerelle d'Albert — `/v1/embeddings`, `/v1/rerank`, `/v1/ocr`,
    # `/v1/audio/transcriptions`, `/v1/chat/completions`, collections et `/v1/search` ;
    # `/v1/models` rend 401 sans jeton. Famille `rag` et non `llm` (décision de Fabien) : poser la
    # clé n'ouvre aucun modèle et RIEN ne la lit encore — son usage se tranche avec le routage des
    # modèles cloud. Une fois tranché, la déclarer comme Albert (`kind='llm'`, `protocol`).
    ExternalSource(
        'ilaas_rag', 'ILaaS RAG (ESR)', 'https://rag-api.ilaas.fr/v1',
        "Embeddings, reclassement et RAG mutualisés de l'ESR (OpenGateLLM) — clé posée, pas encore "
        "utilisée par WAMA", kind='rag', env='ILAAS_RAG_API_BASE',
        api_key_env='ILAAS_RAG_API_KEY',
        api_key_help_url='https://www.ilaas.fr/demande-de-cles-ilaas/',
        hosting='sovereign', cost_tier='free', doc='docs/construction/ia/WAMA_LLM.md'),
    # 2026-10-10 (décision de Fabien) : OpenRouter, AGRÉGATEUR — une clé, plusieurs centaines de
    # modèles de nombreux éditeurs, protocole OpenAI. Sa liste (`GET /models`, lisible sans clé)
    # ne porte pas de `type` mais les MODALITÉS d'entrée et de sortie (`architecture`) et, pour
    # les modèles ouverts, le dépôt servi (`hugging_face_id`) — lus par
    # `cloud_models.list_remote_models`. Mesuré ce jour : 458 modèles, dont 19 gratuits et 170 qui
    # nomment leur dépôt. Hébergement TIERS (l'éditeur du modèle ou son hébergeur) : le plafond
    # d'hébergement du profil s'applique comme pour Anthropic. Clé PERSONNELLE (crédits par
    # compte), donc non partageable. Modèle par défaut : le routeur automatique d'OpenRouter.
    ExternalSource(
        'openrouter', 'OpenRouter', 'https://openrouter.ai/api/v1',
        "Agrégateur de modèles distants (nombreux éditeurs), compatible OpenAI — assistant, apps "
        "et rôles wama-dev-ai via llm_chat", kind='llm', env='OPENROUTER_API_BASE',
        address_editable=True,
        api_key_env='OPENROUTER_API_KEY', user_key=True,
        api_key_help_url='https://openrouter.ai/settings/keys',
        hosting='third_party', cost_tier='metered', protocol='openai',
        default_model='openrouter/auto',
        # Décision de Fabien (2026-10-10) : une requête n'est routée que vers des hébergeurs qui
        # ne conservent pas les données et n'entraînent pas dessus (`data_collection: deny`, doc
        # « provider routing » ; défaut d'OpenRouter : `allow`). `zdr` (aucune conservation, plus
        # strict) n'est pas imposé : il réduit fortement les hébergeurs possibles.
        # Assoupli le 2026-10-12 (Fabien) : la règle suit le plafond du profil — au dernier cran
        # (`third_party_all`), rien n'est ajouté. Mesuré ce jour sur deux modèles `:free` : un
        # seul hébergeur chacun, leur éditeur (Google AI Studio, NVIDIA) — s'il garde les
        # requêtes, `deny` les rend injoignables. VÉRIFIÉ le soir même avec la clé posée :
        # Nemotron 3 Super `:free` → 404 sous `deny` (« Free model training »), réponse en 1,1 s
        # sans ; les deux Gemma 4 `:free` → 429 de l'hébergeur dans les deux cas (file gratuite
        # saturée, rien à conclure).
        no_reuse_request_body='{"provider": {"data_collection": "deny"}}',
        free_models_need_data_reuse=True,
        # Doc d'OpenRouter (« rate limits ») : les modèles `:free` partagent 20 requêtes par
        # minute et par compte. Leur plafond du JOUR dépend des crédits achetés (50 sans, 1000
        # avec 10 $) : non déclaré, il s'apprend au premier refus plutôt que de bloquer à tort.
        quotas=(Quota(20, 60, models=':free'),),
        doc='docs/construction/ia/WAMA_LLM.md'),
    # 2026-09-15 : l'API Anthropic (fournisseur « claude » de l'assistant) et l'ABONNEMENT Claude
    # Code — deux canaux de facturation opposés vers les mêmes modèles (cf. `claude_code.py`).
    # Chacun porte la clé PERSONNELLE de l'utilisateur, au profil ; le `.env` ne sert qu'aux usages
    # sans utilisateur. Type par défaut : tous les modèles Claude lisent texte ET image, et leur
    # liste (`GET /v1/models`) ne porte pas de tâche.
    ExternalSource(
        'anthropic', 'API Anthropic (Claude)', 'https://api.anthropic.com/v1',
        "Modèles Claude facturés à la requête — fournisseur « claude » de l'assistant, via llm_chat",
        kind='llm', api_key_env='ANTHROPIC_API_KEY', user_key=True,
        api_key_help_url='https://console.anthropic.com/settings/keys',
        # Mesuré le 2026-10-26 sur la clé d'instance et sur une clé de profil : `sk-ant-api03-…`.
        api_key_prefix='sk-ant-api',
        hosting='third_party', cost_tier='metered', protocol='anthropic',
        default_remote_type='image-text-to-text', default_model='claude-sonnet-4-6',
        doc='docs/construction/ia/WAMA_LLM.md'),
    ExternalSource(
        # Libellé SANS « (abonnement) » depuis le 2026-10-10 : le coût se lit dans `cost_tier`
        # et se dit par `remote_origin_label` — l'écrire aussi dans le nom le doublait.
        'claude_code', 'Claude Code', 'https://api.anthropic.com/v1',
        "Abonnement Claude PERSONNEL — CLI headless (outil ask_claude_code, fournisseur "
        "« claude-abo », geste !code) ; réservé aux développeurs", kind='llm',
        api_key_env='CLAUDE_CODE_OAUTH_TOKEN', api_key_label='Jeton « claude setup-token »',
        user_key=True,
        # `claude setup-token` rend un jeton `sk-ant-oat01-…` (OAuth longue durée) : une copie
        # depuis le terminal qui en perd le début se voit donc au dépôt.
        api_key_prefix='sk-ant-oat',
        hosting='third_party', cost_tier='subscription', protocol='claude_cli',
        default_remote_type='image-text-to-text', developer_only=True,
        # Les modèles de l'abonnement (2026-10-04, question de Fabien : « je n'ai accès qu'à un
        # seul modèle et je ne sais même pas lequel »). Ce sont les ALIAS du CLI, pas des
        # versions : `claude --help` (2.1.286, lu le jour même) — « --model : Provide an alias
        # for the latest model (e.g. 'fable', 'opus', or 'sonnet') ». Un alias suit la dernière
        # version tout seul : rien à remettre à jour ici quand un modèle sort. Le modèle
        # RÉELLEMENT servi est lu dans la réponse du CLI et affiché (`claude_code.demander`).
        declared_models=(
            ('default', 'Claude Code — modèle par défaut',
             "Le modèle que Claude Code choisit lui-même pour votre abonnement."),
            ('fable', 'Claude Code — Fable',
             "Le plus récent Claude Fable, par l'alias « fable » de Claude Code."),
            ('opus', 'Claude Code — Opus',
             "Le plus récent Claude Opus, par l'alias « opus » de Claude Code."),
            ('sonnet', 'Claude Code — Sonnet',
             "Le plus récent Claude Sonnet, par l'alias « sonnet » de Claude Code."),
        ),
        doc='docs/construction/suivi/ROADMAP.md'),

    # ── Catalogues de modèles ───────────────────────────────────────────────────────────
    ExternalSource(
        'ollama_site', 'ollama.com', 'https://ollama.com',
        "Pages publiques du catalogue Ollama — prospection (HTML scrapé)", kind='catalogue',
        # `gemma4:12b` → la page de la FAMILLE (`ollama:gemma4`) : un tag n'a pas de page propre.
        model_page='library/{id}', platform_ref_prefix='ollama'),
    ExternalSource(
        'ollama_registry', "Registre d'images Ollama", 'https://registry.ollama.ai',
        "Manifestes et digests des tags Ollama — désambiguïse une variante par son ARTEFACT",
        kind='catalogue'),
    # `api_key_env` posé le 2026-09-02 : le jeton vivait dans un fichier que personne ne
    # localisait ; `settings.py` le promeut en `HF_TOKEN`, la page peut donc le DIRE.
    # `user_key` (2026-09-27, décision de Fabien) : un jeton ne sert qu'à TÉLÉCHARGER (un modèle
    # installé se charge par chemin local, sans jeton). Le téléchargement qu'une personne lance
    # se fait avec SON jeton — c'est son compte qui a obtenu l'accès aux dépôts `gated`, et
    # c'est la règle commune des clés (`accounts/api_keys.py`) : pas de repli sur celui de
    # l'instance, qui reste aux usages sans utilisateur (synchronisation, tâches planifiées).
    ExternalSource(
        'huggingface', 'HuggingFace Hub', 'https://huggingface.co',
        "Poids, datasets et fiches de modèles — source principale du parc ; jeton = dépôts "
        "gated + quota d'API relevé", kind='catalogue', api_key_env='HF_TOKEN', user_key=True,
        api_key_label='Jeton HuggingFace (lecture)',
        api_key_help_url='https://huggingface.co/settings/tokens', model_page='{id}'),
    ExternalSource(
        'roboflow', 'Roboflow Universe', 'https://universe.roboflow.com',
        "Fiches de modèles de vision (référence de plateforme, pas de téléchargement)",
        kind='catalogue', model_page='{id}'),
    # ── Corpus de voix : Mozilla Data Collective (décision de Fabien, 2026-09-27) ────────────
    # Pourquoi cette source EXISTE, alors que les corpus arrivaient jusqu'ici par le Hub :
    # depuis **octobre 2025, Common Voice n'est PLUS distribué que par cette plateforme**. Le
    # dépôt `mozilla-foundation/common_voice_17_0` du Hub ne porte plus que `.gitattributes`
    # et `README.md` (mesuré le 27/09) — un `load_dataset` y échoue sur « aucun fichier de
    # données », et la version de `datasets` du venv refuse en plus les scripts de chargement
    # que ce jeu employait. Ce n'est donc pas une panne : c'est une migration.
    #
    # ⚠ DEUX limites MESURÉES à la documentation de l'API, qui décident de ce qu'on peut en
    # faire — et qu'il vaut mieux lire ici qu'à l'usage :
    #   • **chaque utilisateur doit accepter les conditions du jeu de données SUR LE SITE**
    #     avant que sa clé n'ouvre quoi que ce soit ; l'acceptation par l'API seule n'est pas
    #     prévue. Une clé posée au profil ne suffit donc pas : ce prérequis se dit à l'écran.
    #     ✅ VÉRIFIÉ sur l'API réelle le 2026-09-27 : sans clé, `POST /api/datasets/<id>/download`
    #     rend `401 Authentication required` ; avec la clé de Fabien, `403 Terms must be accepted
    #     before downloading: <url du jeu>`. L'API nomme elle-même la page où cliquer — c'est ce
    #     message qu'il faut relayer à l'utilisateur, pas un échec générique ;
    #   • le téléchargement se fait par ARCHIVE (`POST /api/datasets/<id>/download` → URL
    #     présignée), jamais au clip.
    #     ⚠⚠ **Ce commentaire a dit « l'exemple de la doc pèse 268 Go, donc en tirer quatre voix
    #     demanderait de rapatrier tout un corpus » — c'était FAUX**, et la mesure sur le
    #     catalogue RÉEL (2026-09-27, clé de Fabien) l'a renversé : les jeux sont découpés par
    #     LANGUE et par version, et les tailles vont de **51 Mo** (Common Voice Spontaneous 5.0
    #     — French) à **175 Mo** (Scripted 26.0 — French of France, qui porte le **TSV** des
    #     métadonnées, donc `age` et `gender`) et 30,65 Go pour la Scripted 27.0 complète. Tous
    #     en CC0-1.0, `isPaid: false`. Le créneau « âgé » est donc PRATICABLE.
    #     *J'avais pris le chiffre d'un EXEMPLE de documentation pour une propriété de l'API —
    #     un ordre de grandeur lu au lieu d'être mesuré.*
    #
    # `user_key` ET `api_key_env` : la clé de CHACUN pour ce qu'un utilisateur demande, celle
    # de l'instance pour les tâches SANS utilisateur — le téléchargement des voix SYSTÈME en
    # est une (règle des clés personnelles, Fabien 2026-09-15).
    ExternalSource(
        'mozilla_data_collective', 'Mozilla Data Collective (Common Voice)',
        'https://mozilladatacollective.com',
        "Corpus de voix Common Voice — seule distribution depuis octobre 2025 ; métadonnées "
        "d'âge et de genre DÉCLARÉES par le locuteur (ce que VoxPopuli n'a pas)",
        kind='corpus', user_key=True,
        api_key_env='MOZILLA_DATA_COLLECTIVE_API_KEY',
        api_key_label='Clé API Mozilla Data Collective',
        api_key_help_url='https://mozilladatacollective.com/profile/credentials',
        attribution='Mozilla Common Voice (CC0)',
        doc='docs/construction/exploitation/MEDIA_STORAGE_TIERING.md'),

    # ── Bancs de performance (cf. `benchmark_sync`) ──────────────────────────────────────
    ExternalSource(
        'artificial_analysis', 'Artificial Analysis', 'https://artificialanalysis.ai/api/v2',
        "Indices de performance tiers par modalité — API JSON authentifiée",
        kind='banc', api_key_env='ARTIFICIAL_ANALYSIS_API_KEY',
        attribution='Artificial Analysis',
        doc='wama/model_manager/PROSPECTION_PIPELINE.md'),
    ExternalSource(
        'arena', 'LMArena (leaderboard-dataset)', 'https://huggingface.co',
        "Scores Elo par préférence humaine — parquet publié sur le Hub",
        kind='banc', attribution='Arena (leaderboard-dataset, CC-BY-4.0)',
        doc='wama/model_manager/PROSPECTION_PIPELINE.md'),
    # 2026-09-02 : 3ᵉ banc, le premier hors génération — la TRANSCRIPTION (WER, plus bas =
    # mieux). Choisi parce que ses résultats sont des CSV publics sur le Hub, avec un fichier
    # PAR LANGUE (dont le français — le seul banc tiers qui mesure ce que le transcriber fait
    # ici). ⚠ La licence des CSV de résultats n'est pas énoncée par le dépôt (les corpus
    # sous-jacents vont de CC0 à CC-BY-NC-ND) : on cite la source, on ne redistribue rien.
    ExternalSource(
        'open_asr', 'Open ASR Leaderboard (Hugging Face)', 'https://huggingface.co',
        "WER par modèle de transcription (anglais + français) — CSV publiés sur le Hub",
        kind='banc', attribution='Open ASR Leaderboard (Hugging Face, hf-audio)',
        doc='wama/model_manager/PROSPECTION_PIPELINE.md'),

    # 2026-09-02 : 4ᵉ banc — les EMBEDDINGS (le RAG tourne sur bge-m3 sans aucune mesure
    # tierce). Résultats bruts du dépôt `embeddings-benchmark/results` (CC0-1.0) : un JSON par
    # modèle et par tâche, lu sur raw.githubusercontent.com ; l'INDEX des dossiers passe par
    # l'API GitHub (`github_api`, déjà déclarée) parce que `paths.json` du dépôt est périmé
    # (333 modèles sur 685 le 02/09, sans Qwen3-Embedding). Pas de clé : quota anonyme.
    ExternalSource(
        'mteb', 'MTEB — résultats bruts (embeddings-benchmark)', 'https://raw.githubusercontent.com',
        "nDCG@10 par tâche de recherche (jeu FRANÇAIS déclaré) — JSON CC0 lus sur GitHub",
        kind='banc', attribution='MTEB results (embeddings-benchmark/results, CC0-1.0)',
        doc='wama/model_manager/PROSPECTION_PIPELINE.md'),
    # 2026-10-10 : 5ᵉ banc — les CLASSEMENTS des jeux de référence OFFICIELS du Hub
    # (`/api/datasets/<jeu>/leaderboard`), lus par `benchmark_sync.load_hf_benchmarks` à l'adresse
    # de `huggingface`. Valeurs DÉCLARÉES par les auteurs (rarement vérifiées) : dernière priorité,
    # jamais de rang centile. Ils nourrissent aussi la DÉCOUVERTE (`seed_benchmark_candidates`).
    ExternalSource(
        'hf_bench', 'Classements officiels (Hugging Face)', 'https://huggingface.co',
        "Classements des jeux de référence officiels du Hub (OCR documentaire…) — dépôt exact, "
        "valeur et provenance par modèle", kind='banc',
        attribution='Hugging Face — classements des jeux de référence officiels',
        doc='docs/construction/ia/WAMA_QUALITE.md'),

    # ── Outillage et poids ──────────────────────────────────────────────────────────────
    ExternalSource(
        'github', 'GitHub', 'https://github.com',
        "Poids et échantillons publiés en releases (ultralytics, coqui, "
        "serengil/deepface_models…) — TOUT poids qui n'est pas sur HuggingFace passe par ici",
        # `github:owner/repo` ou `github:owner/repo/releases/tag/<tag>` (pilote `github`) : le
        # chemin EST l'identifiant.
        kind='poids', model_page='{id}'),
    # Jeton FACULTATIF (2026-10-12) : deux lecteurs le prenaient dans l'environnement, hors du
    # registre (`prospector.github_release`, `benchmark_sync._mteb_index`) — la page ne pouvait
    # ni le dire ni le poser. Il ne sert qu'à l'API ; le téléchargement d'un poids publié
    # (`github`) n'en a pas besoin.
    ExternalSource(
        'github_api', 'API GitHub', 'https://api.github.com',
        "Versions publiées (fichiers, licence) et index du banc MTEB — jeton facultatif : quota "
        "relevé de 60 à 5000 appels/h", kind='poids',
        api_key_env='GITHUB_TOKEN', api_key_optional=True,
        api_key_label='Jeton GitHub (lecture des dépôts publics, aucune permission)',
        api_key_help_url='https://github.com/settings/personal-access-tokens/new'),
    # 2026-09-30 : le rôle librarian doit savoir si un dépôt est PUBLIÉ sur PyPI — un
    # `pyproject.toml` ne suffit pas (YuE, ACE-Step en ont un et sont absents de PyPI) : sans
    # publication, la route `library` refuse pip, et la voie est vendor.
    ExternalSource(
        'pypi', 'PyPI', 'https://pypi.org',
        "Index des paquets Python — un paquet est-il publié, sous quel nom (API JSON, lecture seule)",
        kind='poids'),
    ExternalSource(
        'pytorch_download', 'download.pytorch.org', 'https://download.pytorch.org',
        "Roues PyTorch/CUDA — installation de dépendances de modèles ; poids officiels de "
        "torchvision (`/models/…`, fichiers DÉCLARÉS : la dorsale resnet18 de MuseTalk)",
        kind='poids'),
    # 2026-10-11 (décision de Fabien : « une version officielle quand elle existe ») — deux
    # serveurs de poids OFFICIELS, chacun pour des fichiers qu'une app DÉCLARE (pilote `files` de
    # la route d'installation, empreinte épinglée). Ils n'ont pas d'autre usage.
    ExternalSource(
        'mediapipe_models', 'Modèles MediaPipe (Google)',
        'https://storage.googleapis.com/mediapipe-models',
        "Modèles des tâches MediaPipe publiés par Google — `face_landmarker.task` du Face Analyzer",
        kind='poids'),
    ExternalSource(
        'face_alignment', 'face-alignment (site de son auteur)',
        'https://www.adrianbulat.com/downloads/python-fan',
        "Poids publiés par l'auteur de la librairie face-alignment — le détecteur de visages S3FD "
        "que MuseTalk charge (l'empreinte du fichier est dans son nom, convention torch.hub)",
        kind='poids'),
    ExternalSource(
        'beat_this', 'Beat This! (JKU Linz, serveur de ses auteurs)',
        'https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp',
        "Points de contrôle publiés par les auteurs du suivi de temps Beat This! (CPJKU) — "
        "`final0.ckpt`, que MuScriptor charge pour trouver tempo, métrique et barres de mesure ; "
        "aucun dépôt officiel sur HuggingFace (2026-10-16)",
        kind='poids'),
    ExternalSource(
        'encodec', 'EnCodec (Meta, serveur de ses auteurs)',
        'https://dl.fbaipublicfiles.com/encodec/v0',
        "Points de contrôle publiés par les auteurs du codec audio EnCodec — "
        "`encodec_24khz-d7cc33bc.th`, que Bark charge pour rendre le son ; la version du Hub "
        "(`facebook/encodec_24khz`) est au format transformers, pas celui que lit la librairie "
        "(2026-10-19)",
        kind='poids'),
    ExternalSource(
        'osv', 'OSV (Open Source Vulnerabilities)', 'https://api.osv.dev/v1',
        "Audit de vulnérabilités des dépendances (contrôle nocturne)",
        kind='audit', doc='docs/construction/suivi/PROJECT_STATUS.md'),
    ExternalSource(
        'duckduckgo', 'DuckDuckGo (HTML)', 'https://html.duckduckgo.com/html/',
        "Recherche web de l'assistant, sans clé — ⚠ HORS SERVICE depuis le 2026-09-26 : le "
        "moteur répond un défi anti-robot au lieu de résultats", kind='recherche'),
    # ── Moteurs de recherche à CLÉ (décision de Fabien, 2026-09-26) ──────────────────────────
    # Même forme que les connecteurs de la médiathèque : sources COMMUNES, clé de CHACUN au
    # profil. Le choix du moteur est une PRÉFÉRENCE (profil) sur un défaut d'instance ; les
    # options de ce choix se dérivent d'ICI, jamais d'une liste écrite ailleurs.
    ExternalSource(
        'exa', 'Exa', 'https://api.exa.ai',
        "Recherche NEURONALE (par le sens) pour l'assistant — 20 000 requêtes/mois offertes, "
        "sans carte bancaire ; le plus généreux des moteurs à clé mesurés le 26/09",
        kind='recherche', user_key=True, api_key_env='EXA_API_KEY',
        api_key_help_url='https://dashboard.exa.ai/api-keys', api_key_label='Clé API Exa'),
    ExternalSource(
        'staan', 'Staan (Qwant + Ecosia)', 'https://api.staan.ai/v2',
        "Index de recherche EUROPÉEN (coentreprise Qwant + Ecosia, Paris) — données sous "
        "juridiction UE, 1 000 requêtes/mois offertes puis 2 €/1 000 ; API ouverte en "
        "libre-service depuis 2026",
        kind='recherche', user_key=True, api_key_env='STAAN_API_KEY',
        api_key_help_url='https://staan.ai/', api_key_label='Clé API Staan'),
    ExternalSource(
        'searxng', 'SearXNG (instance du labo)', 'http://127.0.0.1:8888',
        "Méta-moteur AUTO-HÉBERGÉ, sans clé — n'a PAS d'index propre : il interroge les mêmes "
        "moteurs, depuis l'IP du labo (mesuré en juillet 2026 : Google et Brave y opposent un "
        "défi, seul DuckDuckGo répond). Vie privée, pas fiabilité",
        kind='recherche', scope=LOCAL, setting='SEARXNG_URL', env='SEARXNG_URL',
        address_editable=True),

    # ── Banques de médias — les connecteurs de la médiathèque (décision de Fabien, 22/09) ────
    # Sources COMMUNES, clé de CHACUN (`user_key`) : aucune clé d'instance, donc pas
    # d'`api_key_env`. L'adresse est la BASE que chaque connecteur complète de son chemin ;
    # `media_library/providers/*` la lit ici (`base_url`), et son proxy suit la portée déclarée
    # (`proxies_for`). Libellé et page de la clé repris des lignes `MediaProvider` (migrations
    # 0005 et 0007) — la saisie, elle, reste au profil.
    ExternalSource(
        'wikimedia', 'Wikimedia Commons', 'https://commons.wikimedia.org/w/api.php',
        "Images et médias libres (CC, domaine public) — recherche de la médiathèque, sans clé",
        kind='media'),
    ExternalSource(
        'pixabay', 'Pixabay', 'https://pixabay.com/api',
        "Photos et vidéos libres de droits — recherche de la médiathèque",
        kind='media', user_key=True, api_key_help_url='https://pixabay.com/api/docs/',
        api_key_label='Clé API Pixabay'),
    ExternalSource(
        'pexels', 'Pexels', 'https://api.pexels.com',
        "Photos et vidéos libres de droits (Pexels License) — recherche de la médiathèque",
        kind='media', user_key=True, api_key_help_url='https://www.pexels.com/api/',
        api_key_label='Clé API Pexels'),
    ExternalSource(
        'openverse', 'Openverse', 'https://api.openverse.org/v1',
        "Moteur Creative Commons (images, musiques) — recherche de la médiathèque ; jeton optionnel",
        kind='media', user_key=True,
        api_key_help_url='https://api.openverse.org/v1/auth_tokens/register/',
        api_key_label='Token Openverse (optionnel)'),
    ExternalSource(
        'jamendo', 'Jamendo', 'https://api.jamendo.com/v3.0',
        "Musiques Creative Commons — recherche de la médiathèque",
        kind='media', user_key=True, api_key_help_url='https://devportal.jamendo.com/',
        api_key_label='Client ID Jamendo'),
    ExternalSource(
        'freesound', 'Freesound', 'https://freesound.org/apiv2',
        "Voix et bruitages — recherche de la médiathèque",
        kind='media', user_key=True, api_key_help_url='https://freesound.org/apiv2/apply/',
        api_key_label='Clé API Freesound'),
    # Avatars 3D (2026-09-30) : l'API GitHub publique LISTE les dossiers d'avatars déclarés
    # (`media_library/providers/avatars3d.py`, une ligne par dépôt) ; sans clé. Même adresse que
    # `github_api`, source distincte : c'est un CONNECTEUR de la médiathèque (clé = son slug).
    ExternalSource(
        'avatars3d', 'Avatars 3D (dépôts GitHub)', 'https://api.github.com',
        "Avatars GLB riggés publiés dans des dépôts déclarés (TalkingHead…) — recherche de la "
        "médiathèque, pour le moteur d'avatar 3D de l'avatarizer ; sans clé",
        kind='media'),

    # ── Stockage de fichiers (décision de Fabien, 2026-10-10) ─────────────────────────────────
    # Le Nextcloud de l'ÉTABLISSEMENT, monté au filemanager par rclone : la PREMIÈRE source
    # d'hébergement `private` (la donnée quitte le poste, pas l'institution). Son adresse se POSE
    # sur la page « Sources externes » par un admin (repli : `WAMA_NEXTCLOUD_URL` de `.env`) : le
    # dépôt est public, l'adresse d'un établissement n'y a pas sa place ; le défaut ci-dessous
    # n'est qu'un exemple, que la sonde dira injoignable. Posée, le filemanager la PROPOSE dans
    # la fenêtre « Connecter un dossier » (`filemanager.views.api_mounts`).
    # Joint par l'EXTÉRIEUR : portée sortante, donc le proxy sortant passé à rclone
    # (`remote_mounts._env`). Ni `api_key_env` ni `user_key` : le mot de passe d'application
    # est saisi en connectant le dossier et gardé chiffré sur le montage.
    ExternalSource(
        'nextcloud', "Nextcloud de l'établissement", 'https://nextcloud.example.org',
        "Nuage de fichiers monté comme un dossier connecté du filemanager (rclone, WebDAV) — "
        "parcourir, prévisualiser, envoyer vers une app", kind='stockage',
        env='WAMA_NEXTCLOUD_URL', hosting='private', address_editable=True, address_required=True,
        doc='docs/construction/suivi/ROADMAP.md'),
    # Stockages à connexion OAUTH (2026-10-11, demande de Fabien : « si on veut ajouter Google
    # Drive, etc. ») — montés par rclone comme le nuage (`remote_mounts.STORAGE_TYPES`). La clé
    # d'instance est le CLIENT OAuth que l'établissement déclare chez le fournisseur, posé sur la
    # page sous la forme `identifiant:secret` ; l'adresse de retour à y déclarer est
    # `<adresse de WAMA>/filemanager/api/mounts/oauth/callback/`. Le jeton de CHAQUE utilisateur
    # est gardé chiffré sur son montage. Sans client posé, le stockage n'est pas proposé.
    ExternalSource(
        'google_drive', 'Google Drive', 'https://www.googleapis.com',
        "Stockage Google monté comme un dossier connecté du filemanager (rclone, OAuth) — "
        "l'utilisateur accorde l'accès dans son navigateur", kind='stockage',
        api_key_env='WAMA_GOOGLE_DRIVE_OAUTH_CLIENT', hosting='third_party',
        api_key_label='Client OAuth (identifiant:secret)',
        api_key_help_url='https://console.cloud.google.com/apis/credentials',
        doc='docs/construction/suivi/ROADMAP.md'),
    # L'adresse est celle de l'ANNUAIRE Microsoft : `common` (tout compte) par défaut ; un
    # établissement y pose la sienne (`https://login.microsoftonline.com/<tenant>`).
    ExternalSource(
        'onedrive', 'OneDrive / SharePoint', 'https://login.microsoftonline.com/common',
        "Stockage Microsoft monté comme un dossier connecté du filemanager (rclone, OAuth) — "
        "l'utilisateur accorde l'accès dans son navigateur", kind='stockage',
        api_key_env='WAMA_ONEDRIVE_OAUTH_CLIENT', hosting='third_party', address_editable=True,
        api_key_label='Client OAuth (identifiant:secret)',
        api_key_help_url='https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps',
        doc='docs/construction/suivi/ROADMAP.md'),
)

#: Le dataset Arena, nommé une fois (ce n'est pas une URL : un identifiant de dataset du Hub).
ARENA_DATASET = 'lmarena-ai/leaderboard-dataset'

#: Les datasets de RÉSULTATS de l'Open ASR Leaderboard, nommés une fois — même nature que
#: `ARENA_DATASET`. Le Space lit ces CSV par `snapshot_download` (vérifié dans son `init.py`
#: le 2026-09-02) ; les noms de fichier sont ceux qu'il consomme. Clé = jeu (celle que
#: `benchmark_sync.CATEGORIES` cite), valeur = (dépôt, fichier).
OPEN_ASR_DATASETS = {
    'english_short': ('hf-audio/open-asr-leaderboard-results', 'english_short_latest.csv'),
    'multilingual_fr': ('hf-audio/multilingual_evals', 'multilingual_fr.csv'),
}

#: Le dépôt GitHub des résultats MTEB, nommé une fois (identifiant `owner/repo`, pas une URL).
MTEB_RESULTS_REPO = 'embeddings-benchmark/results'


def by_key() -> dict[str, ExternalSource]:
    return {s.key: s for s in SOURCES}


def model_platforms() -> dict[str, ExternalSource]:
    """Les PLATEFORMES de modèles, par préfixe de `AIModel.platform_ref` — les sources qui déclarent
    la fiche d'un modèle (`model_page`). C'est le vocabulaire des plateformes : la validation du
    manifeste `model`, `backfill_platform_refs` et le lien de la card le lisent (2026-10-22).
    Ajouter une plateforme = déclarer sa fiche sur sa source, ici."""
    return {(s.platform_ref_prefix or s.key): s for s in SOURCES if s.model_page}


def model_page_url(platform_ref: str) -> str | None:
    """L'adresse de la fiche publique d'un modèle, DÉRIVÉE de son `platform_ref`
    (`huggingface:org/repo` → `https://huggingface.co/org/repo`), ou None pour une plateforme que
    rien ne déclare. L'adresse de base est celle de la source (`base_url`), jamais recopiée."""
    platform, _, ident = (platform_ref or '').partition(':')
    source = model_platforms().get(platform)
    if source is None or not ident:
        return None
    return f"{base_url(source.key)}/{source.model_page.format(id=ident)}"


#: La plateforme du Hub Hugging Face dans `platform_ref` — la clé de sa source ci-dessus.
HUGGINGFACE = 'huggingface'


def hf_repo(platform_ref) -> str:
    """Le dépôt du Hub (`org/nom`) qu'un `platform_ref` désigne, '' pour une autre plateforme.

    LA lecture du dépôt d'un modèle (2026-10-27, décision de Fabien : « ne garder que
    `platform_ref` »). `AIModel.hf_id` était le même fait écrit à part, né avant les autres
    plateformes : mesuré ce jour, 397 lignes sur 398 portaient la même valeur des deux côtés. Une
    déclaration d'app ou de moteur dit `platform_ref`, et qui doit appeler le Hub lit ceci."""
    platform, _, ident = str(platform_ref or '').strip().partition(':')
    return ident.strip() if platform == HUGGINGFACE else ''


def hf_platform_ref(repo) -> str:
    """Le `platform_ref` d'un dépôt du Hub (`org/nom` → `huggingface:org/nom`), '' sans dépôt."""
    repo = str(repo or '').strip()
    return f'{HUGGINGFACE}:{repo}' if repo else ''


class _RemoteEngine:
    """Porteur d'inventaire d'un fournisseur DISTANT — pas un backend Python (patron
    `ollama_host._MoteurOllama` : un moteur qui n'est pas du code qu'on charge).

    `missing_packages()` rend toujours [] : ce qui manque vraiment pour appeler un modèle distant
    — une clé ouverte à CET utilisateur — est une disponibilité PAR UTILISATEUR, que l'inventaire
    (global) ne sait pas dire ; la sélection la reçoit à part (`select_model(cloud_keys=…)`).
    """

    __slots__ = ()

    @classmethod
    def missing_packages(cls):
        return []

    def __repr__(self):
        return '<moteur distant>'


def serves_many_tasks(key: str) -> bool:
    """La source `key` sert-elle des modèles de plusieurs tâches sous un même moteur, hors du
    processus WAMA ? Déclaré (`multi_task`), ou par nature pour un fournisseur LLM. False pour un
    moteur qui n'est pas une source (une bibliothèque : `transformers`, `onnxruntime`…)."""
    source = by_key().get(key or '')
    return source is not None and (source.multi_task or source.kind == 'llm')


def llm_engine_inventory() -> dict:
    """{moteur: porteur} des fournisseurs LLM distants — un par source `llm` (2026-09-15)."""
    return {s.key: _RemoteEngine for s in SOURCES if s.kind == 'llm'}


_BY_KEY = by_key()


def get(key: str) -> ExternalSource:
    """La source déclarée. `KeyError` explicite : une clé inconnue est un défaut de code."""
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(
            f"source externe inconnue : {key!r}. Déclarées : {', '.join(sorted(_BY_KEY))}"
        ) from None


def base_url(key: str) -> str:
    """Adresse EFFECTIVE : celle posée sur la page « Sources externes » (source déclarée
    `address_editable`, 2026-10-10), puis réglage Django, puis variable d'environnement, puis
    défaut déclaré.

    Sans barre finale — les appelants concatènent leur chemin.

    ⚠ Le défaut déclaré ne vit QU'ICI. C'est tout l'objet de la brique : un `getattr(settings,
    'OLLAMA_HOST', 'http://127.0.0.1:11434')` recopié chez huit appelants promet un repli qui
    ne se déclenche jamais, et qui divergerait le jour où il se déclencherait.
    """
    return (_address_override(key)[1] or get(key).base).rstrip('/')


def _address_override(key: str) -> tuple[str, str]:
    """`(origine, adresse)` qui surcharge le défaut déclaré : 'stored' (page), 'setting',
    'env', ou `('', '')` quand seul le défaut déclaré vaut."""
    src = get(key)
    if src.address_editable:
        stored = stored_instance_address(key)
        if stored:
            return 'stored', stored
    if src.setting:
        try:
            from django.conf import settings
            val = getattr(settings, src.setting, '') or ''
        except Exception:
            val = ''
        if val:
            return 'setting', val
    if src.env and os.environ.get(src.env, ''):
        return 'env', os.environ[src.env]
    return '', ''


def address_origin(key: str) -> str:
    """D'où vient l'adresse : 'stored', 'setting', 'env', ou '' (défaut déclaré)."""
    return _address_override(key)[0]


def stored_instance_address(key: str) -> str:
    """L'adresse posée en base pour `key` (`InstanceApiKey.base_url`), ou ''. Même lecture
    paresseuse et même repli silencieux que `stored_instance_key`."""
    try:
        from wama.accounts.models import InstanceApiKey
        row = InstanceApiKey.objects.filter(source=key).exclude(base_url='').first()
        return row.base_url if row else ''
    except Exception:
        return ''


def valid_address(text: str) -> str:
    """L'adresse saisie, normalisée (sans barre finale), ou '' si ce n'en est pas une :
    schéma http(s), hôte présent, aucun espace — elle part telle quelle dans des requêtes."""
    from urllib.parse import urlsplit
    text = (text or '').strip()
    if not text or any(c.isspace() for c in text):
        return ''
    parts = urlsplit(text)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        return ''
    return text.rstrip('/')


def proxies_for(key: str):
    """`proxies` à passer à `requests`, choisis d'après la PORTÉE déclarée.

    L'appelant n'a plus à savoir si sa source est locale : c'est une propriété de la source.
    Neutralise le proxy pour un service local, l'emprunte pour une source Internet.
    """
    from wama.common.utils.http_proxy import local_proxies, outbound_proxies
    return local_proxies() if get(key).scope == LOCAL else outbound_proxies()


def api_key(key: str) -> str:
    """Clé d'API de l'INSTANCE, ou '' — jamais une exception : une source sans clé se SKIPPE
    avec un motif, elle ne fait pas tomber l'appelant.

    Celle posée par un admin sur la page « Sources externes » d'abord (`accounts.InstanceApiKey`,
    2026-10-07), la variable `.env` ensuite — repli du démarrage et de la ligne de commande."""
    src = get(key)
    if not src.api_key_env:
        return ''
    return stored_instance_key(key) or os.environ.get(src.api_key_env, '')


def stored_instance_key(key: str) -> str:
    """La clé d'instance ENREGISTRÉE en base pour `key`, ou ''. Lue paresseusement : ce module
    ne dépend pas de Django, et une base pas encore prête (démarrage, migration en attente)
    ou une clé illisible (secret changé) se replient sur le `.env` au lieu de lever."""
    try:
        from wama.accounts.models import InstanceApiKey
        row = InstanceApiKey.objects.filter(source=key).exclude(api_key='').first()
        return row.api_key if row else ''
    except Exception:
        return ''


def api_key_origin(key: str) -> str:
    """D'où vient la clé d'instance : 'stored' (page Sources externes), 'env' (`.env`) ou ''."""
    src = get(key)
    if not src.api_key_env:
        return ''
    if stored_instance_key(key):
        return 'stored'
    return 'env' if os.environ.get(src.api_key_env, '') else ''


def is_configured(key: str) -> bool:
    """La source est-elle utilisable en l'état ? (clé posée si elle en exige une)

    ⚠ Ne dit RIEN de sa joignabilité — sonder appartient à l'étape 3 (page en nature `mesure`).
    Une source anonyme est toujours « configurée » ; cela ne veut pas dire qu'elle répond.
    ⚠ Ne dit RIEN non plus de la clé d'UN utilisateur (`user_key`) : c'est la configuration de
    l'INSTANCE. Un connecteur de la médiathèque n'a rien à configurer ici — sa clé se pose au
    profil de chacun, et c'est son connecteur qui refuse, avec un motif, quand elle manque. La
    page le dit en toutes lettres (« clé par utilisateur ») au lieu d'un « configurée » trompeur.
    Une source dont l'adresse est EXIGÉE (`address_required`) ne l'est pas tant qu'aucune
    adresse n'est posée : son défaut déclaré n'est qu'un exemple. Une clé FACULTATIVE
    (`api_key_optional`) absente ne la rend pas « non configurée » : la source répond sans elle.
    """
    src = get(key)
    if src.address_required and not address_origin(key):
        return False
    return bool(api_key(key)) if src.api_key_env and not src.api_key_optional else True


def attributions() -> tuple[str, ...]:
    """Attributions exigées par les licences des sources qui en portent une.

    DÉRIVÉE du registre, jamais écrite en dur : une source ajoutée se cite d'elle-même. L'Arena
    est sous CC-BY-4.0 — l'attribution est une obligation, pas une politesse, et une chaîne
    figée quelque part est une chaîne qu'on oubliera de mettre à jour.
    """
    return tuple(s.attribution for s in SOURCES if s.attribution)


# ── La SONDE (étape 3) — ce que le bouton « Actualiser » de la page mesure ──────────────────

#: Court à dessein : la sonde répond « joignable ? », pas « performant ? ». Un service local qui
#: met 5 s à répondre est déjà une information — la latence est relevée à part.
PROBE_TIMEOUT_S = 5.0


def effective_url(key: str) -> str:
    """Adresse EFFECTIVE d'une source — celle qu'on sonde et qu'on appelle. Pour Ollama, le
    résolveur spécialisé : sonder `127.0.0.1` depuis WSL2 dirait « injoignable » d'un service qui
    tourne — le mensonge exact que la réécriture vers la passerelle Windows existe pour empêcher.

    Publique depuis le 2026-10-20 : le moteur de vectorisation (`common/vectors/engine.py`) en
    écrivait une copie pour ses fournisseurs."""
    if key == 'ollama':
        from wama.common.utils.ollama_host import ollama_base
        return ollama_base()
    return base_url(key)


def probe(key: str, timeout: float = PROBE_TIMEOUT_S) -> dict:
    """Sonde UNE source : clé posée ? adresse joignable ? en combien de temps ?

    « Joignable » = le serveur a RÉPONDU en HTTP, quel que soit le statut : un 403 (tier d'API),
    un 404 (pas de page à la racine) ou un 405 prouvent autant la joignabilité qu'un 200 — seul
    un échec de connexion ou un délai expiré dit le contraire. Exiger `200` ferait accuser de
    panne des sources en parfaite santé dont la racine n'est simplement pas une page.

    ⚠ La sonde ne suit PAS les redirections et ne lit PAS le corps (`stream=True`, fermé
    aussitôt) : elle prouve la connectivité, elle ne télécharge rien.
    """
    import time as _time

    import requests

    out = {'key': key, 'url': effective_url(key), 'configured': is_configured(key),
           'reachable': None, 'status': None, 'latency_ms': None, 'error': ''}
    if get(key).address_required and not address_origin(key):
        # Le défaut déclaré n'est qu'un exemple : le sonder dirait « en panne » une source
        # simplement pas encore configurée.
        out['error'] = 'adresse à poser (page Sources externes)'
        return out
    t0 = _time.monotonic()
    try:
        r = requests.get(out['url'], timeout=timeout, proxies=proxies_for(key),
                         stream=True, allow_redirects=False)
        out['reachable'] = True
        out['status'] = r.status_code
        r.close()
    except requests.RequestException as e:
        out['reachable'] = False
        out['error'] = f"{type(e).__name__}: {str(e)[:160]}"
    out['latency_ms'] = round((_time.monotonic() - t0) * 1000)
    return out


def report_path():
    from django.conf import settings
    from pathlib import Path
    return Path(settings.BASE_DIR) / 'logs' / 'external_sources_report.json'


def probe_all(write: bool = False) -> dict:
    """Sonde TOUTES les sources déclarées, et écrit le rapport si demandé.

    Tourne en Celery (nature `mesure` du registre `sources_externes`) : une quinzaine de
    requêtes réseau, même courtes, n'ont rien à faire dans un worker web.
    """
    import datetime
    import json

    results = [probe(s.key) for s in SOURCES]
    counts = {
        'total': len(results),
        'reachable': sum(1 for r in results if r['reachable']),
        'unreachable': sum(1 for r in results if r['reachable'] is False),
        'unconfigured': sum(1 for r in results if not r['configured']),
    }
    rapport = {'generated_at': datetime.datetime.now().isoformat(timespec='seconds'),
               'counts': counts, 'results': results}
    if write:
        p = report_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding='utf-8')
    return rapport


def last_report() -> dict | None:
    """Le dernier rapport ÉCRIT, ou None — la page l'affiche sans jamais sonder elle-même."""
    import json
    try:
        return json.loads(report_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
