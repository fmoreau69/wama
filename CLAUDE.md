# CLAUDE.md — harnais Claude Code (WAMA)

@AGENTS.md

> ⚠ **La doctrine WAMA n'est PAS dans ce fichier** — elle est dans `AGENTS.md`, importé
> par la ligne ci-dessus, et c'est là qu'elle se modifie. Ce fichier ne garde que ce qui
> n'a de sens que **dans Claude Code** : le matcher de permissions de
> `.claude/settings.local.json` et les hooks de `.claude/hooks/`. Donner ces règles à
> Codex ou Copilot leur imposerait des interdits sans objet.
>
> **Si l'import `@AGENTS.md` ne se voit pas dans une session, lire `AGENTS.md`
> directement** — c'est lui qui fait foi, ce fichier n'en est jamais un résumé.

## Ce que porte `AGENTS.md` (index, pas un résumé)

Philosophie en 6 points · vérifier la route avant de PROPOSER · discipline git
multi-instances · patches de venv · nommage des dossiers et langue des identifiants ·
un monde n'est pas un sous-dossier du substrat · pas de `.md` concurrent (+ table des
fichiers de référence par domaine) · centralisation dans `common/` · ajout d'un modèle
AI · conventions UI & architecture · collaboration wama-dev-ai · modèles imager actifs.

---

## 🔴 RÈGLE OBLIGATOIRE : JAMAIS de `cd` EN PRÉFIXE DE COMMANDE SHELL

> Le répertoire de travail est **déjà** `D:\WAMA\web-app-for-media-automation`. Préfixer une
> commande par `cd` (ex. `cd /d/WAMA/... && cmd`) **déclenche une validation de permission à chaque
> appel** et **bloque la progression**. C'est inutile et coûteux.

- ❌ `cd /d/WAMA/web-app-for-media-automation && cp a b`
- ✅ `cp a b` (chemins relatifs au repo) ou chemins **absolus** si besoin d'un autre dossier.
- Pour exécuter dans WSL2 : `wsl.exe -e bash -lc '... && python ...'` (le `cd` est alors **dans** la
  chaîne WSL, pas un préfixe de la commande Bash hôte — c'est toléré).

---

## 🔴 RÈGLE OBLIGATOIRE : UNE COMMANDE COMMENCE PAR UN EXÉCUTABLE (sinon : encapsuler)

> Une règle de permission est un **préfixe**. Une commande qui commence par `$var = …`, `(`, `&`,
> `foreach`, `try` n'en offre aucun : elle **ne pourra JAMAIS être autorisée durablement**, coûtera
> une validation à chaque appel, et n'ajoutera qu'un littéral mort dans `settings.local.json`.
> Mesuré le 10/08 : **52 des 74 entrées** réaccumulées en 4 jours étaient de tels littéraux.

- ❌ `$pw = (Get-Content .env | Where-Object …); & "C:\…\psql.exe" -c "…"`
- ✅ `Write <scratchpad>/step.ps1` puis `pwsh -NoProfile -File <scratchpad>/step.ps1`
- ✅ Une commande à préfixe reste libre, **pipes compris** : `Get-ChildItem … | Where-Object …`,
  `wsl.exe -e bash -lc "… && …"`. Le pipe n'a jamais été le problème (vérifié : la surface Bash,
  truffée de pipes, était couverte à 100 %).
- Appliqué par `.claude/hooks/block_composite_oneliner.py` (n'agit que sur l'outil PowerShell).
- **Écrire toute règle sur LES DEUX outils** (`Bash(...)` ET `PowerShell(...)`) et dans la graphie
  réellement émise : c'est l'asymétrie entre les deux qui causait 100 % des sollicitations résiduelles.

---
