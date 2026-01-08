import os
from pathlib import Path
import difflib
import ollama

# ========= BYPASS PROXY =========
# CRITICAL: Désactive le proxy pour localhost
os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'
os.environ['no_proxy'] = 'localhost,127.0.0.1,::1'

# Si tu as des variables proxy définies, supprime-les pour localhost
for var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    if var in os.environ:
        del os.environ[var]

# ========= CONFIG =========
BASE_DIR = Path(__file__).parent
PROMPTS_DIR = BASE_DIR / "prompts"
OUTPUT_DIR = BASE_DIR / "AI-outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# Utilise ollama.Client avec bypass proxy
client = ollama.Client(host="http://127.0.0.1:11434")

MODIFICATIONS = []


# ========= UTILS =========
EXCLUDE_DIRS = {
    "venv",
    "venv_win",
    "venv_linux",
    "site-packages",
    ".git",
    "AI-outputs",
    "__pycache__",
}

def is_allowed_file(path: Path) -> bool:
    for part in path.parts:
        if part in EXCLUDE_DIRS:
            return False
    return True


def resolve_path(user_input: str) -> Path:
    """
    Résout un chemin utilisateur :
    - absolu → utilisé tel quel
    - relatif → résolu par rapport à BASE_DIR
    """
    p = Path(user_input).expanduser()
    if not p.is_absolute():
        p = (BASE_DIR / p).resolve()
    return p


def load_prompt(name):
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def backup_file(path, content):
    backup = OUTPUT_DIR / f"{path.name}.bak"
    backup.write_text(content, encoding="utf-8")


def ask(model, prompt, user_input=None):
    """
    Envoie un prompt à un modèle

    Args:
        model: Nom du modèle Ollama
        prompt: Template de prompt (peut contenir des placeholders)
        user_input: Texte de l'utilisateur pour compléter le prompt
    """
    # Si user_input fourni, remplace les placeholders
    if user_input:
        prompt = prompt.replace("{ma_demande}", user_input)
        prompt = prompt.replace("{code_a_analyser}", user_input)

    print(f"   → {model}")

    try:
        response = client.generate(model=model, prompt=prompt)
        return response["response"]
    except Exception as e:
        print(f"      ❌ Erreur: {e}")
        return None


def diff_stats(old, new):
    diff = list(difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        lineterm=""
    ))
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    preview = "\n".join(diff[:8])
    return added, removed, preview


# ========= FILE PROCESS =========
def process_file(file_path, run_arch, run_vision, vision_path, dry_run, user_request=None):
    print(f"\n▶ {file_path.relative_to(BASE_DIR)}")
    original = file_path.read_text(encoding="utf-8")

    # DEV - Si user_request fourni, l'utilise, sinon analyse le code existant
    if user_request:
        dev_prompt = load_prompt("dev_prompt.txt").replace("{ma_demande}", user_request)
    else:
        dev_prompt = f"""Tu es un développeur expert Python/Django. 
Améliore ce code en appliquant les meilleures pratiques, typage, et optimisations.
Réponds uniquement par le code amélioré sans explications.

Code:
{original}
"""

    dev_code = ask("qwen2.5-coder:32b", dev_prompt)

    if not dev_code:
        print("   ⚠️ Échec Dev, passage au suivant")
        return

    # DEBUG
    debug_prompt = load_prompt("debug_prompt.txt").replace("{code_a_analyser}", dev_code)
    final_code = ask("deepseek-coder-v2:16b", debug_prompt)

    if not final_code:
        print("   ⚠️ Échec Debug, utilisation du code Dev")
        final_code = dev_code

    added, removed, preview = diff_stats(original, final_code)
    print(preview or "✔ Aucun changement majeur")

    if not dry_run and (added or removed):
        backup_file(file_path, original)
        file_path.write_text(final_code, encoding="utf-8")

    MODIFICATIONS.append(f"- {file_path.name}: +{added}/-{removed}")

    # ARCHITECT
    if run_arch:
        arch_prompt = load_prompt("architect_prompt.txt").replace("{code}", final_code)
        analysis = ask("llama3.1:70b", arch_prompt)
        out = OUTPUT_DIR / f"architect_{file_path.stem}.txt"
        out.write_text(analysis, encoding="utf-8")

    # VISION
    if run_vision:
        vision_prompt = load_prompt("vision_prompt.txt").replace(
            "{path}", str(vision_path)
        )
        # CORRECTION: Pour vision avec image, utilise chat avec images
        # Charge l'image en base64
        import base64
        with open(vision_path, 'rb') as f:
            img_data = base64.b64encode(f.read()).decode('utf-8')

        response = client.chat(
            model="llava:34b",
            messages=[{
                'role': 'user',
                'content': vision_prompt,
                'images': [img_data]
            }]
        )
        vision = response['message']['content']

        out = OUTPUT_DIR / f"vision_{vision_path.stem}.txt"
        out.write_text(vision, encoding="utf-8")


