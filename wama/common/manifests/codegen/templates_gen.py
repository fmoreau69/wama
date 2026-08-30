"""
Gabarit `templates/<app>/index.html` (marche A — v1, marche S2).

Convention MESURÉE (témoin converter, 2026-08-18) : la page d'index est déjà largement
pilotée par les briques COMMUNES — extends du base d'app, `_global_progress`,
`_new_item_card` (paramétrée : accept dérivé d'identity.input_extensions), `_queue_toolbar`,
boucle de lots sur `_batch_card`. Le gabarit rend CE squelette-là ; les parties d'app
restent des TROUS DE GLU marqués et VISIBLES (détecteur Playwright) :
  • volet droit réglages (contenu app) — hôte WamaParams minimal seulement ;
  • modales spécifiques, bloc javascript d'app ;
  • les PREVIEWS de la card (miniature/lecteur du média) — l'écart visuel résiduel EST la mesure.

⚠ Ce qui a QUITTÉ cette liste le 2026-08-29, et pourquoi c'est la leçon du fichier :
les ACTIONS de card et l'INSPECTEUR y étaient rangés comme trous de glu assumés. Ils ne
l'étaient pas. La barre d'actions est faite de CONTRATS COMMUNS à écouteur délégué
(`queue-actions.js`) et d'un partial commun (`_cycle_button.html`) ; l'inspecteur
s'initialise DEPUIS UN SCHÉMA (`WamaInspector.initFromSchema`) et clone les actions de la
card. Le manifeste déclarait déjà tout le nécessaire (facette `inspector`). C'est la
DEUXIÈME fois que ce gabarit range en « trou de glu » une facette qu'il lui suffisait de
lire — la première était `accepts_url` (2026-08-19), et les deux fois le constat est venu
d'une comparaison à l'œil entre la jumelle et sa source, jamais d'un contrôle automatique.
Les SECTIONS × CHIPS ont suivi le même jour (3ᵉ occurrence) : leur raison écrite disait
« décoration propre à la vue d'app » alors que `card_chips` est une brique COMMUNE nourrie
du schéma de params, lui aussi au manifeste. *Le classement « trou de glu » n'est jamais une
observation : c'est une hypothèse, et rien ici ne la réfute jamais.*
*Un trou déclaré assumé cesse d'être cherché : c'est le plus coûteux des classements.*
Avant d'écrire « TROU DE GLU », vérifier que l'information n'est pas DÉJÀ au manifeste.

Le HTML généré vise l'app SOURCE (`converter`) ; la substitution (app_sandbox) applique
ensuite les renommages de jumelle. Le nom de bloc `<app>_content` suit le base d'app
copié (non renommé par la copie : pas un littéral quoté) — le gabarit l'émet à
L'IDENTIQUE pour rester substituable.
"""
from __future__ import annotations

from wama.common.manifests.codegen.urls_gen import resolve_route


