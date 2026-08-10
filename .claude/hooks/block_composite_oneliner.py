#!/usr/bin/env python3
"""Bloque les one-liners PowerShell SANS préfixe binaire : ils sont structurellement
inautorisables, donc ils coûtent une sollicitation à CHAQUE appel, pour toujours.

Mesure du 10/08 (288 appels shell sur 4 jours, transcripts du projet) :
- 163 appels (57 %) n'étaient couverts par aucune règle, et 100 % passaient par
  l'outil PowerShell — la surface Bash, elle, était couverte à 100 %.
- Après comblement des trous de parité (wsl.exe, venv, rtk, Copy-Item…) : 23 %.
- Le résidu est dominé par 44 commandes composites de la forme
  `$pw = (Get-Content .env | …); $env:PGPASSWORD = …; & "…\\psql.exe" …`.

Pourquoi elles ne peuvent PAS être réglées par la config : une règle de permission
est un PRÉFIXE (`PowerShell(Get-ChildItem:*)`). Une commande qui commence par `$`,
`(`, `&`, `foreach`, `try`… n'a aucun préfixe binaire à offrir. Le système ne peut
alors mémoriser QUE la commande littérale entière — qui, unique par construction
(ce chemin, ces lignes, cette date), ne rematchera jamais. Preuve : sur les 74
entrées réaccumulées dans settings.local.json en 4 jours, 52 sont de tels littéraux
morts, dont trois commandes `psql` quasi identiques stockées séparément.

La sortie est l'encapsulation : écrire la logique dans un `.ps1` (outil Write, déjà
autorisé) puis l'exécuter via `pwsh -NoProfile -File <script>` — forme à préfixe,
couverte par UNE règle, valable pour un nombre illimité d'invocations.

Ce que le hook NE bloque PAS :
- toute commande à préfixe binaire, même avec `|` et `;` — elles sont couvertes par
  les règles existantes et ne sollicitent rien (`Get-ChildItem … | Where-Object …`) ;
- `wsl.exe -e bash -lc "… && …"` — préfixe `wsl.exe`, désormais autorisé ;
- l'outil Bash, dont la surface ne présente aucun trou mesuré.
"""
import json
import re
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)  # entrée illisible : ne pas bloquer

if data.get("tool_name") != "PowerShell":
    sys.exit(0)

cmd = ((data.get("tool_input") or {}).get("command") or "").strip()
if not cmd:
    sys.exit(0)

# Un préfixe binaire, c'est un premier token exécutable : `Get-ChildItem`, `git`,
# `wsl.exe`, `./venv_win/Scripts/python.exe`. Tout le reste est inautorisable.
SANS_PREFIXE = (
    r"^[\$\(\&\@\[\"']"                        # $var= , (…) , & "…" , @(…) , [type] , "texte"
    r"|^(foreach|if|try|while|do|switch|function)\b"   # mot-clé de structure
)

if not re.search(SANS_PREFIXE, cmd, re.IGNORECASE):
    sys.exit(0)

# `pwsh -NoProfile -File …` est justement la sortie : ne jamais la bloquer.
if re.match(r"^pwsh\b", cmd, re.IGNORECASE):
    sys.exit(0)

extrait = cmd if len(cmd) <= 90 else cmd[:90] + " …"
sys.stderr.write(
    "REGLE WAMA bloquee : ce one-liner PowerShell n'a pas de prefixe binaire\n"
    f"  ({extrait})\n"
    "donc AUCUNE regle de permission ne pourra jamais le couvrir : il coutera une\n"
    "sollicitation a chaque appel et n'ajoutera qu'un litteral mort dans\n"
    "settings.local.json (52 sur 74 entrees en 4 jours sont de cette nature).\n"
    "\n"
    "Encapsule a la place, en deux gestes :\n"
    "  1. Write  <scratchpad>/step.ps1   avec exactement cette logique\n"
    "  2. PowerShell: pwsh -NoProfile -File <scratchpad>/step.ps1\n"
    "\n"
    "La forme `pwsh -NoProfile -File *` est autorisee par UNE regle, valable pour\n"
    "un nombre illimite d'invocations. Le script reste lisible et rejouable.\n"
    "Si la logique tient en une commande a prefixe (`Get-ChildItem …`, `git …`,\n"
    "`wsl.exe -e bash -lc \"…\"`), reecris-la sous cette forme : elle passera seule."
)
sys.exit(2)
