"""
Gabarit `templates/<app>/index.html` (marche A — v1, marche S2).

Convention MESURÉE (témoin converter, 2026-08-18) : la page d'index est déjà largement
pilotée par les briques COMMUNES — extends du base d'app, `_global_progress`,
`_new_item_card` (paramétrée : accept dérivé d'identity.input_extensions), `_queue_toolbar`,
boucle de lots sur `_batch_card`. Le gabarit rend CE squelette-là ; les parties d'app
restent des TROUS DE GLU marqués et VISIBLES (détecteur Playwright) :
  • volet droit réglages (contenu app) — hôte WamaParams minimal seulement ;
  • modales spécifiques, bloc javascript d'app ;
  • les SECTIONS × CHIPS et les previews de la card (elles dépendent de `card_chips`,
    décoration propre à la vue d'app) — l'écart visuel résiduel EST la mesure.

⚠ Ce qui a QUITTÉ cette liste le 2026-08-29, et pourquoi c'est la leçon du fichier :
les ACTIONS de card et l'INSPECTEUR y étaient rangés comme trous de glu assumés. Ils ne
l'étaient pas. La barre d'actions est faite de CONTRATS COMMUNS à écouteur délégué
(`queue-actions.js`) et d'un partial commun (`_cycle_button.html`) ; l'inspecteur
s'initialise DEPUIS UN SCHÉMA (`WamaInspector.initFromSchema`) et clone les actions de la
card. Le manifeste déclarait déjà tout le nécessaire (facette `inspector`). C'est la
DEUXIÈME fois que ce gabarit range en « trou de glu » une facette qu'il lui suffisait de
lire — la première était `accepts_url` (2026-08-19), et les deux fois le constat est venu
de Fabien comparant la jumelle à sa source, jamais d'un contrôle automatique.
*Un trou déclaré assumé cesse d'être cherché : c'est le plus coûteux des classements.*
Avant d'écrire « TROU DE GLU », vérifier que l'information n'est pas DÉJÀ au manifeste.

Le HTML généré vise l'app SOURCE (`converter`) ; la substitution (app_sandbox) applique
ensuite les renommages de jumelle. Le nom de bloc `<app>_content` suit le base d'app
copié (non renommé par la copie : pas un littéral quoté) — le gabarit l'émet à
L'IDENTIQUE pour rester substituable.
"""
from __future__ import annotations


