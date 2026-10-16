#!/usr/bin/env python3
"""
Rôle « app » — le BROUILLON du manifeste `app` d'une app NOUVELLE : le maillon de la route
« dépôt → app » qu'aucun rôle ne produisait (`WAMA_APP_GENERATION_ROUTE.md §10.5`, « le trou
unique »).

Décision de Fabien, 2026-10-15 : la règle du 30/09 (« seul le manifeste `app` de départ peut être
écrit à la main ») est levée comme le reste de la levée progressive — un modèle de WAMA RÉDIGE
le brouillon, un humain le juge, l'app naît dans le BAC À SABLE (`app_sandbox create
--from-manifest`, dev seulement) où chaque générateur la rend ou refuse en disant pourquoi. La
promotion hors du bac à sable reste un geste humain.

Ce que le rôle ne fait pas : inventer la capacité. Elle vient des briques déjà produites
(`--requires` : manifestes `library` / `model` des rôles librarian, scout, model), et la
décision « app nouvelle plutôt qu'existante » est celle de l'`integrator`.

Pilote BORNÉ, comme les autres rôles :
  1. contexte MÉCANIQUE : le seul brouillon né de zéro (`manifests/app_drafts/writer.json`) pour la
     FORME, l'app existante la plus proche (`--like`) pour la NATURE, les manifestes `requires`
     résolus, le catalogue d'apps et les vocabulaires FERMÉS ; une clé déjà prise est REFUSÉE
     avant tout appel ;
  2. un seul appel LLM (modèle tiré pour le compte par la surface, garde GPU commune) ;
  3. contrôles MÉCANIQUES : l'enveloppe est IMPOSÉE (clé, kind, source, visibilité, `requires`
     donnés — jamais ceux que le LLM a écrits), puis `ingest.validate` (enveloppe, corps, références) ;
  4. écrit le rapport ET le manifeste seul (`*.manifest.json`, la forme que lit
     `app_sandbox create --from-manifest`) dans `outputs/` — PENDING_HUMAN_VALIDATION.

Usage (racine du repo, venv_linux) :
    python wama-dev-ai/run_app_manifest.py --key translator \
        --need "traduire des textes et des documents" --like reader \
        --requires library:libretranslate --dry-run
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import os  # noqa: E402
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django  # noqa: E402
django.setup()

from role_utils import (  # noqa: E402
    REPO_ROOT, add_llm_arguments, call_llm, consigne_role, extract_json, local_llm_guard,
    resolve_model, write_output)

from wama.common.manifests.codegen.pipeline_decl import DRAFTS_DIR  # noqa: E402

PROMPT = consigne_role('app')

#: Le seul manifeste `app` né de zéro : il montre la FORME (enveloppe, facettes) à reproduire.
SHAPE_EXAMPLE = REPO_ROOT / DRAFTS_DIR / 'writer.json'
#: Facettes d'une app existante qui ne s'écrivent pas dans un brouillon : `data` est introspectée
#: APRÈS la génération, `tool_api` dérive des tâches — les montrer apprendrait à les recopier.
NOT_AUTHORED_FACETS = ('data', 'tool_api')
#: Facettes propres à l'app de l'EXEMPLE, retirées avant de le montrer : la surface d'édition du
#: Writer nomme SES fichiers (`draft_file`) — recopiée telle quelle dans le premier brouillon du
#: Translator (2026-10-16), la naissance l'a refusée. Une page d'édition se déclare une fois que
#: les process de l'app existent, pas dans un premier brouillon.
EXAMPLE_ONLY_FACETS = ('surfaces',)
#: Plafond d'un manifeste montré en contexte (caractères). 24 000 au premier essai (2026-10-15) :
#: contexte de ~30 000 caractères + un manifeste de ~11 000 en réponse + la réflexion de qwen3.8
#: remplissaient la fenêtre d'Ollama (16 384 jetons, `call_ollama`) et COUPAIENT la réponse au
#: milieu d'une phrase. L'élargir coûterait des Go de VRAM sur un 27B : on montre moins.
MAX_SHOWN_CHARS = 12000
#: Fenêtre d'Ollama pour ce rôle — celle de `run_codegen`, l'autre rôle qui ÉCRIT un long objet.
#: Vécu le 2026-10-16 (Translator, deux essais) : à 16 384, la réponse s'arrêtait APRÈS `params`,
#: sans `processing` ni `decisions`/`concerns` — un manifeste qu'aucun gabarit ne peut rendre.
NUM_CTX = 32768
#: Ce qui, d'une app existante, se DÉRIVE et n'apprend rien de sa nature : sa liste de routes.
DERIVED_PROCESSING_KEYS = ('endpoints', 'extra_routes')


class AppDraftRefused(SystemExit):
    """Refus LISIBLE, avant tout appel au modèle."""


def parse_requires(spec: str) -> list:
    """`library:libretranslate,model:ollama:qwen3.8:latest` → `[{'kind', 'key'}]`."""
    refs = []
    for raw in [s.strip() for s in (spec or '').split(',') if s.strip()]:
        kind, sep, key = raw.partition(':')
        if not sep or not key or kind not in ('library', 'model', 'function', 'dataset'):
            raise AppDraftRefused(f"[app] REFUS : référence {raw!r} — forme attendue "
                                  "<library|model|function|dataset>:<clé>")
        refs.append({'kind': kind, 'key': key})
    return refs


def check_key(key: str) -> None:
    """La clé d'une app NEUVE — la règle de la naissance elle-même (`app_sandbox.new_app_key_error`),
    appliquée AVANT l'appel au modèle : un brouillon que la naissance refuserait ne se rédige pas."""
    from wama.common.management.commands.app_sandbox import new_app_key_error
    error = new_app_key_error(key)
    if error:
        raise AppDraftRefused(f'[app] REFUS : {error}')