def render_index(manifest: dict) -> tuple:
    """(source, raison) — templates/<app>/index.html conventionnel, jamais partiel."""
    from ..builtin.app import _GEN_MARK
    app = manifest.get('key')
    body = manifest.get('body') or {}
    ident = body.get('identity') or {}
    label = ident.get('verbose_name') or (manifest.get('name') or app)
    # `file_accept` — RÉTRÉCI aux catégories du PORT TRAVAIL (moitié TRAVAIL de §S2bis.6 (b),
    # débloquée le 2026-08-30 par le retrait de l'homonyme `text` : les .txt/.md/.csv du
    # describer sont désormais des `document`, donc plus de contre-exemple). L'union PLATE
    # d'`input_extensions` faisait proposer `.docx` au slot « image de travail » dès la 2ᵉ app
    # portée. On garde : les extensions dont la nature ∈ types du port travail, PLUS les
    # formats de FICHIER DE LOT si l'app a le batch (le même input les reçoit — détection
    # structurelle). Sans port travail (app prompt-primaire) : lot seul, sinon l'union.
    exts = [str(e) for e in (ident.get('input_extensions') or [])]
    work = next((p for p in ((body.get('ports') or {}).get('inputs') or [])
                 if p.get('group') == 'travail'), None)
    if work and exts:
        from wama.common.app_registry import category_of_path
        cats = set(work.get('types') or [])
        retenues = [e for e in exts if category_of_path('x' + e) in cats]
        if (body.get('capabilities') or {}).get('has_batch'):
            from wama.common.utils.batch_parsers import SUPPORTED_BATCH_EXTENSIONS
            retenues += ['.' + b for b in SUPPORTED_BATCH_EXTENSIONS
                         if '.' + b not in retenues]
        exts = retenues or exts
    accept = ','.join(exts) or '*/*'
    mark = _GEN_MARK.format(app_id=app)

    # Import par URL — DÉRIVÉ des capacités du manifeste (2026-08-19). La jumelle converter_01
    # n'offrait pas le champ URL alors que l'app source l'a : ce n'était PAS un trou de glu
    # assumé mais un manque du gabarit — l'information était DANS le manifeste
    # (`capabilities.accepts_url` / `has_url_import`) et n'était pas lue. Constat fait à l'œil en
    # comparant la jumelle à sa source.
    # Inspecteur contextuel + bouton de cycle — MÊME LEÇON que l'URL ci-dessus, reprise le
    # 2026-08-29 sur un second constat fait à l'œil : « les cards du bac à sable ne sont pas
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
    # Noms de routes LUS au manifeste, jamais supposés (leçon du 2026-08-29, jumelle de celle
    # de `views_gen`) : 8 apps nomment l'arrêt `stop`, le converter le nomme `cancel`, et
    # l'édition d'un élément est `update`. Un nom deviné ici produit un POST 404 muet.
    proc = body.get('processing') or {}
    noms_routes = set(proc.get('endpoints') or []) | {
        str(e.get('name') or '') for e in (proc.get('extra_routes') or [])}
    route_stop = resolve_route('stop', noms_routes)
    route_update = resolve_route('update', noms_routes)
    champs_params = list(((proc.get('model_spec') or {}).get('item') or {})
                         .get('params_fields') or [])

    insp = body.get('inspector') or {}
    insp_js = ''
    if insp.get('detail_registered') or insp.get('preview_registered'):
        stop_js = (f'''
            stop:  function (id) {{ return post(urlFor(U.stop, id)); }},'''
                   if route_stop else '''
            // TROU : aucune route d'arrêt déclarée au manifeste — ⏹ non câblé (plutôt qu'un POST 404 muet).''')
        insp_js = f'''
    // Bouton de cycle ▶/⏹/↻ : contrat commun (`_cycle_button.html` rend le bouton, `wire`
    // câble le clic, `autoSync` suit `data-status`). La brique est complète depuis le
    // 2026-08-13 et n'est pas en cause : elle DÉLÈGUE l'appel HTTP à l'app, par construction
    // (chaque app a ses routes). Ce qui manquait était ici, du côté appelant, et deux fois.
    var q = document.getElementById('{app}Queue');
    if (q && window.WamaCycleButton) {{
        WamaCycleButton.wire(q, {{
            start: function (id) {{ return post(urlFor(U.start, id)); }},{stop_js}
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

    # ⚙ des cards — DERNIER bouton inerte de la jumelle, et son trou n'était pas au gabarit de
    # card : `queue-actions.js` tient le clic depuis toujours et attendait qu'une app DÉCLARE
    # son ouvreur, ce qu'on ne pouvait pas faire tant que `views_gen` bouchait l'édition en 501.
    # Les deux se débloquent ensemble (même commit) — un bouton mort se referme des DEUX côtés
    # ou pas du tout. Rien d'app ici : le cycle complet (rendre → lire → POST → toast) est
    # `WamaParams.settingsModal` ; seules les VALEURS courantes et l'URL viennent du manifeste.
    # Sources d'options DYNAMIQUES (`options_source`) — le schéma déclare une CLÉ (`formats`,
    # `backends`, `voices`, `avatar_gallery`) et le gabarit doit savoir la résoudre. DEUX familles
    # de sources existent, toutes deux au COMMUN, aucune propre à une app :
    #   • endpoints ASYNC — registre `OPTION_SOURCES` de `wama-params.js` (`voices` →
    #     `/common/api/voices/`) : `_bindOptionSources` peuple le select après rendu ;
    #   • données de PAGE, résolution SYNCHRONE — registre `PAGE_OPTION_SOURCES`, interrogé par
    #     `WamaParams.resolvePageOptions(param, valeurs)`. C'est là que vit `formats`, adossé à
    #     `window.WAMA_OUTPUT_FORMATS` (= `CONVERTER_OUTPUT_FORMATS`, posé sur toutes les pages).
    #
    # ⚠⚠ CE COMMENTAIRE DISAIT LE CONTRAIRE, ET C'EST LA LEÇON. Il rangeait `options_source` en
    # « trou STRUCTUREL du formalisme » au motif que « RIEN, ni dans `Param` ni au manifeste, ne
    # dit d'où viennent ses options », et le resolver généré affichait donc « ⚠ options
    # « formats » non déclarées » — un select sans aucun format de sortie, donc une jumelle où
    # rien n'était lançable. La donnée existait pourtant sur CHAQUE page, exposée par un
    # processeur de contexte global. *Un trou annoncé sans avoir cherché l'accesseur est une
    # hypothèse déguisée en mesure* — troisième fois cette semaine dans ce même fichier, après
    # `accepts_url` et la facette `inspector`. Le réflexe qui manque n'est pas la prudence, c'est
    # le grep.
    #
    # Ce qui reste vrai : une clé qui n'est dans AUCUN des deux registres ne résout nulle part.
    # Le resolver le DIT alors (option nommée + `console.warn`) plutôt que de rendre un select
    # vide — *un select vide ne dit pas s'il l'est par absence d'options ou par défaut de
    # câblage ; une option qui se nomme le dit.* Y répondre, c'est ajouter la source au registre
    # commun (comme `formats` ici), jamais écrire un resolver dans l'app ou dans ce gabarit.
    schemas = (body.get('params') or {}).get('schemas') or {}
    schema_primaire = schemas.get((body.get('params') or {}).get('primary') or '') or []
    sources_dyn = sorted({str(p.get('options_source')) for p in schema_primaire
                          if isinstance(p, dict) and p.get('options_source')})

    params_js = ''
    if route_update and champs_params:
        lect = '\n'.join(f"                v['{c}'] = card.getAttribute('data-param-{c}') || '';"
                         for c in champs_params)
        resolver_js = ('' if not sources_dyn else f'''
                optionsResolver: function (p) {{
                    // Sources déclarées au schéma de cette app : {', '.join(sources_dyn)}
                    // 1. Clé à endpoint → ne rien renvoyer : `_bindOptionSources` peuple le
                    //    select après le rendu (chemin ASYNC existant).
                    var SRC = window.WAMA_OPTION_SOURCES || {{ voices: '/common/api/voices/' }};
                    if (SRC[p.options_source]) return null;
                    // 2. Clé adossée à une donnée de page → registre commun, résolution
                    //    synchrone, alimentée par les valeurs courantes de l'élément.
                    var opts = WamaParams.resolvePageOptions(p, v);
                    if (opts) return opts;
                    // 3. Aucun des deux registres : la clé ne résout nulle part. Le DIRE.
                    console.warn('[manifest-gen app:{app}] options_source « ' + p.options_source +
                                 ' » : absente des deux registres communs (endpoints et données de page).');
                    return [{{ value: '', label: '⚠ options « ' + p.options_source + ' » non déclarées' }}];
                }},''')
        params_js = f'''
    if (window.WamaQueueActions && window.WamaParams) {{
        WamaQueueActions.onSettings(function (id, btn) {{
            var card = btn.closest('.wama-card[data-id]');
            // Valeurs courantes lues sur la CARD (`data-param-*`) : pas de route de lecture
            // conventionnelle à inventer, et la card les porte déjà pour l'inspecteur.
            var v = {{}};
            if (card) {{
{lect}
            }}
            WamaParams.settingsModal({{
                id: id,
                title: 'Paramètres — élément #' + id,
                titleIcon: 'fa-gear',
                schema: {{{{ params_json|safe }}}},
                values: v,
                saveUrl: urlFor(U.update, id),
                csrf: CSRF,{resolver_js}
                onSaved: function () {{ location.reload(); }},
            }});
        }});
    }}