def render_index(manifest: dict) -> tuple:
    """(source, raison) — templates/<app>/index.html conventionnel, jamais partiel."""
    from ..builtin.app import _GEN_MARK
    app = manifest.get('key')
    body = manifest.get('body') or {}
    ident = body.get('identity') or {}
    label = ident.get('verbose_name') or (manifest.get('name') or app)
    accept = ','.join(ident.get('input_extensions') or []) or '*/*'
    mark = _GEN_MARK.format(app_id=app)

    # Import par URL — DÉRIVÉ des capacités du manifeste (2026-08-19). La jumelle converter_01
    # n'offrait pas le champ URL alors que l'app source l'a : ce n'était PAS un trou de glu
    # assumé mais un manque du gabarit — l'information était DANS le manifeste
    # (`capabilities.accepts_url` / `has_url_import`) et n'était pas lue. Constat Fabien en
    # comparant la jumelle à sa source.
    # Inspecteur contextuel + bouton de cycle — MÊME LEÇON que l'URL ci-dessus, reprise le
    # 2026-08-29 sur un second constat de Fabien : « les cards du bac à sable ne sont pas
    # cliquables, n'affichent rien, pas d'action — alors que le converter d'origine fonctionne ».
    # Ce n'était PAS un trou de glu assumé. La facette `inspector` est DÉCLARÉE au manifeste
    # (`detail_registered`, `preview_registered`, `detail_spec`, `preview`) et n'était pas lue,
    # exactement comme `accepts_url` ne l'était pas. ⚠ La première fois, la cause a été traitée
    # au cas par cas ; la voici une seconde fois, sur une autre facette. *Une facette déclarée
    # au manifeste et non projetée n'est pas un trou de glu — c'est un manque de gabarit, et le
    # marquer « TROU DE GLU » le rend invisible en le déclarant normal.*
    #
    # Rien de ce qui suit n'est propre à l'app : `initFromSchema` prend des sélecteurs
    # conventionnels, et `renderItemActions` CLONE la barre d'actions de la card
    # (`cloneActions`) au lieu de la redéclarer.
    insp = body.get('inspector') or {}
    insp_js = ''
    if insp.get('detail_registered') or insp.get('preview_registered'):
        insp_js = f'''
    // Bouton de cycle ▶/⏹/↻ : contrat commun (`_cycle_button.html` rend, `wire` câble,
    // `autoSync` suit `data-status`). Les routes sont conventionnelles (ROUTE_TABLE).
    var q = document.getElementById('{app}Queue');
    if (q && window.WamaCycleButton) {{
        WamaCycleButton.wire(q, {{
            start: function (id) {{ return WamaApp.csrfFetch("/{app}/" + id + "/start/", {{ method: 'POST' }}).then(function () {{ location.reload(); }}); }},
            stop:  function (id) {{ return WamaApp.csrfFetch("/{app}/" + id + "/cancel/", {{ method: 'POST' }}).then(function () {{ location.reload(); }}); }},
        }});
        WamaCycleButton.autoSync({{ container: q, cardSelector: '.wama-card[data-id]' }});
    }}

    // Inspecteur contextuel — DÉRIVÉ de la facette `inspector` du manifeste.
    if (q && window.WamaInspector && WamaInspector.initFromSchema) {{
        WamaInspector.initFromSchema({{
            queueContainer: q,
            cardSelector:  '.wama-card[data-id]',
            batchSelector: '.batch-group',
            schema: {{{{ params_json|safe }}}},
            itemLabel:  function (id) {{ return "l'élément #" + id; }},
            batchLabel: function (id) {{ return "le batch #" + id; }},
            renderItemActions: function (host, card) {{
                WamaInspector.cloneActions(host, card.querySelector('.btn-group-actions'),
                    '<i class="fas fa-clone text-info"></i> Actions — élément #' + card.dataset.id);
            }},
            renderBatchActions: function (host, batchId) {{
                WamaInspector.cloneActions(
                    host,
                    q.querySelector('.batch-group[data-batch-id="' + batchId + '"] .btn-group-actions'),
                    '<i class="fas fa-layer-group text-info"></i> Actions — batch #' + batchId);
            }},
        }});
    }}
'''

    caps = body.get('capabilities') or {}
    url_bits = url_js = ''
    if caps.get('accepts_url') or caps.get('has_url_import'):
        url_bits = (f" show_url=True url_input_id='{app}Url' url_submit_id='{app}UrlSubmit'"
                    " url_placeholder='https://… (page web, média distant)'")
        # L'URL est routée vers le MÊME formalisme de lot (une URL = un lot d'une ligne) :
        # c'est le choix déjà fait par l'app en place, et il évite une seconde route serveur.
        url_js = f'''
    // URL : même chemin que le fichier de lot (WamaApp.initUrlImport, brique commune).
    if (window.WamaApp && WamaApp.initUrlImport) {{
        WamaApp.initUrlImport({{
            inputId:  '{app}Url',
            buttonId: '{app}UrlSubmit',
            onSubmit: function (u) {{ return window._import.ingestText(u + '\\n', 'url.txt'); }},
        }});
    }}
'''

    src = f'''{{% extends '{app}/base.html' %}}
{{% load static %}}
{{% load wama_static %}}
{{% comment %}}{mark} — index.html GÉNÉRÉ (gabarit templates_gen v1, marche S2).
Squelette CONVENTIONNEL (briques communes) ; les TROUS DE GLU sont marqués — l'écart
visuel avec l'app en place est LA mesure (Playwright côte à côte).{{% endcomment %}}

{{% block title %}}{label} — WAMA{{% endblock %}}

{{% block app_right_panel_settings %}}
{{% comment %}}TROU DE GLU {mark} — volet réglages d'app non généré : hôte WamaParams
minimal (le schéma params.py est rendu si présent).{{% endcomment %}}
<div class="wama-params" id="{app}PanelParams"></div>
<script>
document.addEventListener('DOMContentLoaded', function () {{
    var host = document.getElementById('{app}PanelParams');
    if (host && window.WamaParams) {{
        try {{ WamaParams.render(host, {{{{ params_json|safe }}}}, {{ context: 'panel' }}); }}
        catch (e) {{ /* schéma absent → volet vide (trou visible) */ }}
    }}
}});
</script>
{{% endblock %}}

{{% block {app}_content %}}
<div style="overflow-x:hidden;">

    {{% include 'common/_global_progress.html' %}}

    {{% url '{app}:batch_template' as batch_tpl_url %}}
    {{% include 'common/_new_item_card.html' with drop_zone_id='{app}DropZone' file_input_id='{app}FileInput' file_accept='{accept}' formats_label='{label}' show_batch_bar=True show_media_library=True batch_template_url=batch_tpl_url collapsible=True{url_bits} %}}
    <hr class="border-secondary">

    {{% include 'common/_queue_toolbar.html' with q_sort=q_sort q_filter=q_filter start_id='{app}StartAllBtn' clear_id='{app}ClearAllBtn' download_id='{app}DownloadAllBtn' show_download=True %}}

    <div id="{app}Queue" class="wama-queue-{{{{ card_layout|default:'list' }}}}">
        {{% for b in batches_list %}}
            {{% if b.is_group %}}
            {{% comment %}}Wrapper `.batch-group` : `_batch_card.html:32` le déclare À LA CHARGE
            de l'app (« l'app garde autour »). Il n'était pas émis — d'où un lot sans identité
            dans le DOM : l'inspecteur ne pouvait pas le sélectionner et le nettoyage de lot vidé
            de `queue-actions.js` ne le trouvait pas non plus.{{% endcomment %}}
            <div class="batch-group" data-batch-id="{{{{ b.obj.id }}}}">
            {{% include 'common/_batch_card.html' with batch_info=b eta_ids=b.eta_ids %}}
            <div class="collapse show" id="batchItems{{{{ b.obj.id }}}}" data-wama-batch-key="{app}-{{{{ b.obj.id }}}}">
                {{% for item in b.items %}}{{% include '{app}/_generic_card.html' %}}{{% endfor %}}
            </div>
            </div>
            {{% else %}}
            {{% for item in b.items %}}{{% include '{app}/_generic_card.html' %}}{{% endfor %}}
            {{% endif %}}
        {{% empty %}}
            <p class="text-muted small">Aucun élément dans la file.</p>
        {{% endfor %}}
    </div>

</div>
{{% endblock %}}

{{% comment %}}{mark} — COUCHE JS D'APPLICATION. Ce bloc manquait : le JS de l'app existait
dans static/ mais n'était JAMAIS chargé (le socle offre pourtant le point d'extension,
app_modern_base.html:294). Aucun écouteur n'était posé, aucune voie d'import n'émettait de
requête, et RIEN ne le signalait — zéro erreur console, puisque rien ne plante quand rien
n'est chargé. Mesuré sur converter_01 le 2026-08-22 : 0 card créable par 5 voies.

Une app générée n'a PAS besoin d'un JS sur mesure pour importer : les cinq modalités sont
des briques communes. On ne déclare donc ici que ce qui est propre à l'app — ses URL.{{% endcomment %}}
{{% block app_scripts %}}
{{% include 'common/_app_scripts.html' %}}
<script>
window.WAMA_GLOBAL_PROGRESS_URL = "{{% url '{app}:global_progress' %}}";

document.addEventListener('DOMContentLoaded', function () {{
    // Fichier de LOT : détection structurelle + aperçu AVANT création (brique commune).
    window._batchImport = WamaBatchImport({{
        batchPreviewUrl: "{{% url '{app}:batch_preview' %}}",
        batchCreateUrl:  "{{% url '{app}:batch_create' %}}",
        csrfToken:       '{{{{ csrf_token }}}}',
        afterCreate:     function () {{ location.reload(); }},
    }});

    // Fichier ORDINAIRE (dépôt, clic, médiathèque) : le maillon qu'aucune brique ne portait.
    window._import = WamaImport({{
        uploadUrl:      "{{% url '{app}:upload' %}}",
        consolidateUrl: "{{% url '{app}:consolidate' %}}",
        csrfToken:      '{{{{ csrf_token }}}}',
        dropZoneId:     '{app}DropZone',
        fileInputId:    '{app}FileInput',
        batch:          window._batchImport,
    }});
{url_js}{insp_js}}});
</script>
{{% endblock %}}
'''

    # Card GÉNÉRIQUE (partial compagnon). Elle porte désormais les ACTIONS — cf. l'en-tête de
    # module : le commentaire qui vivait ici annonçait « actions conventionnelles inertes »
    # alors que la card n'en rendait AUCUNE. Un trou décrit comme comblé est un trou qu'on
    # cesse de chercher.
    card = f'''{{% comment %}}{mark} — _generic_card.html GÉNÉRÉ (templates_gen v1).
TROU DE GLU RESTANT : les sections × chips et les previews de la card RÉELLE ne sont pas
générées (elles dépendent de `card_chips`, décoration propre à la vue d'app). L'écart
résiduel reste MESURABLE au Playwright.
Les ACTIONS, elles, ne sont plus un trou : ce sont des CONTRATS COMMUNS à écouteur délégué
(`queue-actions.js` : `.settings-btn[data-id]`, `.duplicate-btn[data-duplicate-url]`,
`.delete-btn[data-delete-url]`) plus le partial `_cycle_button.html`. Rien ici n'est propre
à l'app sauf les URL, et elles sont conventionnelles (ROUTE_TABLE).{{% endcomment %}}
<div class="card bg-dark border-secondary mb-2 wama-card" data-id="{{{{ item.id }}}}" data-status="{{{{ item.status }}}}">
  <div class="card-body py-2">
    <div class="d-flex align-items-center gap-2">
      <strong class="text-light">#{{{{ item.id }}}}</strong>
      <span class="text-truncate flex-fill">{{{{ item.input_filename|default:item.id }}}}</span>
      <span class="badge bg-{{% if item.status == 'SUCCESS' %}}success{{% elif item.status == 'FAILURE' %}}danger{{% elif item.status == 'RUNNING' %}}warning text-dark{{% else %}}secondary{{% endif %}}">{{{{ item.status }}}}</span>
    </div>
    {{% if item.status != 'PENDING' %}}
    <div class="wama-progress-track mt-1">
      <div class="wama-progress-fill{{% if item.status == 'RUNNING' %}} active{{% endif %}}" style="width:{{% if item.status == 'SUCCESS' %}}100{{% else %}}{{{{ item.progress }}}}{{% endif %}}%"></div>
    </div>
    {{% endif %}}
    {{% if item.error_message %}}<div class="small text-danger mt-1">{{{{ item.error_message|truncatechars:120 }}}}</div>{{% endif %}}
    {{% comment %}}Ordre CONVENTIONNEL imposé (CLAUDE.md) : ⚙ · ▶ cycle · ⬇ · ⧉ · 🗑.
    `.btn-group-actions` est aussi la source que l'inspecteur CLONE (`cloneActions`) — la
    classe n'est donc pas décorative : sans elle le volet droit reste vide.
    ⚠ Le ⚙ reste le SEUL bouton inerte, et son trou n'est pas ici : il attend un ouvreur
    (`WamaQueueActions.onSettings`), qu'on ne peut pas déclarer tant que `views_gen` rend
    l'endpoint d'édition en 501 (« politique d'app non conventionnelle », marche B). La
    brique commune ne l'avale pas en silence — elle avertit en console. Ne pas retirer le
    bouton pour autant : l'ordre conventionnel est un critère de grille, et son absence
    ferait disparaître le trou au lieu de le montrer.{{% endcomment %}}
    <div class="btn-group-actions d-flex gap-1 mt-2">
      <button type="button" class="btn btn-sm btn-outline-secondary settings-btn" data-id="{{{{ item.id }}}}" title="Paramètres"><i class="fas fa-cog"></i></button>
      {{% include 'common/_cycle_button.html' with id=item.id status=item.status %}}
      {{% if item.status == 'SUCCESS' %}}<a class="btn btn-sm btn-outline-info" href="{{% url '{app}:download' item.id %}}" title="Télécharger"><i class="fas fa-download"></i></a>{{% endif %}}
      <button type="button" class="btn btn-sm btn-outline-warning duplicate-btn" data-duplicate-url="{{% url '{app}:duplicate' item.id %}}" title="Dupliquer"><i class="fas fa-clone"></i></button>
      <button type="button" class="btn btn-sm btn-outline-danger delete-btn" data-delete-url="{{% url '{app}:delete' item.id %}}" title="Supprimer"><i class="fas fa-trash"></i></button>
    </div>
  </div>
</div>
'''
    return {'index.html': src, '_generic_card.html': card}, None