# ========= MAIN =========
def main():
    print("\n=== AI WORKFLOW WAMA ===\n")

    # -------- Message utilisateur (optionnel) --------
    print("Message/demande (optionnel, Enter pour skip) :")
    user_request = input("→ ").strip()
    if not user_request:
        user_request = None

    # -------- Choix workflow --------
    print("\nWorkflow :")
    print("1 - Dev + Debug")
    print("2 - Dev + Debug + Architect")
    print("3 - Dev + Debug + Architect + Vision")
    workflow = input("Choix (1/2/3) : ").strip()

    run_arch = workflow in ("2", "3")
    run_vision = workflow == "3"

    vision_path = None
    if run_vision:
        vision_path = Path(input("Chemin image / frame / snapshot : ").strip())
        if not vision_path.exists():
            print("⚠️ Vision ignorée (fichier introuvable)")
            run_vision = False

    # -------- Cible --------
    print("\nCible :")
    print("1 - Tout le projet")
    print("2 - Un dossier")
    print("3 - Un fichier")
    target = input("Choix (1/2/3) : ").strip()

    if target == "1":
        files = list(BASE_DIR.rglob("*.py"))
    elif target == "2":
        folder_input = input("Chemin dossier (relatif au projet ou absolu) : ").strip()
        folder = resolve_path(folder_input)

        if not folder.exists() or not folder.is_dir():
            print(f"❌ Dossier introuvable : {folder}")
            return

        files = list(folder.rglob("*.py"))
    else:
        file_input = input("Chemin fichier (relatif au projet ou absolu) : ").strip()
        file_path = resolve_path(file_input)

        if not file_path.exists() or not file_path.is_file():
            print(f"❌ Fichier introuvable : {file_path}")
            return

        files = [file_path]

    dry_run = input("Dry-run ? (y/n) : ").lower() == "y"

    # -------- Traitement --------
    for f in files:
        if is_allowed_file(f) and f.name != "ai_workflow.py":
            if "AI-outputs" not in str(f) and "ai_workflow" not in str(f):
                try:
                    process_file(
                        file_path=f,
                        run_arch=run_arch,
                        run_vision=run_vision,
                        vision_path=vision_path,
                        dry_run=dry_run,
                        user_request=user_request,
                    )
                except Exception as e:
                    print(f"❌ Erreur sur {f.name}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

    # -------- Génération commit --------
    title_parts = ["AI:"]

    if workflow == "1":
        title_parts.append("Dev+Debug")
    elif workflow == "2":
        title_parts.append("Dev+Debug+Architect")
    else:
        title_parts.append("Dev+Debug+Architect+Vision")

    title_parts.append("refactor WAMA")
    commit_title = " ".join(title_parts)

    commit_body = []
    commit_body.append("Models used:")
    commit_body.append("- Dev: Qwen2.5-Coder 32B")
    commit_body.append("- Debug: DeepSeek-Coder-V2 16B")

    if run_arch:
        commit_body.append("- Architect: Llama 3.1 70B")
    if run_vision:
        commit_body.append("- Vision: Llava 34B")

    commit_body.append("\nModified files:")
    if MODIFICATIONS:
        commit_body.extend(MODIFICATIONS)
    else:
        commit_body.append("- Aucun changement significatif")

    # -------- Affichage final --------
    print("\n=== COMMIT PROPOSÉ ===\n")
    print(commit_title)
    print("\n".join(commit_body))

    if not dry_run:
        print("\nCommandes recommandées :\n")
        print("git add .")
        print(
            'git commit -m "{title}" -m "{body}"'.format(
                title=commit_title,
                body="\\n".join(commit_body),
            )
        )
    else:
        print("\n(Dry-run activé : aucun fichier modifié, aucun commit)")


if __name__ == "__main__":
    main()