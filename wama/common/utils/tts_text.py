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

Les entrées, les suivantes étant des étapes de la première (publiques parce qu'un appelant
peut vouloir l'une sans le nettoyage, ex. un texte déjà propre) :
  • `text_for_speech(text)` — la chaîne complète, dans l'ordre ;
  • `make_audible(text)`    — la mise en forme visuelle traduite en respirations ;
  • `say_incises` / `say_emphasis` — parenthèses dites en incises, emphase et lexique (18/10) ;
  • `pause_segments(text, sentence_pause, clause_pause)` — où la voix respire, et combien :
    le RÉGLAGE des pauses (`assistant/params.py`), appliqué par le moteur (18/10).
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
#: ⚠⚠ ELLE SE REMPLACE, ELLE NE S'EFFACE PAS — mesuré le 2026-09-26 par un smoke réel sur le
#: serveur relancé, et c'est un défaut que les gardes ne voyaient pas : elles vérifiaient
#: l'ABSENCE de l'adresse, jamais que la phrase restait dicible. « Écrivez à contact@… ou
#: https://… » devenait **« Écrivez a ou. »** — une phrase qui ne dit plus rien, lue telle
#: quelle à voix haute.
#: *Vérifier qu'une chose a disparu ne dit pas ce qui reste à sa place.* Même principe que le
#: contrôle de source des liens : on DIT le retrait, on ne l'efface pas en silence.
_URL = re.compile(r'https?://\S+|www\.\S+')
_EMAIL = re.compile(r'\S+@\S+\.\w+')
#: Ce que la voix dit à la place. L'auditeur a le texte sous les yeux : nommer la NATURE de ce
#: qui a été retiré lui suffit pour le retrouver.
_URL_SPOKEN = 'un lien'
_EMAIL_SPOKEN = 'une adresse électronique'

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

#: Un BLOC de code se signale, il ne se lit pas (`` ``` `` … `` ``` ``). Règle portée du nettoyage
#: qu'écrivait le navigateur (`wama-assistant-voice.js`, retiré le 2026-10-18) : le serveur était
#: l'autre moitié d'un même domaine, la voix de l'assistant passait par les DEUX.
_CODE_BLOCK = re.compile(r'```.*?```', re.S)
_CODE_BLOCK_SPOKEN = 'bloc de code.'

#: Le tiret bas d'un identifiant se dit comme une ESPACE (`instant_preview` → « instant
#: preview »). Retiré tel quel avec les marqueurs Markdown, il collait les deux mots : entendu
#: « instant-travilleux » (aller-retour voix → transcription du 2026-10-18). Entre deux lettres
#: ou chiffres seulement — un `_` d'italique Markdown, lui, est collé à un seul mot.
_IDENTIFIER_UNDERSCORE = re.compile(r'(?<=[^\W_])_(?=[^\W_])')

#: Une PARENTHÈSE est une incise : on la DIT comme une incise, entre deux virgules — la seule
#: ponctuation intérieure qui fasse respirer Kokoro (`kokoro_onnx` ne compte que `,;:` et
#: `.!?…`). Mesuré le 2026-10-18 : « Le chat (gris et blanc) dort » est entendu « Le chat gris
#: est blanc d'or », « Le chat, gris et blanc, dort » mot pour mot. Les crochets d'un texte (un
#: lien Markdown est déjà réduit à son libellé, plus haut) se disent pareil.
#: Le pluriel facultatif COLLÉ (« fichier(s) », « un(e) ») n'est pas une incise : il se fond.
_GLUED_OPTIONAL = re.compile(r'(?<=[^\W\d_])[(\[]([^\W\d_]{1,3})[)\]]')
_OPEN_INCISE = re.compile(r'[ \t]*[(\[][ \t]*')
_CLOSE_INCISE = re.compile(r'[ \t]*[)\]]')
#: Ponctuation REDOUBLÉE par les réécritures (« …dort (vraiment). » → « …dort, vraiment,. ») :
#: la marque la plus forte l'emporte, une virgule en tête de ligne s'efface.
_DOUBLED_PUNCT = re.compile(r',\s*(?=[.,;:!?…])')
_LEADING_COMMA = re.compile(r'^[ \t]*,[ \t]*', re.M)
#: …et une incise qui FERME la ligne ne laisse rien : une virgule y priverait la ligne du point
#: que `make_audible` lui donne — la pause de fin la plus longue. Seule la fermante réécrite est
#: visée : une virgule écrite en fin de ligne par l'auteur reste la sienne.
_CLOSE_AT_LINE_END = re.compile(r'[ \t]*[)\]][ \t]*$', re.M)

#: Mots COURTS que espeak-ng ÉPELLE quand ils sont écrits en MAJUSCULES — l'emphase des docs
#: de WAMA, que l'assistant reprend (« ce n'est PAS UNE erreur »). Mesuré le 2026-10-18 en
#: phonémisant chaque mot en majuscules puis en minuscules : « UNE », « UN », « MOT », « CE »,
#: « DIT », « NE » épelés ; « PAS », « TOUT », « RIEN », « JAMAIS », « TOUJOURS » lus. Une
#: liste FERMÉE de mots courants plutôt qu'une règle de longueur : un SIGLE inconnu mis en
#: minuscules se lirait comme un mot (« RAG » → « rag »), pire que l'emphase épelée.
_SHORT_EMPHASIS_WORDS = frozenset("""
    un une le la les de des du au aux ce ces cet cette se sa son ses ne ni et ou où on il ils
    elle je tu me te nous vous que qui quoi dont mot mots dit fait est sont a ai as pas plus peu
    non oui si tout tous rien seul sans avec pour par sur sous dans en lui leur mon ton ma ta mes
    tes nos vos car mais donc or bien mal très trop deux une ici là va vont doit être été
""".split())
_LETTER_WORD = re.compile(r'\b[^\W\d_]{2,}\b')

#: Ce qui se PRONONCE autrement que ça ne s'écrit — un LEXIQUE, déclaré ici et nulle part
#: ailleurs (le moteur, lui, dit « c'est l'affaire d'un lexique », `kokoro_onnx_backend`).
#: « WAMA » est lu à l'anglaise par espeak quelle que soit sa casse (`wˈɑːmə`, entendu « WAM ») ;
#: « Ouama » donne la lecture française (`wamˈa`). Mot ENTIER, casse exacte.
SPOKEN_FORMS = {'WAMA': 'Ouama'}
_SPOKEN_FORM = re.compile(r'\b(' + '|'.join(map(re.escape, SPOKEN_FORMS)) + r')\b')

#: Marques après lesquelles la voix RESPIRE — le vocabulaire même de `kokoro_onnx`
#: (`chunker.SENTENCE_MARKS` / `CLAUSE_MARKS`) : fin de phrase, et fin de proposition (où
#: arrivent aussi parenthèses et tirets d'incise, réécrits en virgules ci-dessus).
SENTENCE_MARKS = '.!?…'
CLAUSE_MARKS = ',;:'
_PAUSE_AFTER = re.compile(r'(?<=[' + re.escape(SENTENCE_MARKS + CLAUSE_MARKS) + r'])\s+')


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


def say_incises(text: str) -> str:
    """Parenthèses et crochets dits comme des INCISES — entre deux virgules (voir
    `_OPEN_INCISE`). Le pluriel facultatif collé se fond ; la ponctuation redoublée se résout."""
    text = _GLUED_OPTIONAL.sub(r'\1', text)
    text = _OPEN_INCISE.sub(', ', text)
    text = _CLOSE_AT_LINE_END.sub('', text)
    text = _CLOSE_INCISE.sub(',', text)
    text = _DOUBLED_PUNCT.sub('', text)
    return _LEADING_COMMA.sub('', text)


def say_emphasis(text: str) -> str:
    """Les mots courts d'EMPHASE en majuscules (`_SHORT_EMPHASIS_WORDS`) passent en minuscules ;
    tout autre mot en majuscules — un sigle — est laissé tel quel, puis le LEXIQUE s'applique."""
    def lower(match):
        word = match.group(0)
        if not (word.isupper() and word.lower() in _SHORT_EMPHASIS_WORDS):
            return word
        before = match.string[:match.start()].rstrip()
        # En tête de phrase, la majuscule initiale reste : « CE n'est » → « Ce n'est ».
        return word.capitalize() if not before or before[-1] in SENTENCE_MARKS + '\n' else word.lower()
    text = _LETTER_WORD.sub(lower, text)
    return _SPOKEN_FORM.sub(lambda m: SPOKEN_FORMS[m.group(1)], text)


def pause_segments(text: str, sentence_pause: float = 0.0, clause_pause: float = 0.0) -> list:
    """Le texte À DIRE découpé là où la voix doit RESPIRER : `[(segment, pause en s), …]`.

    POURQUOI ICI, et pas dans le moteur (2026-10-18) : `kokoro_onnx` sait allonger la pause après
    chaque marque, mais seulement avec un modèle qui rend la DURÉE de ses phonèmes — celui de WAMA
    ne la rend pas (`has_timings` faux, mesuré : 3,58 s de son avec des pauses de 0, 0,25 ou 0,8 s).
    Le moteur synthétise donc chaque segment et pose le silence demandé entre eux ; où couper est
    une question de TEXTE, d'où sa place dans cette brique, pour tout moteur qui voudra l'adopter.

    Une pause nulle ne coupe pas : avec les deux à 0, le texte reste d'un seul tenant (le
    comportement d'avant). La marque reste collée au segment qu'elle termine — le moteur la
    prononce, c'est elle qui lui donne l'intonation de fin."""
    sentence_pause = max(0.0, float(sentence_pause or 0))
    clause_pause = max(0.0, float(clause_pause or 0))
    text = (text or '').strip()
    if not text:
        return []
    if not (sentence_pause or clause_pause):
        return [(text, 0.0)]
    segments, start = [], 0
    for match in _PAUSE_AFTER.finditer(text):
        mark = text[match.start() - 1]
        pause = sentence_pause if mark in SENTENCE_MARKS else clause_pause
        if not pause:
            continue
        segments.append((text[start:match.start()], pause))
        start = match.end()
    segments.append((text[start:], 0.0))
    return [(s.strip(), p) for s, p in segments if s.strip()]


def text_for_speech(text: str) -> str:
    """Prépare un texte pour la synthèse vocale : la TTS doit LIRE, pas décrire.

    L'ORDRE compte et chaque place se justifie :
      1. NFC          — les accents deviennent des codepoints uniques, donc à l'abri du (3) ;
      2. flèches      — avant (3), qui les ferait disparaître sans laisser de pause ;
      3. pictogrammes — sinon espeak verbalise leur nom Unicode ;
      4. Markdown     — le libellé d'un lien survit, son adresse non ;
      5. URL/e-mails  — après (4), pour ne pas décapiter un lien de son libellé. REMPLACÉS par
                        un mot, jamais effacés : sinon la phrase porteuse devient indicible ;
      6. incises      — après (4) et (5) : un lien et une adresse ont leurs propres parenthèses ;
      7. emphase      — les mots courts en majuscules, puis le lexique ;
      8. respirations — en dernier : elle raisonne LIGNE PAR LIGNE, donc après tout ce qui
                        peut vider ou fusionner une ligne.
    Le bloc de code part EN PREMIER (0) : tout ce qu'il contient serait sinon nettoyé, puis lu.
    """
    if not text:
        return '' if text is None else text
    text = unicodedata.normalize('NFC', text)
    text = _CODE_BLOCK.sub(f' {_CODE_BLOCK_SPOKEN} ', text)
    # Caractères de contrôle, sauf ceux qui portent la mise en page.
    text = ''.join(c for c in text if ord(c) >= 32 or c in '\n\r\t')
    text = _ARROWS_AND_BULLETS.sub(', ', text)
    text = ''.join(c for c in text
                   if unicodedata.category(c) not in _PICTO_CATEGORIES
                   and c not in _EMOJI_EXTRA)
    text = _MARKDOWN_LINK.sub(r'\1', text)
    text = _TABLE_SEPARATOR.sub('', text)
    text = text.replace('|', ' ')
    text = _IDENTIFIER_UNDERSCORE.sub(' ', text)
    text = _MARKDOWN_MARKERS.sub('', text)
    text = _EMAIL.sub(_EMAIL_SPOKEN, text)
    text = _URL.sub(_URL_SPOKEN, text)
    text = say_incises(text)
    text = say_emphasis(text)
    text = make_audible(text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