'''

    # Routes d'ÉLÉMENT — par `{% url %}` avec pk 0, JAMAIS par un chemin écrit à la main.
    # ⚠⚠ Défaut mesuré le 2026-08-29 dans ma propre génération de la veille : j'avais écrit
    # `"/" + app + "/" + id + "/start/"`. La substitution du bac à sable renomme les LITTÉRAUX
    # de gabarit (`{% url 'converter:…' %}` → `converter_01:…`) mais PAS une chaîne de chemin
    # construite en JS : la jumelle POSTait donc sur l'app SOURCE. Une jumelle qui agit sur son
    # original ne mesure plus rien — elle contamine ce qu'elle devait servir de témoin.
    # *Un chemin écrit à la main échappe à toute machinerie de renommage ; `{% url %}` non.*
    routes_dispo = [(nom, cle) for nom, cle in
                    (('start', 'start'), ('stop', route_stop), ('update', route_update))
                    if cle and cle in noms_routes]
    routes_js = ''
    if routes_dispo:
        lignes = '\n'.join(f"""        {nom + ':':8} "{{% url '{app}:{cle}' 0 %}}","""
                           for nom, cle in routes_dispo)
        routes_js = f'''
    var U = {{
{lignes}
    }};
    function urlFor(t, id) {{ return t.replace('/0/', '/' + id + '/'); }}
    // ⚠ `csrfFetch(url, csrfToken, opts)` — TROIS arguments. Appelé à deux (2026-08-29), le
    // `{{method:'POST'}}` était reçu comme JETON et les options restaient vides : requête GET,
    // 405 face à `@require_POST`, et un bouton qui « ne fait rien » sans rien dire.
    // *Une signature de brique se LIT ; deviner un argument coûte un bouton mort.*
    function post(u) {{
        return WamaApp.csrfFetch(u, CSRF, {{ method: 'POST' }})
            .then(function () {{ location.reload(); }});
    }}
