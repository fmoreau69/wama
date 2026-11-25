# WAMA_CONCEPTS.md — dictionnaire des concepts clés

> **Ce fichier est un INDEX, pas une doctrine de plus.** Demandé par Fabien le 2026-11-24
> (*« Dictionnaire de concepts clés : alignement, schéma-driven, imbrication, etc. »*) : les mots
> qui reviennent dans chaque demande et chaque revue, dits en deux lignes, avec le test qui permet
> de les reconnaître et le DOMICILE de leur définition. **La définition qui fait foi est celle du
> domicile cité** — ici on ne fait que la nommer et y renvoyer. Un mot neuf s'ajoute ici le jour où
> il sert dans deux mondes ; un mot dont le domicile change se corrige ici dans le même commit.
>
> Marques : ✅ en service · 🔄 en cours · ⏳ décidé (D1 à D14, validées par Fabien le 2026-11-24),
> pas encore construit.

---

## 1. Les quatre exigences d'une livraison

| mot | ce qu'il veut dire | on le reconnaît à | domicile |
|---|---|---|---|
| **aligné** ✅ | ce qu'on écrit suit la route déjà tracée : la brique existante est réemployée, la convention existante suivie, la décision existante respectée | la livraison peut CITER ce qu'elle a lu (mécanisme, section de route, registre) ; aucun chemin parallèle | `AGENTS.md` § « vérifier la route avant de proposer » |
| **universel** ✅ | la même chose vaut pour toutes les apps et pour les trois mondes (Médias, Data, Lab) | aucun nom d'app dans le commun ; une app neuve en hérite sans une ligne | `AGENTS.md` § philosophie, points 1 et 2 |
| **uniforme** ✅ | l'utilisateur retrouve les mêmes gestes, les mêmes mots, le même écran partout | un seul gabarit, une seule brique d'interface pour un geste | `AGENTS.md` § philosophie, point 2 ; `WAMA_APP_CONVENTIONS.md` |
| **schéma-driven** (métadonnée-driven) ✅ | l'interface et le comportement se DÉRIVENT de déclarations (schéma de réglages, capacités, ports, surfaces), ils ne s'écrivent pas à la main par app | changer la déclaration change l'écran ; le générateur d'app et la jumelle régénérée suivent | `AGENTS.md` § philosophie, points 3 et 4 ; `WAMA_APP_GENERATION_ROUTE.md` |

## 2. Dire ce qui est vrai

| mot | ce qu'il veut dire | on le reconnaît à | domicile |
|---|---|---|---|
| **déclaré / dérivé / mesuré** ✅ | déclaré : écrit une fois, à la source ; dérivé : calculé d'une déclaration ; mesuré : lu sur le code ou la base | une valeur dérivée n'est jamais recopiée ; une mesure nomme sa ligne ou sa commande | `wama/common/registries.py` (nature d'un registre) ; `AGENTS.md` § durcissement |
| **constat / intention** ✅ | un constat dit l'état présent et se corrige s'il contredit le code ; une intention projette et se garde, marquée | une marque ✅ 🔄 ⏳ et une date | `AGENTS.md` § durcissement |
| **garde / contre-épreuve** ✅ | une garde est un test qui tient un contrat ; sa contre-épreuve prouve qu'elle rougit quand on casse ce qu'elle surveille | le test est générique (il boucle sur les déclarations) et a été vu rouge | `WAMA_VERIFICATION.md §8` ; skill `contre-epreuve` |

## 3. Les pièces

| mot | ce qu'il veut dire | domicile |
|---|---|---|
| **monde** ✅ | Médias, Data, Lab : trois racines de code, un substrat commun au-dessous | `AGENTS.md` § « un monde n'est pas un sous-dossier du substrat » |
| **brique** ✅ | un morceau de code ou d'interface commun, écrit une fois dans `wama/common/`, que les apps emploient | `WAMA_MECANISMES.md` (l'index, généré) |
| **registre** ✅ | ce que WAMA sait NOMMER (apps, modèles, backends, fonctions, surfaces…) et la relation entre ces objets | `wama/common/registries.py` |
| **manifeste** ✅ | la déclaration complète d'un objet (app, modèle, librairie, fonction, pipeline, projet, jeu de données) | `WAMA_MANIFEST_SPEC.md` |
| **route** ✅ | le chemin tracé pour faire une chose (générer une app, installer un modèle) — on le suit, on ne passe pas à côté | `WAMA_APP_GENERATION_ROUTE.md` ; `AGENTS.md` § installation par la route |
| **domaine / mode** ✅ | un domaine est un workflow distinct d'une app (un onglet) ; un mode en est une variante d'entrée | `wama/common/utils/app_modes.py` ; `MODES_QUEUE_UX.md §2bis` |
| **port** ✅ | ce qu'une app ou une fonction reçoit et rend, typé | `WAMA_APP_GENERATION_ROUTE.md §10.1` |
| **surface** ✅ | un écran déclaré d'une app (page d'édition, onglet), composé de briques d'interface | `WAMA_APP_GENERATION_ROUTE.md §F3b` |

