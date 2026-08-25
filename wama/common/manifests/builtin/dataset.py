"""
Kind `dataset` — généralisation d'un manifeste de toolbox tierce (référence quasi-idéale).

À la différence de `app`/`model` (EXTRAITS du code existant), un `dataset` est AUTORÉ : le manifeste EST
l'origine (wama-dev-ai explore un dossier projet → infère un brouillon → l'humain valide). Donc PAS de
`extract` : ce kind est validate + store.

⚠ Et PAS de `write_back` non plus — mais pas pour la même raison que les autres kinds, d'où cette
mise au point (Fabien, 2026-08-05 ; la formulation précédente parlait de « projection » et de
« instancier le dataset », ce qui induisait en erreur).

Un dataset ne s'INSTANCIE pas : c'est un **accès**. Les données sont un corpus d'expérimentation
qui vit dans une arborescence sur un serveur, et `source.ref` en donne le chemin. Il n'y a aucune
table de registre où écrire — `dataset` est d'ailleurs le SEUL kind sans contrepartie
(app→apps, model→AIModel, library→Library, project→Project, dataset→∅). Le manifeste EST la
représentation du dataset ; l'exploitation se fait depuis **wama-data**.

Le chantier ultérieur n'est donc pas une projection mais un **reader source-agnostique** : le code
qui va lire `source.ref` et rendre les `signals`/`records` déclarés ici. Ne pas le confondre avec
`write_back`, qui pour les autres kinds signifie « écrire dans le registre ».

Généralisation du modèle tiers → WAMA (cf. mémoire project_manifests_projects) :
  - `das`/`channel`/`signal` typés + unités        → `signals[]` typés sur `data_types` (source-agnostique)
  - `reference_table` (enums : NV_AnnotationTag…)   → `reference_tables{}`
  - `record`/`timeseries` (GNSS→geo_track, …)       → `records[]` (groupements de signaux)
  - couche propriété/projet/visibilité (absente du modèle tiers) → portée par l'ENVELOPPE commune (world/visibility/scope)
"""

from __future__ import annotations

from ..kinds import ManifestKind, register_kind

# Sources brutes reconnues (le reader WAMA sera source-AGNOSTIQUE — pas que rtMapsOutputName).
DATASET_SOURCES = ('rtmaps', 'lsl', 'rosbag', 'csv', 'parquet', 'db', 'docs', 'other')

#: Rôles d'un axe du PLAN D'EXPÉRIENCE (`WAMA_DATA_WORLD §13.3`). Vocabulaire **FERMÉ** ; les clés
#: et libellés, eux, sont **ouverts** — c'est ce qui rend la taxonomie universelle (une passation de
#: conduite, une série d'essais mécaniques et une campagne de comptage se décrivent avec les mêmes
#: trois rôles, seuls les libellés changent).
#:
#: Le critère vient de SDMX (ISO 17369, §13.3ter) et il ne parle **ni de mesure ni d'unité** :
#:   • `factor`      — IDENTIFIE une observation (retire-le : deux observations deviennent
#:                     indiscernables). C'est la *dimension* SDMX ;
#:   • `attribute`   — QUALIFIE une observation sans l'identifier. C'est l'*attribute* SDMX ;
#:   • `observation` — le GRAIN : le facteur le plus fin, celui qui porte l'indépendance
#:                     statistique. DDI l'appelle « unité d'analyse ».
#:
#: ⚠ `block` et `covariate` ont été délibérément ÉCARTÉS : ils nomment un rôle **dans un modèle
#: donné** (« sans intérêt », « inclus pour contrôler »), pas un fait de corpus. Le manifeste
#: déclare ce que le corpus EST, jamais ce qu'une analyse en fera.
AXIS_ROLES = ('observation', 'factor', 'attribute')

#: Clés d'axe réservées aux facteurs (y compris ceux de rôle `observation`, qui SONT des facteurs).
_FACTOR_ONLY = ('contains', 'crosses', 'levels', 'manipulated', 'counterbalanced')


def _valid_data_types() -> set:
    from wama.common.catalog.data_types import DataType
    return {v for k, v in vars(DataType).items() if k.isupper() and isinstance(v, str)}


