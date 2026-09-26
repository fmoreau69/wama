"""
Le texte À DIRE — brique commune de préparation d'un texte pour la synthèse vocale.

POURQUOI UNE BRIQUE, et pas une fonction de vue (Fabien, 2026-09-26 : « il faut une brique
commune complète qui conserve bien les améliorations pour la vocalisation »). Le domaine était
écrit DEUX FOIS, sous le MÊME NOM, avec deux comportements disjoints — relevé le jour même :

| où                                              | appelants | ce qu'il faisait                        |
|-------------------------------------------------|-----------|-----------------------------------------|
| `wama/views.py::_clean_text_for_tts`            | 1         | emojis, Markdown, flèches, RESPIRATIONS |
| `synthesizer/utils/text_extractor.py` (même nom)| 6         | URL, e-mails, espaces                   |

Aucun des deux n'était faux ; ensemble ils faisaient un demi-vocabulaire. Le synthesizer, qui
lit des DOCUMENTS à voix haute, n'avait ni retrait d'emoji ni pause de fin de ligne — les deux
améliorations mesurées sur l'assistant. L'assistant, lui, lisait les URL à voix haute.
⚠ Et le nom dupliqué est ce qui rendait la chose invisible : un `grep clean_text_for_tts`
renvoyait sept résultats qui semblaient parler de la même fonction.

CE QUE CE MODULE NE FAIT PAS : il ne reformule pas et ne traduit pas. Il rend AUDIBLE ce que
l'œil lisait dans la disposition. Toute règle ici se justifie par un défaut ENTENDU, pas par
une préférence de style — et chacune porte sa date.

Deux entrées, la seconde étant une étape de la première (elle est publique parce qu'un appelant
peut vouloir la respiration sans le nettoyage, ex. un texte déjà propre) :
  • `text_for_speech(text)` — la chaîne complète, dans l'ordre ;
  • `make_audible(text)`    — la mise en forme visuelle traduite en respirations.
"""
import re
import unicodedata

#: ZWJ, sélecteurs de variation VS15/VS16, combinateur de keycap. Ils n'ont pas de catégorie
#: Unicode qui les trie avec les pictogrammes, et espeak les verbalise.
_EMOJI_EXTRA = {'‍', '︎', '️', '⃣'}

#: Catégories Unicode des pictogrammes et modificateurs à retirer. ⚠ Les accents français
#: (Mn) n'y sont PAS : après une normalisation NFC ils sont des codepoints uniques (Ll/Lu),
#: donc intacts. C'est la normalisation qui protège le français, pas la liste.
_PICTO_CATEGORIES = ('So', 'Sk', 'Cs', 'Me')

#: Flèches et puces → virgule (une pause). AVANT le retrait des symboles, sinon la flèche
#: disparaît et « Anonymisation → Masque » se lit d'un trait.
_ARROWS_AND_BULLETS = re.compile(r'\s*[→⇒➜➔↦⇨▶►▸‣•◦∙]\s*')

#: Ponctuation qui porte DÉJÀ une respiration — ne pas en ajouter une seconde.
#: ⚠ `)`, `»` et les guillemets en sont VOLONTAIREMENT absents : ils ferment une incise, ils ne
#: terminent pas une phrase. « …nettoyage vocal) » s'enchaînait donc sur l'item suivant — le
#: défaut même qu'on corrige. On ponctue APRÈS la fermeture : « …nettoyage vocal). »
_PUNCTUATED_END = '.,;:!?…'

#: Ce qui ne se DIT pas : une adresse lue caractère par caractère est du bruit, dans les deux
#: surfaces. Le libellé d'un lien Markdown, lui, est conservé (il est retiré plus tôt, par
#: `_MARKDOWN_LINK`) — on perd l'adresse, jamais le sens de la phrase.
_URL = re.compile(r'https?://\S+|www\.\S+')
_EMAIL = re.compile(r'\S+@\S+\.\w+')

_MARKDOWN_LINK = re.compile(r'\[([^\]]+)\]\([^)]+\)')
_TABLE_SEPARATOR = re.compile(r'^[ \t]*\|?[ \t:|-]{3,}\|?[ \t]*$', re.M)
_MARKDOWN_MARKERS = re.compile(r'[#*`_>~]')
_LEADING_BULLET = re.compile(r'^[-*•·–—]+\s+')

