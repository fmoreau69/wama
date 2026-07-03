/**
 * WAMA — Appariement card d'entrée ↔ modèles (brique COMMUNE — INPUT_MODEL_MATCHING.md).
 *
 * Doctrine (validée Fabien 2026-07-03, état de l'art Suno/Kling/ComfyUI) :
 *   • ENTRÉE-D'ABORD : une entrée fournie (chip retirable ✕) DÉSACTIVE les modèles incompatibles
 *     — jamais cachés, toujours « grisé + raison » ; la ligne d'état explique la causalité et la
 *     réversibilité (« retirez la chip pour les retrouver »).
 *   • Complément MODÈLE→ENTRÉES : choisir un modèle met en évidence les slots qu'il attend
 *     (requis → lancement gaté avec raison ; optionnel → suggestion), sans jamais bloquer le choix.
 *
 * Déclaratif : `meta` vient du CATALOGUE (AIModel.capabilities.inputs_required/optional, ids
 * d'INPUT_TYPES) ; les libellés d'INPUT_TYPES ; les slots présents dans la card. Zéro hardcode/app.
 *
 * Usage :
 *   const m = WamaInputMatch.init({
 *     selectId: 'modelSelect',
 *     meta: { 'musicgen-melody': { inputs_optional: ['reference_melody'] }, … },
 *     inputLabels: { reference_melody: 'Mélodie de référence' },
 *     slots: { reference_melody: { inputId: 'melodyInput', chipId: 'melodyChip', zoneId: 'melodySlot' } },
 *     statusId: 'inputMatchStatus',
 *     onState: (st) => generateBtn.disabled = !st.launchable,
 *   });
 *   m.refresh() après tout changement programmatique ; m.isLaunchable() avant lancement.
 */
(function (global) {
  'use strict';

  function init(cfg) {
    cfg = cfg || {};
    const select = document.getElementById(cfg.selectId);
    if (!select) return null;
    const meta = cfg.meta || {};
    const labels = cfg.inputLabels || {};
    const slots = cfg.slots || {};
    const status = cfg.statusId ? document.getElementById(cfg.statusId) : null;

    const label = (id) => labels[id] || id;
    const acceptsOf = (mid) => {
      const m = meta[mid] || {};
      return new Set([].concat(m.inputs_required || [], m.inputs_optional || []));
    };
    const requiredOf = (mid) => (meta[mid] || {}).inputs_required || [];

    // ── Entrées fournies (état) ─────────────────────────────────────────────
    function provided() {
      const out = [];
      Object.keys(slots).forEach((sid) => {
        const inp = document.getElementById(slots[sid].inputId);
        if (inp && inp.files && inp.files.length) out.push(sid);
      });
      return out;
    }

    // ── Chips (vignette retirable = l'annulation évidente) ─────────────────
    function renderChips() {
      Object.keys(slots).forEach((sid) => {
        const s = slots[sid];
        const chip = s.chipId ? document.getElementById(s.chipId) : null;
        const inp = document.getElementById(s.inputId);
        if (!chip || !inp) return;
        if (inp.files && inp.files.length) {
          const name = inp.files[0].name;
          chip.innerHTML =
            '<span class="badge bg-info text-dark d-inline-flex align-items-center gap-1">' +
            '<i class="fas fa-paperclip"></i> ' + name.replace(/[<>&]/g, '') +
            ' <button type="button" class="btn-close btn-close-white btn-sm ms-1" ' +
            'title="Retirer (réactive les modèles filtrés)" data-wim-clear="' + sid + '"></button></span>';
          chip.style.display = '';
        } else {
          chip.innerHTML = '';
          chip.style.display = 'none';
        }
      });
    }

    // ── Cœur : appliquer l'appariement dans les deux directions ────────────
    function refresh() {
      const prov = provided();
      const causes = {};   // input_id -> nb de modèles désactivés
      Array.from(select.options).forEach((opt) => {
        if (!opt.value) return;
        const acc = acceptsOf(opt.value);
        const bad = prov.filter((i) => !acc.has(i));
        opt.disabled = bad.length > 0;
        opt.title = bad.length
          ? 'Incompatible avec : ' + bad.map(label).join(', ') + ' — retirez la pièce (✕) pour réactiver'
          : '';
        bad.forEach((i) => { causes[i] = (causes[i] || 0) + 1; });
      });
      // Groupes entièrement désactivés : grisés (pas cachés).
      Array.from(select.querySelectorAll('optgroup')).forEach((g) => {
        const all = Array.from(g.querySelectorAll('option'));
        g.classList.toggle('text-muted', all.length > 0 && all.every((o) => o.disabled));
      });
      // Si le modèle courant vient d'être désactivé → basculer sur le 1er compatible (visible).
      const cur = select.selectedOptions[0];
      if (cur && cur.disabled) {
        const first = Array.from(select.options).find((o) => o.value && !o.disabled);
        if (first) { select.value = first.value; select.dispatchEvent(new Event('change', { bubbles: true })); }
      }
      // Direction MODÈLE→ENTRÉES : mettre en évidence les slots attendus.
      let launchable = true, reason = '';
      const mid = select.value;
      const req = requiredOf(mid).filter((i) => prov.indexOf(i) === -1);
      const opt = ((meta[mid] || {}).inputs_optional || []).filter((i) => prov.indexOf(i) === -1);
      Object.keys(slots).forEach((sid) => {
        const zone = slots[sid].zoneId ? document.getElementById(slots[sid].zoneId) : null;
        if (zone) {
          zone.classList.toggle('wama-slot-required', req.indexOf(sid) !== -1);
          zone.classList.toggle('wama-slot-suggested', opt.indexOf(sid) !== -1);
        }
      });
      if (req.length) { launchable = false; reason = 'Ce modèle requiert : ' + req.map(label).join(', '); }
      // Ligne d'état : causalité + réversibilité, ou attentes du modèle.
      if (status) {
        const parts = [];
        Object.keys(causes).forEach((i) => {
          parts.push(causes[i] + ' modèle(s) désactivé(s) par « ' + label(i) + ' » — ✕ pour les retrouver');
        });
        if (req.length) parts.push('⚠ ' + reason);
        else if (opt.length) parts.push('Ce modèle accepte : ' + opt.map(label).join(', '));
        status.textContent = parts.join(' · ');
        status.style.display = parts.length ? '' : 'none';
      }
      renderChips();
      if (cfg.onState) cfg.onState({ provided: prov, launchable: launchable, reason: reason });
      return { provided: prov, launchable: launchable, reason: reason };
    }

    // ── Écouteurs : slots (fourniture/retrait) + select (direction A) + chips ✕ ──
    Object.keys(slots).forEach((sid) => {
      const inp = document.getElementById(slots[sid].inputId);
      if (inp) inp.addEventListener('change', refresh);
    });
    select.addEventListener('change', refresh);
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-wim-clear]');
      if (!btn) return;
      const s = slots[btn.getAttribute('data-wim-clear')];
      const inp = s && document.getElementById(s.inputId);
      if (inp) { inp.value = ''; refresh(); }
    });

    refresh();
    return { refresh: refresh, isLaunchable: () => refresh().launchable, provided: provided };
  }

  global.WamaInputMatch = { init: init };
})(window);