'''

    # Actions GLOBALES de la file (▶ Démarrer tout / ⬇ Télécharger tout / 🗑 Tout effacer).
    # 4ᵉ occurrence du motif du fichier, et la plus discrète : la barre était bien émise
    # (`_queue_toolbar.html`), avec ses trois ids — mais le contrat du partial dit « handlers JS
    # de l'app », et un gabarit ne peut pas écrire de handler. Les trois boutons étaient donc
    # rendus, visibles, cliquables et INERTES. Le bouton ⬇ était même désactivé PAR
    # CONSTRUCTION : sans `download_url`, le partial rend un `<button disabled>`.
    # ⚠ Ici la facette n'était ni absente ni mal lue — les routes `start_all` / `clear_all` /
    # `download_all` sont dans `ROUTE_TABLE`, générées par `views_gen`, présentes dans le urls
    # généré. *Trois routes existantes, trois boutons rendus, et rien entre les deux* : le
    # câblage était le seul maillon, et il n'appartenait à personne. Il appartient désormais au
    # COMMUN (`queue-actions.js`, 3ᵉ étage : élément → lot → file) ; le gabarit n'a plus qu'à
    # passer les URLs — même contrat que `data-batch-<action>-url` pour les lots.
    route_start_all = resolve_route('start_all', noms_routes)
    route_clear_all = resolve_route('clear_all', noms_routes)
    route_dl_all = resolve_route('download_all', noms_routes)
    urls_file = ''.join(
        f"""    {{% url '{app}:{cle}' as {var} %}}\n"""
        for cle, var in ((route_start_all, 'q_start_url'), (route_clear_all, 'q_clear_url'),
                         (route_dl_all, 'q_download_url')) if cle)
    bits_file = ''.join(bit for cle, bit in (
        (route_start_all, ' start_url=q_start_url'), (route_clear_all, ' clear_url=q_clear_url'),
        (route_dl_all, ' download_url=q_download_url')) if cle)

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

    # Slot de RÉFÉRENCE — DÉRIVÉ des ports `group='reference'` du manifeste (§S2bis.6 (b),
    # 2026-08-30). La card commune sait typer par slot depuis toujours (`reference_accept`,
    # `_new_item_card.html`) ; ce qui manquait était la DÉCLARATION : `inputs[]` ne se posait
    # que sur un MODE, or 6 apps sur 10 n'ont pas de switch. Un domaine sans switch les porte
    # désormais (app_modes), le port `reference` en dérive (studio_node_ports), et ce gabarit
    # lit LE PORT — jamais un littéral par app.
    ref_bits = ref_js = ''
    refs = [p for p in ((body.get('ports') or {}).get('inputs') or [])
            if p.get('group') == 'reference']
    if refs:
        # La card commune n'offre qu'UN slot de référence — vrai aussi des 2 gabarits manuels
        # qui la paramètrent (composer, imager). Plusieurs ports déclarés : on rend le premier
        # et on NOMME les autres (trou visible), jamais un slot silencieusement perdu.
        ref = refs[0]
        mime = {'image': 'image/*', 'video': 'video/*', 'audio': 'audio/*'}
        ref_accept = ','.join(mime[c] for c in (ref.get('types') or []) if c in mime) or '*/*'
        ref_bits = (f" show_reference=True reference_zone_id='{app}RefSlot'"
                    f" reference_input_id='{app}RefInput' reference_chip_id='{app}RefChip'"
                    f" reference_accept='{ref_accept}'"
                    f" reference_label='{ref.get('label') or 'Référence'}'")
        surplus = ''.join(
            f"\n    // TROU DE GLU {mark} — port de référence supplémentaire NON rendu : `{p.get('id')}`."
            for p in refs[1:])
        ref_js = f'''
    // TROU DE GLU {mark} — slot de référence RENDU (port `{ref.get('id')}`), câblage d'ATTACHE
    // non généré : joindre le fichier du slot au POST de création est un geste d'app
    // (`depot_cree=False`/FormData) que la marche B remplit. Le slot est visible et nommé
    // plutôt qu'absent — l'écart avec l'app en place EST la mesure.{surplus}
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
    {{% include 'common/_new_item_card.html' with drop_zone_id='{app}DropZone' file_input_id='{app}FileInput' file_accept='{accept}' formats_label='{label}' show_batch_bar=True show_media_library=True batch_template_url=batch_tpl_url collapsible=True{url_bits}{ref_bits} %}}
    <hr class="border-secondary">

