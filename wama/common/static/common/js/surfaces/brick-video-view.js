/**
 * Brique `video_view` — une VIDÉO sur l'axe partagé (2026-10-29 ; le second plugin graphique du
 * monde Data, `WAMA_DATA_WORLD §8.4` — la « visionneuse vidéo » de BIND, `VideoSynchroniser`, écrite
 * sur le face_analyzer).
 *
 * Universelle : la vidéo d'un rôle lu par la surface (`options.role`, défaut `video`) SUIT l'axe
 * (`ctx.axis().attach`) comme tout média — l'axe est la seule horloge, et la recale (2026-11-02,
 * décision de Fabien : jusque-là elle DEVENAIT l'horloge en jouant). Les autres vues (courbes,
 * segments) suivent l'axe, jamais elle. Elle n'a pas de commandes à elle : ce sont celles du
 * transport commun (la brique `media_transport`, posée sans média : `media: false`). Un clic sur
 * l'image lance ou arrête la lecture — une COMMANDE à l'axe, le geste de toute vidéo. Sa durée et
 * sa cadence (`options.fps`) entrent à l'axe par son attache.
 */
(function (global) {
    'use strict';

    function mount(body, ctx, options) {
        options = options || {};
        var role = options.role || 'video';
        var axis = ctx.axis ? ctx.axis() : null;
        body.classList.add('wama-brick-video');
        var video = document.createElement('video');
        video.preload = 'metadata';
        video.playsInline = true;
        video.className = 'wama-video-view';
        var empty = document.createElement('div');
        empty.className = 'wama-chart-empty';
        body.appendChild(video);
        body.appendChild(empty);

        // Le suiveur de CETTE vue : on ne détache que lui.
        var dropVideo = null;
        function load(url) {
            video.hidden = !url;
            empty.hidden = !!url;
            if (dropVideo) { dropVideo(); dropVideo = null; }
            if (!url) { empty.textContent = 'Aucune vidéo à lire pour l’instant.'; return; }
            if (!axis) return;
            axis.pause();
            video.src = url;
            dropVideo = axis.attach(video, { offset: Number(options.offset) || 0,
                                             fps: Number(options.fps) || 0 });
        }
        video.addEventListener('click', function () { if (axis) axis.toggle(); });

        ctx.on('source', function (p) {
            if (p && p.role === role) load(ctx.source(role).url);
        });
        load(ctx.source(role).url);
        return {};
    }

    global.WamaSurface.registerBrick('video_view', { title: 'Vidéo', mount: mount });
})(window);
