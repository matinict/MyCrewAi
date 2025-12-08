#!/usr/bin/env python
import sys
import warnings

from datetime import datetime
from debate.crew import Debate

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

 
def run():
    """
    Run the crew.
    """
    inputs = {
        'motion': 'Ai call centers will handle 80%+ of customer service interactions',
    }
    
    try:
        result = Debate().crew().kickoff(inputs=inputs)
        print(result.raw)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")
 