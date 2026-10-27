---
name: contre-epreuve
description: Prouver qu'une garde neuve MESURE vraiment — en neutralisant la brique qu'elle surveille et en exigeant du ROUGE. Utiliser après avoir écrit un test ou un contrat (« à blanc », « contre-épreuve », « est-ce que ce test verrait le défaut ? », « le test est-il aveugle ? »), et avant de déclarer une garde livrée.
---

# /contre-epreuve — un test vert ne prouve rien s'il ne peut pas rougir

> PROMU (n=2 : 2026-09-27, distillé de 7 déroulés en deux sessions — 22/09 : confirmation de
> suppression, suivi des liens, enregistrement de provenance ; 27/09 : partage entre apps,
> pointage, copie hors de l'arbre, repointage vers la médiathèque — où il a attrapé **deux tests
> aveugles de ma main** ; 2026-10-21→22, déroulé GUIDÉ par ce skill sur onze gardes d'une même
> session — rôle du compte, lecture des dossiers connectés, déplacement d'un nœud de monde,
> portes de l'exécuteur du Studio —, toutes rouges, et le piège du §4 « fonction liée à
> l'import » rencontré et résolu).

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

- 🔴 **TOUJOURS par `get_runner(settings)` — JAMAIS `unittest.TextTestRunner`, `suite.run()` ni
  `TestCase(...).run()`** (perte TOTALE des médias le 2026-10-27). Seul le lanceur WAMA redirige
  `MEDIA_ROOT` vers `media_tests/` et monte une base de TEST : un test lancé hors de lui tourne sur
  le vrai `media/` et la vraie base. Un `setUp` qui programmait `rmtree(settings.MEDIA_ROOT)` a
  ainsi effacé les médias de tous les utilisateurs (restaurés depuis le NAS ; perdu ce qui datait
  d'après la sauvegarde de la nuit). Depuis : `common/utils/media_guard.py` refuse tout
  `rmtree` de `media/` dans tout processus Django, et `tests_media_tests_hygiene` interdit le
  motif — mais le lanceur reste la règle, la garde n'est qu'un filet.
- Le script vit dans le **scratchpad de session**, se lance depuis la racine, et se **supprime
  après** (il ne se commite jamais — et on ne l'écrit pas par son chemin dans une doc, cf. le
  piège `check_docs` du `/cloture §3`).
- ⚠ **« Depuis la racine » ne suffit pas** (vécu le 2026-10-19) : Python met en tête de
  `sys.path` le dossier du SCRIPT, pas le dossier courant — un script du scratchpad lancé par
  `python <scratchpad>/x.py` sort en `ModuleNotFoundError: No module named 'wama'`. Le lancer
  avec `PYTHONPATH=.` (depuis la racine), ou par `manage.py shell -c "exec(open(...).read())"`.
- `--keepdb` : la base de test est partagée entre instances, on ne la recrée pas.
- ⚠ **Patcher l'ATTRIBUT DE MODULE, pas l'appelant** : les vues du dépôt importent leurs briques
  DANS la fonction (`from … import usage`), donc la résolution se fait à l'appel — c'est
  précisément ce qui rend `mock.patch('module.fonction')` efficace ici.
- 🔴 **Et le TEST qui importe la brique en tête (`from m import f`) l'importe pendant le patch**
  (vécu le 2026-10-20). `run_tests` charge le module de test DANS le `with mock.patch(...)` : il
  lie la FAUSSE fonction, compare le faux au faux, et reste vert — puis la garde le reste dans
  `sys.modules` et contamine la contre-épreuve suivante du même processus. ✅ Importer le module
  de test AVANT le patch (`import wama.….tests_x as t ; assert t.f is m.f`), et une
  contre-épreuve par processus. *Un vert après un patch accuse d'abord l'ordre des imports.*

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
- **2026-10-13 — dans V8, une PROMESSE ne se règle qu'ENTRE deux `eval`** (`py_mini_racer`). Deux
  fois le même jour, une contre-épreuve écrite en UN seul `eval` (geste, réponse, minuterie,
  lecture) a rendu le même résultat pour le code sain et le code muté : la réponse était encore
  « en vol » au moment de lire. ✅ Découper comme le test qu'on éprouve : un `eval` par étape, et un
  tour de minuterie par `eval` quand une réponse doit se régler avant le suivant. *Deux résultats
  identiques sain / muté accusent d'abord le harnais.*
- **2026-10-13 — une garde qui BOUCLE sur un ensemble peut boucler sur RIEN.** « Le demandeur ne
  reçoit aucun bouton » parcourait les notifications du demandeur — qui ne reçoit jamais ce type :
  vert avec la garde retirée. ✅ Exiger l'élément qu'on vérifie (`(item,) = [...]` plutôt qu'un
  `for`) : le dépaquetage échoue si l'ensemble est vide. Seule la mutation l'a montré.
- 🔴 **2026-10-18 — une mutation par ÉDITION se restaure PAR POSITION, jamais en recherchant le
  texte muté.** Quand le patch d'attribut ne suffit pas (un appel retiré d'une vue, une ligne de
  JS), on mute le fichier. Ma restauration faisait `replace(muté, original, 1)` : le texte muté
  (« `    step` », quatre espaces et un mot) existait PLUS HAUT dans le fichier — l'original s'est
  réinséré au mauvais endroit, au milieu d'une autre fonction de `gateway/core.py`. Ce qui l'a
  vu : l'assertion de fin `octets restaurés == octets d'avant`, qui a arrêté le script ; réparé à
  la main, revérifié par `git diff --numstat` avant tout commit.
  ✅ Le geste : exiger que l'original apparaisse UNE fois (`count == 1`), noter sa POSITION, muter
  à cette position, restaurer à cette même position (`cur[at:at+len(muté)] == muté` vérifié
  d'abord), puis comparer les octets à ceux d'avant. *Une restauration qui cherche ce qu'elle a
  écrit trouve aussi ce que d'autres ont écrit.* (Et jamais par copie d'un fichier co-édité.)

- **2026-10-21 — une fonction LIÉE À L'IMPORT échappe au patch d'attribut.** La garde de
  l'écrivain du niveau d'un compte importait `set_account_tier` en tête de module
  (`from wama.accounts.permissions import set_account_tier`) : neutraliser l'attribut du module
  n'atteignait pas l'objet déjà lié, et la mutation par ÉDITION du fichier non plus tant que le
  module de test gardait l'ancienne fonction. ✅ Après la mutation : `importlib.reload(<brique>)`
  PUIS `sys.modules.pop('<module de test>')` avant de lancer le runner (il réimporte), et la même
  restauration à la fin. *Le patch atteint ce qui se résout à l'appel, pas ce qui l'a déjà été.*

- **2026-10-27 — en bash, une fonction de restauration PARTAGE la variable de la boucle.** Une
  contre-épreuve par brique (« remettre chaque JS servi à HEAD, un par un ») appelait `restore()`
  en tête de boucle ; `restore` bouclait elle-même avec `for f in …` : à son retour, `$f` valait
  le DERNIER fichier de sa liste. Les trois passes ont muté la même brique — trois fois le même
  rouge, attribué à trois briques différentes par l'en-tête affiché. Vu en lisant les NOMS des
  rouges (tous ceux du chat), pas leur nombre. ✅ `local g` dans toute fonction appelée depuis une
  boucle ; et une passe par mutation doit afficher des rouges DIFFÉRENTS — *trois sorties
  identiques pour trois mutations accusent d'abord le harnais.*

- **2026-10-27 — muter le fichier que la garde LIT, pas son jumeau.** Une garde du noyau des
  surfaces lisait la SOURCE (`wama/common/static/…`) ; ma mutation visait la copie SERVIE
  (`staticfiles/…`) : vert, que j'aurais pu lire comme « garde aveugle ». ✅ Avant de muter, lire
  dans le test quel chemin il ouvre (`STATIC = …`, `_js()`, `staticfiles`) ; un fichier synchronisé
  en deux copies se mute à celle-là.
- 🔴 **2026-10-27 — contre le LIVE, la mutation se fait DANS LE NAVIGATEUR du scénario, jamais
  sur le disque.** Les scénarios nocturnes visent le gunicorn en service : réécrire un `.js` ou un
  `.css` servi l'enverrait à tous les comptes. ✅ Le scénario accepte un `page_hook(page)` ; la
  contre-épreuve y pose `page.route(<motif>, handler)` qui fait `route.fetch()`, remplace le
  texte et `route.fulfill(...)` — le serveur et les autres utilisateurs ne voient rien. Relever
  le nombre d'occurrences remplacées : ⚠ un motif GLOB (`'**/wama-surface.js'`) ne prend PAS une
  URL statique qui porte `?v=…` — trois contre-épreuves « vertes » sans mutation posée (`[]`) ;
  un motif `re.compile(r'/js/…\.js')` les a posées (`[1, 1, 1]`) et rendues rouges. *Une
  contre-épreuve verte dont la mutation n'a pas été posée ne prouve rien — compter la pose.*

## 5. Ce que la contre-épreuve ne remplace pas

Le GESTE RÉEL. Une garde peut mesurer exactement ce qu'on croit et le geste rester cassé à l'écran :
un statut HTTP 409 « prévu » écrivait une erreur dans la console du navigateur — trouvé par le
scénario nocturne, invisible pour 23 contrats Python verts et leurs contre-épreuves. Contre-épreuve
ET smoke : elles ne répondent pas à la même question.