def _validate_axes(axes, reference_tables: dict, errs: list) -> None:
    """Valide le PLAN D'EXPÉRIENCE (`WAMA_DATA_WORLD §13`). Écrit dans `errs`, ne rend rien.

    Ce qui est vérifié ici est **structurel** et mécanique — jamais un jugement d'analyse :
    l'existence des renvois, l'exclusivité des clés par rôle, et l'ABSENCE DE CYCLE dans la
    nidification (`contains` est récursif — une situation de suivi peut porter des
    sous-situations —, mais une boucle rendrait le plan insensé).
    """
    if not isinstance(axes, list):
        errs.append("axes doit être une liste de {key, role, ...}")
        return

    cles: dict = {}
    for i, a in enumerate(axes):
        if not isinstance(a, dict):
            errs.append(f"axes[{i}] doit être un dict"); continue
        k = a.get('key')
        if not k or not isinstance(k, str):
            errs.append(f"axes[{i}] : 'key' manquant ou non-str"); continue
        if k in cles:
            errs.append(f"axes : key '{k}' dupliquée")
        cles[k] = a

    grains = [k for k, a in cles.items() if a.get('role') == 'observation']

    for k, a in cles.items():
        role = a.get('role')
        if role not in AXIS_ROLES:
            errs.append(f"axes['{k}'] : role '{role}' invalide (attendu: {', '.join(AXIS_ROLES)})")
            continue

        # ── exclusivité des clés par rôle ────────────────────────────────────
        # `observation` EST un facteur (le plus fin) : il garde donc les clés de facteur.
        if role == 'attribute':
            for interdit in _FACTOR_ONLY:
                if interdit in a:
                    errs.append(f"axes['{k}'] : '{interdit}' n'a de sens que sur un facteur, "
                                f"pas sur un attribute")
        elif 'attached_to' in a:
            errs.append(f"axes['{k}'] : 'attached_to' n'a de sens que sur un attribute "
                        f"(un facteur se relie par contains/crosses)")

        # ── renvois : tout ce qui cite un axe doit citer un axe QUI EXISTE ───
        for champ in ('contains', 'crosses', 'attached_to'):
            cible = a.get(champ)
            if cible is None:
                continue
            if not isinstance(cible, str):
                errs.append(f"axes['{k}'].{champ} doit être la clé d'un autre axe")
            elif cible == k:
                errs.append(f"axes['{k}'].{champ} se réfère à lui-même")
            elif cible not in cles:
                errs.append(f"axes['{k}'].{champ} : axe inconnu '{cible}'")

        if a.get('contains') and a.get('contains') == a.get('crosses'):
            errs.append(f"axes['{k}'] : contains et crosses désignent le même axe "
                        f"('{a.get('contains')}') — niché OU croisé, jamais les deux")

        # ── derived_from : un autre axe, ou un manifeste (typiquement un `model`) ──
        # Le second cas est le PROFIL APPRIS : un facteur dont les niveaux ne viennent pas du
        # protocole mais d'un modèle (`WAMA_APPRENTISSAGE.md`). La provenance reste déclarée.
        df = a.get('derived_from')
        if df is not None:
            if isinstance(df, str):
                if df not in cles:
                    errs.append(f"axes['{k}'].derived_from : axe inconnu '{df}'")
            elif isinstance(df, dict):
                if not (df.get('kind') and df.get('key')):
                    errs.append(f"axes['{k}'].derived_from : référence de manifeste malformée "
                                f"(attendu {{kind, key}})")
            else:
                errs.append(f"axes['{k}'].derived_from doit être une clé d'axe ou {{kind, key}}")

        # ── niveaux : 'ref:<table>' renvoie au catalogue déjà existant ───────
        lv = a.get('levels')
        if isinstance(lv, str):
            if not lv.startswith('ref:'):
                errs.append(f"axes['{k}'].levels : chaîne attendue sous la forme 'ref:<table>'")
            elif lv[4:] not in (reference_tables or {}):
                errs.append(f"axes['{k}'].levels : reference_tables['{lv[4:]}'] absente")
        elif lv is not None and not isinstance(lv, list):
            errs.append(f"axes['{k}'].levels doit être une liste ou 'ref:<table>'")

        for drapeau in ('manipulated', 'counterbalanced'):
            if drapeau in a and not isinstance(a[drapeau], bool):
                errs.append(f"axes['{k}'].{drapeau} doit être un booléen")

    # ── PLUSIEURS UNITÉS D'OBSERVATION : autorisé, mais alors plus rien d'implicite ──
    # Un corpus peut porter deux grains non emboîtés (dyade conducteur+passager, plusieurs
    # sujets codés dans une même observation). Tant qu'il n'y en a qu'un, le rattachement peut
    # rester sous-entendu ; dès qu'il y en a deux, « à quoi se rapporte cet axe ? » n'a plus de
    # réponse par défaut — et un défaut deviné est le genre d'erreur qu'on découvre à l'analyse.
    if len(grains) > 1:
        for k, a in cles.items():
            if a.get('role') == 'observation':
                continue
            if not (a.get('contains') or a.get('crosses') or a.get('attached_to')):
                errs.append(f"axes['{k}'] : {len(grains)} unités d'observation déclarées "
                            f"({', '.join(sorted(grains))}) — le rattachement "
                            f"(contains/crosses/attached_to) devient obligatoire")
    elif not grains and cles:
        errs.append("axes : aucune unité d'observation (role='observation') — le grain du corpus "
                    "n'est pas déclaré")

    # ── cycles de nidification ───────────────────────────────────────────────
    for depart in cles:
        vu, courant = set(), depart
        while courant is not None:
            if courant in vu:
                errs.append(f"axes : cycle de nidification via contains, passant par '{depart}'")
                break
            vu.add(courant)
            suivant = cles.get(courant, {}).get('contains')
            courant = suivant if isinstance(suivant, str) and suivant in cles else None


