# src/crewai_video_factory/crew.py
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_video_factory.tools.csv_tool import CSVTool
from crewai_video_factory.tools.smart_video_tool import SmartVideoTool
from crewai_video_factory.tools.audio_tool import AudioGenerationTool  # Added import
from crewai_video_factory.tools.merge_tool import MergeAudioVideoTool # NEW: Import merge tool
import re

@CrewBase
class CrewaiVideoFactory:
    """Video Factory Crew for generating data-driven videos"""
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    def __init__(self):
        # Will be set during kickoff
        self.filename = None

    @agent
    def data_researcher(self) -> Agent:
        return Agent(
            config=self.agents_config['data_researcher'],
            verbose=True
        )

    @agent
    def csv_generator(self) -> Agent:
        return Agent(
            config=self.agents_config['csv_generator'],
            tools=[CSVTool()],
            verbose=True
        )

    @agent
    def video_producer(self) -> Agent:
        return Agent(
            config=self.agents_config['video_producer'],
            tools=[SmartVideoTool()],
            verbose=True
        )

    # ===== DEDICATED AUDIO AGENT (AUDIO TOOL ONLY HERE) =====
    @agent
    def audio_engineer(self) -> Agent:
        # AUDIO AGENT HAS ONLY AUDIO TOOLS - NO VIDEO
        return Agent(
            config=self.agents_config['audio_engineer'],
            tools=[AudioGenerationTool()],  # Video tool NOT included
            verbose=True
        )

    # ===== DEDICATED MERGE AGENT (MERGE TOOL ONLY HERE) =====
    @agent
    def merge_specialist(self) -> Agent:
        # MERGE AGENT HAS ONLY MERGE TOOL
        return Agent(
            config=self.agents_config['merge_specialist'], # Defined in agents.yaml
            tools=[MergeAudioVideoTool()], # Only merge tool
            verbose=True
        )

    @task
    def research_data(self) -> Task:
        return Task(
            config=self.tasks_config['research_data'],
        )

    @task
    def generate_csv(self) -> Task:
        return Task(
            config=self.tasks_config['generate_csv'],
        )

    @task
    def create_video(self) -> Task:
        return Task(
            config=self.tasks_config['create_video'],
        )

    # ===== DEDICATED AUDIO TASK =====
    @task
    def add_audio(self) -> Task:
        return Task(
            config=self.tasks_config['add_audio'],
        )

    # ===== DEDICATED MERGE TASK =====
    @task
    def merge_audio_video(self) -> Task:
        return Task(
            config=self.tasks_config['merge_audio_video'], # Defined in tasks.yaml
        )

    @crew
    def crew(self) -> Crew:
        """Creates the Video Factory crew with ALL potential agents and tasks.
         Conditional execution of merge task is handled in main.py."""
        all_agents = [self.data_researcher(), self.csv_generator(), self.video_producer(), self.audio_engineer()]
        all_tasks = [self.research_data(), self.generate_csv(), self.create_video(), self.add_audio()]

        # Always include merge agent and task; they will be filtered later if needed
        all_agents.append(self.merge_specialist())
        all_tasks.append(self.merge_audio_video())

        return Crew(
            agents=all_agents,
            tasks=all_tasks,
            process=Process.sequential,
            verbose=True
        )
