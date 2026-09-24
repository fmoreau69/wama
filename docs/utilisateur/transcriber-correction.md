<!-- WAMA:GENERE(user-transcriber-correction) — généré par « python manage.py doc_facts » depuis le plan de wama/common/docs_catalog.py ; ne pas éditer -->
# Transcriber — corriger une transcription

> Doc utilisateur **générée** : chaque section vient de la doc de construction (source citée en pied) ou des registres eux-mêmes. Pour la corriger, corriger la SOURCE — ce fichier est réécrit par `python manage.py doc_facts`.

## Corriger une transcription

Une fois la transcription terminée, sa card porte un bouton **Éditer** (icône crayon). Il ouvre
l'éditeur : la forme d'onde, une bande colorée qui signale les passages douteux, et la liste des
segments, synchronisée avec la lecture. Le survol du bouton dit où en est la correction :
brouillon en cours, ou corrigée.

### Deux modes : naviguer, puis éditer

À l'ouverture, l'éditeur est en **navigation** : le clavier pilote l'audio et la sélection des
segments. `Entrée` ouvre le texte du segment sélectionné — c'est le mode **édition**, où les
touches servent à taper ; `Échap` revient à la navigation.

| touche | en navigation | en édition |
|---|---|---|
| `Espace` | lecture / pause | (tape un espace) |
| `J` · `K` · `L` | un cran vers l'arrière · arrêt · un cran vers l'avant (plus rapide à chaque appui) | — |
| `←` · `→` | recule · avance de 5 secondes | — |
| `↑` · `↓` | segment précédent · suivant | — |
| `Tab` · `Maj+Tab` | la lecture saute au segment suivant · précédent | champ suivant · précédent |
| `Alt+↑` · `Alt+↓` | segment précédent · suivant | segment précédent · suivant |
| `Alt+L` | verrouille ou libère le suivi de lecture | idem |
| `Ctrl+Entrée` | coupe le segment à la tête de lecture | coupe le segment à l'endroit du curseur |
| `C` | outil **Bornes** (voir ci-dessous) ; `Échap` pour le quitter | — |
| `Suppr` en fin de texte | — | fusionne avec le segment suivant |
| `Retour arrière` en début de texte | — | fusionne avec le segment précédent |
| `Ctrl+Z` · `Ctrl+Maj+Z` | annule · rétablit | idem |

### Déplacer une borne, couper un segment

Sur la forme d'onde, un trait marque chaque **borne** : la fin d'un segment est le début du
suivant. Les passages hachurés sont des silences qu'aucun segment ne couvre. Le bouton **Bornes**
(ou la touche `C`) active l'outil :

- **glisser une borne** la déplace ; les mots passent d'un segment à l'autre selon leur heure ;
- **cliquer dans un segment** le coupe en deux à cet endroit (ciseaux) ;
- glisser ailleurs que sur une borne déplace la vue, comme sans l'outil.

Une borne se pose toujours **entre deux mots**, jamais au milieu d'un mot, et chaque segment garde
au moins un mot : aucun mot n'est perdu. Si vous avez corrigé le texte d'un segment, ses mots
sont d'abord recalés sur la transcription automatique. Chaque geste s'annule avec `Ctrl+Z`.
`Échap` quitte l'outil.

### La bande de qualité

Chaque segment y a sa couleur : vert, orange ou rouge. Si la vérification de cohérence a été
demandée, la couleur vient de l'IA et le survol affiche sa remarque ; sinon, elle vient de la
confiance de la reconnaissance vocale. Un clic sur une zone y place la lecture et sélectionne le
segment.

### Enregistrer, terminer

Les modifications s'enregistrent seules, peu après la frappe ; l'indicateur de la barre d'outils
affiche « À jour » quand c'est fait, et le texte téléchargeable suit la correction. **Compacter**
fusionne les segments consécutifs d'un même locuteur. **Terminer la correction** marque la
transcription comme corrigée et reconstruit ses sous-titres.

### Évaluer une transcription contre une référence

Si vous disposez d'une transcription juste — corrigée à la main, par exemple un export Sonal —,
WAMA peut mesurer l'écart entre elle et la transcription automatique. Dans le menu d'une card
(bouton « … » ou clic droit), **Résultat de référence… → Joindre…** : choisissez le fichier
(SRT, VTT, TXT, DOCX, PDF ou Markdown). Seul le texte placé sous un locuteur (`Speaker 1 :`…) est
comparé ; titres, en-têtes et notes sont écartés.

L'onglet **Évaluation** de la card affiche alors le taux d'erreur par mot (WER) et par caractère
(CER), avec le détail : mots remplacés, oubliés, ajoutés. Les hésitations (« euh ») comptent : ce
sont des paroles. La casse et la ponctuation ne comptent pas.

Pour **comparer plusieurs moteurs** sur le même audio : dupliquez la card dans son lot (« Dupliquer
dans le batch »), choisissez un autre moteur sur le double, relancez, puis posez la référence sur
le lot entier (menu de la card du lot : **Référence du lot…**). Une ligne sous la card du lot
classe les moteurs, le meilleur en tête. Une transcription faite par un autre outil se compare de
la même façon : sur un double de la card, **Résultat existant… → Reprendre un fichier…**.

Sans référence, la même ligne indique l'**accord entre moteurs** : le pourcentage de désaccord de
chacun avec les autres, sur le même audio. Il montre où regarder, pas qui a raison — aucun moteur
n'y est déclaré meilleur. À partir de trois moteurs, celui qui s'écarte le plus est signalé en
orange.

<!-- WAMA:PORTE-FERMEE(wama/transcriber/TRANSCRIBER_CORRECTION.md — 9.4 Le guidage de nettoyage) : intention ⏳ — n'arrive chez l'utilisateur qu'une fois implémentée -->

*Source : [wama/transcriber/TRANSCRIBER_CORRECTION.md — 9. Corriger une transcription — le guide](../../wama/transcriber/TRANSCRIBER_CORRECTION.md#9-corriger-une-transcription--le-guide)*
