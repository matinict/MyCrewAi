"""
CSV Writer Tool
Writes agent-researched time-series data to output/{filename}.csv

Key features:
- Deterministic filename from first 3 words of topic
- Founding-year enforcement: zeroes out values before a tool/framework actually existed
- __file__-anchored output path (CWD-independent — crewai tools run with CWD = /)
"""

import csv
import os
import re
from crewai.tools import BaseTool
from typing import Type, Union, List, Dict
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Founding year database
# Any column whose name matches a key here will be zeroed for years before
# that tool/framework/language actually existed.
# Keys are lowercase; matching is case-insensitive substring.
# ---------------------------------------------------------------------------
FOUNDING_YEARS: Dict[str, int] = {
    # AI/ML Frameworks
    "tensorflow": 2015, "tf": 2015,
    "pytorch": 2016,
    "keras": 2015,
    "scikit-learn": 2007, "sklearn": 2007,
    "jax": 2018,
    "mxnet": 2015,
    "theano": 2010,
    "caffe": 2014,
    "caffe2": 2017,
    "paddlepaddle": 2016, "paddle": 2016,
    "mindspore": 2020,

    # LLM / Generative AI
    "chatgpt": 2022,
    "gpt-4": 2023, "gpt4": 2023,
    "gpt-3": 2020, "gpt3": 2020,
    "gpt-2": 2019, "gpt2": 2019,
    "bert": 2018,
    "llama": 2023,
    "llama2": 2023,
    "llama3": 2024,
    "mistral": 2023,
    "claude": 2023,
    "gemini": 2023,
    "bard": 2023,
    "palm": 2022,
    "falcon": 2023,
    "bloom": 2022,
    "opt": 2022,
    "codex": 2021,
    "copilot": 2021,
    "dall-e": 2021, "dalle": 2021,
    "stable diffusion": 2022,
    "midjourney": 2022,
    "whisper": 2022,

    # AI Agent Frameworks
    "langchain": 2022,
    "llamaindex": 2022, "llama index": 2022, "llama_index": 2022,
    "crewai": 2023, "crew ai": 2023,
    "autogen": 2023,
    "autogpt": 2023, "auto-gpt": 2023,
    "babyagi": 2023, "baby agi": 2023,
    "agentgpt": 2023,
    "superagi": 2023,
    "metagpt": 2023,
    "camel": 2023,
    "haystack": 2019,
    "semantic kernel": 2023, "semantickernel": 2023,
    "dspy": 2023,
    "langflow": 2023,
    "flowise": 2023,
    "n8n": 2019,
    "make": 2012, "integromat": 2012,
    "zapier": 2011,
    "prefect": 2018,
    "airflow": 2014,

    # MLOps / Infrastructure
    "mlflow": 2018,
    "wandb": 2018, "weights and biases": 2018,
    "neptune": 2017,
    "kubeflow": 2018,
    "bentoml": 2019,
    "ray": 2017,
    "dvc": 2017,
    "feast": 2019,
    "seldon": 2017,
    "onnx": 2017,
    "triton": 2019,
    "vllm": 2023,
    "ollama": 2023,
    "hugging face": 2016, "huggingface": 2016,
    "transformers": 2019,

    # Programming Languages
    "python": 1991,
    "javascript": 1995, "js": 1995,
    "typescript": 2012, "ts": 2012,
    "java": 1995,
    "rust": 2015,
    "go": 2009, "golang": 2009,
    "kotlin": 2016,
    "swift": 2014,
    "dart": 2011,
    "julia": 2012,

    # Databases & Vector DBs
    "postgresql": 1996, "postgres": 1996,
    "mysql": 1995,
    "mongodb": 2009,
    "redis": 2009,
    "elasticsearch": 2010,
    "cassandra": 2008,
    "neo4j": 2007,
    "dynamodb": 2012,
    "cockroachdb": 2015,
    "snowflake": 2012,
    "pinecone": 2021,
    "weaviate": 2019,
    "chroma": 2022,
    "qdrant": 2021,
    "milvus": 2019,
    "faiss": 2017,

    # Cloud / DevOps
    "docker": 2013,
    "kubernetes": 2014, "k8s": 2014,
    "terraform": 2014,
    "ansible": 2012,
    "github actions": 2019,
    "vercel": 2015,
    "netlify": 2014,
}


# Merge user-defined entries from custom_tool.py (user entries override built-ins)
try:
    from crewai_video_factory.tools.custom_tool import CUSTOM_FOUNDING_YEARS as _custom
    FOUNDING_YEARS.update(_custom)
    if _custom:
        print(f"[CSVTool] Loaded {len(_custom)} custom founding year(s) from custom_tool.py")
