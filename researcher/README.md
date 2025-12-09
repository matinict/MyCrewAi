
# 🔍 AI Researcher Agent (Researcher Crew)

Repository Link: [https://github.com/matinict/MyCrewAi/tree/main/researcher](https://github.com/matinict/MyCrewAi/tree/main/researcher)
Video Tutorial: [How to Create an AI Researcher Agent Using Crew AI](https://youtu.be/I-SgWzUZlwQ)

Welcome to the Researcher Crew project, powered by [CrewAI](https://crewai.com). This project demonstrates how to build a fully autonomous AI researcher that can automate web research, analyze data, and generate reports automatically.

[](https://www.crewai.com/)
[](https://docs.litellm.ai/)
[](https://www.python.org/)

-----

## 🔥 Project Summary

This crew is designed to execute end-to-end research tasks autonomously, showcasing core principles of agentic intelligence: multi-agent collaboration, tool utilization (for web searches), and multi-model flexibility.

### Goal

To build a fully functional AI Researcher that can automate the entire research pipeline from information gathering to final report generation.

### Key Features Demonstrated

  Multi-Model Flexibility: Use multiple AI models (GPT-4, Google Gemini, Anthropic Claude) within the same crew using `litellm`.
  Real-Time Tracing: Enable tracing to monitor and debug the AI agents' decision-making processes.
  Automatic Research: Agents that gather, analyze, and synthesize information into a coherent report.
  Easy Setup: Utilizes the `uv` package manager for fast, reliable installation.

-----

## 🛠️ Setup and Installation

This project requires Python and uses the UV package manager for optimal dependency handling.

### Prerequisites

  Python `>=3.10 <3.14`
  API Key Setup: You must configure your environment variables or the CrewAI CLI with the necessary API keys for your chosen LLM providers (e.g., OpenAI, Google GenAI, Anthropic).

### Installation Commands

1.  Install UV (if needed):

   ```bash
   pip install uv
   ```

2.  Create the Crew Structure:

   ```bash
   crewai create crew researcher
   ```

3.  Navigate to the project directory:

   ```bash
   cd researcher/
   ```

4.  Install Dependencies (Multi-LLM ready):

   ```bash
   uv add "crewai[google-genai]" "crewai[anthropic]" litellm
   ```

   (Optional) Lock the dependencies and install them using the CLI command:

   ```bash
   crewai install
   ```

5.  Enable Tracing (Recommended):
   Watch your AI agents think and make decisions in real-time.

   ```bash
   crewai traces enable
   ```

### Running the Project

To kickstart your crew of AI agents and begin the research task (by default, research on LLMs):

```bash
$ crewai run
```

This command initializes the Researcher Crew, assembling the agents and assigning them tasks as defined in your configuration. The unmodified example will create a `report.md` file in the root folder with the research output.

-----

## 💻 Customization

To tailor the research project to your needs, modify the following files:

  API Key Setup: Add your `OPENAI_API_KEY` into the `.env` file (or use the CLI commands provided in the tutorial).
  Agent Definitions: Modify `src/researcher/config/agents.yaml` to define your agents' roles, goals, and tools.
  Task Definitions: Modify `src/researcher/config/tasks.yaml` to define the steps of the research workflow.
  Crew Logic: Modify `src/researcher/crew.py` to add custom logic, tools, and specific arguments.
  Custom Inputs: Modify `src/researcher/main.py` to add custom inputs (the research topic) for your agents and tasks.

-----

## 📚 Resources & Support

For support, questions, or feedback regarding the Researcher Crew or CrewAI:

  CrewAI Documentation: [https://docs.crewai.com](https://docs.crewai.com)
  CrewAI GitHub: [https://github.com/joaomdmoura/crewai](https://github.com/joaomdmoura/crewai)
  Join the Discord: [https://discord.com/invite/X4JWnZnxPb](https://discord.com/invite/X4JWnZnxPb)

Let's create wonders together with the power and simplicity of CrewAI.

```