"""Nom du fichier de SORTIE — une règle unique pour toutes les apps.

POURQUOI (relevé du 2026-08-25, demande de Fabien)
    La convention EXISTE — l'anonymizer et l'enhancer écrivent tous deux
    `<entrée>_<process>_<modèle><ext>` — mais chaque app la réinvente, et deux familles
    coexistent sans être alignées à l'intérieur d'elles-mêmes :

      | app         | avant                                | famille |
      |-------------|--------------------------------------|---------|
      | anonymizer  | `{nom}_blurred_{modèle}{ext}`        | fichier |
      | enhancer    | `{nom}_enhanced_{modèle}{ext}`       | fichier |
      | converter   | dérive du `stem` d'entrée            | fichier |
      | imager      | `gen_{id}_{index}_{modèle}.png`      | prompt  |
      | composer    | `{modèle}_{uuid8}.wav`  ← ni id ni index | prompt |
      | synthesizer | `synthesis_{id}_…`                   | prompt  |
      | avatarizer  | `job{id}_{nom}.mp4`                  | fichier |

    Le mot de process y est écrit EN DUR (`blurred`, `enhanced`, `gen`), donc invisible à
    tout relevé et impossible à changer sans toucher chaque app.

LA RÈGLE
    • entrée = un FICHIER  → `<stem>_<process>_<modèle>[_<i>]<ext>`
      L'utilisateur retrouve SON nom, augmenté de ce qu'on lui a fait et avec quoi.
    • entrée = un PROMPT   → `<process><id>_<modèle>[_<i>]<ext>`
      Il n'y a pas de nom d'origine ; l'identifiant de card le remplace et garantit
      l'unicité dans un `output/` PLAT.
    • plusieurs fichiers pour une card → suffixe `_<i>` (1-based), et SEULEMENT alors.
      Cas réel : `imager.num_images` va de 1 à 4.

⚠ Le mot de process est DÉCLARÉ (`APP_CATALOG[app]['output_tag']`), pas écrit dans la tâche.
  À défaut, il se dérive du nom de l'app — de sorte qu'une app qui ne déclare rien obtienne
  quand même un nom correct, au lieu d'un trou silencieux.

⚠ `output/` est PLAT et le reste : c'est ce qui rend le téléchargement en masse et l'aperçu
  simples. C'est le NOM qui porte l'unicité, pas un sous-dossier par card — un sous-dossier
  par card est précisément ce qu'on a démonté le 2026-08-25 (`job_<id>/`, 1,7 Go
  d'intermédiaires).
"""
import os
import re
import unicodedata

#: Mots de process par défaut quand l'app n'en déclare pas. Dérivés du VERBE de l'app, pas
#: de son nom : l'utilisateur lit ce qu'on a fait à son fichier, pas quel outil l'a fait.
_TAGS_PAR_DEFAUT = {
    'anonymizer': 'blurred',      # graphie HISTORIQUE conservée — cf. avertissement plus bas
    'enhancer': 'enhanced',       # idem
    'converter': 'converted',
    'converter_01': 'converted',
    'avatarizer': 'avatar',
    'imager': 'gen',
    'composer': 'audio',
    'synthesizer': 'voice',
}

#: Longueur max du nom produit (hors extension). Bien en deçà des 255 usuels : le nom passe
#: aussi dans des URL, des en-têtes `Content-Disposition` et des chemins déjà profonds.
_MAX = 120


def _nettoyer(valeur: str, *, defaut: str = 'x') -> str:
    """Assainit un fragment TECHNIQUE (modèle, tag) : ASCII strict, rien qui casse un chemin."""
    if not valeur:
        return defaut
    # Un identifiant de modèle est souvent un chemin HF (`Shakker-Labs/FLUX.1-dev-LoRA`) :
    # on ne garde que la feuille, sinon le `/` créerait un sous-dossier fantôme.
    valeur = str(valeur).replace('\\', '/').split('/')[-1]
    valeur = unicodedata.normalize('NFKD', valeur).encode('ascii', 'ignore').decode('ascii')
    valeur = re.sub(r'[^A-Za-z0-9._-]+', '-', valeur).strip('-._')
    return valeur or defaut