def validate_dataset_body(body: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(body, dict):
        return ["body 'dataset' doit être un dict"]

    # source ------------------------------------------------------------------
    src = body.get('source')
    if not isinstance(src, dict):
        errs.append("source manquant ou non-dict {type, ref}")
    else:
        if src.get('type') and src['type'] not in DATASET_SOURCES:
            errs.append(f"source.type '{src['type']}' inconnu (attendu: {', '.join(DATASET_SOURCES)})")
        if not src.get('ref'):
            errs.append("source.ref manquant (chemin/dossier/URI du jeu brut)")

    # signals -----------------------------------------------------------------
    # ⚠ `signals` N'EST PLUS OBLIGATOIRE (2026-08-26, `WAMA_DATA_WORLD §13.10`). Un corpus de
    # QUESTIONNAIRES — panel en ligne, passation papier, tests psychotechniques — n'a **aucun flux
    # temporel** : exiger `signals` non vide refusait une méthodologie entière, et c'était le
    # premier trou d'universalité mesuré du kind. La règle devient « au moins l'un des deux » : un
    # dataset décrit des flux, un plan d'expérience, ou les deux.
    dtypes = _valid_data_types()
    signals = body.get('signals')
    axes = body.get('axes')
    signal_ids: set = set()
    if not signals and not axes:
        errs.append("dataset vide : au moins 'signals' (flux typés) ou 'axes' (plan d'expérience)")
    if signals is not None and not isinstance(signals, list):
        errs.append("signals doit être une liste")
    elif isinstance(signals, list):
        for i, s in enumerate(signals):
            if not isinstance(s, dict):
                errs.append(f"signals[{i}] doit être un dict"); continue
            sid = s.get('id')
            if not sid:
                errs.append(f"signals[{i}] : 'id' manquant")
            else:
                if sid in signal_ids:
                    errs.append(f"signals : id '{sid}' dupliqué")
                signal_ids.add(sid)
            dt = s.get('data_type')
            if not dt:
                errs.append(f"signals[{sid or i}] : 'data_type' manquant")
            elif dt not in dtypes:
                errs.append(f"signals[{sid or i}] : data_type '{dt}' hors taxonomie ({', '.join(sorted(dtypes))})")

    # reference_tables --------------------------------------------------------
    rts = body.get('reference_tables', {})
    if rts and not isinstance(rts, dict):
        errs.append("reference_tables doit être un dict {name: {...}}")
    elif isinstance(rts, dict):
        for name, tbl in rts.items():
            if not isinstance(tbl, dict):
                errs.append(f"reference_tables['{name}'] doit être un dict"); continue
            if 'values' not in tbl and 'mapping' not in tbl:
                errs.append(f"reference_tables['{name}'] exige 'values' (liste) ou 'mapping' (code→label)")

    # records (groupements de signaux) ----------------------------------------
    records = body.get('records', [])
    if records and not isinstance(records, list):
        errs.append("records doit être une liste")
    elif isinstance(records, list):
        for i, r in enumerate(records):
            if not isinstance(r, dict):
                errs.append(f"records[{i}] doit être un dict"); continue
            for ref in (r.get('signals') or []):
                if signal_ids and ref not in signal_ids:
                    errs.append(f"records[{r.get('id', i)}] référence un signal inconnu: '{ref}'")

    # axes — le PLAN D'EXPÉRIENCE (§13) -----------------------------------------
    if axes is not None:
        _validate_axes(axes, rts if isinstance(rts, dict) else {}, errs)
    return errs


register_kind(ManifestKind(
    kind='dataset',
    validate=validate_dataset_body,
    extract=None,      # AUTORÉ (pas de registre code) — le manifeste est l'origine
    description="Jeu de données brut typé (généralisation d'un modèle tiers) : source-agnostique + signals typés sur "
                "data_types + reference_tables (enums) + records + AXES (plan d'expérience : "
                "observation/factor/attribute, contains/crosses, manipulated — WAMA_DATA_WORLD §13). "
                "`signals` et `axes` sont l'un OU l'autre obligatoires, pas les deux : un corpus de "
                "questionnaires n'a aucun flux temporel. Validate+store : un dataset est un "
                "ACCÈS (source.ref = arborescence serveur), pas un objet à instancier — aucun "
                "registre où écrire. Chantier ultérieur = un reader source-agnostique.",
))