#: Tiret ISOLÉ en incise (« via Celery - vous recevrez ») → virgule : espeak le prononce
#: « moins » ou l'avale, alors qu'il porte visuellement une respiration. Le tiret COLLÉ d'un mot
#: composé (« arrière-plan ») n'est pas touché — c'est l'ESPACEMENT qui distingue les deux.
#: ⚠ Sur `[ \t]` SEULEMENT, et LIGNE PAR LIGNE : écrit `\s+` et appliqué au texte entier, il
#: traversait les sauts de ligne et fusionnait toute une liste en une phrase (mesuré au test —
#: la « correction » était pire que le défaut). Une classe d'espaces qui inclut `\n` n'a rien à
#: faire dans une règle qui raisonne sur la ligne.
_DASH_INCISE = re.compile(r'(?<=\S)[ \t]+[-–—][ \t]+(?=\S)')

_AMPERSAND = re.compile(r'(?<=[\w])\s*&\s*(?=[\w])')
#: `/` entre deux MOTS seulement : préserve les dates, les fractions et les chemins résiduels.
_SLASH_BETWEEN_WORDS = re.compile(r'(?<=[^\W\d_])\s*/\s*(?=[^\W\d_])')


def make_audible(text: str) -> str:
    """Traduit la MISE EN FORME VISUELLE en respirations audibles.

    Le nettoyage rend le texte *prononçable* (plus d'emoji verbalisé, plus de tuyaux de
    tableau) ; il ne le rend pas *écoutable*. Une liste à puces reste une succession de
    fragments SANS ponctuation : le moteur les enchaîne d'un trait et l'auditeur perd le fil
    (constaté par Fabien le 2026-08-31 sur le descriptif de WAMA lu par Kokoro — cinq sections,
    quinze items, aucune pause).

    ⚠ Le saut de ligne n'est PAS une pause pour un moteur TTS : ni Kokoro (espeak/misaki) ni
    XTTS n'en font une — seule la PONCTUATION en produit une. C'est tout le sujet.

    Quatre gestes, tous réversibles à la lecture : puce de tête retirée (« - » se prononce
    « moins ») ; fin de ligne non ponctuée → point, LA pause qui manquait ; « / » entre deux
    mots → « ou » ; « & » → « et » ; tiret d'incise → virgule.
    Une ligne déjà ponctuée (dont un titre en « : ») est laissée intacte.
    """
    text = _AMPERSAND.sub(' et ', text)
    text = _SLASH_BETWEEN_WORDS.sub(' ou ', text)

    lines = []
    for line in text.split('\n'):
        bare = line.strip()
        if not bare:
            lines.append('')
            continue
        bare = _LEADING_BULLET.sub('', bare).strip()
        bare = _DASH_INCISE.sub(', ', bare)
        if bare and bare[-1] not in _PUNCTUATED_END:
            bare += '.'
        lines.append(bare)
    return '\n'.join(lines)


def text_for_speech(text: str) -> str:
    """Prépare un texte pour la synthèse vocale : la TTS doit LIRE, pas décrire.

    L'ORDRE compte et chaque place se justifie :
      1. NFC          — les accents deviennent des codepoints uniques, donc à l'abri du (3) ;
      2. flèches      — avant (3), qui les ferait disparaître sans laisser de pause ;
      3. pictogrammes — sinon espeak verbalise leur nom Unicode ;
      4. Markdown     — le libellé d'un lien survit, son adresse non ;
      5. URL/e-mails  — après (4), pour ne pas décapiter un lien de son libellé ;
      6. respirations — en dernier : elle raisonne LIGNE PAR LIGNE, donc après tout ce qui
                        peut vider ou fusionner une ligne.
    """
    if not text:
        return '' if text is None else text
    text = unicodedata.normalize('NFC', text)
    # Caractères de contrôle, sauf ceux qui portent la mise en page.
    text = ''.join(c for c in text if ord(c) >= 32 or c in '\n\r\t')
    text = _ARROWS_AND_BULLETS.sub(', ', text)
    text = ''.join(c for c in text
                   if unicodedata.category(c) not in _PICTO_CATEGORIES
                   and c not in _EMOJI_EXTRA)
    text = _MARKDOWN_LINK.sub(r'\1', text)
    text = _TABLE_SEPARATOR.sub('', text)
    text = text.replace('|', ' ')
    text = _MARKDOWN_MARKERS.sub('', text)
    text = _EMAIL.sub('', text)
    text = _URL.sub('', text)
    text = make_audible(text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