def _souche_utilisateur(valeur: str, *, defaut: str = 'fichier') -> str:
    """Souche du nom D'ORIGINE — PRÉSERVÉE, accents et espaces compris.

    ⚠ Décision du 2026-08-25, après une première version qui l'assainissait comme un fragment
    technique : « Réunion équipe.mp4 » y devenait « Reunion-equipe… ». La règle de la famille
    FICHIER est que **l'utilisateur retrouve SON nom** ; le normaliser le lui reprend, et sur
    un labo francophone ce n'est pas un cas limite mais le cas courant. L'ancien code le
    préservait depuis toujours sans incident, et le stockage Django assainit déjà à l'écriture.

    On ne retire donc que ce qui casserait un chemin : séparateurs, caractères de contrôle,
    et les caractères interdits par Windows.
    """
    if not valeur:
        return defaut
    valeur = str(valeur).replace('\\', '/').split('/')[-1]
    valeur = re.sub(r'[\x00-\x1f<>:"|?*]+', '', valeur).strip(' .')
    return valeur or defaut


def output_tag(app: str) -> str:
    """Mot de process de l'app : déclaré dans `APP_CATALOG`, sinon table de repli, sinon l'app."""
    try:
        from wama.common.app_registry import APP_CATALOG
        declare = (APP_CATALOG.get(app) or {}).get('output_tag')
        if declare:
            return _nettoyer(declare)
    except Exception:
        pass
    return _TAGS_PAR_DEFAUT.get(app, _nettoyer(app))


def compose_output_name(*, app: str, model: str = '', ext: str = '',
                        source_name: str = '', item_id=None,
                        index: int = None, total: int = 1) -> str:
    """Compose le nom du fichier de sortie. Rend un NOM, jamais un chemin.

    `source_name` fourni  → famille FICHIER (`<stem>_<tag>_<modèle>…`)
    sinon `item_id`       → famille PROMPT  (`<tag><id>_<modèle>…`)

    `index`/`total` : suffixe `_<i>` uniquement si la card produit plusieurs fichiers.
    `ext` : avec ou sans point ; déduite de `source_name` si absente.
    """
    tag = output_tag(app)
    modele = _nettoyer(model, defaut='') if model else ''

    if source_name:
        souche, ext_source = os.path.splitext(os.path.basename(str(source_name)))
        souche = _souche_utilisateur(souche)
        ext = ext or ext_source
        # ⚠ L'identifiant est FACULTATIF dans cette famille, et c'est délibéré. Le plus souvent
        # la souche suffit à l'unicité : le fichier d'entrée porte déjà un nom unique donné par
        # le stockage Django à l'upload (constat écrit dans `enhancer/tasks.py:398`). Mais ce
        # n'est PAS vrai quand l'entrée vient d'un dossier MONTÉ (converter), où deux jobs sur
        # le même fichier produiraient le même nom — le converter s'en protégeait avec un
        # HORODATAGE, unique mais muet. L'identifiant de card dit la même chose en désignant
        # la card, et c'est le même mécanisme que la famille PROMPT : une seule règle.
        morceaux = [souche, tag] + ([modele] if modele else [])
        if item_id is not None:
            morceaux.append(str(item_id))
    else:
        # ⚠ Sans identifiant, deux cards du même modèle produiraient le MÊME nom : Django en
        # renommerait une (`_c5e24b5d`) et le lien affiché deviendrait faux. C'est le défaut
        # que `composer` porte encore avec son uuid — unique, mais illisible et non rattaché.
        morceaux = [f"{tag}{item_id}" if item_id is not None else tag]
        if modele:
            morceaux.append(modele)

    if total and total > 1 and index is not None:
        morceaux.append(str(index))

    nom = '_'.join(m for m in morceaux if m)[:_MAX]
    if not ext:
        return nom
    return nom + (ext if ext.startswith('.') else '.' + ext)
