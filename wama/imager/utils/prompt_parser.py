"""
Prompt file parser for batch image generation.
Supports text (one prompt per line), JSON, and YAML formats.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def parse_prompt_file(file_path: str) -> List[Dict[str, Any]]:
    """
    Parse a prompt file and return a list of prompt configurations.

    Automatically detects format based on file extension:
    - .txt: One prompt per line
    - .json: JSON array or object
    - .yaml/.yml: YAML format

    Args:
        file_path: Path to the prompt file

    Returns:
        List of dicts, each containing at least 'prompt' key,
        and optionally: negative_prompt, steps, guidance_scale, width, height, seed
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == '.json':
        return parse_json_prompts(file_path)
    elif ext in ('.yaml', '.yml'):
        return parse_yaml_prompts(file_path)
    else:
        return parse_text_prompts(file_path)


def parse_text_prompts(file_path: str) -> List[Dict[str, Any]]:
    """
    Parse a text file with one prompt per line.

    - Empty lines are skipped
    - Lines starting with # are treated as comments
    - Leading/trailing whitespace is stripped

    Format:
        A beautiful sunset over mountains
        A cyberpunk city at night
        # This is a comment
        A medieval castle in a forest
    """
    prompts = []

    # Try multiple encodings
    encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
    content = None

    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue

    if content is None:
        raise ValueError(f"Could not decode file: {file_path}")

    for line in content.splitlines():
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith('#'):
            continue

        prompts.append({'prompt': line})

    logger.info(f"Parsed {len(prompts)} prompts from text file")
    return prompts


def parse_json_prompts(file_path: str) -> List[Dict[str, Any]]:
    """
    Parse a JSON file containing prompts.

    Supported formats:

    1. Array of objects:
        [
            {"prompt": "A sunset", "steps": 30},
            {"prompt": "A city", "negative_prompt": "ugly"}
        ]

    2. Array of strings:
        ["A sunset", "A city", "A castle"]

    3. Single object:
        {"prompt": "A sunset", "steps": 30}
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    prompts = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                prompts.append({'prompt': item})
            elif isinstance(item, dict):
                if 'prompt' in item:
                    prompts.append(item)
                else:
                    logger.warning(f"Skipping JSON item without 'prompt' key: {item}")
            else:
                logger.warning(f"Skipping invalid JSON item: {item}")

    elif isinstance(data, dict):
        if 'prompt' in data:
            prompts.append(data)
        elif 'prompts' in data and isinstance(data['prompts'], list):
            # Support for {"prompts": [...]} format
            return parse_json_prompts_list(data['prompts'])
        else:
            logger.warning("JSON object has no 'prompt' key")

    else:
        raise ValueError(f"Invalid JSON format: expected array or object")

    logger.info(f"Parsed {len(prompts)} prompts from JSON file")
    return prompts


def parse_json_prompts_list(items: List) -> List[Dict[str, Any]]:
    """Parse a list of prompt items from JSON."""
    prompts = []
    for item in items:
        if isinstance(item, str):
            prompts.append({'prompt': item})
        elif isinstance(item, dict) and 'prompt' in item:
            prompts.append(item)
    return prompts


def parse_yaml_prompts(file_path: str) -> List[Dict[str, Any]]:
    """
    Parse a YAML file containing prompts.

    Supported formats:

    1. List of objects:
        - prompt: "A sunset"
          steps: 30
        - prompt: "A city"
          negative_prompt: "ugly"

    2. List of strings:
        - "A sunset"
        - "A city"

    Requires PyYAML to be installed.
    """
    try:
        import yaml
    except ImportError:
        raise ImportError(
            "PyYAML is required for YAML prompt files. "
            "Install it with: pip install pyyaml"
        )

    with open(file_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    prompts = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                prompts.append({'prompt': item})
            elif isinstance(item, dict):
                if 'prompt' in item:
                    prompts.append(item)
                else:
                    logger.warning(f"Skipping YAML item without 'prompt' key: {item}")
            else:
                logger.warning(f"Skipping invalid YAML item: {item}")

    elif isinstance(data, dict):
        if 'prompt' in data:
            prompts.append(data)
        elif 'prompts' in data and isinstance(data['prompts'], list):
            for item in data['prompts']:
                if isinstance(item, str):
                    prompts.append({'prompt': item})
                elif isinstance(item, dict) and 'prompt' in item:
                    prompts.append(item)

    else:
        raise ValueError(f"Invalid YAML format: expected list or object")

    logger.info(f"Parsed {len(prompts)} prompts from YAML file")
    return prompts


def validate_prompt_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and normalize a prompt configuration.

    Args:
        config: Raw prompt configuration dict

    Returns:
        Validated configuration with proper types
    """
    validated = {}

    # Required: prompt
    if 'prompt' not in config:
        raise ValueError("Prompt configuration must have 'prompt' key")
    validated['prompt'] = str(config['prompt']).strip()

    # Optional: negative_prompt
    if 'negative_prompt' in config:
        validated['negative_prompt'] = str(config['negative_prompt']).strip()

    # Optional: numeric parameters
    if 'steps' in config:
        validated['steps'] = int(config['steps'])
        if not 1 <= validated['steps'] <= 100:
            validated['steps'] = max(1, min(100, validated['steps']))

    if 'guidance_scale' in config:
        validated['guidance_scale'] = float(config['guidance_scale'])
        if not 1.0 <= validated['guidance_scale'] <= 20.0:
            validated['guidance_scale'] = max(1.0, min(20.0, validated['guidance_scale']))

    if 'width' in config:
        validated['width'] = int(config['width'])
        if not 64 <= validated['width'] <= 2048:
            validated['width'] = max(64, min(2048, validated['width']))

    if 'height' in config:
        validated['height'] = int(config['height'])
        if not 64 <= validated['height'] <= 2048:
            validated['height'] = max(64, min(2048, validated['height']))

    if 'seed' in config and config['seed'] is not None:
        validated['seed'] = int(config['seed'])

    if 'num_images' in config:
        validated['num_images'] = int(config['num_images'])
        if not 1 <= validated['num_images'] <= 4:
            validated['num_images'] = max(1, min(4, validated['num_images']))

    if 'model' in config:
        validated['model'] = str(config['model']).strip()

    return validated