## 4. La file

| mot | ce qu'il veut dire | domicile |
|---|---|---|
| **card** ✅ | l'unité de traitement : une entrée, ses réglages, son pipeline, ses résultats, sa page d'édition | `CARD_DESIGN.md` ; `WAMA_APP_GENERATION_ROUTE.md §10.6` |
| **process / pipeline** ✅ | un process est une étape de traitement ; le pipeline d'une card est le graphe de ses process | `WAMA_APP_GENERATION_ROUTE.md §10.6` |
| **lot** ✅ | un groupe ordonné de cards de même niveau ; toute card est dans un lot (une card seule est un lot d'un) | `CARD_DESIGN.md` (anatomie des lots) ; `MODES_QUEUE_UX.md §5ter` ; `BATCH_FORMAT.md` (le fichier de lot) |
| **variation** ✅ | N cards qui traitent la MÊME entrée différemment (N modèles sur un audio) — c'est un lot | `MODES_QUEUE_UX.md §5quater` |
| **composition** (famille) ✅ | des cards qui sont les PARTIES d'une card (les pistes d'un morceau) — le lien `derived_from`, leur lot rangé sous la card | `MODES_QUEUE_UX.md §5quater` |

## 5. Le temps et l'imbrication (réflexion du 2026-11-24)

