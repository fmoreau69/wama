"""Le PIPELINE de l'anonymizer — ses process internes, déclarés au catalogue commun.

`WAMA_APP_GENERATION_ROUTE.md §10.6`, marche P6 (2026-10-03) : décision n°11 — un registre de
process en code, chaque process un `FunctionSpec binding: app`, le registre exporté en manifeste
`pipeline`. `load_all()` importe ce module ; `tasks.py` en lit `PIPELINE`.

TROIS process (2026-10-04, décision de Fabien : « on sépare détection/segmentation et
floutage ») :
  • `detect` — « Détection » : le média → ses DÉTECTIONS (document `detections`, type de donnée
    commun) — choix du ou des modèles (couverture des classes), YOLO ou SAM3, boîtes et contours.
    C'est le process coûteux (GPU, la durée d'une vidéo).
  • `blur`   — « Floutage » : le média réécrit depuis ses détections — intensité, contour
    progressif, agrandissement de la zone, interpolation des trous d'une piste. Aucun modèle.
  • `output` — le format et la qualité de sortie (process COMMUN, `output_process`) : le
    fichier flouté d'origine est gardé tant que la sortie le transforme.

Et, pour un DOCUMENT (2026-11-02, domaine `document`, ROADMAP §16.4bis), TROIS autres, réservés à
son domaine (`ProcessSpec.applies`, comme ceux du dessus le sont à l'image et à la vidéo) :
  • `ocr`         — « OCR des scans et des images » : le process COMMUN (`ocr_process`), optionnel ;
  • `detect_text` — les données personnelles du texte (`common/privacy`), lignes de l'OCR comprises ;
  • `occult_text` — le document réécrit sur place, passages remplacés par leur libellé.

Ce que la séparation apporte : changer l'intensité du flou ou l'interpolation ne redétecte plus ;
changer le format ne re-floute plus ; et l'aperçu peut montrer les détections à côté du flou.
"""
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.services.output_process import output_spec
from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline

_APP = 'anonymizer'
_IMPL = 'anonymizer.tasks:process_single_media'

register(FunctionSpec(
    key='anonymizer.detect', name='Anonymizer — détecter',
    description="Détecte, dans une image ou une vidéo, les classes désignées (visages, plaques…) "
                "ou ce qu'une description nomme, avec le ou les modèles qui les couvrent : boîtes, "
                "contours (segmentation) et pistes, frame par frame.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['image', 'video', 'detection', 'gpu'],
    inputs=[PortSpec('work_media', 'video', description="L'image ou la vidéo à anonymiser.")],
    outputs=[PortSpec('detections', 'detections',
                      description="Les objets détectés, frame par frame (boîte, contour, piste).")]))

register(FunctionSpec(
    key='anonymizer.blur', name='Anonymizer — flouter',
    description="Floute le média selon ses détections : au contour quand elles en portent un, au "
                "rectangle sinon, trous d'une piste interpolés. Aucun modèle n'est chargé.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['image', 'video', 'blur'],
    inputs=[PortSpec('work_media', 'video', description="L'image ou la vidéo à anonymiser."),
            PortSpec('detections', 'detections', description="Ce qu'il faut flouter.")],
    outputs=[PortSpec('native', 'video', description="Le média flouté, tel que le floutage "
                                                     "l'écrit.")]))

register(FunctionSpec(
    key='anonymizer.output', name='Anonymizer — réglages de sortie',
    description="Applique le format et la qualité de sortie de la card au média flouté. Garde le "
                "fichier d'origine tant que la sortie le transforme, pour se rejouer sans re-flouter.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['image', 'video', 'format'],
    inputs=[PortSpec('native', 'video', description="Le média flouté d'origine.")],
    outputs=[PortSpec('result', 'video', description="Le média flouté au format demandé.")]))


# ── Domaine DOCUMENT (2026-11-02, ROADMAP §16.4bis) — trois process, la forme d'origine gardée ──
# L'OCR est le process COMMUN (`ocr_process`, celui du Translator) ; détecter et occulter passent par
# la brique de confidentialité (`common/privacy` : Presidio orchestre l'union des détecteurs
# installés) sur la couche texte commune (`document_text`), les lignes de l'OCR comprises.
register(FunctionSpec(
    key='anonymizer.ocr', name='Anonymizer — OCR des scans et des images',
    description="Lit par OCR les pages d'un PDF qui n'ont pas de couche texte et le texte dessiné "
                "dans les images de ses pages natives, en gardant la PLACE de chaque mot ; les "
                "lignes sont gardées sur la card pour que la détection les lise et que "
                "l'occultation les efface à leur place. Brique commune : "
                "`common/services/ocr_process.ocr_step`.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['document', 'ocr', 'gpu'],
    inputs=[PortSpec('work_file', 'document', description="Le document déposé : seules ses pages "
                                                          "sans couche texte et ses images sont lues.")],
    outputs=[PortSpec('read_lines', 'document',
                      description="Les lignes lues, avec la place de chaque mot (JSON sur la card) : "
                                  "la détection les lit avec le document.")]))

