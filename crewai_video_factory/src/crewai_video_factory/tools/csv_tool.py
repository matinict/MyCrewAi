"""
UPDATED FILE: src/crewai_video_factory/tools/csv_tool.py

This is the COMPLETE updated CSV tool file.
Replace your existing csv_tool.py with this content.
"""

import csv
import os
import re
from crewai.tools import BaseTool
from typing import Type, Union, List, Dict
from pydantic import BaseModel, Field


class CSVToolInput(BaseModel):
    """Input schema for CSVTool.

    TOPIC DEFINITION:
    The topic is the subject of the data visualization (e.g. "LLM Tuning Methods",
    "Programming Language Popularity", "AI Framework Adoption").
    - First 3 words become the filename slug: "LLM Tuning Methods" → "LLMTuningMethods"
    - Saved as: output/LLMTuningMethods.csv
    - Topic name also saved as: output/LLMTuningMethods.txt
    """
    topic: str = Field(..., description="The subject of the visualization. First 3 words used as filename slug (e.g. 'LLM Tuning Methods' → 'LLMTuningMethods.csv')")
    data: Union[List[Dict], str] = Field(..., description="List of dictionaries containing the data to write to CSV, or a string representation")


class CSVTool(BaseTool):
    name: str = "CSV Writer Tool"
    description: str = """Writes data to a CSV file with a deterministic filename based on the topic (first 3 words, no spaces).

    Supports multi-column format for tracking multiple items over time.
    Example format:
    Year,LangChain,CrewAI,AutoGPT,BabyAGI,...
    2015,0,0,0,0,...
    2016,2,0,0,0,...

    Data should be a list of dictionaries where each dict represents one row.
    """
    args_schema: Type[BaseModel] = CSVToolInput

    def _run(self, topic: str, data: Union[List[Dict], str]) -> str:
        """
        Write data to CSV with filename derived from first 3 words of topic.

        Args:
            topic: The topic string (e.g., "AI Agent Framework Popularity")
            data: List of dictionaries with keys matching CSV columns, or string representation

        Returns:
            String indicating success and filepath
        """
        # Extract first 3 words and remove spaces
        words = re.findall(r'\w+', topic)[:3]
        filename = ''.join(words) + '.csv'

        # Ensure output directory exists
        output_dir = 'output'
        os.makedirs(output_dir, exist_ok=True)

        filepath = os.path.join(output_dir, filename)

        # Handle string input (convert to list if needed)
        if isinstance(data, str):
            # Try to parse as CSV or evaluate as Python structure
            try:
                import ast
                data = ast.literal_eval(data)
            except:
                return f"Error: Could not parse data string for {filepath}"

        # Write CSV
        if not data:
            return f"Error: No data provided for {filepath}"

        if not isinstance(data, list):
            return f"Error: Data must be a list of dictionaries, got {type(data)}"

        keys = data[0].keys()

        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(data)

            # Show sample of data for verification
            sample = f"\nFirst row: {data[0]}"
            if len(data) > 1:
                sample += f"\nLast row: {data[-1]}"

            # Save topic definition file alongside CSV
            txt_path = filepath.replace('.csv', '.txt')
            with open(txt_path, 'w', encoding='utf-8') as tf:
                tf.write(f"Topic: {topic}\n")
                tf.write(f"Filename: {filename}\n")
                tf.write(f"CSV: {filepath}\n")
                tf.write(f"Rows: {len(data)}\n")
                tf.write(f"Columns: {list(keys)}\n")

            return f"Successfully wrote {len(data)} rows to {filepath}\nTopic definition saved to: {txt_path}{sample}"
        except Exception as e:
            return f"Error writing CSV to {filepath}: {str(e)}"
