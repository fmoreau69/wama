"""
Gabarit `templates/<app>/index.html` (marche A — v1, marche S2).

Convention MESURÉE (témoin converter, 2026-08-18) : la page d'index est déjà largement
pilotée par les briques COMMUNES — extends du base d'app, `_global_progress`,
`_new_item_card` (paramétrée : accept dérivé d'identity.input_extensions), `_queue_toolbar`,
boucle de lots sur `_batch_card`. Le gabarit rend CE squelette-là ; les parties d'app
restent des TROUS DE GLU marqués et VISIBLES (détecteur Playwright) :
  • volet droit réglages (contenu app) — hôte WamaParams minimal seulement ;
  • modales spécifiques, bloc javascript d'app ;
  • le PARTIAL de card d'item (nom/markup app) → card GÉNÉRIQUE minimale inline
    (id, nom, statut, barre) — l'écart visuel avec la vraie card EST la mesure.

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
    caps = body.get('capabilities') or {}
    url_bits = ''
    if caps.get('accepts_url') or caps.get('has_url_import'):
        url_bits = (f" show_url=True url_input_id='{app}Url' url_submit_id='{app}UrlSubmit'"
                    " url_placeholder='https://… (page web, média distant)'")

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
            {{% include 'common/_batch_card.html' with batch_info=b eta_ids=b.eta_ids %}}
            <div class="collapse show" id="batchItems{{{{ b.obj.id }}}}" data-wama-batch-key="{app}-{{{{ b.obj.id }}}}">
                {{% for item in b.items %}}{{% include '{app}/_generic_card.html' %}}{{% endfor %}}
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
'''

    # Card GÉNÉRIQUE minimale (partial compagnon) : le TROU DE GLU rendu VISIBLE — id,
    # nom, statut, barre, actions conventionnelles inertes tant que le JS d'app n'existe pas.
    card = f'''{{% comment %}}{mark} — _generic_card.html GÉNÉRÉ (templates_gen v1).
TROU DE GLU : la card RÉELLE de l'app (sections × chips, previews, actions câblées) n'est
pas généré — cette card minimale rend l'écart MESURABLE au Playwright.{{% endcomment %}}
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
  </div>
</div>
'''
    return {'index.html': src, '_generic_card.html': card}, None
