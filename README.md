# MyCrewAi

```markdown
# 🤖 MyCrewAi: CrewAI Multi-Agent Systems Collection

GitHub Repository: [https://github.com/matinict/MyCrewAi](https://github.com/matinict/MyCrewAi)

[![Framework](https://img.shields.io/badge/Framework-CrewAI-5A2594?logo=python&logoColor=white)](https://www.crewai.com/)
[![Language](https://img.shields.io/badge/Language-Python%203.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![LLMs](https://img.shields.io/badge/LLMs-Multi%20Model%20Support-007bff)](https://docs.litellm.ai/)
[![Video](https://img.shields.io/badge/Demonstration-YouTube-FF0000?logo=youtube&logoColor=white)](https://www.youtube.com/@matinict)

This repository serves as a collection of advanced Agentic Intelligence examples built using the CrewAI framework. Each sub-project demonstrates a distinct multi-agent architecture for autonomous task execution and complex reasoning.

---

## 📂 Project Structure

```

MyCrewAi/
│
├── README.md                  \# This file
│
├── researcher/                \# Sub-project 1: Autonomous AI Researcher
│   ├── main.py
│   └── ...
│
└── debate/                    \# Sub-project 2: Multi-Agent Debate System
├── main.py
└── ...

````

---

## 1. 🔍 AI Researcher Agent

Autonomous Web Research and Reporting

[![Built with CrewAI](https://img.shields.io/badge/Framework-CrewAI-5A2594?logo=python&logoColor=white)](https://www.crewai.com/)
[![LangChain](https://img.shields.io/badge/AI-LangChain-blue)](https://www.langchain.com/)
[![LLMs](https://img.shields.io/badge/LLMs-Google%20GenAI%2FAnthropic-007bff)](https://docs.litellm.ai/)
[![Python](https://img.shields.io/badge/Language-Python%203.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)

- 🌐 Project Code: [https://github.com/matinict/MyCrewAi/tree/main/researcher](https://github.com/matinict/MyCrewAi/tree/main/researcher)
- 🎥 Video Walkthrough: [https://youtu.be/I-SgWzUZlwQ](https://youtu.be/I-SgWzUZlwQ)
- Goal: How to Create an AI Researcher Agent Using Crew AI
- Summary: This project creates an Autonomous AI Researcher Agent capable of searching the web, analyzing sources, and synthesizing comprehensive reports on a given topic, highlighting multi-step task execution.

---

## 2. 🗣️ AI Debate System

Multi-Agent Structured Conflict Resolution

[![Built with CrewAI](https://img.shields.io/badge/Framework-CrewAI-5A2594?logo=python&logoColor=white)](https://www.crewai.com/)
[![LangChain](https://img.shields.io/badge/AI-LangChain-blue)](https://www.langchain.com/)
[![LLMs](https://img.shields.io/badge/LLMs-Multiple%20(Litellm)-007bff)](https://docs.litellm.ai/)
[![Python](https://img.shields.io/badge/Language-Python%203.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)

- 🌐 Project Code: [https://github.com/matinict/MyCrewAi/tree/main/debate](https://github.com/matinict/MyCrewAi/tree/main/debate)
- 🎥 Video Walkthrough: [https://youtu.be/FoHdXlgs_b0](https://youtu.be/FoHdXlgs_b0)
- Goal: How to Create an AI Debate System Using Crew AI and Multiple LLMs
- Summary: This project showcases a complex Multi-Agent Debate System where agents adopt opposing roles and utilize different large language models (LLMs) to argue a thesis, demonstrating sophisticated coordination and conflict resolution.

---

### 🚀 Setup and Execution

To run any of the projects above, follow these general steps:

1.  Clone the Repository:
    ```bash
    git clone [https://github.com/matinict/MyCrewAi.git](https://github.com/matinict/MyCrewAi.git)
    cd MyCrewAi
    ```

2.  Initialize the Crew (Example: Researcher):
    ```bash
    crewai create crew researcher
    cd researcher/
    ```
    (Note: This step may be optional if the code structure is already fully defined in the repository.)

3.  Install Dependencies:
    Use `uv` to install the required dependencies, ensuring support for multiple LLMs via `litellm`.
    ```bash
    uv add "crewai[google-genai]" "crewai[anthropic]" litellm
    ```
    (Alternatively, use `pip install crewai[google-genai] crewai[anthropic] litellm`)

4.  Run the Crew:
    ```bash
    crewai run
    ```

### Prerequisites

 Python: Ensure Python 3.11 or newer is installed.
 LLM Keys: Configure your environment variables with the necessary API keys (e.g., `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.) as these crews are designed for multi-model usage.
````
