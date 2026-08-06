#!/usr/bin/env python3
"""Bloque la lecture de fichiers par one-liner shell : l'outil Read/Grep le fait mieux.

Motif observé (06/08) : pour afficher les lignes 166-176 d'un template, l'assistant
écrit `$c = Get-Content …; 166..176 | ForEach-Object { … }`. Cette commande
- ne peut matcher AUCUN motif de permission (elle commence par `$c =`),
- est découpée en segments par le `;` (une sollicitation PAR segment),
- est unique par construction (ce fichier, ces lignes) : l'approuver n'apprend rien.
Elle coûte donc une sollicitation à chaque fois, pour un résultat que
`Read(file_path, offset=166, limit=11)` rend gratuitement et sans découpage.

On ne bloque QUE les formes « inspecter un fichier » qui ont un équivalent natif
exact. Tout ce qui écrit, transforme ou canalise vers un traitement réel passe.
"""
import json
import re
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)  # entrée illisible : ne pas bloquer

cmd = (data.get("tool_input", {}) or {}).get("command", "") or ""

# Un pipeline qui MODIFIE (écrit, remplace, supprime) n'est pas une lecture : on laisse.
if re.search(r"\b(Set-Content|Out-File|Add-Content|Remove-Item|-replace|>|>>)\b", cmd):
    sys.exit(0)

# Charger un fichier pour le TRAITER (parser, agréger, comparer) n'est pas
# « regarder des lignes » : Read ne le remplace pas. On laisse passer.
if re.search(
    r"\b(ConvertFrom-Json|ConvertFrom-Csv|ConvertFrom-StringData|Measure-Object|"
    r"Group-Object|Compare-Object|Sort-Object|Import-Csv|Test-Json)\b",
    cmd,
):
    sys.exit(0)

REDIRECTIONS = [
    (
        # `$c = Get-Content …` / `(Get-Content …)[…]` / Get-Content + découpage de lignes
        r"(\$\w+\s*=\s*Get-Content|\(\s*Get-Content[^)]*\)\s*\[|"
        r"Get-Content[^|;]*(\||;)[^|;]*(ForEach-Object|Select-Object|\.\.))",
        "Read(file_path, offset=<1re ligne>, limit=<nb lignes>) — numérotation incluse",
    ),
    (
        # Recherche de motif dans des fichiers
        r"\bSelect-String\b[^|]*-Path|\bfindstr\b",
        "Grep(pattern, path, output_mode='content', -n=true)",
    ),
    (
        # Affichage brut d'un fichier entier
        r"^\s*(cat|type)\s+\S+\s*$|^\s*Get-Content\s+\S+\s*$",
        "Read(file_path)",
    ),
    (
        # Tranche de lignes via sed
        r"\bsed\s+-n\s+['\"]?\d+\s*,\s*\d+\s*p",
        "Read(file_path, offset=…, limit=…)",
    ),
]

for pattern, better in REDIRECTIONS:
    if re.search(pattern, cmd):
        sys.stderr.write(
            "REGLE WAMA bloquee : lire un fichier par one-liner shell coute une "
            "sollicitation de permission a chaque appel (motif non generalisable, "
            "et un `;`/`|` = une demande PAR segment).\n"
            f"Utilise l'outil natif a la place : {better}\n"
            "Il ne demande aucune permission, numerote les lignes et ne subit pas "
            "le decoupage. Si la lecture native te revient compressee/illisible, "
            "relis par tranches de 10-15 lignes — ne contourne pas par le shell."
        )
        sys.exit(2)
