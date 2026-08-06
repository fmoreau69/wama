#!/usr/bin/env python3
"""
Garde-fou ENFORCANT (hook PreToolUse/Bash) : refuse toute commande Bash commençant par `cd`.

Le cwd du tool Bash est déjà le repo → préfixer par `cd /d/WAMA/...` est inutile et déclenche une
validation de permission. La règle est dans CLAUDE.md mais elle est PASSIVE ; ce hook la rend active.

Autorisé : `cd` À L'INTÉRIEUR d'une chaîne `wsl.exe -e bash -lc '... cd ... && ...'` (le cd est alors
dans la chaîne WSL, pas un préfixe de la commande hôte). On ne bloque donc que le `cd` en TÊTE.

Protocole hook : on lit le JSON sur stdin ; pour bloquer, on écrit la raison sur stderr et exit 2.
"""
import sys
import json
import re

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)  # entrée illisible : ne pas bloquer

cmd = (data.get("tool_input", {}) or {}).get("command", "") or ""

# Bloque seulement si la commande COMMENCE par `cd` (préfixe), pas un cd interne (wsl, &&, etc.).
if re.match(r"^\s*cd(\s|$)", cmd):
    sys.stderr.write(
        "RÈGLE WAMA bloquée : pas de `cd` en préfixe de commande Bash — le cwd est déjà le repo "
        "(D:\\WAMA\\web-app-for-media-automation). Relance SANS le `cd` (chemins relatifs/absolus). "
        "Pour exécuter dans WSL2, mets le `cd` DANS la chaîne : wsl.exe -e bash -lc 'cd /mnt/... && ...'."
    )
    sys.exit(2)

sys.exit(0)
