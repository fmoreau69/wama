---
name: reverif
description: Revérification COMPLÈTE de ce qu'une session a livré, à la demande et sans la clore — aligné sur le fonctionnement inter-mondes et la route de génération, rien réinventé, aucun chemin parallèle, tests nécessaires ajoutés et prouvés, rien cassé, doc confrontée au code, tout consigné, tout commité. Utiliser quand l'utilisateur demande « revérifie », « revérification complète », « rien réinventé ? », « c'est bien aligné ? », « on n'a rien cassé ? », « tout est consigné ? tout commité ? », « méticuleusement, en profondeur ». Pour la FIN de session (handoff, mémoire), c'est /cloture, qui inclut ce passage.
---

# /reverif — revérifier une session, en profondeur, sans la clore

> ⚠ CANDIDAT (n=1, 2026-10-12) — distillé d'une revérification unique, demandée par Fabien
> (« je le demande très souvent »), non confrontée à une 2ᵉ occurrence.

**Posture, une fois pour toutes** : méticuleusement, en profondeur, en confrontant la doc au
CODE. Toute affirmation nomme la LIGNE (ou la sortie de commande, ou l'assertion de test) qui la
fonde — la règle « citer ne suffit pas » d'`AGENTS.md` (§ VÉRIFIER LA ROUTE, DURCISSEMENT).
Ce skill n'ajoute que ce qui manque ailleurs ; chaque étape RENVOIE à son domicile.

## 0. L'inventaire de ce qu'il faut revérifier

```bash
git log --format='%h %ad %s' --date=short -<n>        # les commits de la session (les miens)
git status --porcelain                                 # ce qui reste dans l'arbre : à moi ? à qui ?
```
Une ligne par LIVRABLE (fonction, critère, gabarit, doc, retrait) : c'est la table que remplissent
les étapes suivantes. Un fichier de l'arbre qui n'est pas à moi se laisse, se nomme (cf.
`/cloture §0` pour le départager par la date).

## 1. Aligné — la seule étape propre à ce skill

Pour CHAQUE livrable, trois questions, chacune tranchée par une lecture :
1. **La route** — quelle section de `docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md`
   le porte (§10.x, §F…, palier) ? Le livrable la suit-il, ou en crée-t-il une variante ? Les
   quatre sources d'autorité d'`AGENTS.md` (mécanismes, ROUTE §S/§10.5, `registries.overview()`,
   règle des mondes) sont lues, pas citées de mémoire.
2. **Les mondes** — substrat / Médias / Data / Lab : le livrable cite-t-il un monde en dur dans le
   substrat, ou fait-il dépendre un monde d'un autre (`AGENTS.md` § UN MONDE N'EST PAS UN
   SOUS-DOSSIER) ?
3. **Un seul chemin** — existe-t-il DÉJÀ, dans WAMA, une déclaration ou une lecture de la même
   NATURE ? Pas du même nom : de la même nature (un langage de champs, une lecture AST, une
   résolution de chemin, un lecteur de fichier).

🔴 **Vécu le 2026-10-12 — le gardien n'a RIEN vu, la lecture a trouvé quatre écarts.**
`check_redundancy` filtré sur les fichiers de la session : une seule trouvaille, antérieure et
d'une autre session. La lecture des fonctions VOISINES et des briques du même domaine a trouvé :
une lecture AST des noms d'un module recopiée sans les blocs de tête (`sandbox.resolves` à côté
du juge d'imports d'`app_sandbox`) ; une lignée de classes recalculée à côté de
`backend_inventory._class_lineage` ; un lecteur de manifeste sans sa validation, à côté de celui
de `create --from-manifest` ; et un SECOND LANGAGE de champs (lignes de statut de la triade) à
côté de celui de la spec de détail (`common/utils/detail_registry.py`). ⇒ `/cloture §2a ter` le
dit déjà (« faux négatifs ») ; ici c'est l'étape, pas une note.

## 2. Testé — lancer, garder, prouver

- Lancer : `/cloture §2a` (périmètre ciblé, puis la suite si le substrat a bougé ; lire les NOMS
  des rouges ; « à qui il appartient » s'ÉTABLIT, ses cinq gestes y sont).
- Garder : `/cloture §2a bis` — une ligne par livrable : son symbole → le test qui le nomme.
- Prouver : `/contre-epreuve` sur chaque garde neuve (brique neutralisée → ROUGE exigé). Vécu le
  2026-10-12 : sept gardes, toutes rouges — mais c'est la seule façon de le SAVOIR.

## 3. Consigné — la doc confrontée au code

- `python manage.py doc_facts --check` et `check_docs` (cibles distinctes, pas références —
  `/cloture §2c`). ⚠ Vécu le 2026-10-12 : un RETRAIT raccourcit un fichier et périme les
  renvois `fichier:ligne` des traces datées (`PROJECT_STATUS`) — `check_docs` les nomme.
- Chaque livrable a sa ligne dans son doc-domicile (table des domaines d'`AGENTS.md`) ; un retrait
  a son `R<n>` au `REMOVAL_LEDGER` (numéro UNIQUE : relire la dernière ligne au moment d'écrire,
  une autre session a pu le prendre) ; un registre qui a bougé a son corpus régénéré (`/cloture §2b`).
- Une doc générée régénérée porte aussi le travail d'autrui : n'en commiter que sa part
  (`/commit-partiel §4`).

## 4. Commité — et rien d'autre

- `/commit-partiel` CHARGÉ dès qu'un fichier est co-édité (jamais refait de mémoire : 3ᵉ récidive
  du patch `-U0` le 2026-10-12, `/palier §3` le prescrivait encore).
- Après chaque commit : `git show --stat HEAD` = mes seuls fichiers ; le diff de l'arbre contre
  le nouveau HEAD ne montre plus MES lignes ; aucune ligne `Co-Authored-By`.
- `git status` final : ce qui reste est nommé, avec son propriétaire.

## 5. Sortie — une table, des preuves

| étape | verdict | preuve (une donnée, jamais « oui ») |
|---|---|---|
| 1 aligné | ✓/✗ par livrable | la section de ROUTE ; l'écart trouvé et son sort (ramené / consigné) |
| 2 testé | ✓/✗ | chiffre MESURÉ, noms des rouges et à qui ; gardes → tests ; contre-épreuves |
| 3 consigné | ✓/✗ | `doc_facts --check`, `check_docs`, docs touchées, `R<n>` |
| 4 commité | ✓/✗ | shas ; ce qui reste dans l'arbre et à qui |

Un écart trouvé se RAMÈNE à son domicile dans la session quand il est petit ; sinon il se
CONSIGNE comme chantier (doc-domicile + handoff), nommé, jamais tu.
