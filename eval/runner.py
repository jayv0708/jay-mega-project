from pathlib import Path


def load_cases(directory: Path):
    return [path for path in directory.glob("*.json") if path.is_file()]


def run_all_cases(cases_directory: Path):
    cases = load_cases(cases_directory)
    return {"total_cases": len(cases), "cases": [str(case.name) for case in cases]}