| mot | ce qu'il veut dire | domicile |
|---|---|---|
| **imbrication** 🔄 | un arbre DÉCLARÉ : parent unique, enfants ordonnés, loi d'agencement, contrainte sur le parent, héritage déclaré, aucune borne de profondeur dans la donnée. ✅ pour les cards (rangement à toute profondeur) ; ⏳ comme concept commun aux cards, aux marques et à la base | `WAMA_APP_GENERATION_ROUTE.md §10.7.9` |
| **card ou segment** ⏳ | LE critère (révisé le 2026-11-24 au soir) : ce qui demande une génération ou un traitement propre est une CARD ; ce qui ne fait que délimiter le temps est un SEGMENT. Un segment ne devient jamais une card : un traitement lancé sur lui est une card dérivée qui POINTE vers lui. Affûté (proposition du 2026-11-24, `§10.7.13 ⑦`) : une card a un réglage, un état dans la file et une relance ; un traitement qui rend des VALEURS par segment est une étape de la card, ses résultats des colonnes de la table de segments | `§10.7.12 ①` ; `§10.7.13 ⑦` |
| **plage active** ⏳ | les bornes du segment qu'on vient de cliquer sur la zone temporelle d'une card : tout ce que montre CETTE card s'y restreint (données, texte, plan, indicateurs). Un état d'affichage — rien n'est enregistré ni calculé ; calculer dessus est un geste explicite, qui en fait un segment nommé | `§10.7.13 ⑧ ⑨` |
| **contexte** ⏳ | ce dont dépend chaque vue : la sélection de CARDS de la page (tri, filtre, recherche par facettes déclarées) et la PLAGE active d'une card. Les vues suivent le contexte, elles ne se parlent pas | `§10.7.13 ⑩` |
| **composition / classement** ⏳ | deux imbrications à ne pas confondre : la composition est structurelle et enregistrée (une card dérivée de sa source) ; le classement est une VUE dynamique (grouper les passations par participant, groupe, scénario), jamais des lots imbriqués | `§10.7.13 ⑪` ; `WAMA_DATA_WORLD §13` |
| **échelle de couleur** ⏳ | les couleurs d'une zone temporelle se DÉCLARENT par piste, dans un vocabulaire commun : état (avancement seul), sévérité (trois niveaux), intensité (continue), catégorie ; masqué = hachuré, sélectionné = contour ; jamais la couleur seule | `§10.7.13 ⑭` |
| **partie** ⏳ | une card dérivée d'une autre : elle couvre un segment de sa source (une piste d'instrument tout le morceau, un plan un segment de son film) | `§10.7.9`, `§10.7.12` |
| **flux** ⏳ | ce qu'une card porte en parallèle sur son axe : vidéo, audio, signaux de données — de même nature, chacun avec son placement. La bande son d'un film est un flux, pas une card à côté | `§10.7.12 ③` |
| **emploi** ⏳ | un segment qui POINTE vers une card (un plan repris dans deux séquences) et porte sa propre coupe — une source, des pointages, jamais une copie. Décidé le 2026-11-25 : l'emploi ne porte QUE la coupe ; un traitement différent du même plan est une autre card | `§10.7.12 ②` ; `§10.7.14` (E5) |
| **zone temporelle** ⏳ | la ligne de temps d'une card, sous son aperçu : ses segments à leur place et à leur durée, niveaux superposés, la même partout (file, aperçu, page d'édition). Elle dit le CONTENU ; la barre de progression (d'une card, d'un lot) dit l'AVANCEMENT. Décidé le 2026-11-24 : la LIGNE COMPLÈTE (l'axe, toujours là, on y revient en désélectionnant) + UNE ligne segmentée (la piste principale déclarée) ; les autres lignes se déplient par un geste dédié ; la zone se zoome | `§10.7.12 ④` ; `§10.7.13 ⑬` ; `§10.7.14` |
| **piste dérivée** 🔄 | une piste source + la liste ordonnée des gestes faits dessus (scinder, fusionner, masquer…) : la source n'est jamais modifiée, la dérivée la remplace à l'affichage sur la même ligne. Scinder reste au même niveau ; créer un niveau en dessous (sous-segments) est un autre geste. ✅ le rejeu par le lecteur commun (`read_derived`, 2026-11-25) : un geste désigne sa cible par sa PLACE (comme une correction de détection), il survit à une piste remesurée et dit quand sa marque a bougé ou disparu ; ⏳ où se range la liste, et l'interface. ⚠ Ne pas dire « dérivée » d'une piste CALCULÉE d'une autre (les tours de parole, suites de phrases d'un locuteur) | `§10.7.14 ⑰` ; `wama/common/catalog/marks.py` |
| **ligne effective** ✅ | ce qui reste d'une piste après ses masques : les marques gardées, dans l'ordre de la piste, chaque segment à sa place une fois les masques retirés (`effective_line`) — ce que lit un aperçu à travers une coupe | `§10.7.14` ①ter ; `wama/common/catalog/marks.py` |
| **coupe** ⏳ | la piste dérivée qui dit ce qu'une card GARDE de son fichier d'entrée (segments gardés, masqués, réordonnés) : le média est découpé virtuellement, l'aperçu lit à travers, le traitement reçoit l'entrée telle que coupée, le fichier n'est jamais modifié. Décidé le 2026-11-25 : elle se range dans la table commune des entrées | `§10.7.14 ⑱` ; `INPUT_MODEL_MATCHING §6.13` |
| **geste de segment** ⏳ | déplacer, changer une borne, scinder, fusionner, masquer, supprimer, étiqueter — chaque piste DÉCLARE ceux qu'elle permet (un segment mesuré du monde Data ne se déplace ni ne se supprime) | `§10.7.12 ⑤` |
| **loi d'agencement** ⏳ | comment les parties se placent dans leur parent : en parallèle (les pistes d'un morceau) ou en série (les plans d'une séquence, l'ordre faisant le montage) | `§10.7.3 ③` |
| **axe** ✅ / ⏳ | une coordonnée qui ne fait qu'avancer. ✅ l'axe du temps, seule horloge de la lecture (`wama-axis.js`) ; ⏳ d'autres axes (distance, texte, page, image). ⚠ À ne pas confondre avec un AXE DU PLAN d'expérience du monde Data (participant, groupe, scénario) : une dimension de classement, pas une coordonnée qui avance | `WAMA_APP_GENERATION_ROUTE.md §F3b` ; `§10.7.10` ; `WAMA_DATA_WORLD §13.0` |
| **placement** ⏳ | la place d'un axe dans un autre : un décalage, une vitesse, ou des repères par morceaux | `§10.7.3 ⑤` |
| **événement** ✅ | une marque à un instant (`time`) | `wama/common/catalog/data_types.py` ; `WAMA_DATA_WORLD §9ter` |
| **segment** ✅ | une marque sur un intervalle (`start`, `end`, fin absente = segment ouvert). Le mot du MODÈLE ; l'écran dit situation, état, phrase, plan… | `wama/common/catalog/data_types.py:20-42` ; `WAMA_DATA_WORLD §9ter` |
| **plage** | PAS un concept de plus : les deux bornes d'un segment (et le nom du type natif de PostgreSQL). L'objet s'appelle toujours un segment | `§10.7.3 ⑤` |
| **piste** ✅ | un ensemble nommé de marques de même niveau sur un axe (les phrases d'une transcription, les situations d'un essai) ; une piste peut avoir une piste parente (partition ou inclusion). Une app DÉCLARE les siennes (registre `tracks`), un fichier de données DIT les siennes ; un seul lecteur les rend | `wama/common/catalog/marks.py`, `wama_data/frames.py` ; `§10.7.3 ⑤`, `§10.7.6` |
| **rôle** ⏳ | ce qu'un segment EST pour l'utilisateur (mot, phrase, plan, situation, masque) — déclaré, jamais un type de plus | `§10.7.3 ⑤ ⑥` |
| **fragment / masque** ⏳ | « fragment » n'est qu'un mot pour un petit segment : aucun geste ne lui est propre. MASQUER est un geste de segment : le retirer virtuellement, par ses bornes, de façon réversible — la source n'est jamais modifiée | `§10.7.12 ⑤`, `§10.7.9` |
| **zone** ✅ / ⏳ | une région en deux dimensions (boîte, polygone). PAS un segment : « segmentation » d'image et segment de temps sont deux choses | `data_types.py:35-40` ; `§10.7.10` |
| **Segmenter** ✅ / ⏳ | ✅ la bibliothèque de fonctions qui produit et combine des segments (monde Data) ; ⏳ universel par son modèle, ses producteurs restant propres à chaque monde | `WAMA_DATA_WORLD §9ter`, `§11.9` ; `§10.7.3 ⑨` |
