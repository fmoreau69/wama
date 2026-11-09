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
        return programsOnTheirChannels(midi instanceof Uint8Array ? midi : new Uint8Array(midi));
    }

    /** Chaque changement d'instrument sur le canal des notes de SA piste. abcjs 6.4.4 écrit le canal
     *  0 en dur (`setInstrument` : `%C0`, mesuré le 2026-11-09 sur une vraie partition à 5 voix) : hors
     *  de son propre synthétiseur, la première voix prenait le son du dernier instrument et toutes les
     *  autres celui du piano. Une piste d'abcjs ne joue qu'un canal, et son instrument précède ses notes. */
    function programsOnTheirChannels(midi) {
        var word = function (at) { return (midi[at] * 16777216) + (midi[at + 1] << 16) + (midi[at + 2] << 8) + midi[at + 3]; };
        var at = 8 + word(4);
        while (at + 8 <= midi.length) {
            var start = at + 8, end = start + word(at + 4);
            if (midi[at] === 77 && midi[at + 1] === 84 && midi[at + 2] === 114 && midi[at + 3] === 107) { // MTrk
                moveProgramsOfTrack(midi, start, Math.min(end, midi.length));
            }
            at = end;
        }
        return midi;
    }

    function moveProgramsOfTrack(midi, at, end) {
        var programs = [], status = 0;
        function skipLength() {
            var size = 0, byte;
            do { byte = midi[at++]; size = size * 128 + (byte & 127); } while ((byte & 128) && at < end);
            return size;
        }
        while (at < end) {
            skipLength();                            // le délai de l'événement
            var explicit = midi[at] >= 128;
            if (explicit) status = midi[at++];
            if (status === 255) { at++; var meta = skipLength(); at += meta; continue; }
            if (status === 240 || status === 247) { var sysex = skipLength(); at += sysex; continue; }
            var kind = status & 240;
            if (kind === 144) {                      // la première note : le canal de la piste
                programs.forEach(function (where) { midi[where] = 192 | (status & 15); });
                return;
            }
            if (kind === 192 && explicit) programs.push(at - 1);
            at += (kind === 192 || kind === 208) ? 1 : 2;
        }
    }

    function midiOf(abc) {
        var midi = midiBytes(abc);
        return midi.buffer.slice(midi.byteOffset, midi.byteOffset + midi.byteLength);
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
    function renderSpessa(abc, bank, config) {
        return Promise.all([loadEngine(config), fetchBank(bank)]).then(function (got) {
            var lib = got[0], sound = got[1];
            var midiData = midiOf(abc);
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
                return { url: URL.createObjectURL(lib.audioBufferToWav(buffer)), from: sound.from };
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

    function render(abc, choice, config) {
        if (!String(abc || '').trim()) return Promise.reject(new Error('partition vide'));
        var id = choice + '|' + abc;
        if (!cache[id]) {
            var bank = ((config || {}).banks || []).filter(function (b) { return b.key === choice; })[0];
            cache[id] = (choice === 'abcjs' ? renderAbcjs(abc, config)
                         : bank ? renderSpessa(abc, bank, config)
                         : Promise.reject(new Error('lecture inconnue : ' + choice)));
            cache[id].catch(function () { delete cache[id]; });   // un échec se retente
        }
        return cache[id];
    }

    global.WamaMidiPlayer = { render: render, choices: choices, fetchBank: fetchBank, midiBytes: midiBytes };
})(window);
