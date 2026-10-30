/**
 * Brique `video_view` — une VIDÉO sur l'axe partagé (2026-10-29 ; le second plugin graphique du
 * monde Data, `WAMA_DATA_WORLD §8.4` — la « visionneuse vidéo » de BIND, `VideoSynchroniser`, écrite
 * sur le face_analyzer).
 *
 * Universelle : la vidéo d'un rôle lu par la surface (`options.role`, défaut `video`) devient
 * l'HORLOGE de l'axe (`ctx.axis().attach`) — les autres vues (courbes, segments) la suivent sans la
 * connaître. Elle n'a pas de commandes à elle : ce sont celles du transport commun (la brique
 * `media_transport`, posée sans son propre média : `media: false`). Un clic sur l'image lance ou
 * arrête la lecture, le geste de toute vidéo.
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

        function load(url) {
            video.hidden = !url;
            empty.hidden = !!url;
            if (!url) { empty.textContent = 'Aucune vidéo à lire pour l’instant.'; return; }
            if (!axis) return;
            axis.pause();
            axis.detach();
            video.src = url;
            axis.attach(video, { offset: Number(options.offset) || 0 });
        }
        video.addEventListener('loadedmetadata', function () {
            if (axis && isFinite(video.duration)) axis.setDuration(video.duration);
        });
        video.addEventListener('click', function () { if (axis) axis.toggle(); });

        ctx.on('source', function (p) {
            if (p && p.role === role) load(ctx.source(role).url);
        });
        load(ctx.source(role).url);
        return {};
    }

    global.WamaSurface.registerBrick('video_view', { title: 'Vidéo', mount: mount });
})(window);