{urls_file}    {{% include 'common/_queue_toolbar.html' with q_sort=q_sort q_filter=q_filter start_id='{app}StartAllBtn' clear_id='{app}ClearAllBtn' download_id='{app}DownloadAllBtn' show_download=True{bits_file} %}}

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
    var CSRF = '{{{{ csrf_token }}}}';
{routes_js}
    // Fichier de LOT : détection structurelle + aperçu AVANT création (brique commune).
    window._batchImport = WamaBatchImport({{
        batchPreviewUrl: "{{% url '{app}:batch_preview' %}}",
        batchCreateUrl:  "{{% url '{app}:batch_create' %}}",
        csrfToken:       CSRF,
        afterCreate:     function () {{ location.reload(); }},
    }});

    // Fichier ORDINAIRE (dépôt, clic, médiathèque) : le maillon qu'aucune brique ne portait.
    window._import = WamaImport({{
        uploadUrl:      "{{% url '{app}:upload' %}}",
        consolidateUrl: "{{% url '{app}:consolidate' %}}",
        csrfToken:      CSRF,
        dropZoneId:     '{app}DropZone',
        fileInputId:    '{app}FileInput',
        batch:          window._batchImport,
    }});
{url_js}{ref_js}{insp_js}{params_js}}});
</script>
{{% endblock %}}
'''

    # Card GÉNÉRIQUE (partial compagnon). Elle porte désormais les ACTIONS — cf. l'en-tête de
    # module : le commentaire qui vivait ici annonçait « actions conventionnelles inertes »
    # alors que la card n'en rendait AUCUNE. Un trou décrit comme comblé est un trou qu'on
    # cesse de chercher.
    # Valeurs courantes des `params_fields` PORTÉES par la card (`data-param-<champ>`) : la
    # modale les lit sans route de lecture supplémentaire. C'est le même choix que
    # `data-status` pour `autoSync` — la card est auto-suffisante (formalisme CARD_DESIGN).
    attrs_params = ''.join(f''' data-param-{c}="{{{{ item.{c}|default:'' }}}}"'''
                           for c in champs_params)

    card = f'''{{% comment %}}{mark} — _generic_card.html GÉNÉRÉ (templates_gen v1).
