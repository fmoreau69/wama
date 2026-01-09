# WAMA Dev AI

AI-powered development assistant for WAMA, inspired by Claude Code.

Uses local LLMs via Ollama for privacy-first AI-assisted development.

## Features

- **Smart File Discovery**: Semantic search to find relevant files instead of scanning everything
- **Beautiful Console Output**: Colored diffs, progress bars, and formatted output using Rich
- **Multi-Model Workflow**: Chain multiple AI models for different tasks (Dev → Debug → Architect)
- **Tool-Based Architecture**: AI can read, search, and edit files using tools
- **Git-Aware**: Automatic backups and change tracking

## Quick Start

### Prerequisites

1. **Install Ollama**: https://ollama.ai
2. **Pull required models**:
```bash
# Essential
ollama pull qwen2.5-coder:7b     # Fast development
ollama pull qwen2.5-coder:32b    # Quality development
ollama pull deepseek-coder-v2:16b # Code review

# Optional
ollama pull llama3.1:70b         # Architecture analysis
ollama pull llava:34b            # Vision/image analysis
ollama pull nomic-embed-text     # Semantic search
```

3. **Install Python dependencies**:
```bash
pip install -r wama-dev-ai/requirements.txt
```

### Run

```bash
# Interactive mode
python wama-dev-ai/run.py

# Or as a module
python -m wama-dev-ai

# Non-interactive (single task)
python wama-dev-ai/run.py -t "Fix the bug in views.py"
```

## Usage

### Interactive Mode

```
You: /help                  # Show commands
You: /search views.py       # Search for files
You: /read wama/imager/views.py  # Read a file
You: /workflow              # Run a full workflow

You: Fix the error handling in the transcriber
     # Natural language request - AI will find files and help
```

### Workflows

| Workflow | Models | Description |
|----------|--------|-------------|
| `quick` | Fast Qwen 7B | Quick single-model fix |
| `standard` | Dev + Debug | Development with code review |
| `full` | Dev + Debug + Architect | Full analysis with architecture review |
| `vision` | All + Vision | Includes image/screenshot analysis |

### Commands

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/search <query>` | Search for files by content or name |
| `/read <path>` | Read and display a file |
| `/workflow` | Run a development workflow |
| `/models` | Show available models |
| `/clear` | Clear screen |
| `/exit` | Exit |

## Architecture

```
wama-dev-ai/
├── cli.py              # Main CLI entry point
├── config.py           # Configuration (models, paths, themes)
├── run.py              # Quick runner script
├── requirements.txt    # Python dependencies
├── core/
│   ├── llm.py          # LLM client (Ollama interface)
│   ├── files.py        # Smart file discovery
│   └── tools.py        # Tool system for AI
├── ui/
│   ├── console.py      # Rich console wrapper
│   └── diff.py         # Colored diff renderer
├── prompts/
│   ├── system.txt      # System prompt
│   ├── dev.txt         # Developer prompt
│   ├── debug.txt       # Code review prompt
│   └── architect.txt   # Architecture prompt
└── outputs/            # Generated outputs and backups
```

## Key Features Explained

### 1. Smart File Discovery

Instead of scanning all files, the AI:
- Extracts keywords from your request
- Searches by content and file names
- Uses semantic embeddings (if available) for intelligent matching
- Prioritizes important files (views.py, models.py, etc.)

### 2. Colored Diffs

Changes are displayed with:
- Green for additions
- Red for deletions
- Line numbers and context
- Syntax highlighting

### 3. Tool-Based Architecture

The AI can call tools to:
- `read_file`: Read file contents
- `edit_file`: Make changes to files
- `search_files`: Find files by pattern
- `search_content`: Search text in files
- `run_command`: Execute shell commands

### 4. Streaming Responses

Responses are streamed in real-time, so you see the AI thinking as it works.

## Configuration

Edit `config.py` to customize:
- Model assignments for each role
- Excluded directories
- Code file extensions
- Console theme colors

## Tips

1. **Be specific**: "Fix the null pointer in transcriber/views.py line 42" works better than "fix bugs"
2. **Use workflows**: For significant changes, use `/workflow` to get Dev + Review
3. **Check diffs**: Always review the colored diff before applying changes
4. **Use search**: When unsure where code is, use `/search` first

## Comparison with Claude Code

| Feature | WAMA Dev AI | Claude Code |
|---------|-------------|-------------|
| LLM | Local (Ollama) | Claude API |
| Privacy | 100% local | Cloud-based |
| Cost | Free | API costs |
| Speed | Depends on hardware | Fast |
| Quality | Good (with good models) | Excellent |
| Features | Core features | Full features |

## Future Plans

- [ ] Integration with WAMA web interface
- [ ] Persistent conversation memory
- [ ] Git commit generation
- [ ] Test generation
- [ ] Documentation generation
- [ ] Multi-file refactoring

## Troubleshooting

### "Model not found"
```bash
ollama pull <model-name>
```

### "Connection refused"
Start Ollama:
```bash
ollama serve
```

### Slow performance
- Use smaller models (`qwen2.5-coder:7b` instead of `:32b`)
- Ensure GPU is being used (check `nvidia-smi`)
- Reduce context with targeted file selection

## License

Part of the WAMA project.
