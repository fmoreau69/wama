"""
Métadonnée d'app — déclaration des « prompt targets » (ROADMAP §2bis / §16.6).

SOURCE UNIQUE décrivant, pour chaque app, quels champs sont des prompts et leur **KIND**.
Consommée par : la PromptPipeline (traitement), l'assistant IA et la méta-app (découverte de la
structure de prompt d'une app sans lire son code). Au lieu de coder `kind=...` dans chaque tâche,
le KIND est déclaré ICI, en un seul endroit.

Chaque target : {field, kind, [model_field, source, default_model_type, when, domain, domain_field]}.
- field             : nom du champ prompt sur l'instance.
- kind              : 'generative' | 'concept' | 'intent' | 'text' (cf. prompt_pipeline).
- model_field       : attribut de l'instance donnant l'id du modèle cible (pour ses capacités langue).
- source            : source du modèle dans le catalogue AIModel (défaut = nom de l'app).
- default_model_type: type de repli si le modèle est introuvable (ex. 'diffusion').
- when              : ce qui conditionne le traitement — un attribut booléen de l'instance
                      (ex. 'use_sam3'), ou une condition de la grammaire `show_if` du schéma
                      ({'field': 'target_mode', 'equals': 'description'}, 2026-09-27).
- lyrics            : le prompt peut porter des PAROLES balisées après sa description
                      (`[Verse]`, `[Chorus]`… — `tagged_lyrics`). Traduction et enrichissement
                      ne touchent que la DESCRIPTION ; les paroles sont rendues telles quelles
                      (2026-10-04 : un LLM qui « améliore » ou traduit des paroles les détruit).
- domain / domain_field : domaine média pour la sélection du SKILL d'enrichissement
  ([[prompt_skills]] : `<app>-<domain>.md`) — statique (`domain='music'`) ou lu sur l'instance
  (`domain_field='output_type'`, ex. imager image|video). Repli = model_type du modèle cible.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PROMPT_TARGETS = {
    'imager': [
        # `enrich=True` : le prompt positif est « upsamplé » si l'enrichissement est activé
        # (settings.WAMA_PROMPT_ENRICH, OFF par défaut). PAS le négatif (liste de choses à éviter,
        # l'étoffer n'aurait pas de sens).
        # `model` : nomme le modèle Django porteur du prompt → le branchement de l'enrichissement
        # À L'INGESTION en est DÉDUIT ([[prompt_ingest]]). Aucune app n'écrit de récepteur ni de
        # tâche Celery ; il suffit que le modèle hérite du mixin `PromptScoped`.
        {'field': 'prompt',          'kind': 'generative', 'model_field': 'model',
         'source': 'imager', 'default_model_type': 'diffusion', 'enrich': True,
         'model': 'imager.ImageGeneration',
         'domain_field': 'output_type'},   # image|video → skill imager-image / imager-video
        {'field': 'negative_prompt', 'kind': 'generative', 'model_field': 'model',
         'source': 'imager', 'default_model_type': 'diffusion'},
    ],
    'anonymizer': [
        # `enrich: True` AJOUTÉ le 2026-09-23 — sans lui le skill `anonymizer-detection` était
        # résolu mais jamais appliqué, et SAM3 recevait la phrase de l'utilisateur telle quelle
        # (« Detect faces and license plates. » → 0 masque, image inchangée, aucune erreur).
        # Le hook « concept » de la pipeline (`prompt_pipeline`, Hook A bis) transforme la
        # phrase en LISTE de concepts, que `SAM3Processor` segmente un par un.
        # `when` : le prompt ne sert qu'en mode DESCRIPTION (`app_modes`, `mode_param`) — il
        # suivait le booléen `use_sam3` jusqu'au 2026-09-27.
        {'field': 'sam3_prompt', 'kind': 'concept',
         'when': {'field': 'target_mode', 'equals': 'description'},
         'domain': 'detection', 'enrich': True},
    ],
    'cam_analyzer': [
        # Prompts de marquages SAM3 : LISTE de {label, prompt}. Enrichis en « concept »
        # anglophone (skill cam_analyzer-transport) — l'itération sur la liste est faite
        # dans la tâche (`analyze_sam3_only_task`) via enrich_on_demand ; `list_item_field`
        # documente la structure pour un futur hook générique.
        # `when` : le champ RÉEL du modèle (2026-09-27) — la déclaration citait `use_sam3`, que
        # `Session` n'a jamais eu ; `_when_ok` l'aurait donc toujours lu faux.
        {'field': 'sam3_markings_prompts', 'kind': 'concept', 'when': 'sam3_markings_enabled',
         'domain': 'transport', 'list_item_field': 'prompt'},
    ],
    'composer': [
        # MusicGen / AudioCraft : prompt texte décrivant la musique/SFX à générer, entraîné en
        # anglais → un prompt FR doit être traduit. default_model_type='music' mappe sur ['en']
        # ([[lang_routing]]) tant que les modèles composer ne sont pas catalogués avec leurs langues.
        # enrich activé 2026-07-08 : le blocage était les consignes visuelles uniques — levé par
        # le skill dédié `composer-music.md` ([[prompt_skills]]). Reste gaté par l'interrupteur
        # maître WAMA_PROMPT_ENRICH (OFF par défaut).
        # `model` (2026-10-04, la route de l'imager) : `ComposerGeneration` hérite de
        # `PromptScoped` — enrichi à l'ingestion, éditable à deux états, annulable.
        {'field': 'prompt', 'kind': 'generative', 'model_field': 'model',
         'source': 'composer', 'default_model_type': 'music', 'enrich': True,
         'model': 'composer.ComposerGeneration',
         'domain': 'music', 'lyrics': True},
    ],
    'assistant': [
        # Le message chat = intention pour un LLM. Modèle résolu dynamiquement (pas un champ
        # d'instance) → passer `model_id=` à process_prompt_for. LLM assistant multilingue →
        # routing direct → AUCUNE traduction/chargement (résource-safe). Ne traduit que si le
        # modèle résolu déclare explicitement ne pas gérer la langue de l'utilisateur.
        {'field': 'message', 'kind': 'intent', 'model_field': None, 'source': 'ollama'},
    ],
    # describer : le prompt vision est interne (piloté par output_language), pas un champ texte user.
    # synthesizer : AUCUN target actif (décision §16.6). `text_content` = contenu à FAIRE DIRE
    #   (TTS) → ne JAMAIS traduire (on prononce ce que l'utilisateur a écrit). `scene_description`
    #   (conditionnement de scène Higgs Audio multi-speaker) = candidat 'concept' EN possible, mais
    #   non câblé tant que la langue d'entraînement Higgs n'est pas vérifiée (prudence).
    'synthesizer': [],
}


def prompt_targets(app: str) -> list:
    """Targets de prompt déclarés pour une app (liste, vide si aucune).

    Une app créée DE ZÉRO depuis un manifeste (bac à sable) n'est pas dans `PROMPT_TARGETS` : ses
    targets sont ceux de sa facette `prompts`, lus par `sandbox.born_declaration` (2026-10-01)."""
    if app in PROMPT_TARGETS:
        return PROMPT_TARGETS[app]
    from wama.common.sandbox import born_declaration   # module PUR — aucun cycle
    return list(((born_declaration(app, 'prompts') or {}).get('targets')) or [])


def _target(app: str, field: str):
    for t in prompt_targets(app):
        if t['field'] == field:
            return t
    return None


def _resolve_model(app: str, instance, tgt, model_id=None):
    """
    Capacités + type + contrat de prompt du modèle cible (AIModel) pour ce target,
    ou (None, default_type, None).

    `model_id` (optionnel) court-circuite la lecture du `model_field` de l'instance : utile quand
    le modèle est résolu dynamiquement (ex. assistant : modèle Ollama choisi à l'exécution).

    Le CONTRAT (`prompt_contract`, déclaré par le manifeste du modèle) rejoint les capacités
    (2026-08-26) : même lecture, même modèle cible — le skill d'app porte la méthode
    d'enrichissement, le modèle porte son contrat de sortie (prompt_skills/README.md).
    """
    mid = model_id
    if mid is None:
        mfield = tgt.get('model_field')
        if not mfield or instance is None:
            return None, tgt.get('default_model_type'), None
        mid = getattr(instance, mfield, None)
    if not mid:
        return None, tgt.get('default_model_type'), None
    try:
        from wama.common.utils.model_keys import catalog_key
        from wama.model_manager.models import AIModel
        source = tgt.get('source', app)
        # `catalog_key` (brique `model_keys`, ralliée le 2026-10-01) : une valeur déjà CLÉ
        # (`ollama:qwen3.8:latest`, l'imager depuis F4b) est rendue telle quelle, un identifiant nu
        # reçoit `source`. Le `f"{source}:{mid}"` d'avant fabriquait `imager:imager:…` sur une clé.
        m = AIModel.objects.filter(model_key=catalog_key(str(mid), source)).first()
        return ((m.capabilities if m else None),
                (m.model_type if m else tgt.get('default_model_type')),
                (m.prompt_contract or None) if m else None)
    except Exception:
        return None, tgt.get('default_model_type'), None


def process_prompt_for(app: str, field: str, value, instance=None, user=None, console=None,
                       model_id=None, enrich=None, glossary=None, full=False):
    """
    Traite UN prompt d'une app selon sa déclaration `PROMPT_TARGETS` (KIND + modèle cible).
    L'app passe la VALEUR résolue (gère ses propres fallbacks) ; le KIND vient de la déclaration.
    `model_id` : id de modèle explicite (apps sans instance Django, ex. assistant).

    `enrich`   : force/inhibe l'enrichissement en surchargeant la déclaration. `None` = suivre
                 `PROMPT_TARGETS`. Passer `False` depuis une tâche dont le prompt a DÉJÀ été
                 enrichi à l'ingestion (cf. [[prompt_enrichment]]) évite une seconde passe LLM.
    `glossary` : termes à préserver verbatim (mots-clés cliqués par l'utilisateur).
    `full`     : retourner le dict complet de la pipeline (`prompt`, `original`, `enriched`,
                 `translated`, `routing`, `reason`) au lieu du seul prompt traité — nécessaire
                 pour PERSISTER la trace et pouvoir montrer/annuler côté UI.

    Fail-safe : retourne `value` inchangé si pas de target / valeur vide / erreur (et, si
    `full`, un dict de même forme marquant l'absence de traitement).
    """
    tgt = _target(app, field)
    if tgt is None or not value or not str(value).strip():
        if full:
            return {'prompt': value, 'original': value, 'translated': False, 'enriched': False,
                    'reference_context': False, 'routing': None, 'reason': 'no-target'}
        return value
    from .prompt_pipeline import process_prompt
    caps, mtype, contract = _resolve_model(app, instance, tgt, model_id=model_id)
    domain = _domain_for(instance, tgt)
    original, (value, lyrics) = value, _spared_lyrics(tgt, value)
    res = process_prompt(value or '', kind=tgt.get('kind', 'text'),
                         model_capabilities=caps, model_type=mtype,
                         enrich=tgt.get('enrich', False) if enrich is None else enrich,
                         reference_files=_resolve_reference_files(instance, tgt),
                         user=user, console=console, glossary=glossary,
                         app=app, domain=domain, prompt_contract=contract)
    if lyrics:
        res = _rejoin_lyrics(res, original, lyrics, user, console)
    return res if full else res['prompt']


def _spared_lyrics(tgt, value):
    """(description, paroles) d'une cible qui déclare `lyrics` ; sinon (valeur, '')."""
    if not tgt or not tgt.get('lyrics') or not value:
        return value, ''
    from wama.common.backends.music_generation_base import tagged_lyrics
    caption, lyrics = tagged_lyrics(str(value))
    return (caption, lyrics) if lyrics else (value, '')


def _with_lyrics(head, lyrics):
    head = str(head or '').strip()
    return f"{head}\n\n{lyrics}" if head else lyrics


def _rejoin_lyrics(res, original, lyrics, user, console):
    """Les paroles reviennent INTACTES après la description traitée — et on prévient quand le
    modèle ne déclare pas la langue dans laquelle elles sont (supposée : celle du profil, comme
    pour la description ; aucune détection de langue du texte n'existe dans WAMA)."""
    res = dict(res)
    res['prompt'] = _with_lyrics(res.get('prompt'), lyrics)
    res['original'] = original
    res['lyrics_spared'] = True
    routing = res.get('routing') or {}
    if console:
        if routing.get('input_translate'):
            from .prompt_pipeline import _user_lang
            langs = ', '.join(l for l in (routing.get('model_languages') or []) if l != '*')
            console(f"🎤 Paroles gardées telles quelles (jamais traduites). Si elles sont en "
                    f"« {_user_lang(user)} », ce modèle ne déclare pas cette langue"
                    f"{f' ({langs})' if langs else ''} : il risque de mal les chanter.")
        else:
            console("🎤 Paroles gardées telles quelles : seule la description est traitée.")
    return res


def enrich_prompt_value(app, field, value, **kwargs):
    """`enrich_on_demand` sur une valeur de champ-prompt, en suivant la DÉCLARATION de la cible :
    des paroles balisées (`lyrics`) sont tenues hors du LLM et recollées telles quelles. Le ✨ et
    l'ingestion passent ici — mêmes règles que la pipeline du lancement. Lève `RuntimeError`
    comme `enrich_on_demand`."""
    from .prompt_enrichment import enrich_on_demand
    caption, lyrics = _spared_lyrics(_target(app, field), value)
    if not lyrics:
        return enrich_on_demand(value, app=app, **kwargs)
    if not str(caption or '').strip():
        raise RuntimeError("Rien à enrichir : le prompt ne porte que des paroles — décrivez le "
                           "style avant elles (les paroles ne sont jamais réécrites).")
    return _with_lyrics(enrich_on_demand(caption, app=app, **kwargs), lyrics)


def write_lyrics_for(app, field, description, *, language='en', timeout=90):
    """Les PAROLES d'une chanson décrite par `description`, balisées (`[Verse]`, `[Chorus]`…), ou
    '' — le SEUL lieu où un LLM écrit des paroles, et seulement quand on les DEMANDE (réglage de
    voix « Chanson » sans paroles fournies, composer, 2026-10-04). Skill `<app>-lyrics` ; une cible
    qui ne déclare pas `lyrics` n'en reçoit jamais. Ne lève jamais."""
    tgt = _target(app, field)
    if not tgt or not tgt.get('lyrics'):
        return ''
    try:
        from wama.common.backends.music_generation_base import tagged_lyrics
        from .prompt_enrichment import enrich_generative
        from .prompt_skills import resolve_skill
        name, text = resolve_skill(app=app, domain='lyrics', kind=None)
        if not text:
            return ''
        brief = str(description or '').strip() or 'A song.'
        out = enrich_generative(brief, language=language, skill_name=name, skill_text=text,
                                timeout=timeout, allow_shorter=True)
        _caption, lyrics = tagged_lyrics(out if out != brief else '')
        return lyrics
    except Exception as exc:
        logger.debug(f"[app_metadata] paroles {app}.{field} non écrites ({exc})")
        return ''


def _contract_decided_at_launch(model_value) -> bool:
    """Un « auto » borné à une tâche dont un candidat déclare un CONTRAT de prompt : le modèle —
    donc la forme attendue de l'enrichi — n'est connu qu'au tirage. Enrichir à l'ingestion sans
    contrat produirait la forme d'un AUTRE modèle (2026-10-04 : 32 mots de MusicGen pour YuE2)."""
    from wama.common.utils.model_keys import auto_task
    task = auto_task(model_value)
    if not task:
        return False
    try:
        from wama.model_manager.models import AIModel
        return (AIModel.objects.filter(capabilities__task=task)
                .exclude(prompt_contract__isnull=True).exclude(prompt_contract='').exists())
    except Exception:
        return False


def _domain_for(instance, tgt):
    """Domaine média du target (`domain` statique, sinon `domain_field` lu sur l'instance)."""
    if tgt.get('domain'):
        return tgt['domain']
    if tgt.get('domain_field') and instance is not None:
        return getattr(instance, tgt['domain_field'], None)
    return None


def _when_ok(instance, tgt):
    """Clause `when` déclarée : un champ booléen de l'instance, ou une condition `show_if`
    (MÊME grammaire que le schéma, évaluée par la MÊME fonction)."""
    cond = tgt.get('when')
    if not cond:
        return True
    if instance is None:
        return False
    if isinstance(cond, dict):
        from wama.common.utils.param_schema import _show_if_met
        name = cond.get('field')
        return _show_if_met(cond, {name: getattr(instance, name, None)})
    return bool(getattr(instance, cond, False))


# ── Persistance du prompt traité (traçabilité + retour arrière) ────────────────────────────
# Convention métadonnée-driven, opt-in par modèle : une app qui déclare un champ-prompt et
# ajoute `<field>_processed` (+ `prompt_trace`) hérite de la mécanique ; un modèle non migré
# n'est jamais touché (comportement d'avant strictement conservé).
PROCESSED_SUFFIX = '_processed'
TRACE_FIELD = 'prompt_trace'


def apply_prompt_state(instance, field, value, state):
    """
    Écrit une édition de prompt DANS LE BON CHAMP, selon l'état à deux faces de l'UI.

    Contrat unique pour toutes les apps (avant : réimplémenté dans chaque vue de sauvegarde) —
    cf. [[wama-prompt-enrich]] et WAMA_LLM.md :
    - `state == 'processed'` : l'utilisateur édite l'ENRICHI → n'écrase surtout pas son original ;
    - sinon : il a repris ou modifié SON prompt → l'enrichi devient périmé et est **vidé**.

    C'est le piège des deux champs éditables : ici l'invalidation est explicite au lieu d'être
    silencieuse. Retourne la liste des attributs modifiés (pour `update_fields`).
    """
    pfield = f"{field}{PROCESSED_SUFFIX}"
    if state == 'processed' and hasattr(instance, pfield):
        setattr(instance, pfield, value)
        return [pfield]
    setattr(instance, field, value)
    touched = [field]
    if hasattr(instance, pfield) and getattr(instance, pfield, ''):
        setattr(instance, pfield, '')
        touched.append(pfield)
    return touched


def detected_keywords(text, user=None, domain=None):
    """
    Mots-clés de la palette PRÉSENTS VERBATIM dans un prompt.

    Les chips ([[wama-prompt-chips]]) insèrent du TEXTE dans le champ : à l'ingestion, on n'a donc
    aucune liste de ce qui a été cliqué. On la RETROUVE en confrontant le prompt à la palette de
    l'utilisateur (+ tronc commun `user=None`). Dérivé plutôt que transmis : aucun handler de
    création à patcher (imager en a sept), et un mot-clé tapé à la main est protégé pareil.

    Sert de glossaire d'enrichissement → ces termes sont préservés verbatim.
    """
    try:
        from django.db.models import Q
        from wama.media_library.models import PromptKeyword

        low = (text or '').lower()
        if not low:
            return []
        qs = PromptKeyword.objects.filter(Q(user=user) | Q(user__isnull=True))
        if domain:
            qs = qs.filter(Q(domain=domain) | Q(domain=''))
        return [k.text for k in qs.only('text') if k.text and k.text.lower() in low]
    except Exception:
        return []


def effective_prompt(instance, field):
    """
    Valeur à ENVOYER au modèle pour ce champ-prompt.

    `<field>_processed` (enrichi/traité, écrit à l'ingestion) prime sur `<field>` — qui reste
    CE QUE L'UTILISATEUR A TAPÉ et n'est jamais écrasé, seule façon de pouvoir y revenir.
    Modèle sans `_processed` → retourne `<field>` : comportement inchangé.
    """
    if instance is None:
        return None
    processed = getattr(instance, f"{field}{PROCESSED_SUFFIX}", None)
    if processed and str(processed).strip():
        return processed
    return getattr(instance, field, None)


def enrich_instance_prompts(app, instance, user=None, glossary=None, source='ingest'):
    """
    Enrichit À L'INGESTION tous les champs-prompt que l'app DÉCLARE `enrich=True`.

    UN seul point d'entrée pour toutes les apps (la liste des champs vient de PROMPT_TARGETS) :
    pas de patch par app, pas de patch par handler de création. Écrit `<field>_processed` et une
    entrée dans `prompt_trace`, **sans jamais toucher `<field>`**.

    Pourquoi à l'ingestion et pas dans la tâche : (1) l'utilisateur VOIT et peut éditer/annuler
    ce qui partira, (2) la passe LLM ne recouvre plus le chargement du modèle de génération
    (~6,6 Go de LLM + le modèle de diffusion en même temps). La traduction, elle, reste dans la
    tâche : elle dépend du modèle cible, que l'utilisateur peut encore changer après l'ingestion.

    No-op si : kill switch/préférence OFF, champ vide, clause `when` fausse, `<field>_processed`
    déjà rempli (duplication de card, relance), ou modèle non migré. Fail-safe : toute erreur
    laisse l'instance intacte.

    Retourne la liste des champs effectivement enrichis.
    """
    from .prompt_enrichment import KEEP_ALIVE_INGEST, enrichment_enabled

    if instance is None or not enrichment_enabled(user):
        return []

    lang = getattr(getattr(user, 'profile', None), 'preferred_language', None) or 'en'
    trace = dict(getattr(instance, TRACE_FIELD, None) or {})
    done, updates = [], []

    for tgt in prompt_targets(app):
        field = tgt.get('field')
        pfield = f"{field}{PROCESSED_SUFFIX}"
        if not field or tgt.get('kind') != 'generative' or not tgt.get('enrich'):
            continue
        if not hasattr(instance, pfield):
            continue                                    # modèle non migré → on ne force rien
        if getattr(instance, pfield, None):
            continue                                    # déjà traité (duplication, relance)
        if not _when_ok(instance, tgt):
            continue
        value = getattr(instance, field, None)
        if not value or not str(value).strip():
            continue

        # Le CONTRAT du modèle visé (2026-10-04) : l'ingestion enrichissait sans lui, donc à la
        # forme du skill d'app — celle de MusicGen pour une card destinée à YuE2. Sous un « auto »
        # dont un candidat porte un contrat, le modèle n'est connu qu'au tirage : on laisse la
        # pipeline du LANCEMENT enrichir, avec le contrat du modèle tiré.
        mfield = tgt.get('model_field')
        if mfield and _contract_decided_at_launch(getattr(instance, mfield, None)):
            continue
        _caps, _mtype, contract = _resolve_model(app, instance, tgt)

        domain = _domain_for(instance, tgt)
        # Glossaire non fourni → on le DÉRIVE du prompt (cf. detected_keywords).
        gloss = list(glossary) if glossary else detected_keywords(value, user, domain)
        try:
            enriched = enrich_prompt_value(app, field, value, domain=domain,
                                           language=lang, glossary=gloss or None,
                                           keep_alive=KEEP_ALIVE_INGEST, contract=contract)
        except Exception as e:                           # LLM injoignable, timeout, réponse vide
            logger.debug(f"[app_metadata] enrichissement {app}.{field} ignoré ({e})")
            continue
        if not enriched or enriched == value:
            continue

        setattr(instance, pfield, enriched)
        updates.append(pfield)
        trace[field] = {'enriched': True, 'source': source, 'language': lang,
                        'keywords': gloss}
        # Mots-clés conservés comme DONNÉE : ils survivent à un retour au prompt d'origine et
        # resservent de glossaire à un ré-enrichissement.
        if gloss and hasattr(instance, 'prompt_keywords') and not instance.prompt_keywords:
            instance.prompt_keywords = gloss
            updates.append('prompt_keywords')
        done.append(field)

    if updates:
        if hasattr(instance, TRACE_FIELD):
            setattr(instance, TRACE_FIELD, trace)
            updates.append(TRACE_FIELD)
        instance.save(update_fields=updates)
    return done


def _resolve_reference_files(instance, tgt):
    """Chemin(s) du/des fichier(s) de référence déclaré(s) par `reference_field`, ou None.

    `reference_field` peut viser un FileField/ImageField (→ .path) ou une liste de fichiers.
    """
    rfield = tgt.get('reference_field')
    if not rfield or instance is None:
        return None
    val = getattr(instance, rfield, None)
    if not val:
        return None
    items = val if isinstance(val, (list, tuple)) else [val]
    paths = []
    for it in items:
        # FileField/ImageField → .path (si un fichier est réellement associé), sinon str
        p = getattr(it, 'path', None)
        try:
            if p is None and it:
                p = str(it)
        except Exception:
            p = None
        if p:
            paths.append(p)
    return paths or None
