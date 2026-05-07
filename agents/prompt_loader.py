from pathlib import Path
from typing import Dict

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    prompt_path = PROMPT_DIR / f"{name}.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def load_prompt_json(name: str) -> Dict[str, str]:
    prompt_path = PROMPT_DIR / f"{name}.json"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt JSON file not found: {prompt_path}")
    import json

    return json.loads(prompt_path.read_text(encoding="utf-8"))