def shape_example() -> str:
    """L'exemple de FORME, sans ce qui n'appartient qu'à son app (`EXAMPLE_ONLY_FACETS`)."""
    example = json.loads(SHAPE_EXAMPLE.read_text(encoding='utf-8'))
    body = {k: v for k, v in (example.get('body') or {}).items() if k not in EXAMPLE_ONLY_FACETS}
    return json.dumps({**example, 'body': body}, ensure_ascii=False, indent=1)


def shown(manifest: dict) -> str:
    body = {k: v for k, v in (manifest.get('body') or {}).items() if k not in NOT_AUTHORED_FACETS}
    if isinstance(body.get('processing'), dict):
        body['processing'] = {k: v for k, v in body['processing'].items()
                              if k not in DERIVED_PROCESSING_KEYS}
    return json.dumps({**manifest, 'body': body}, ensure_ascii=False, indent=1)[:MAX_SHOWN_CHARS]


def like_manifest(app_id: str) -> str:
    if not app_id:
        return '(aucune)'
    from wama.common.manifests.builtin.app import extract_app
    manifest = extract_app(app_id)
    if manifest is None:
        raise AppDraftRefused(f"[app] REFUS : --like {app_id!r} n'est pas une app du catalogue")
    return shown(manifest)


def requires_context(refs: list) -> tuple:
    """(texte des manifestes résolus, références pendantes)."""
    from wama.common.manifests.ingest import resolve_requires
    resolved, dangling = resolve_requires({'requires': refs})
    text = '\n\n'.join(json.dumps(m, ensure_ascii=False, indent=1)[:8000] for m in resolved)
    return text or '(aucune)', dangling


def catalog_context() -> str:
    from wama.common.app_registry import APP_CATALOG
    return '\n'.join(f"- {app_id} : {(spec or {}).get('description', '')}"
                     for app_id, spec in sorted(APP_CATALOG.items())
                     if not (spec or {}).get('sandbox'))


def vocabularies() -> str:
    from wama.common.app_registry import known_port_types
    from wama.common.manifests.builtin.app import APP_INPUT_GROUPS
    from wama.common.models import job_status_values
    return (f"port types : {sorted(known_port_types())}\n"
            f"statuses (processing.statuses, this exact list) : {list(job_status_values())}\n"
            f"input groups : {' | '.join(APP_INPUT_GROUPS)}")