TROU DE GLU RESTANT : les PREVIEWS de la card RÉELLE (miniature/lecteur du média) ne sont pas
générées. L'écart résiduel reste MESURABLE au Playwright.
⚠ Les SECTIONS × CHIPS ont quitté cette ligne le 2026-08-29 : la raison écrite — « décoration
propre à la vue d'app » — était FAUSSE. `card_chips.chips_by_section` est une brique COMMUNE
appliquée au schéma de params DÉJÀ déclaré au manifeste ; les 10 apps l'appellent à
l'identique. Ce qui manquait était le point d'attache, et `views_gen` l'émet désormais
(`_decorer`, posé sur l'index ET sur `card_html` — sinon la card se vide au 1ᵉʳ rafraîchissement).
Les ACTIONS, elles, ne sont plus un trou : ce sont des CONTRATS COMMUNS à écouteur délégué
(`queue-actions.js` : `.settings-btn[data-id]`, `.duplicate-btn[data-duplicate-url]`,
`.delete-btn[data-delete-url]`) plus le partial `_cycle_button.html`. Rien ici n'est propre
à l'app sauf les URL, et elles sont conventionnelles (ROUTE_TABLE).{{% endcomment %}}
<div class="card bg-dark border-secondary mb-2 wama-card" data-id="{{{{ item.id }}}}" data-status="{{{{ item.status }}}}"{attrs_params}>
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
    {{% comment %}}Sections RÉGLAGES / SORTIE — chips GÉNÉRÉS du schéma de params par la brique
    commune (`card_chips.chips_by_section`, section déclarée champ par champ au manifeste).
    Rien n'est écrit à la main ici : une app qui ne déclare aucun `chip` ne rend aucune
    section (le `{{% if %}}` la retire), et un champ qui change de section suit sa
    déclaration. C'est la règle métadonnée-driven appliquée à la card.{{% endcomment %}}
    {{% if item.chips.settings %}}
    <div class="d-flex align-items-center gap-1 mt-1 flex-wrap">
      <span class="small text-muted me-1">Réglages</span>
      {{% include 'common/_card_chips.html' with chips=item.chips.settings %}}
    </div>
    {{% endif %}}
    {{% if item.chips.output %}}
    <div class="d-flex align-items-center gap-1 mt-1 flex-wrap">
      <span class="small text-muted me-1">Sortie</span>
      {{% include 'common/_card_chips.html' with chips=item.chips.output %}}
    </div>
    {{% endif %}}
    {{% comment %}}Ordre CONVENTIONNEL imposé (CLAUDE.md) : ⚙ · ▶ cycle · ⬇ · ⧉ · 🗑.
    `.btn-group-actions` est aussi la source que l'inspecteur CLONE (`cloneActions`) — la
    classe n'est donc pas décorative : sans elle le volet droit reste vide.
    Le ⚙ a cessé d'être inerte le 2026-08-29 : son ouvreur est déclaré dans l'index (bloc
    `params_js`) et l'édition d'un élément n'est plus un 501 (`views_gen`). ⚠ Il fallait les
    DEUX — un bouton mort se referme des deux côtés ou pas du tout ; câbler le seul ouvreur
    aurait donné un enregistrement qui échoue, et ouvrir la seule vue n'aurait rien changé
    à l'écran. Les valeurs courantes voyagent en `data-param-*` sur la card.{{% endcomment %}}
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