register(FunctionSpec(
    key='anonymizer.detect_text', name='Anonymizer — détecter les données personnelles',
    description="Détecte les données personnelles d'un document (noms, adresses, courriels, "
                "téléphones, identifiants…) : Presidio orchestre les motifs et les modèles "
                "installés (`common/privacy`) sur la couche texte du document, les lignes de "
                "l'OCR comprises. Rend un document de détections en forme texte (passages).",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['document', 'pii', 'nlp'],
    inputs=[PortSpec('work_file', 'document', description="Le document (PDF, DOCX).")],
    outputs=[PortSpec('detections', 'detections',
                      description="Les passages détectés, segment par segment (page, paragraphe).")]))

register(FunctionSpec(
    key='anonymizer.occult_text', name='Anonymizer — occulter les données personnelles',
    description="Réécrit le document sur place, chaque passage détecté (et corrigé) remplacé par "
                "son libellé (`[PERSONNE]`…) — sa forme d'origine gardée ; sur un scan, les "
                "pixels du passage sont effacés. Relit le fichier produit et dit ce qui y reste. "
                "Aucun modèle n'est chargé.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['document', 'pii'],
    inputs=[PortSpec('work_file', 'document', description="Le document d'origine."),
            PortSpec('detections', 'detections', description="Ce qu'il faut occulter.")],
    outputs=[PortSpec('result', 'document', description="Le document occulté, dans son format "
                                                        "et sa forme d'origine.")]))


def _is_document(media, _model_key=None) -> bool:
    """Le média est-il du domaine DOCUMENT (`app_modes.element_domain`, la nature que la spec de
    détail lit) ? `ProcessSpec.applies` : les process d'un domaine n'ont lieu que pour lui."""
    from wama.common.utils.app_modes import element_domain
    return element_domain(media) == 'document'


def _is_image_or_video(media, _model_key=None) -> bool:
    return not _is_document(media)


#: Ce que la DÉTECTION surveille HORS schéma : le fichier et les classes (liste éditée à part).
#: Les RÉGLAGES déclarent eux-mêmes ce qu'ils périment (`Param.stales`, params.py, 2026-10-05) —
#: détection : mode, prompt SAM3, modèle, curseur, segmentation, seuil ; floutage : flou, bords,
#: zone, flou progressif, interpolation. `PIPELINE.watched_of(spec)` réunit les deux. Les réglages
#: d'AFFICHAGE (`show_*`) ne périment rien : ils ne changent que l'aperçu (`stales=()`).
DETECT_WATCHED = ('file', 'classes2blur')
#: Les corrections humaines (2026-10-10) : les modifier rend le floutage périmé, jamais la
#: détection — corriger ne redétecte rien.
BLUR_WATCHED = ('detection_corrections',)

from wama.common.services.ocr_process import OCR_KEY, OCR_LABEL  # noqa: E402

PIPELINE = register_app_pipeline(_APP, (
    ProcessSpec('detect', label='Détection', watched=DETECT_WATCHED, gpu=True, share=7,
                outputs=('detections_file',), eta='anonymizer.tasks:anonymizer_eta_key_size',
                applies=_is_image_or_video),
    ProcessSpec('blur', label='Floutage', depends_on=('detect',), watched=BLUR_WATCHED, share=3,
                outputs=('output_file',), eta='anonymizer.tasks:blur_eta',
                applies=_is_image_or_video),
    output_spec(depends_on=('blur',), applies=_is_image_or_video),
    # Domaine document : chacun n'a lieu que pour un document (`applies`). L'OCR est OPTIONNEL,
    # à interrupteur — le fichier propose sa valeur (`Param.default_from`, `needs_ocr`).
    ProcessSpec(OCR_KEY, label=OCR_LABEL, watched=('file',), degree='optional', gpu=True, share=2,
                outputs=('ocr_file',), toggle='ocr_scanned_pages', applies=_is_document,
                eta='anonymizer.tasks:ocr_eta'),
    ProcessSpec('detect_text', label='Détection des données personnelles', depends_on=(OCR_KEY,),
                watched=('file',), share=3, outputs=('detections_file',), applies=_is_document,
                eta='anonymizer.tasks:detect_text_eta'),
    ProcessSpec('occult_text', label='Occultation', depends_on=('detect_text',),
                watched=BLUR_WATCHED, share=1, outputs=('output_file',), applies=_is_document,
                eta='anonymizer.tasks:occult_text_eta'),
), label='Anonymizer — détection, floutage, réglages de sortie ; document : OCR, détection et '
         'occultation des données personnelles',
   source_ref='anonymizer.function_specs:PIPELINE',
   model_of=lambda media: media.model_to_use or 'auto')
