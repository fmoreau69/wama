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
| `Ctrl+Entrée` | — | coupe le segment à l'endroit du curseur |
| `Suppr` en fin de texte | — | fusionne avec le segment suivant |
| `Retour arrière` en début de texte | — | fusionne avec le segment précédent |
| `Ctrl+Z` · `Ctrl+Maj+Z` | annule · rétablit | idem |

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

<!-- WAMA:PORTE-FERMEE(wama/transcriber/TRANSCRIBER_CORRECTION.md — 9.4 Le guidage de nettoyage) : intention ⏳ — n'arrive chez l'utilisateur qu'une fois implémentée -->

*Source : [wama/transcriber/TRANSCRIBER_CORRECTION.md — 9. Corriger une transcription — le guide](../../wama/transcriber/TRANSCRIBER_CORRECTION.md#9-corriger-une-transcription--le-guide)*
