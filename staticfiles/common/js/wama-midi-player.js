/* ===========================================================================
 * WAMA — LA LECTURE MIDI D'UNE PARTITION, sans générer d'audio (2026-11-08)
 * ===========================================================================
 * Demande de Fabien : « si l'on part d'une partition sans fournir l'audio correspondant et que l'on
 * veut jouer la partition et écouter le résultat sans générer d'audio, il faudrait que l'on puisse
 * sélectionner dans le player une version de lecture midi, outre les versions entrée/sortie audio
 * […] avec la meilleure restitution possible ». Veille et choix : `PROSPECTION_PIPELINE.md §Session
 * du 2026-11-08` — SpessaSynth (Apache-2.0), et deux banques de sons à COMPARER à l'écoute.
 *
 * Le rendu est un FICHIER WAV fait dans la page, une fois, à la demande : il devient une version du
 * transport commun comme une autre (`ctx.addSource`), calée sur le même axe que la partition — le
 * lecteur, la position, l'onde, rien n'est réécrit pour le MIDI.
 *
 * Deux moteurs, « ceinture et bretelles » (Fabien) :
 *   • SpessaSynth + une banque (`config.sound_banks.banks`) : son adresse EN LIGNE d'abord quand son
 *     serveur le permet, sa copie VENDORISÉE en secours si l'accès extérieur est coupé ;
 *   • abcjs + sa banque MIDI.js FluidR3_GM, en ligne seulement : coupé, c'est SpessaSynth qui joue.
 * Le rendu DIT d'où vient le son (`from`) : la page l'affiche, rien ne se substitue en silence.
 *
 * API (global `WamaMidiPlayer`) :
 *   render(abc, choice, config) -> Promise<{url, from}>   choice = clé d'une banque, ou 'abcjs'
 *   choices(config) -> [{key, label}]                      les lectures proposées
 * ======================================================================== */
