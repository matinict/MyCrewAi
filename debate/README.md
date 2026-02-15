
# 🗣️ AI Debate System (Debate Crew)

Repository Link: [https://github.com/matinict/MyCrewAi/tree/main/debate](https://github.com/matinict/MyCrewAi/tree/main/debate)
Video Tutorial: [CrewAI Debate System Tutorial | Multi-Agent AI Debate Workflow (PlayOwnAi)](https://youtu.be/FoHdXlgs_b0)

Welcome to the Debate Crew project, powered by [CrewAI](https://crewai.com). This project implements a fully autonomous, multi-agent AI Debate System capable of running structured debates using specialized LLM-powered agents.

[![Built with CrewAI](https://img.shields.io/badge/Framework-CrewAI-5A2594?logo=python&logoColor=white)](https://www.crewai.com/)
[![LLMs](https://img.shields.io/badge/LLM-GPT--4o--mini%2FMulti--Model-007bff)](https://docs.litellm.ai/)
[![Python](https://img.shields.io/badge/Language-Python%203.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)

---

## 🔥 Project Overview

This system is designed to showcase complex Agentic Intelligence through structured collaboration and conflict.

### Goal
To create a fully autonomous AI Debate System that can run structured debates using multiple LLM-powered agents.

### Summary
The system builds a complete RAG-style debate workflow where agents propose, oppose, and judge a dynamically defined motion. The entire process runs with a single command, automatically saving all output for review.

### Example Motion
> "AI call centers will handle 80%+ of customer service interactions within 5 years."
(You can change the topic anytime in the `main.py` file.)

---

## ⚙️ Architecture & Workflow
The debate system orchestrates a sequence of specialized tasks:
1.  Motion Definition: The debate topic (`{motion}`) is set in `main.py`.
2.  Agent Assembly: The Propose, Oppose, and Judge agents are initialized with their specialized roles.
3.  Propose Argument: The "Propose" agent argues for the motion and saves its output.
4.  Oppose Argument: The "Oppose" agent argues against the motion and saves its output.
5.  Judge Decision: The "Judge" agent evaluates both arguments, provides justification, and picks a winner.

### Final Output

The results are automatically saved to the following markdown files in the `output/` directory:

 `output/propose.md`
 `output/oppose.md`
 `output/decide.md`

---

## 🛠️ Setup and Installation

This project recommends using [UV](https://docs.astral.sh/uv/) for fast dependency management.

### Prerequisites

 Python `>=3.10 <3.14`
 Add your `OPENAI_API_KEY` into the `.env` file (The system uses `openai/gpt-4o-mini` and is configured for multi-LLM support via `litellm`).

### Installation Commands

1.  Install UV (if needed):
    ```bash
    pip install uv
    ```

2.  Navigate to the project directory:
    ```bash
    cd debate/
    ```

3.  Install Dependencies (Multi-LLM ready):
    ```bash
    uv add "crewai[google-genai]" "crewai[anthropic]" litellm
    # OR (Optional) Lock and install using the CrewAI CLI:
    # crewai install
    ```

### Running the Debate

To kickstart your crew of AI agents and begin the debate:

```bash
$ crewai run


OR to define the motion directly:

```bash
python main.py --debate_title "AI call centers will handle over 80% of customer service interactions."
```

-----

## 🧩 Configuration Details

The system is fully customizable using the following YAML and Python files:

### 1\. `agents.yaml`

Defines the specialized agents:

   Debater Agent: Focuses on research and argument construction.
   Judge Agent: Focuses on objective evaluation and decision-making.
   Uses the `{motion}` placeholder for dynamic roles/goals.
   LLM set to `openai/gpt-4o-mini`.

### 2\. `tasks.yaml`

Defines the sequential workflow:

   `propose` → saves output to `output/propose.md`
   `oppose` → saves output to `output/oppose.md`
   `decide` → saves final decision to `output/decide.md`

### 3\. `crew.py`

This file orchestrates the workflow:

   Uses the `@agent` and `@task` decorators to define the agents and tasks.
   Combines the sequential tasks using the `@crew` decorator.

-----

## 📚 Resources

| Resource | Link |
| :--- | :--- |
| Project Code | [https://github.com/matinict/MyCrewAi/tree/main/debate](https://github.com/matinict/MyCrewAi/tree/main/debate) |
| Video Tutorial | [https://youtu.be/FoHdXlgs\_b0](https://youtu.be/FoHdXlgs_b0) |

-----

## Support & Community

For support, questions, or feedback regarding the Debate Crew or CrewAI:

   Visit the official [CrewAI documentation](https://docs.crewai.com)
   [Join the Discord community](https://discord.com/invite/X4JWnZnxPb)

Let's create wonders together with the power and simplicity of CrewAI.
