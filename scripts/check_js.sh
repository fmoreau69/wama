#!/usr/bin/env bash
# Contrôle syntaxique de tout le JS applicatif WAMA.
#
# Pourquoi : une erreur de syntaxe JS casse SILENCIEUSEMENT une page entière (le navigateur
# arrête le script, rien n'apparaît dans les logs serveur). Deux régressions de ce type ont
# été introduites le 2026-07-29 faute de runtime JS sur l'hôte.
#
# Node est installé en ESPACE UTILISATEUR (pas de sudo) : ~/.local/opt/node
# Réinstaller : voir CAM_ANALYZER_CHANGELOG.md 2026-07-29, ou
#   curl -sL https://nodejs.org/dist/<V>/node-<V>-linux-x64.tar.xz | tar -xJ -C ~/.local/opt
#
# Usage : bash scripts/check_js.sh   (depuis la racine du dépôt, sous WSL2)
set -uo pipefail

export PATH="$HOME/.local/opt/node/bin:$PATH"

if ! command -v node >/dev/null 2>&1; then
    echo "ERREUR : node introuvable (attendu dans ~/.local/opt/node/bin)." >&2
    exit 127
fi

ko=0
n=0
while IFS= read -r f; do
    n=$((n + 1))
    if ! node --check "$f" 2>/dev/null; then
        echo "KO  $f"
        node --check "$f" 2>&1 | sed 's/^/      /' | head -5
        ko=$((ko + 1))
    fi
done < <(find wama wama_lab -name "*.js" \
            -not -path "*/venv*" -not -path "*/node_modules/*" \
            -not -path "*/vendors/*" -not -name "*.min.js" | sort)

echo "=== $n fichiers contrôlés, $ko en erreur ==="

# ── Parité source ↔ staticfiles ────────────────────────────────────────────────────────
# Pourquoi ici : `CLAUDE.md` impose de recopier tout JS/CSS modifié de `wama/<app>/static/`
# vers `staticfiles/<app>/`, et c'est CETTE copie que le serveur sert. Le contrôle syntaxique
# ci-dessus ne balaie que les sources : une copie oubliée laisse donc le script au vert
# pendant que la page tourne avec l'ANCIEN code — exactement le mode de défaillance
# silencieux que ce script existe pour empêcher. Ajouté le 2026-08-20 (0 divergence à la pose,
# 53 paires).
div=0
paires=0
while IFS= read -r src; do
    rel="${src#*/static/}"
    dst="staticfiles/$rel"
    [ -f "$dst" ] || continue
    paires=$((paires + 1))
    if ! cmp -s "$src" "$dst"; then
        echo "DIVERGE  $rel   (recopier vers staticfiles/)"
        div=$((div + 1))
    fi
done < <(find wama -path "*/static/*" -name "*.js" \
            -not -path "*/vendors/*" -not -name "*.min.js" | sort)

echo "=== $paires paires source↔staticfiles, $div divergente(s) ==="
[ "$ko" -eq 0 ] && [ "$div" -eq 0 ]
