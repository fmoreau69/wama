/* WamaTheme — pose le THÈME choisi sur <html> (`common/themes.py`, étape 5 du chantier, 2026-10-19).
 *
 * Le serveur pose déjà le thème d'un choix explicite. Ce script ne fait que ce que le serveur ne
 * peut pas savoir : le choix « Automatique » suit le mode clair ou sombre du SYSTÈME
 * (`prefers-color-scheme`), et le suit encore s'il change pendant que la page est ouverte.
 * Chargé de façon SYNCHRONE dans le <head> de base.html : le thème est posé avant le premier
 * rendu, sans éclair.
 *
 * Il ne déclare rien : clés, modes de Bootstrap et correspondance du mode système viennent de
 * `themes.declared_for_pages()`, servis dans `#wama-theme-declared`.
 *
 * `WamaTheme.apply(choix)` change le thème de la page sur place (le Profil s'en sert pour que le
 * choix se voie dès le clic) ; `WamaTheme.choice()` rend le choix courant.
 */
(function () {
    'use strict';
    const root = document.documentElement;
    const node = document.getElementById('wama-theme-declared');
    let declared = null;
    try { declared = node ? JSON.parse(node.textContent) : null; } catch (e) { declared = null; }
    if (!declared || !declared.modes) return;

    const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;
    let current = declared.choice;

    function resolve(choice) {
        if (choice === declared.auto) {
            return declared.system[media && media.matches ? 'light' : 'dark'] || declared.fallback;
        }
        return Object.prototype.hasOwnProperty.call(declared.modes, choice) ? choice : declared.fallback;
    }

    function apply(choice) {
        current = choice;
        const key = resolve(choice);
        root.setAttribute('data-wama-theme', key);
        root.setAttribute('data-bs-theme', declared.modes[key]);
        return key;
    }

    apply(current);
    if (media) {
        const follow = function () { if (current === declared.auto) apply(current); };
        if (media.addEventListener) media.addEventListener('change', follow);
        else if (media.addListener) media.addListener(follow);
    }

    window.WamaTheme = { apply: apply, choice: function () { return current; } };
})();
