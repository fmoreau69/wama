/* ==========================================================================
   WAMA — constellation des utilisateurs (2026-10-20, demande de Fabien) : l'ADAPTATEUR de la
   scène `users` sur la brique commune (`wama/constellation`, `common/js/wama-constellation.js`).

   Chaque personne est une étoile ; la DISTANCE entre deux étoiles se calcule de ce qui les lie,
   avec des poids réglables (facteurs déclarés par la scène, `accounts/constellation.py`) :
     - un partage (dans un sens ou dans l'autre) rapproche ;
     - un projet commun rapproche ;
     - une unité commune rapproche, d'autant plus qu'elle est fine (équipe > labo > établissement) ;
     - des métiers communs rapprochent un peu.
   Des sphères translucides enveloppent les membres d'une même unité (arbre LDAP/SUPANN) ou d'un
   même projet. Les satellites d'une étoile sont ce qu'elle a fait entrer dans WAMA.

   Les FAITS viennent de `accounts:user-constellation-data` (`accounts/constellation.py`) ; ce
   module les met au contrat de la brique et rend le volet d'une personne et la légende. Tout le
   reste — rendu, forces, sphères, liens, étiquettes, HUD — est la brique.
   ========================================================================== */
import { mountConstellation, css, esc, initials, fmtDate } from 'wama/constellation';

// Palettes de DESSIN propres à la scène (aucune donnée ne les porte ailleurs) : un point par rôle
// métier, un satellite par famille du catalogue.
const ROLE_PALETTE = [0x93c5fd, 0xf9a8d4, 0xfcd34d, 0x86efac, 0xc4b5fd, 0xfda4af];
const FAMILY_STYLE = {
  models: { color: 0xc4b5fd, shape: 'octa' },
  functions: { color: 0xfcd34d, shape: 'tetra' },
  skills: { color: 0xf9a8d4, shape: 'box' },
  themes: { color: 0x86efac, shape: 'torus' },
  sandbox_apps: { color: 0x38e1ff, shape: 'ico' },
};
const FAMILY_DEFAULT = { color: 0xe2e8f0, shape: 'dodeca' };
const familyStyle = key => FAMILY_STYLE[key] || FAMILY_DEFAULT;
const unitId = id => 'u' + id, projectId = id => 'p' + id;

let F = null;                         // les faits, indexés une fois

// ── Les faits → le contrat de la brique ───────────────────────────────
function adapt(data) {
  const roleIndex = new Map(data.roles.map((r, i) => [r.key, i]));
  const projectsOf = new Map();     // user id → [ {project, role} ]
  for (const p of data.projects) for (const m of p.members) {
    if (!projectsOf.has(m.user)) projectsOf.set(m.user, []);
    projectsOf.get(m.user).push({ project: p, role: m.role_label });
  }
  const shareOut = new Map(), shareIn = new Map();
  for (const s of data.shares) {
    if (!shareOut.has(s.from)) shareOut.set(s.from, []); shareOut.get(s.from).push(s);
    if (!shareIn.has(s.to)) shareIn.set(s.to, []); shareIn.get(s.to).push(s);
  }
  F = { data, roleIndex, projectsOf, shareOut, shareIn,
        unitById: new Map(data.units.map(u => [String(u.id), u])),
        userById: new Map(data.users.map(u => [u.id, u])),
        roleLabel: k => (data.roles.find(r => r.key === k) || {}).label || k,
        familyLabel: k => (data.families.find(f => f.key === k) || {}).label || k,
        tierLabel: k => (data.tiers.find(t => t.key === k) || {}).label || k };

  const groups = [
    // L'arbre des unités : une sphère par membres distincts (la brique fond les unités aux MÊMES
    // membres) ; une unité générique de l'annuaire (`autre`) nomme moins bien qu'une unité typée.
    ...data.units.map(u => ({ id: unitId(u.id), kind: 'unit', name: u.name, type: u.type,
      sub: u.type_label + (u.source === 'profile' ? ' · profil LDAP' : ''),
      parent: u.parent != null ? unitId(u.parent) : null, weak: u.type === 'autre', color: `--wc-unit-${u.type}` })),
    ...data.projects.map(p => ({ id: projectId(p.id), kind: 'project', name: p.name, sub: 'Projet',
      color: '--wc-project', members: p.members.map(m => m.user) })),
  ];
  const nodes = data.users.map(u => {
    const total = u.activity.reduce((s, a) => s + a.total, 0);
    const worlds = {};
    for (const a of u.activity) worlds[a.monde] = (worlds[a.monde] || 0) + a.total;
    const topWorld = Object.entries(worlds).sort((a, b) => b[1] - a[1])[0];
    const items = Object.entries(u.contributions).flatMap(([fam, f]) => f.items.map(it => ({ fam, ...it })));
    return {
      id: u.id, seed: u.id, name: u.name, handle: u.username, sub: u.org.entity || u.tier_label,
      size: total, faded: !u.active, layer: u.kind === 'person' ? null : 'tests',
      groups: [...u.units.map(unitId), ...(projectsOf.get(u.id) || []).map(x => projectId(x.project.id))],
      sets: { roles: u.roles },
      cats: { tier: u.tier, world: topWorld ? topWorld[0] : null },
      // Anneau des métiers : un point par rôle tenu, à sa place dans le catalogue des rôles.
      ring: u.roles.map(k => { const i = roleIndex.get(k) ?? 0; return { slot: i, of: data.roles.length, color: ROLE_PALETTE[i % ROLE_PALETTE.length] }; }),
      // Satellites : ce que la personne a fait entrer dans WAMA (un par élément, plafonné côté serveur).
      sats: items.map(it => { const st = familyStyle(it.fam);
        return { shape: st.shape, color: it.status === 'promoted' ? 0xffffff : st.color, opacity: it.status === 'owned' ? 0.55 : 1 }; }),
      data: u,
    };
  });
  // Partages À UNE PORTÉE : un faisceau de la personne vers sa sphère (unité, projet) ou vers le
  // cœur (tout le monde).
  const beams = data.users.flatMap(u => u.scope_shares.map(sc => ({ from: u.id,
    to: sc.unit != null ? unitId(sc.unit) : sc.project != null ? projectId(sc.project) : null })));
  return {
    nodes, groups, beams,
    links: data.shares.map(s => ({ from: s.from, to: s.to, count: s.count })),
    colorings: {
      tier: { palette: Object.fromEntries(data.tiers.map(t => [t.key, `--wc-tier-${t.key}`])), fallback: 0x94a3b8 },
      world: { palette: Object.fromEntries(Object.keys(data.worlds).map(w => [w, `--wc-world-${w}`])), fallback: 0x64748b },
    },
  };
}