(function (global) {
    'use strict';

    var SAMPLE_RATE = 44100;
    var TAIL_SECONDS = 2;            // la résonance après la dernière note
    var cache = {};                  // `${choix}|${abc}` -> Promise<{url, from}>
    var engine = null;               // le module SpessaSynth, chargé une fois

    function choices(config) {
        var banks = ((config || {}).banks || []).filter(function (b) { return b.local || b.online; });
        var out = banks.map(function (b) { return { key: b.key, label: 'MIDI — ' + b.label }; });
        if ((config || {}).abcjs_online) out.push({ key: 'abcjs', label: 'MIDI — abcjs (en ligne)' });
        return out;
    }

    /** Les octets MIDI d'une partition — texte ABC ou gravure abcjs —, par abcjs. UNE écriture,
     *  lue par la lecture ci-dessous et par l'export de la brique partition (MIDI, audio WAV). */
    function midiBytes(abcOrTune) {
        var midi = global.ABCJS.synth.getMidiFile(abcOrTune, { midiOutputType: 'binary' });
        if (Array.isArray(midi)) midi = midi[0];
        if (!midi || !midi.length) throw new Error('partition sans notes à jouer');
        var bytes = midi instanceof Uint8Array ? midi : new Uint8Array(midi);
        // abcjs rend un fichier sans aucune note plutôt qu'une erreur (mesuré le 2026-11-10) : joué,
        // ce serait un silence, jamais annoncé.
        var placed = programsOnTheirChannels(bytes);
        if (!placed) throw new Error('partition sans notes à jouer');
        return placed;
    }

    /** Chaque changement d'instrument sur le canal des notes de SA piste. abcjs 6.4.4 écrit le canal
     *  0 en dur (`setInstrument` : `%C0`, mesuré le 2026-11-09 sur une vraie partition à 5 voix) : hors
     *  de son propre synthétiseur, la première voix prenait le son du dernier instrument et toutes les
     *  autres celui du piano. Une piste d'abcjs ne joue qu'un canal, et son instrument précède ses notes.
     *  Rend les octets réécrits, ou null si aucune piste ne joue de note. Lu par `parseMidi`, la seule
     *  lecture des octets MIDI de la page (2026-11-15 : la lecture des repères en avait écrit une
     *  seconde à côté de celle-ci). */
    function programsOnTheirChannels(midi) {
        var song = parseMidi(midi);
        if (!song) return null;
        var played = false;
        song.tracks.forEach(function (events) {
            var programs = [];
            for (var i = 0; i < events.length; i++) {
                var status = events[i].bytes[0], kind = status & 240;
                if (status >= 240) continue;
                if (kind === 144) {                      // la première note : le canal de la piste
                    programs.forEach(function (ev) { ev.bytes[0] = 192 | (status & 15); });
                    played = true;
                    return;
                }
                if (kind === 192) programs.push(events[i]);
            }
        });
        return played ? writeMidi(midi, song) : null;
    }

    // ── LE MIDI SUR LES REPÈRES DE LA PARTITION (2026-11-15) ──────────────────────────────────
    // Une partition calée sur un audio (`WamaScore.syncOf` : l'instant d'audio de chaque mesure) se
    // JOUE au même rythme que lui : passer de l'audio au MIDI dans le transport ne déplace rien. Les
    // tempos d'abcjs (le tempo écrit) sont remplacés par un tempo par mesure, chaque mesure durant ce
    // que l'audio lui donne ; le MIDI commence où l'audio place sa mesure 1 (`start`, le décalage de
    // son suiveur sur l'axe). Sans repères, le MIDI garde le tempo écrit et commence à 0.

    function readVar(bytes, at) {
        var value = 0, byte;
        do { byte = bytes[at++]; value = value * 128 + (byte & 127); } while (byte & 128);
        return { value: value, next: at };
    }
    function writeVar(out, value) {
        var stack = [value & 127];
        while ((value = Math.floor(value / 128)) > 0) stack.unshift((value & 127) | 128);
        stack.forEach(function (b) { out.push(b); });
    }

    /** Les pistes d'un MIDI : `{division, tracks: [[{tick, bytes}]]}` — chaque événement avec son
     *  octet d'état ÉCRIT (le statut courant déplié). Null pour un fichier que cette lecture ne sait
     *  pas suivre (division SMPTE, en-tête absent). */
    function parseMidi(midi) {
        var word = function (at) { return (midi[at] * 16777216) + (midi[at + 1] << 16) + (midi[at + 2] << 8) + midi[at + 3]; };
        if (midi[0] !== 77 || midi[1] !== 84 || midi[2] !== 104 || midi[3] !== 100) return null;   // MThd
        var division = (midi[12] << 8) | midi[13];
        if (division & 0x8000) return null;
        var tracks = [], at = 8 + word(4);
        while (at + 8 <= midi.length) {
            var start = at + 8, end = Math.min(start + word(at + 4), midi.length);
            if (midi[at] === 77 && midi[at + 1] === 84 && midi[at + 2] === 114 && midi[at + 3] === 107) {
                var events = [], tick = 0, status = 0, p = start;
                while (p < end) {
                    var delta = readVar(midi, p); p = delta.next; tick += delta.value;
                    if (midi[p] >= 128) status = midi[p++];
                    var from = p, head = [status];
                    if (status === 255) {
                        var type = midi[p++], len = readVar(midi, p);
                        p = len.next + len.value;
                        head.push(type);
                        var body = Array.prototype.slice.call(midi, from + 1, p);
                        events.push({ tick: tick, bytes: head.concat(body), meta: type });
                        continue;
                    }
                    if (status === 240 || status === 247) {
                        var size = readVar(midi, p); p = size.next + size.value;
                        events.push({ tick: tick, bytes: head.concat(Array.prototype.slice.call(midi, from, p)) });
                        continue;
                    }
                    var kind = status & 240;
                    p += (kind === 192 || kind === 208) ? 1 : 2;
                    events.push({ tick: tick, bytes: head.concat(Array.prototype.slice.call(midi, from, p)) });
                }
                tracks.push(events);
            }
            at = end;
        }
        return { division: division, tracks: tracks };
    }

    function writeMidi(header, song) {
        // L'en-tête tel quel : on ne retire ni n'ajoute jamais de piste.
        var out = Array.prototype.slice.call(header, 0, 14);
        song.tracks.forEach(function (events) {
            var body = [], last = 0;
            events.forEach(function (ev) {
                writeVar(body, ev.tick - last); last = ev.tick;
                body.push.apply(body, ev.bytes);
            });
            var n = body.length;
            out.push(77, 84, 114, 107, (n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255);
            out.push.apply(out, body);
        });
        return new Uint8Array(out);
    }

    /** `midi` rejoué au rythme des repères `pairs` (`[[ms écrit, s d'audio]]`) — `{bytes, start}` :
     *  `start` est l'instant d'audio où le MIDI commence. Null si le MIDI ne se suit pas. */
    function retimed(midi, pairs) {
        var song = parseMidi(midi);
        if (!song || !song.tracks.length || !pairs || pairs.length < 2) return null;
        var div = song.division;
        // Le temps ÉCRIT (ms) d'un tick, par les tempos d'abcjs — avant de les retirer.
        var tempi = [];
        song.tracks.forEach(function (events) {
            events.forEach(function (ev) {
                if (ev.meta === 81) tempi.push({ tick: ev.tick, us: (ev.bytes[3] << 16) | (ev.bytes[4] << 8) | ev.bytes[5] });
            });
        });
        tempi.sort(function (a, b) { return a.tick - b.tick; });
        if (!tempi.length || tempi[0].tick > 0) tempi.unshift({ tick: 0, us: 500000 });
        function tickAt(ms) {                     // le tick du temps écrit `ms`
            var i = 0, elapsed = 0;
            for (; i + 1 < tempi.length; i++) {
                var seg = (tempi[i + 1].tick - tempi[i].tick) * tempi[i].us / div / 1000;
                if (elapsed + seg > ms) break;
                elapsed += seg;
            }
            return tempi[i].tick + (ms - elapsed) * 1000 * div / tempi[i].us;
        }
        var marks = pairs.slice().sort(function (a, b) { return a[0] - b[0]; })
            .map(function (p) { return { tick: tickAt(p[0]), s: p[1] }; });
        var fresh = [], lastUs = 500000;
        for (var k = 0; k + 1 < marks.length; k++) {
            var ticks = marks[k + 1].tick - marks[k].tick, seconds = marks[k + 1].s - marks[k].s;
            if (!(ticks > 0) || !(seconds > 0)) continue;
            lastUs = Math.max(1, Math.min(0xFFFFFF, Math.round(seconds * 1e6 * div / ticks)));
            fresh.push({ tick: Math.round(marks[k].tick), us: lastUs });
        }
        if (!fresh.length) return null;
        // Avant le premier repère (une partition qui ne commence pas à son temps écrit 0) : le
        // tempo du premier segment ; le début du MIDI tombe alors d'autant plus tôt dans l'audio.
        var start = marks[0].s - marks[0].tick * fresh[0].us / div / 1e6;
        if (fresh[0].tick > 0) fresh.unshift({ tick: 0, us: fresh[0].us });
        song.tracks = song.tracks.map(function (events, i) {
            var kept = events.filter(function (ev) { return ev.meta !== 81 && ev.meta !== 47; });
            var end = events.reduce(function (m, ev) { return Math.max(m, ev.tick); }, 0);
            if (i === 0) {
                fresh.forEach(function (t) {
                    kept.push({ tick: t.tick, bytes: [255, 81, 3, (t.us >> 16) & 255, (t.us >> 8) & 255, t.us & 255],
                                meta: 81, first: true });
                    end = Math.max(end, t.tick);
                });
            }
            // Un tempo passe avant les notes du même instant ; l'ordre d'origine sinon (tri stable).
            kept = kept.map(function (ev, n) { return { ev: ev, n: n }; }).sort(function (a, b) {
                return a.ev.tick - b.ev.tick || (b.ev.first ? 1 : 0) - (a.ev.first ? 1 : 0) || a.n - b.n;
            }).map(function (x) { return x.ev; });
            kept.push({ tick: end, bytes: [255, 47, 0], meta: 47 });
            return kept;
        });
        return { bytes: writeMidi(midi, song), start: start };
    }

    function midiOf(abc, pairs) {
        var midi = midiBytes(abc), start = 0;
        var again = pairs ? retimed(midi, pairs) : null;
        if (again) { midi = again.bytes; start = again.start; }
        return { data: midi.buffer.slice(midi.byteOffset, midi.byteOffset + midi.byteLength), start: start };
    }

    /** Les octets d'une banque : en ligne d'abord, sa copie locale en secours. `from` le dit. */
    function fetchBank(bank) {
        var tries = [];
        if (bank.online) tries.push({ url: bank.online, from: bank.label + ' (en ligne)' });
        if (bank.local) tries.push({ url: bank.local, from: bank.label + ' (copie locale)' });
        function next(i, lastError) {
            if (i >= tries.length) {
                return Promise.reject(lastError || new Error('banque « ' + bank.label + ' » introuvable'));
            }
            return fetch(tries[i].url, { credentials: tries[i].url.indexOf('http') === 0 ? 'omit' : 'same-origin' })
                .then(function (r) {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.arrayBuffer().then(function (data) { return { data: data, from: tries[i].from }; });
                })
                .catch(function (e) { return next(i + 1, e); });
        }
        return next(0);
    }

    /** Le module de SpessaSynth et son cœur (`BasicMIDI`, que le module n'exporte pas), réunis. */
    function loadEngine(config) {
        if (!engine) {
            var declared = (config || {}).engine || {};
            if (!declared.module || !declared.core) {
                return Promise.reject(new Error('moteur SpessaSynth non déclaré'));
            }
            engine = Promise.all([import(declared.module), import(declared.core)]).then(function (m) {
                return { WorkletSynthesizer: m[0].WorkletSynthesizer,
                         audioBufferToWav: m[0].audioBufferToWav, BasicMIDI: m[1].BasicMIDI };
            });
            engine.catch(function () { engine = null; });
        }
        return engine;
    }

    /** SpessaSynth : le MIDI rendu HORS TEMPS RÉEL avec la banque choisie, en WAV. */
    function renderSpessa(abc, bank, config, pairs) {
        return Promise.all([loadEngine(config), fetchBank(bank)]).then(function (got) {
            var lib = got[0], sound = got[1];
            var made = midiOf(abc, pairs), midiData = made.data;
            // La durée se lit sur le MIDI lui-même (le cœur, `BasicMIDI`), plus une queue.
            var sequence = lib.BasicMIDI.fromArrayBuffer(midiData);
            var seconds = sequence.duration || 60;
            var context = new OfflineAudioContext({ numberOfChannels: 2, sampleRate: SAMPLE_RATE,
                                                    length: Math.ceil((seconds + TAIL_SECONDS) * SAMPLE_RATE) });
            return context.audioWorklet.addModule(config.engine.processor).then(function () {
                var synth = new lib.WorkletSynthesizer(context);
                synth.connect(context.destination);
                return synth.startOfflineRender({
                    midiSequence: sequence,
                    soundBankList: [{ bankOffset: 0, soundBankBuffer: sound.data }],
                    loopCount: 0,
                });
            }).then(function () {
                return context.startRendering();
            }).then(function (buffer) {
                return { url: URL.createObjectURL(lib.audioBufferToWav(buffer)), from: sound.from,
                         start: made.start };
            });
        });
    }

    /** abcjs : sa banque MIDI.js EN LIGNE ; coupée, SpessaSynth avec la première banque.
     *  ⚠ `init` se RÉSOUT même quand ses notes n'ont pas pu être chargées (mesuré le 2026-11-08,
     *  accès coupé : rendu muet annoncé « en ligne »). abcjs 6.4.4 AVALE l'échec d'un lot de notes
     *  (`_loadBatch(...).catch` ne fait que journaliser) : le résultat est alors `{loaded: [],
     *  cached: [], error: []}` — aucune note obtenue = injoignable ; `error` non vide (note hors
     *  de la banque) = incomplet. Une note manquante est un échec, jamais un silence. */
    function renderAbcjs(abc, config) {
        var ABCJS = global.ABCJS;
        var host = document.createElement('div');
        var tune = ABCJS.renderAbc(host, abc, {})[0];
        var synth = new ABCJS.synth.CreateSynth();
        return synth.init({ visualObj: tune, options: { soundFontUrl: config.abcjs_online } })
            .then(function (loaded) {
                loaded = loaded || {};
                var got = (loaded.loaded || []).length + (loaded.cached || []).length;
                var missing = (loaded.error || []).length;
                if (!got) throw new Error('abcjs injoignable');
                if (missing) throw new Error('abcjs incomplet (' + missing + ' notes manquantes)');
                return synth.prime();
            })
            .then(function () { return { url: synth.download(), from: 'abcjs, FluidR3_GM (en ligne)' }; })
            .catch(function (e) {
                var fallback = ((config || {}).banks || []).filter(function (b) { return b.local; })[0];
                var why = /^abcjs /.test((e && e.message) || '') ? e.message : 'abcjs injoignable';
                if (!fallback) throw new Error(why + ', et aucune copie locale');
                return renderSpessa(abc, fallback, config).then(function (got) {
                    return { url: got.url, from: got.from + ' — ' + why };
                });
            });
    }

    /** `pairs` : les repères de la partition (`WamaScore.syncOf`), ou rien — le MIDI les suit et le
     *  rendu dit où il commence (`start`, s d'audio). La lecture d'abcjs ne sait pas les suivre (sa
     *  synthèse ne lit pas un MIDI) : une partition calée ne la propose pas (`syncable`). */
    function render(abc, choice, config, pairs) {
        if (!String(abc || '').trim()) return Promise.reject(new Error('partition vide'));
        var id = choice + '|' + JSON.stringify(pairs || null) + '|' + abc;
        if (!cache[id]) {
            var bank = ((config || {}).banks || []).filter(function (b) { return b.key === choice; })[0];
            cache[id] = (choice === 'abcjs' ? renderAbcjs(abc, config)
                         : bank ? renderSpessa(abc, bank, config, pairs)
                         : Promise.reject(new Error('lecture inconnue : ' + choice)));
            cache[id].catch(function () { delete cache[id]; });   // un échec se retente
        }
        return cache[id];
    }

    /** La lecture `choice` sait-elle suivre des repères ? (les banques, par SpessaSynth ; pas abcjs) */
    function syncable(choice) { return choice !== 'abcjs'; }

    global.WamaMidiPlayer = { render: render, choices: choices, fetchBank: fetchBank, midiBytes: midiBytes,
                              retimed: retimed, parseMidi: parseMidi, syncable: syncable };
})(window);
