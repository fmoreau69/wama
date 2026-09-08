# Code tiers des moteurs vendorisés

Ce dossier reçoit les **dépôts tiers clonés** que certains backends exécutent en sous-processus —
des MOTEURS livrés comme du code source, pas comme un paquet PyPI. Il vit à côté des backends
(`wama/common/backends/`) parce que c'est là que WAMA les consomme, mais **rien ici n'est du
code WAMA** et **rien ici n'est importé** : le backend pousse le dossier sur le `PYTHONPATH`
d'un sous-processus, c'est tout.

| moteur | dépôt | commit épinglé au 2026-09-07 | backend |
|---|---|---|---|
| `musetalk` | `TMElyralab/MuseTalk` | `0a89dec` (2025-09-26) | `musetalk_backend.py` |
| `codeformer` | `sczhou/CodeFormer` | `b33cc7d` (2025-11-18) | `codeformer_backend.py` |

## Règles

- **Les sous-dossiers sont gitignorés** (`wama/common/backends/vendor/*/`) : le dépôt ne
  grossit pas. Seul ce README est versionné.
- **Reconstruit à l'installation** : `bash wama/avatarizer/setup_avatarizer.sh` (ou
  `tools/install_wama.sh --with-avatarizer`) clone ici. Le nom du sous-dossier est le nom du
  MOTEUR (`BaseModelBackend.ENGINE`), et la racine est DÉCLARÉE une fois dans `settings.py`
  (`BACKEND_VENDOR_DIR`) — jamais recalculée depuis un paquet Python.
- **Pas de `__init__.py` ici** : la découverte de tests et le balayage du vivier (`glob('*.py')`,
  non récursif) n'y entrent pas.
- ⚠ **MuseTalk porte des correctifs LOCAUX** (7 fichiers, non captés par le dépôt amont) :
  ils sont exportés dans `patches/musetalk_local_2026-09-07.diff`. Un clone frais ne les a
  PAS — les réappliquer est un geste d'installation à outiller (`patches/apply_patches.py`).
- Les POIDS ne vivent pas ici : `AI-models/models/lipsync/{musetalk,codeformer}/` (CodeFormer y
  pointe par symlinks absolus depuis `codeformer/weights/`).
