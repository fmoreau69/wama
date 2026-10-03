# Construit la page WAMA du rapport d'évaluation des moteurs de transcription (menu « Présentations
# & annexes » › Rapports, `wama.views.REPORTS`) depuis l'export Markdown du rapport Claude Docs :
# rendu par `docs_catalog.render_markdown` (HTML neutralisé), graphiques redessinés en HTML/CSS
# (l'export les remplace par un texte), enveloppe `report_shell.html` (celle de `wama_fiches.html`).
#
# Usage (racine du dépôt, venv_linux) — l'export n'est PAS versionné (ce serait une copie
# concurrente du rapport) :
#     REPORT_MD=/chemin/export.md python manage.py shell < scripts/reports/build_transcription_report.py
#
# ⚠ GRAINE, PAS L'AUTOMATISATION : les données des trois graphiques sont recopiées des widgets du
# rapport (rev 31, 2026-10-02). Le plan qui remplace ce script par une génération depuis les mesures
# en base vit dans `WAMA_QUALITE` (« Rapports d'évaluation générés »).
import html
import os
import re
from pathlib import Path

from wama.common.docs_catalog import render_markdown

HERE = Path('scripts/reports')
SOURCE = Path(os.environ['REPORT_MD'])
OUT = Path('wama/templates/includes/wama_rapport_transcription.html')


def pct(v):
    return f"{v:.1f}".replace('.', ',') + ' %'


# ── Graphique 1 : réunions SUMM-RE, moyenne + étendue d'une réunion à l'autre ───────────────
SUMMRE = [('Whisper', 28.5, 27.4, 30.5), ('Whisper + nivellement', 28.4, 29.4, 30.8),
          ('Qwen3-ASR + nivellement', 30.8, 27.2, 30.8),
          ('Whisper + débruitage, filtre coupé', 28.1, 28.5, 34.4), ('Qwen3-ASR', 30.2, 27.1, 35.2),
          ('Qwen3-ASR + débruitage', 31.6, 28.3, 32.8), ('Whisper + débruitage', 27.9, 29.7, 39.2),
          ('Canary + nivellement', 33.8, 31.8, 33.5), ('Canary + débruitage', 38.4, 32.3, 36.6),
          ('Canary', 34.8, 42.5, 33.8)]


def chart_summre():
    lo_axis, hi_axis = 20.0, 45.0
    pos = lambda v: (v - lo_axis) / (hi_axis - lo_axis) * 100
    rows = sorted(((n, sum(v) / 3, min(v), max(v), v) for n, *v in SUMMRE), key=lambda r: r[1])
    out = []
    for i, (name, mean, lo, hi, v) in enumerate(rows):
        cls = ' best' if i == 0 else ''
        tip = f"{name} : moyenne {pct(mean)} (007a {pct(v[0])}, 012c {pct(v[1])}, 013c {pct(v[2])})"
        out.append(
            f'<div class="rr{cls}" title="{html.escape(tip)}"><span class="lab">{html.escape(name)}</span>'
            f'<span class="track"><span class="rng" style="left:{pos(lo):.1f}%;width:{pos(hi) - pos(lo):.1f}%"></span>'
            f'<span class="dot" style="left:{pos(mean):.1f}%"></span>'
            f'<span class="val" style="left:{pos(hi):.1f}%">{pct(mean)}</span></span></div>')
    ticks = ''.join(f'<span style="left:{pos(t):.1f}%">{t} %</span>' for t in (20, 25, 30, 35, 40, 45))
    return (
        '<figure class="chart"><figcaption><strong>Whisper reste le meilleur sur les réunions '
        'françaises : 28,8 % d\'erreur par mot</strong><span>3 réunions spontanées de 20 min '
        '(SUMM-RE) · point : moyenne · trait : de la meilleure à la moins bonne réunion</span>'
        f'</figcaption><div class="ranges"><div class="rr axis"><span class="lab"></span>'
        f'<span class="track ticks">{ticks}</span></div>{"".join(out)}</div>'
        '<p class="note">Erreur par mot, axe à partir de 20 % — plus bas = mieux.</p></figure>')


# ── Graphique 2 : audio multilingue FLEURS-CS, erreur et accord de langue ───────────────────
FLEURS = [('Whisper', [('Une seule langue', 55.4, 35.9), ('Plusieurs langues', 42.8, 47.6),
                       ('Auto', 41.9, 48.4), ('Auto + nivellement', 37.2, 51.1)]),
          ('Qwen3-ASR', [('Une seule langue', 48.0, 53.0), ('Plusieurs langues', 39.8, 65.4),
                         ('Auto', 39.8, 65.4), ('Auto + nivellement', 32.8, 65.0)]),
          ('Canary', [('Une seule langue', 54.7, 35.7), ('Plusieurs langues', 44.7, 44.1),
                      ('Auto', 44.7, 44.1), ('Auto + nivellement', 43.3, 46.3)])]


