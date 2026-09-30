# Code tiers des moteurs vendorisés

Ce dossier reçoit les **dépôts tiers clonés** que certains backends exécutent en sous-processus —
des MOTEURS livrés comme du code source, pas comme un paquet PyPI. Il vit à côté des backends
(`wama/common/backends/`) parce que c'est là que WAMA les consomme, mais **rien ici n'est du
code WAMA** et **rien ici n'est importé** : le backend pousse le dossier sur le `PYTHONPATH`
d'un sous-processus, c'est tout.

**La déclaration de chaque moteur vit dans son manifeste** `manifests/libraries/<moteur>.json`
(`body.install.vendor` : dépôt, commit, correctif) — la table ci-dessous n'en est qu'un repère.

| moteur | dépôt | commit épinglé | correctif | backend |
|---|---|---|---|---|
| `musetalk` | `TMElyralab/MuseTalk` | `0a89dec` (2025-09-26) | `patches/musetalk_local_2026-09-07.diff` | `musetalk_backend.py` |
| `codeformer` | `sczhou/CodeFormer` | `b33cc7d` (2025-11-18) | — | `codeformer_backend.py` |
| `triposr` | `VAST-AI-Research/TripoSR` | `107cefd` (2026-06-04) | `patches/triposr_pymcubes_lazy_rembg.diff` | `image_to_3d_backend.py` |

## Règles

- **Les sous-dossiers sont gitignorés** (`wama/common/backends/vendor/*/`) : le dépôt ne
  grossit pas. Seul ce README est versionné.
- **Installés par la route `library`, voie vendor** (ROADMAP D-a, 2026-09-30) :
  `python manage.py install_library <moteur>` (plan) puis `--allow --apply` (décision humaine) —
  clone AU COMMIT, correctif appliqué, état constaté. Les scripts
  `wama/avatarizer/setup_avatarizer.sh` et `tools/setup_triposr.sh` ne font plus qu'appeler
  cette route. Le nom du sous-dossier est le nom du MOTEUR (`BaseModelBackend.ENGINE`, qui
  déclare `VENDORED = True`), et la racine est DÉCLARÉE une fois dans `settings.py`
  (`BACKEND_VENDOR_DIR`) — jamais recalculée depuis un paquet Python.
- **Pas de `__init__.py` ici** : la découverte de tests et le balayage du vivier (`glob('*.py')`,
  non récursif) n'y entrent pas.
- 🔴 **Ne jamais corriger un clone à la main sans exporter le correctif** : la route REFUSE
  d'installer par-dessus une modification locale que le manifeste n'explique pas, et la nomme.
  Le geste : `git -C <clone> diff > patches/<moteur>_<objet>.diff`, puis le déclarer dans
  `install.vendor.patch`. C'est ce qui était arrivé à MuseTalk (7 fichiers corrigés le 07/09,
  réappliqués par rien jusqu'au 30/09).
- Les POIDS ne vivent pas ici : `AI-models/models/lipsync/{musetalk,codeformer}/` (CodeFormer y
  pointe par symlinks absolus depuis `codeformer/weights/`).