// Couleurs lues des jetons (`wama-constellation.css`) — un profil ou un monde inconnu des faits
// garde la couleur neutre de la scène.
const tierColor = (api, k) => F.data.tiers.some(t => t.key === k) ? api.color(`--wc-tier-${k}`) : 0x94a3b8;
const worldColor = (api, w) => w in F.data.worlds ? api.color(`--wc-world-${w}`) : 0x64748b;
// Le nom d'une personne tel qu'on le MONTRE : en clair, ou ses initiales quand les noms sont masqués.
const shownUser = (api, u) => api.masked() ? initials(u.name) : u.name;

function tip(n, api) {
  const u = n.d.data, data = F.data, total = n.d.size;
  return `<b>${esc(api.shownName(n))}</b>${!api.masked() ? ` <span class="mute">@${esc(u.username)}</span>` : ""}<br>${esc(u.tier_label)}` +
    (u.roles.length ? ' · ' + u.roles.map(k => esc(F.roleLabel(k))).join(', ') : '') +
    (u.org.entity ? `<br>${esc(u.org.entity)}` : '') +
    `<br><span class="mute">${total} élément${total > 1 ? 's' : ''} traités · ${u.apps.length}/${data.apps.length} outils</span>`;
}

function legend(api) {
  const data = F.data;
  const types = [...new Set(api.spheres.filter(s => s.kind === 'unit').map(s => s.obj.type))];
  const uncarried = data.uncarried_families.map(f => esc(f.label)).join(', ');
  return `<h2>Lire la constellation</h2>
      <p>Chaque étoile est une personne. Cliquez-en une pour tout voir d'elle : profil, métiers, droits, projets, partages, contributions et activité.</p>
      <h3>Étoiles</h3>
      ${(api.state.colorBy === 'tier' ? data.tiers.map(t => [t.label, api.color(`--wc-tier-${t.key}`)]) : Object.entries(data.worlds).map(([k, l]) => [l, worldColor(api, k)]))
        .map(([l, c]) => `<div class="wc-legend-row"><span class="sw star" style="--c:${css(c)}"></span>${esc(l)}</div>`).join('')}
      <p class="mute">Taille = volume traité (journal). Étoile pâle = compte inactif.</p>
      <div class="wc-legend-row"><span class="sw" style="--c:${css(ROLE_PALETTE[0])};width:6px;height:6px;border:0;background:${css(ROLE_PALETTE[0])}"></span>Anneau de points : un par métier tenu</div>
      ${data.families.map(f => `<div class="wc-legend-row"><span class="sw sat" style="--c:${css(familyStyle(f.key).color)}"></span>Satellite : ${esc(f.label)}</div>`).join('')}
      <h3>Sphères</h3>
      ${types.map(tp => `<div class="wc-legend-row"><span class="sw" style="--c:${css(api.color(`--wc-unit-${tp}`))}"></span>${esc((data.units.find(u => u.type === tp) || {}).type_label || tp)}</div>`).join('')}
      <div class="wc-legend-row"><span class="sw" style="--c:${css(api.color('--wc-project'))}"></span>Projet</div>
      <p class="mute">Une sphère enveloppe les membres d'une unité de l'annuaire (et de ses sous-unités) ou d'un projet ; les plus larges englobent les plus fines.</p>
      <h3>Liens</h3>
      <div class="wc-legend-row"><span class="sw line" style="--c:${css(api.color('--wc-share'))}"></span>Partage à une personne — les particules vont de celui qui partage à celui qui reçoit</div>
      <div class="wc-legend-row"><span class="sw line" style="--c:${css(api.color('--wc-core'))}"></span>Pointillés : partage à une unité, un projet ou à tous (vers le cœur)</div>
      ${!data.projects.length ? '<p class="mute">Aucun projet n\'est déclaré pour l\'instant.</p>' : ''}
      ${uncarried ? `<h3>Pas encore montré</h3><p class="mute">Ces familles du catalogue ne portent pas encore leur auteur (ROADMAP §29) : ${uncarried}.</p>` : ''}`;
}

