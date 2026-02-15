#!/usr/bin/env python
import sys
import warnings
from datetime import datetime
from deep_research.crew import DeepResearch
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# ==========================================
# CONFIGURATION - Change Research Topic Here
# ==========================================
RESEARCH_CONFIG = {
    'topic': 'Immigration use Ai',
    'current_year': str(datetime.now().year)
}

# Examples of topics you can research:
# - 'AI LLMs and Large Language Models'
# - 'Quantum Computing Applications'
# - 'Electric Vehicle Market Trends'
# - 'Web3 and Blockchain Enterprise Adoption'
# - 'Climate Tech and Carbon Capture Innovations'
# - 'Remote Work and AI Automation'
# - 'Cybersecurity Trends and Zero Trust Architecture'


def run():
    """    Run the Deep Research crew with configured topic. """
    print("=" * 60)
    print("🔬 CrewAI Deep Research System")
    print("=" * 60)
    print(f"📌 Research Topic: {RESEARCH_CONFIG['topic']}")
    print(f"📅 Year: {RESEARCH_CONFIG['current_year']}")
    print("=" * 60)
    print("\n🚀 Starting research process...\n")    
    try:
        result = DeepResearch().crew().kickoff(inputs=RESEARCH_CONFIG)        
        print("\n" + "=" * 60)
        print("✅ Research Completed Successfully!")
        print("=" * 60)
        print(f"\n📄 Report saved to: output/report_{RESEARCH_CONFIG['topic'][:30]}.md")
        print("\n" + "=" * 60)        
        return result        
    except Exception as e:
        print(f"\n❌ Error occurred: {e}")
        raise Exception(f"An error occurred while running the crew: {e}")






def train():
    """
    Train the crew for a given number of iterations.
    Usage: python main.py train <iterations> <filename>
    """
    if len(sys.argv) < 3:
        print("Usage: python main.py train <iterations> <filename>")
        sys.exit(1)    
    try:
        DeepResearch().crew().train(
            n_iterations=int(sys.argv[2]), 
            filename=sys.argv[3], 
            inputs=RESEARCH_CONFIG
        )
    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")







def replay():
    """
    Replay the crew execution from a specific task.
    Usage: python main.py replay <task_id>
    """
    if len(sys.argv) < 2:
        print("Usage: python main.py replay <task_id>")
        sys.exit(1)        
    try:
        DeepResearch().crew().replay(task_id=sys.argv[2])
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")






def test():
    """
    Test the crew execution and returns the results.
    Usage: python main.py test <iterations> <eval_llm>
    """
    if len(sys.argv) < 3:
        print("Usage: python main.py test <iterations> <eval_llm>")
        sys.exit(1)        
    try:
        DeepResearch().crew().test(
            n_iterations=int(sys.argv[2]), 
            eval_llm=sys.argv[3], 
            inputs=RESEARCH_CONFIG
        )
    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")




if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "train":
            train()
        elif command == "replay":
            replay()
        elif command == "test":
            test()
        else:
            print(f"Unknown command: {command}")
            print("Available commands: train, replay, test")
            print("Or run without arguments to execute research")
    else:
        run()
