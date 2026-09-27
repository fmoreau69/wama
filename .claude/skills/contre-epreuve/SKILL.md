---
name: contre-epreuve
description: Prouver qu'une garde neuve MESURE vraiment — en neutralisant la brique qu'elle surveille et en exigeant du ROUGE. Utiliser après avoir écrit un test ou un contrat (« à blanc », « contre-épreuve », « est-ce que ce test verrait le défaut ? », « le test est-il aveugle ? »), et avant de déclarer une garde livrée.
---

# /contre-epreuve — un test vert ne prouve rien s'il ne peut pas rougir

> ⚠ CANDIDAT (n=1 comme skill, 2026-09-27) — mais **le geste a été déroulé 7 fois en deux
> sessions** (22/09 : confirmation de suppression, suivi des liens, enregistrement de provenance ;
> 27/09 : partage entre apps, pointage, copie hors de l'arbre, repointage vers la médiathèque), et
> il a attrapé **deux tests aveugles de ma main** que la relecture n'avait pas vus.

La doctrine l'exige déjà partout (« une garde se mesure À BLANC », `AGENTS.md` ; « la SONDE est
suspecte avant le code ») sans dire COMMENT. Ce skill est la recette, et elle tient en une phrase :
**on casse exprès ce que la garde surveille, et on exige que la garde tombe.**

## 0. Quand — et quand c'est inutile

- OUI : un test NEUF sur un comportement neuf ; un contrat générique sur tout le parc ; une garde
  de FORME (AST) ; tout test dont l'échec serait coûteux à ne pas voir (perte de fichier, droit,
  argent).
- OUI aussi : un test ANCIEN qu'on vient de faire passer du rouge au vert — a-t-il vu la
  correction, ou a-t-il cessé de mesurer ?
- NON : un test qui décrit une valeur littérale (`assertEqual(2, 1 + 1)`), ou dont on vient de
  voir l'échec pour de vrai (le rouge observé EST la contre-épreuve).

## 1. Choisir ce qu'on neutralise — c'est tout le geste

Neutraliser **la brique que la garde surveille**, pas le test. Trois formes, par ordre de
préférence :

| forme | quand | exemple mesuré |
|---|---|---|
| **rendre la brique inerte** (`lambda *a, **k: False` / `{}` / `0`) | la garde dépend d'une RÉPONSE | `is_referenced_elsewhere` → `False` : les contrats de partage rougissent |
| **aveugler une décision** | la brique CHOISIT entre deux chemins | `in_user_home` → `False` : la brique recopie au lieu de pointer, les trois contrats de pointage rougissent |
| **déposer un cas fautif JETABLE** | garde de FORME (AST, balayage du parc) | un `…_backend.py` temporaire avec `find_spec('a.b')` : la garde le NOMME, puis on le supprime |

⚠ **Ne jamais neutraliser l'ASSERTION** (commenter la ligne, forcer l'attendu) : ça prouve que le
test peut échouer, pas qu'il VOIT le défaut.

## 2. La recette, sans toucher au dépôt

```python
"""Contre-épreuve : <ce qui est neutralisé> → <les tests qui doivent rougir>. JETABLE."""
import os
from unittest import mock

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django
django.setup()
from django.conf import settings
from django.test.utils import get_runner

with mock.patch('wama.common.utils.<brique>.<fonction>', lambda *a, **k: <valeur inerte>):
    runner = get_runner(settings)(keepdb=True, verbosity=0)
    failures = runner.run_tests(['<chemin.du.Test.la_methode>', ...])
print('COUNTERPROOF <nom>: failures =', failures,
      '->', 'RED as expected' if failures else 'STILL GREEN (tests aveugles !)')
```

- Le script vit dans le **scratchpad de session**, se lance depuis la racine, et se **supprime
  après** (il ne se commite jamais — et on ne l'écrit pas par son chemin dans une doc, cf. le
  piège `check_docs` du `/cloture §3`).
- `--keepdb` : la base de test est partagée entre instances, on ne la recrée pas.
- ⚠ **Patcher l'ATTRIBUT DE MODULE, pas l'appelant** : les vues du dépôt importent leurs briques
  DANS la fonction (`from … import usage`), donc la résolution se fait à l'appel — c'est
  précisément ce qui rend `mock.patch('module.fonction')` efficace ici.

## 3. Lire le résultat, et ce qu'il dit quand il est VERT

- **Rouge attendu** : la garde mesure. Reporter le fait dans le commit (« contre-épreuve à blanc :
  brique neutralisée → rouge »), jamais seulement dans la tête.
- **Vert** = le test est AVEUGLE, et c'est une découverte, pas un contretemps. Deux causes vues :
  1. le test **exclut le cas** qu'il devrait mesurer — vécu le 27/09 : il écartait « le chemin rendu
     est celui de la source », qui venait justement de devenir le cas NORMAL. *Un test qui exclut le
     nouveau comportement le déclare conforme en silence* ;
  2. le test mesure **le décor et non le geste** — vécu le même jour : un budget de temps qui
     chronométrait le `django.setup()` du sous-processus (46 s) au lieu de la sonde (0,04 s).

## 4. Pièges VÉCUS du harnais de contre-épreuve

- **2026-09-22 — un harnais faux accuse le code.** Trois scénarios JS lancés en PARALLÈLE dans le
  même contexte V8 partageaient leurs variables : les résultats se mélangeaient et le code semblait
  fautif. *Chaîner* (promesses en série) au lieu de lancer tout de front.
- **2026-09-27 — l'ORM hors du contexte Playwright.** Toute lecture de base faite DANS
  `sync_playwright()` lève `SynchronousOnlyOperation` : lire les jetons AVANT d'ouvrir le
  navigateur. (Écrit dans l'en-tête du module de smoke ; je l'ai lu après être tombé dedans.)
- **Neutraliser trop haut ne prouve rien** : patcher la fonction que le test appelle lui-même fait
  échouer le test pour la mauvaise raison. Viser la brique **sous** le comportement mesuré.

## 5. Ce que la contre-épreuve ne remplace pas

Le GESTE RÉEL. Une garde peut mesurer exactement ce qu'on croit et le geste rester cassé à l'écran :
un statut HTTP 409 « prévu » écrivait une erreur dans la console du navigateur — trouvé par le
scénario nocturne, invisible pour 23 contrats Python verts et leurs contre-épreuves. Contre-épreuve
ET smoke : elles ne répondent pas à la même question.
