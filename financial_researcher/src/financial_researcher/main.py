#!/usr/bin/env python
import sys
import warnings

from datetime import datetime

from financial_researcher.crew import FinancialResearcher

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information

def run():
    """
    Run the Financial Researcher  crew.
    """
    inputs = {
        'company': 'Saudi Aramco',
        'current_year': str(datetime.now().year)
    }

    try:
        result = FinancialResearcher().crew().kickoff(inputs=inputs)
            # Print the result
        print("\n\n=== FINAL REPORT ===\n\n")
        print(result.raw)
        print("\n\nReport has been saved to output/report.md")

    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")

if __name__ == "__main__":
    run()