def enforce_envelope(manifest: dict, key: str, refs: list, concerns: list) -> dict:
    """L'enveloppe est IMPOSÉE — jamais celle que le LLM a écrite (même règle que
    `role_utils.enforce_identity` pour les modèles)."""
    if manifest.get('key') not in (None, key):
        concerns.append(f"clé écrite par le modèle {manifest.get('key')!r} remplacée par {key!r}")
    llm_refs = {(r.get('kind'), r.get('key')) for r in (manifest.get('requires') or [])
                if isinstance(r, dict)}
    dropped = sorted(llm_refs - {(r['kind'], r['key']) for r in refs})
    if dropped:
        concerns.append(f"références ajoutées par le modèle, écartées : {dropped}")
    body = manifest.get('body') if isinstance(manifest.get('body'), dict) else {}
    # Une facette écrite À LA RACINE est une facette du corps posée hors de lui — vécu le
    # 2026-10-16 (Translator, trois essais) : le modèle refermait `body` après `params` et posait
    # `processing`, `models`, `inspector`, `access`, `studio` à côté de l'enveloppe. Les facettes
    # sont un vocabulaire FERMÉ (`APP_FACETS`) : la remettre à sa place ne décide rien.
    from wama.common.manifests.builtin.app import APP_FACETS
    manifest = dict(manifest)
    for facet in APP_FACETS:
        if facet in manifest:
            value = manifest.pop(facet)
            if facet in body:
                concerns.append(f"facette `{facet}` écrite deux fois (corps et racine) : celle "
                                "du corps est gardée")
            else:
                body[facet] = value
                concerns.append(f"facette `{facet}` écrite hors du corps, remise dans `body`")
    for facet in NOT_AUTHORED_FACETS + EXAMPLE_ONLY_FACETS:
        if body.pop(facet, None) is not None:
            concerns.append(f"facette `{facet}` retirée (elle ne s'écrit pas dans un premier "
                            "brouillon : une page d'édition se déclare une fois les process faits)")
    identity = body.setdefault('identity', {})
    identity['url_name'] = f'{key}:index'
    # La CATÉGORIE se DÉRIVE des types (`app_registry.derive_category`, par la projection que lit
    # le catalogue à la naissance) — vécu le 2026-10-16 : le modèle avait choisi `transform` pour
    # le Translator, que le contrôle du catalogue refusait (« prend du texte = Créer »).
    from wama.common.app_registry import derive_category
    from wama.common.manifests.builtin.app import _ports_target
    category = derive_category(_ports_target({'body': body}))
    if identity.get('category') not in (None, category):
        concerns.append(f"catégorie `{identity.get('category')}` remplacée par `{category}`, "
                        "dérivée des types d'entrée et de sortie")
    identity['category'] = category
    return {**manifest, 'key': key, 'manifest_kind': 'app', 'schema_version': '1.0',
            'visibility': 'private', 'requires': refs,
            'source': {'type': 'authored',
                       'ref': 'wama-dev-ai rôle app — PENDING_HUMAN_VALIDATION'},
            'world': manifest.get('world') or 'media',
            'projects': manifest.get('projects') or [], 'body': body}


_DANGLING = re.compile(r'^requires: référence pendante (?P<ref>.+?) \(')


