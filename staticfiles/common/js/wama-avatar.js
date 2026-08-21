/**
 * WamaAvatar — avatar 3D parlant branché sur le canal de parole commun.
 *
 * POURQUOI CE MODULE. L'assistant disposait déjà de toute la chaîne (STT navigateur → LLM local
 * à outils → TTS Kokoro → `WamaApp.Speech`) : le SEUL maillon manquant était le rendu. Ce module
 * ne refait donc aucun de ces maillons — il se greffe sur l'audio que `Speech` allait jouer.
 *
 * RENDU 100 % NAVIGATEUR (three.js/TalkingHead) : zéro VRAM serveur, aucun conflit avec les
 * files Celery ni le gouverneur de ressources. C'est ce qui distingue cette voie de LiveTalking
 * (photoréaliste, mais une session = un GPU mobilisé).
 *
 * ⚠ MODULE ES6 : à charger en `<script type="module">`, APRÈS l'importmap commune
 * (`common/_three_importmap.html`), qui résout `three`, `three/addons/` et `talkinghead` vers
 * `vendors/`. Sans elle, le navigateur ne sait pas résoudre ces noms et rien ne se charge.
 */
import { TalkingHead } from 'talkinghead';

/** Langues ayant un module de visèmes (lipsync-<lang>.mjs vendorisé). Les autres retombent
 *  sur l'anglais : mieux vaut un lip-sync approximatif qu'un `import()` dynamique en échec. */
const LANGUES_VISEMES = ['fr', 'en', 'de', 'fi', 'lt'];

let head = null;          // instance TalkingHead
let pret = false;         // avatar chargé et affiché
let ctxAudio = null;      // AudioContext partagé (un seul par page)

function langueVisemes(lang) {
  const court = String(lang || 'fr').toLowerCase().split('-')[0];
  return LANGUES_VISEMES.includes(court) ? court : 'en';
}

function contexteAudio() {
  if (!ctxAudio) {
    ctxAudio = new (window.AudioContext || window.webkitAudioContext)();
  }
  return ctxAudio;
}

/**
 * Répartit les mots sur la durée réelle de l'audio, AU PRORATA DE LEUR LONGUEUR.
 *
 * Kokoro ne nous rend pas de timestamps en français : son calcul interne (`join_timestamps`,
 * exact par construction) n'existe que sur la branche anglaise. L'alignement approché est
 * l'arbitrage acté pour le pilote — il suffit à juger si l'avatar convainc, ce qui est la
 * question posée. La voie exacte (remonter les timestamps de Kokoro) reste ouverte, et le
 * catalogue sait déjà DIRE si un moteur en fournit (`timestamp_languages`).
 *
 * Le prorata de longueur bat une répartition uniforme : « anticonstitutionnellement » ne dure
 * pas le même temps que « a ». Ça reste une estimation, pas une mesure.
 */
function estimerTimings(texte, dureeMs) {
  const mots = String(texte || '').trim().split(/\s+/).filter(Boolean);
  if (!mots.length || !dureeMs) return null;
  const total = mots.reduce((n, m) => n + m.length, 0) || mots.length;
  const wtimes = [];
  const wdurations = [];
  let t = 0;
  for (const mot of mots) {
    const part = (mot.length / total) * dureeMs;
    wtimes.push(Math.round(t));
    wdurations.push(Math.round(part));
    t += part;
  }
  return { words: mots, wtimes, wdurations };
}

/**
 * Crée l'avatar dans `node`. Idempotent : un second appel ne recrée rien.
 * @param {HTMLElement} node conteneur (doit avoir une taille non nulle)
 * @param {{glbUrl: string, lang?: string, mood?: string}} opts
 */
export async function init(node, opts) {
  if (head || !node) return head;
  const lang = langueVisemes(opts && opts.lang);
  head = new TalkingHead(node, {
    // Pas de `ttsEndpoint` : la synthèse reste côté WAMA (Kokoro), on ne fait que RENDRE.
    // Le laisser vide évite que TalkingHead tente son propre TTS.
    ttsEndpoint: '',
    lipsyncModules: LANGUES_VISEMES,
    lipsyncLang: lang,          // défaut de la lib = 'fi' (finnois) — à écraser explicitement
    cameraView: 'upper',
    avatarMood: (opts && opts.mood) || 'neutral',
  });
  await head.showAvatar({
    url: opts.glbUrl,
    body: 'F',
    avatarMood: (opts && opts.mood) || 'neutral',
    lipsyncLang: lang,
  });
  pret = true;
  return head;
}

/** Vrai si l'avatar est chargé et peut parler. */
export function estPret() {
  return pret && !!head;
}

/**
 * Fait parler l'avatar sur un audio DÉJÀ synthétisé (Blob WAV rendu par /api/tts-kokoro/).
 * Rend `true` si l'avatar a pris la parole, `false` s'il n'était pas prêt — l'appelant peut
 * alors jouer l'audio normalement (dégradation douce : on ne perd JAMAIS la voix).
 */
export async function speak(blob, texte, lang) {
  if (!estPret() || !blob) return false;
  try {
    const buf = await blob.arrayBuffer();
    // decodeAudioData CONSOMME l'ArrayBuffer : ne pas le réutiliser après cet appel.
    const audio = await contexteAudio().decodeAudioData(buf);
    const timings = estimerTimings(texte, audio.duration * 1000);
    const r = { audio };
    if (timings) Object.assign(r, timings);
    head.speakAudio(r, { lipsyncLang: langueVisemes(lang) });
    return true;
  } catch (e) {
    console.error('[WamaAvatar] speak a échoué — repli sur la voix seule', e);
    return false;
  }
}

/** Coupe la parole en cours (l'utilisateur a relancé une requête). */
export function stop() {
  if (head) { try { head.stopSpeaking(); } catch (_) {} }
}

// Monté en global : le JS de l'assistant est un script CLASSIQUE (pas un module) et ne peut
// pas `import` ce fichier. Même convention que WamaApp/WamaParams.
window.WamaAvatar = { init, speak, estPret, stop };
