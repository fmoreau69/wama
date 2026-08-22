"""
Le MOTEUR de WAMA Data — zéro Django, zéro UI, zéro état global.

Ce qui est ici se teste sans serveur, sans base et sans navigateur, et c'est délibéré : le
référentiel temporel, la segmentation et le codage sont des mécanismes de données, pas des écrans.
L'adaptation vers le catalogue (ports typés, `TypedFrame`) vit dans `wama_data/functions/`, ce qui
laisse ce noyau indépendant de pandas partout où c'est possible.

  - `temporal`     : le référentiel — aligne des flux à cadences incommensurables SANS jamais
                     interpoler ni rééchantillonner (§2-§3 de `WAMA_DATA_WORLD.md`).
  - `segmentation` : les 5 modes de production de `segments` — autour d'une ancre, jonction de deux
                     flux, condition avec hystérésis, plages d'un catégoriel, et le codage.
  - `coding`       : protocole déclaré + exécution — le modèle direct du codage vidéo par IA.
"""