def split_checks(manifest: dict) -> tuple:
    """`(erreurs, briques en attente)` de `ingest.validate`.

    Une référence PENDANTE n'est pas une faute du brouillon : juste après le rôle `librarian`, la
    librairie n'est ni validée ni installée — elle ne se résoudra qu'après la route WAMA (geste
    « Valider » du model manager, puis `install_library`). Le brouillon reste jugeable, et l'app
    peut naître au bac à sable ; seule sa glu attendra la brique. Le dire, ne pas le compter."""
    from wama.common.manifests.ingest import validate
    errors, pending = [], []
    for error in validate(manifest):
        m = _DANGLING.match(error)
        (pending.append(m['ref']) if m else errors.append(error))
    # Le JUGE d'un brouillon est la génération (`app_sandbox.first_pass_refusals`, les gabarits
    # mêmes de la naissance, à blanc) : `validate` ne regarde que la forme — et n'EXIGE aucune
    # facette. Vécu le 2026-10-16 : un brouillon sans `ports` ni `processing` n'a rapporté qu'une
    # faute de capacité, la génération n'ayant pas été jouée. Elle l'est toujours désormais : le
    # rapport dit TOUT ce que la naissance refuserait, pas la première faute de forme.
    from wama.common.management.commands.app_sandbox import first_pass_refusals
    try:
        errors += first_pass_refusals(manifest)
    except Exception as exc:  # un brouillon malformé peut faire tomber un gabarit : le dire
        errors.append(f'génération à blanc impossible : {type(exc).__name__}: {exc}')
    return errors, pending


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--key', required=True, help="Clé de l'app neuve (underscore_case)")
    ap.add_argument('--need', required=True, help="Ce que l'app doit faire, en clair")
    ap.add_argument('--like', default='', help="App existante la plus proche (sa NATURE)")
    ap.add_argument('--requires', default='',
                    help='Briques produites : library:<clé>,model:<clé>… (virgules)')
    add_llm_arguments(ap, role='dev')
    ap.add_argument('--dry-run', action='store_true', help='Contexte seulement, AUCUN appel LLM')
    args = ap.parse_args()

    check_key(args.key)
    refs = parse_requires(args.requires)
    req_text, dangling = requires_context(refs)
    concerns: list = []
    user_msg = (f"NEED:\n{args.need}\n\nKEY: {args.key}\n\n"
                f"EXAMPLE (writer.json — the SHAPE only):\n{shape_example()}\n\n"
                f"LIKE ({args.like or 'none'}):\n{like_manifest(args.like)}\n\n"
                f"REQUIRES:\n{req_text}\n\nCATALOG:\n{catalog_context()}\n\n"
                f"VOCABULARIES:\n{vocabularies()}\n")

    if args.dry_run:
        print(f'[app] DRY-RUN — {len(user_msg)} caractères de contexte')
        for d in dangling:
            print(f'[app] ⏳ brique pas encore validée ni installée : {d}')
        print(user_msg[:3000])
        return

    model = resolve_model(args.provider, 'dev', args.model)
    print(f'[app] {args.provider} / {model} | clé {args.key} | like {args.like or "—"}')
    keep_alive = local_llm_guard(args.provider, model, force=args.force, wait_max=args.wait_max,
                                 log=lambda m: print(f'[app] {m}'))
    raw = call_llm(args.provider, model, PROMPT, user_msg, num_ctx=NUM_CTX, keep_alive=keep_alive,
                   timeout=900)
    try:
        answer = extract_json(raw)
        manifest = answer['manifest'] if isinstance(answer.get('manifest'), dict) else answer
    except (ValueError, KeyError) as e:
        verdict, reason = ('truncated', "réponse TRONQUÉE (fenêtre du modèle pleine) — relancer "
                                        "avec moins de contexte (--like plus petit)") \
            if 'non équilibré' in str(e) else ('unreadable', f'réponse illisible : {e}')
        out = write_output('app', args.key, {'need': args.need, 'verdict': verdict,
                                             'mechanical_checks': [reason], 'raw': raw[:20000]})
        print(f'[app] → {out.relative_to(REPO_ROOT)}\n[app] verdict : {verdict}')
        return
    concerns += list(answer.get('concerns') or [])
    manifest = enforce_envelope(manifest, args.key, refs, concerns)
    checks, pending = split_checks(manifest)

    out = write_output('app', args.key, {
        'need': args.need, 'like': args.like, 'requires': refs,
        'provider': args.provider, 'model': model,
        'mechanical_checks': checks, 'verdict': 'clean' if not checks else 'invalid',
        'pending_bricks': pending,
        'decisions': answer.get('decisions') or [], 'concerns': concerns})
    manifest_file = out.with_name(out.stem + '.manifest.json')
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    report = json.loads(out.read_text(encoding='utf-8'))
    report['manifest_file'] = manifest_file.relative_to(REPO_ROOT).as_posix()
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'[app] → {out.relative_to(REPO_ROOT)}')
    print(f'[app] → {manifest_file.relative_to(REPO_ROOT)}')
    print(f"[app] verdict : {report['verdict']}")
    for c in checks:
        print(f'[app] ✗ {c}')
    for p in pending:
        print(f'[app] ⏳ brique pas encore validée ni installée : {p}')
    for c in concerns:
        print(f'[app] ⚠ {c}')


if __name__ == '__main__':
    main()