function detail(n, api) {
  const u = n.d.data, data = F.data, total = n.d.size, c = css(n.color);
  const sections = [];
  // Organisation
  const units = u.units.map(id => F.unitById.get(String(id))).filter(Boolean);
  sections.push(`<h3>Organisation</h3><dl class="wc-kv">
      ${u.org.path ? `<dt>Rattachement</dt><dd>${esc(u.org.path)}</dd>` : ''}
      ${u.org.establishment ? `<dt>Établissement</dt><dd>${esc(u.org.establishment)}</dd>` : ''}
      ${u.org.affiliation ? `<dt>Affiliation</dt><dd>${esc(u.org.affiliation)}</dd>` : ''}
      ${units.length ? `<dt>Unités</dt><dd>${units.map(x => `${esc(x.name)} <span class="mute">${esc(x.type_label)}</span>${x.source === 'profile' ? '<span class="wc-tag" title="Portée par le profil LDAP, absente de l\'arbre des unités synchronisé">profil</span>' : ''}`).join('<br>')}</dd>` : ''}
      </dl>${!u.org.path && !units.length ? '<p class="mute">Aucun rattachement connu (compte local ou annuaire sans entité).</p>' : ''}`);
  // Projets
  const projs = F.projectsOf.get(u.id) || [];
  sections.push(`<h3>Projets</h3>${projs.length ? `<ul>${projs.map(x => `<li><b>${esc(x.project.name)}</b> <span class="mute">${esc(x.role)}</span></li>`).join('')}</ul>` : '<p class="mute">Aucun projet.</p>'}`);
  // Droits
  const can = new Set(u.apps);
  const byWorld = {};
  for (const a of data.apps) (byWorld[a.world || 'autre'] = byWorld[a.world || 'autre'] || []).push(a);
  sections.push(`<h3>Droits · ${u.apps.length}/${data.apps.length} outils</h3>` + Object.entries(byWorld).map(([w, apps]) => {
    const wc = css(worldColor(api, w)), k = apps.filter(a => can.has(a.id)).length;
    return `<div class="wc-world"><div class="wc-world-head"><span style="color:${wc}">${esc(data.worlds[w] || w)}</span><span>${k}/${apps.length}</span></div>
        <div class="wc-apps">${apps.map(a => `<span class="wc-app${can.has(a.id) ? '' : ' no'}" style="--c:${wc}">${esc(a.label)}</span>`).join('')}</div></div>`;
  }).join('') + (u.active ? '' : '<p class="mute">Compte inactif : aucun outil ouvert.</p>'));
  // Contributions
  const fams = Object.entries(u.contributions);
  const uncarried = data.uncarried_families.map(f => esc(f.label)).join(', ');
  sections.push(`<h3>Apports à WAMA</h3>` + (fams.length ? fams.map(([k, f]) => {
    const tot = f.owned + f.shared + f.promoted;
    const detailLine = [f.owned && `${f.owned} privé${f.owned > 1 ? 's' : ''}`, f.shared && `${f.shared} partagé${f.shared > 1 ? 's' : ''}`, f.promoted && `${f.promoted} promu${f.promoted > 1 ? 's' : ''} au système`].filter(Boolean).join(' · ');
    return `<div class="wc-family"><div class="wc-family-head"><span class="sw" style="--c:${css(familyStyle(k).color)}"></span>${esc(F.familyLabel(k))}<span class="n">${tot}</span></div>
        <div class="items">${f.items.map(it => it.status === 'promoted' ? `<em>${esc(it.name)}</em>` : esc(it.name)).join(', ')}${tot > f.items.length ? '…' : ''}<br><span class="mute">${detailLine}</span></div></div>`;
  }).join('') : '<p class="mute">Rien d\'ajouté au catalogue pour l\'instant.</p>') +
    (uncarried ? `<p class="mute">Non suivi par auteur : ${uncarried}.</p>` : ''));
  // Activité
  const act = u.activity.slice(0, 8), max = Math.max(1, ...act.map(a => a.total));
  sections.push(`<h3>Activité · ${total} élément${total > 1 ? 's' : ''}</h3>` + (act.length ? act.map(a =>
    `<div class="wc-bar" style="--c:${css(worldColor(api, a.monde))}"><span>${esc(a.label)}</span><span>${a.total}</span><i style="width:${Math.max(3, a.total / max * 100)}%"></i></div>`).join('') +
    (u.activity.length > act.length ? `<p class="mute">et ${u.activity.length - act.length} autre(s) outil(s).</p>` : '') : '<p class="mute">Aucun élément au journal.</p>'));
  // Partages
  const out = F.shareOut.get(u.id) || [], inn = F.shareIn.get(u.id) || [];
  const who = id => { const x = F.userById.get(id); return x ? `<b data-goto="${id}" style="cursor:pointer">${esc(shownUser(api, x))}</b>` : '?'; };
  const lv = s => Object.entries(s.levels).map(([k, m]) => `${m} × ${esc((data.levels[k] || k).toLowerCase())}`).join(', ');
  // La portée : l'unité ou le projet NOMMÉ quand il y en a un, sinon le libellé déclaré de la portée.
  const scopeName = sc => (sc.unit != null && (F.unitById.get(String(sc.unit)) || {}).name)
    || (sc.project != null && (data.projects.find(p => p.id === sc.project) || {}).name)
    || data.scopes[sc.visibility] || sc.visibility;
  const shareLines = [
    ...out.map(s => `<li>→ ${who(s.to)} <span class="mute">${lv(s)}</span></li>`),
    ...inn.map(s => `<li>← ${who(s.from)} <span class="mute">${lv(s)}</span></li>`),
    ...u.scope_shares.map(sc => `<li>⇢ ${esc(scopeName(sc))} <span class="mute">${sc.count} élément${sc.count > 1 ? 's' : ''}</span></li>`),
  ];
  sections.push(`<h3>Partages</h3>${shareLines.length ? `<ul>${shareLines.join('')}</ul>` : '<p class="mute">Aucun partage en vigueur.</p>'}`);
  // Proximités
  const near = api.nearest(n);
  sections.push(`<h3>Les plus proches</h3>${near.length ? `<ul class="wc-near">${near.map(x =>
    `<li data-goto="${x.o.id}"><span>${esc(api.shownName(x.o))}</span><span>${x.af.total.toFixed(1)}</span><small>${esc(x.af.why.join(' · '))}</small></li>`).join('')}</ul>`
    : '<p class="mute">Rien ne relie encore ce compte aux autres : son étoile flotte librement.</p>'}`);

  return `<button type="button" class="wc-close" title="Fermer (Échap)">×</button>
      <div class="wc-id"><div class="wc-avatar" style="--c:${c}">${esc(initials(u.name))}</div>
        <div><h2>${esc(api.shownName(n))}</h2>${!api.masked() ? `<div class="wc-handle">@${esc(u.username)}</div>` : ""}</div></div>
      <div class="wc-badges">
        <span class="wc-badge tier" style="--c:${css(tierColor(api, u.tier))}">${esc(F.tierLabel(u.tier))}</span>
        ${u.roles.map(k => `<span class="wc-badge"><span class="sw" style="--c:${css(ROLE_PALETTE[(F.roleIndex.get(k) ?? 0) % ROLE_PALETTE.length])}"></span>${esc(F.roleLabel(k))}</span>`).join('')}
        ${u.active ? '' : '<span class="wc-badge off">Inactif</span>'}
        ${u.kind !== 'person' ? `<span class="wc-badge">${esc(data.account_kinds[u.kind] || u.kind)}</span>` : ''}
      </div>
      <p class="mute" style="margin-top:8px">Inscrit le ${fmtDate(u.joined)} · dernière connexion ${fmtDate(u.last_login)}</p>
      ${sections.join('')}`;
}

mountConstellation(document.getElementById('wc-users'), { adapt, hooks: { tip, legend, detail } });