except Exception:
    pass  # custom_tool.py missing, has no CUSTOM_FOUNDING_YEARS, or any other error


def _get_founding_year(col_name: str):
    """
    Return founding year for a column name, or None if unknown.
    Case-insensitive. Longer keys checked first to avoid false substring matches
    (e.g. 'opt' matching inside 'pytorch').
    """
    key = col_name.lower().strip()
    if key in FOUNDING_YEARS:
        return FOUNDING_YEARS[key]
    # Substring match — prefer longest key to minimise false positives
    matches = [
        (k, v) for k, v in FOUNDING_YEARS.items()
        if k in key or key in k
    ]
    if matches:
        return max(matches, key=lambda x: len(x[0]))[1]
    return None


def _enforce_founding_years(data: List[Dict], time_col: str):
    """
    Zero out any value in a column for years before that tool was founded.
    Returns (corrected_data, corrections_log).
    """
    corrections = []
    if not data:
        return data, corrections

    cols = [c for c in data[0].keys() if c != time_col]

    for row in data:
        # Parse year — handles int, float, "2015", "2015-01", "Jan 2015"
        try:
            raw = str(row[time_col]).split('-')[0].split('/')[0].strip()
            year = int(float(raw))
        except (ValueError, KeyError):
            continue

        for col in cols:
            founding = _get_founding_year(col)
            if founding is None:
                continue  # Unknown tool — trust the agent

            try:
                numeric = float(row.get(col) or 0)
            except (ValueError, TypeError):
                continue

            if year < founding and numeric != 0:
                corrections.append(
                    f"  {col}: {year} zeroed (founded {founding}, agent had {row[col]})"
                )
                row[col] = 0

    return data, corrections


class CSVToolInput(BaseModel):
    """Input schema for CSVTool."""
    topic: str = Field(
        ...,
        description=(
            "The subject of the visualization. First 3 words used as filename slug "
            "(e.g. 'LLM Tuning Methods' → 'LLMTuningMethods.csv')"
        )
    )
    data: Union[List[Dict], str] = Field(
        ...,
        description="List of dicts containing the data to write to CSV, or a string representation"
    )


class CSVTool(BaseTool):
    name: str = "CSV Writer Tool"
    description: str = (
        "Writes data to a CSV file with a deterministic filename based on the topic (first 3 words, no spaces). "
        "Automatically zeroes out values for any tool/framework before its real founding year. "
        "Supports multi-column format for tracking multiple items over time."
    )
    args_schema: Type[BaseModel] = CSVToolInput

    def _run(self, topic: str, data: Union[List[Dict], str]) -> str:

        # ── Filename ──────────────────────────────────────────────────────
        words = re.findall(r'\w+', topic)[:3]
        filename = ''.join(words) + '.csv'

        # ── Anchor output dir to project root via __file__ ────────────────
        # CWD is unreliable in crewai tools (often runs as /).
        # os.path.abspath on a relative path would resolve to /output/ (root fs).
        _t = os.path.dirname(os.path.abspath(__file__))           # .../tools/
        _output_root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(_t))), 'output'
        )  # project_root/output/
        os.makedirs(_output_root, exist_ok=True)
        filepath = os.path.join(_output_root, filename)

        # ── Parse string input ────────────────────────────────────────────
        if isinstance(data, str):
            try:
                import ast
                data = ast.literal_eval(data)
            except Exception:
                return f"Error: Could not parse data string for {filepath}"

        if not data:
            return f"Error: No data provided for {filepath}"

        if not isinstance(data, list):
            return f"Error: Data must be a list of dicts, got {type(data)}"

        # ── Founding-year enforcement ─────────────────────────────────────
        time_col = list(data[0].keys())[0]   # first column = time period
        data, corrections = _enforce_founding_years(data, time_col)

        if corrections:
            print(f"[CSVTool] ⚠️  Founding-year corrections ({len(corrections)} cells zeroed):")
            for c in corrections:
                print(f"[CSVTool]{c}")
        else:
            print("[CSVTool] ✅ No founding-year violations detected.")

        # ── Write CSV ─────────────────────────────────────────────────────
        keys = data[0].keys()
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(data)

            size_kb = os.path.getsize(filepath) // 1024
            sample  = f"\nFirst row: {data[0]}"
            if len(data) > 1:
                sample += f"\nLast row:  {data[-1]}"

            correction_note = (
                f"\n⚠️  {len(corrections)} founding-year corrections applied (pre-existence values zeroed)."
                if corrections else "\n✅ All values respect real founding years."
            )

            return (
                f"Successfully wrote {len(data)} rows to {filepath} ({size_kb} KB)"
                f"{correction_note}{sample}"
            )

        except Exception as e:
            return f"Error writing CSV to {filepath}: {e}"