def chart_fleurs():
    groups = []
    for engine, rows in FLEURS:
        lines = []
        for cfg, wer, agr in rows:
            cls = ' best' if (engine, cfg) == ('Qwen3-ASR', 'Auto + nivellement') else ''
            lines.append(
                f'<div class="br{cls}"><span class="lab">{cfg}</span>'
                f'<span class="cell"><small class="cnd">Erreur par mot</small><span class="bar">'
                f'<i style="width:{wer / 60 * 100:.1f}%"></i><b>{pct(wer)}</b></span></span>'
                f'<span class="cell"><small class="cnd">Accord de langue</small><span class="bar">'
                f'<i style="width:{agr:.1f}%"></i><b>{pct(agr)}</b></span></span></div>')
        groups.append(f'<div class="grp"><div class="eng">{engine}</div>{"".join(lines)}</div>')
    return (
        '<figure class="chart"><figcaption><strong>Audio multilingue : Qwen3-ASR en Auto avec '
        'nivellement fait le moins d\'erreurs, 32,8 %</strong><span>15 enregistrements de 5 min en '
        '2 à 6 langues (FLEURS-CS) · moyennes après correctifs</span></figcaption>'
        '<div class="bars2"><div class="br head"><span class="lab"></span><span>Erreur par mot '
        '(plus bas = mieux)</span><span>Accord de langue (plus haut = mieux)</span></div>'
        f'{"".join(groups)}</div><p class="note">Accord de langue : part du temps de parole où le '
        'segment transcrit porte la bonne langue.</p></figure>')


# ── Graphique 3 : prétraitements, Whisper, trois conditions ──────────────────────────────
CONDITIONS = ['Entretiens réels (CFPP)', 'Réunions, champ lointain', 'Réunions propres']
PRE = [('Aucun prétraitement', 34.4, 40.3, 28.9), ('Nivellement', 30.4, 36.5, 29.4),
       ('Nivellement + VAD coupé', 29.8, 38.0, 29.4), ('Débruitage', 88.7, 56.0, 31.8),
       ('Nivellement → débruitage', 34.8, 43.4, 31.3), ('Amélioration (Resemble)', 51.7, 87.2, 30.8)]


def chart_pre():
    base = PRE[0][1:]
    head = ''.join(f'<span>{c}</span>' for c in CONDITIONS)
    rows = []
    for cfg, *vals in PRE:
        cls = ' best' if cfg.startswith('Nivellement') and '→' not in cfg else ''
        cells = ''.join(
            f'<span class="cell"><small class="cnd">{cond}</small><span class="bar">'
            f'<em style="left:{b:.1f}%"></em><i style="width:{v:.1f}%"></i>'
            f'<b>{pct(v)}</b></span></span>' for v, b, cond in zip(vals, base, CONDITIONS))
        rows.append(f'<div class="br3{cls}"><span class="lab">{cfg}</span>{cells}</div>')
    return (
        '<figure class="chart"><figcaption><strong>Niveler la parole fait le moins d\'erreurs '
        '(30,4 % contre 34,4 % sur les entretiens réels)</strong><span>Taux d\'erreur par mot, '
        'Whisper large-v3, 3 enregistrements par colonne — plus court = mieux</span></figcaption>'
        f'<div class="bars3"><div class="br3 head"><span class="lab"></span>{head}</div>'
        f'{"".join(rows)}</div><p class="note">Trait vertical : sans prétraitement. Débruitage = '
        'DeepFilterNet, le prétraitement du transcriber. Amélioration = Resemble Enhance, la branche '
        'audio de l\'enhancer. VAD automatique sauf mention.</p></figure>')


md = SOURCE.read_text(encoding='utf-8').splitlines()
assert md[0].startswith('# '), md[0]
title = md[0][2:].strip()
assert md[2].startswith('Oct 2, 2026'), md[2]          # ligne d'attribution du document source
body, charts = [], [chart_summre, chart_fleurs, chart_pre]
for line in md[3:]:
    if line.startswith('&#91;embedded content'):
        line = f'@@CHART{len([b for b in body if b.startswith("@@CHART")]) + 1}@@'
    body.append(line)
rendered = render_markdown('\n'.join(body))['html']
for i, build in enumerate(charts, start=1):
    marker = f'<p>@@CHART{i}@@</p>'
    assert rendered.count(marker) == 1, marker
    rendered = rendered.replace(marker, build())
assert '@@CHART' not in rendered and 'embedded content' not in rendered
rendered = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', rendered)
rendered = rendered.replace('<table>', '<div class="tbl"><table>').replace('</table>', '</table></div>')

page = (HERE / 'report_shell.html').read_text(encoding='utf-8')
page = page.replace('@@TITLE@@', html.escape(title)).replace('@@BODY@@', rendered)
OUT.write_text(page, encoding='utf-8')
print('written', OUT, len(page), 'bytes')
