# -*- coding: utf-8 -*-
"""Harnais V8 de validation des JS WAMA (2026-07-15).

Usage : python wama-dev-ai/tools/js_v8_harness.py [chemin/du/script.js]
Prérequis (venv_win) : pip install esprima mini-racer

Exécute le script avec un DOM stub et DÉCLENCHE DOMContentLoaded pour capturer les
erreurs RUNTIME réelles (ReferenceError de portée, contrats de briques, etc.) que
l'équilibre de parenthèses et esprima ne voient pas. A trouvé la cause racine de
l'inspecteur studio vide (global jamais défini — PROJECT_STATUS §37.12).
Charger les briques communes réelles (ex. wama-inspector-autofill.js) avant le script
de l'app pour tester les intégrations. Adapter __TARGET au besoin."""
import sys
from py_mini_racer import MiniRacer

ctx = MiniRacer()
stub = r"""
var __errors = [];
var __logs = [];
function El(id) {
    this.id = id || '';
    this.style = {}; this.dataset = {}; this.classList = {
        add: function(){}, remove: function(){}, toggle: function(){}, contains: function(){ return false; }
    };
    this.children = []; this.innerHTML = ''; this.textContent = ''; this.value = '';
}
El.prototype.addEventListener = function(){};
El.prototype.appendChild = function(c){ this.children.push(c); return c; };
El.prototype.querySelector = function(){ return new El(''); };  // parsing innerHTML non simulé : renvoyer un El neutre
El.prototype.querySelectorAll = function(){ return { forEach: function(){} }; };
El.prototype.getBoundingClientRect = function(){ return {left:0, top:0, width:100, height:100}; };
El.prototype.closest = function(){ return null; };
El.prototype.setAttribute = function(){};
El.prototype.getAttribute = function(){ return null; };
El.prototype.removeChild = function(c){ return c; };
El.prototype.click = function(){};

var __ids = {};
var document = {
    readyState: 'loading',
    createElement: function(t){ return new El(''); },
    createElementNS: function(ns, t){ return new El(''); },
    getElementById: function(id){
        if (!(id in __ids)) __ids[id] = new El(id);
        return __ids[id];
    },
    addEventListener: function(ev, fn){ if (ev === 'DOMContentLoaded') __domready = fn; },
    querySelectorAll: function(){ return { forEach: function(){} }; }
};
var __domready = null;
var window = this;
window.addEventListener = function(){};
window.MEDIA_URL = '/media/';
var console = { log: function(m){ __logs.push('log:'+m); },
                warn: function(m){ __logs.push('warn:'+m); },
                error: function(m, e){ __errors.push('console.error:'+m+' :: '+(e && e.message ? e.message : e)); } };
var fetch = function(url){ __logs.push('fetch:'+url);
    return { then: function(){ return this; }, catch: function(){ return this; } }; };
var WamaApp = { toast: function(){}, csrfHeaders: function(){ return {}; } };
"""
ctx.eval(stub)
src = open(sys.argv[1] if len(sys.argv) > 1 else 'wama/studio/static/studio/js/wama-studio.js', encoding='utf-8').read()
try:
    ctx.eval(src)
    print('script évalué OK (IIFE)')
except Exception as e:
    print('ERREUR à l\'évaluation:', e)
    raise SystemExit(1)
# déclencher le DOMContentLoaded
try:
    ctx.eval("if (__domready) __domready();")
    print('init exécuté OK')
except Exception as e:
    print('ERREUR PENDANT init():', str(e)[:600])
print('logs:', ctx.eval('JSON.stringify(__logs)'))
print('errors:', ctx.eval('JSON.stringify(__errors)'))
