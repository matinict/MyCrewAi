from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_video_factory.tools.csv_tool import CSVTool
from crewai_video_factory.tools.smart_video_tool import SmartVideoTool
from crewai_video_factory.tools.audio_tool import AudioGenerationTool  # VALID IMPORT
import re

@CrewBase
class CrewaiVideoFactory:
    """Video Factory Crew for generating data-driven videos"""
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    def __init__(self):
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

    @agent
    def audio_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['audio_engineer'],
            tools=[AudioGenerationTool()],
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

    @task
    def add_audio(self) -> Task:
        return Task(
            config=self.tasks_config['add_audio'],
        )

    @crew
    def crew(self) -> Crew:
        """Creates the Video Factory crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True
        )