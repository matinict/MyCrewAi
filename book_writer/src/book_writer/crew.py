# ============================================
# FILE: src/book_writer/crew.py
# ============================================
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai_tools import SerperDevTool
import os

@CrewBase
class BookWriter():
    """Book Writing Crew"""
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    @agent
    def researcher(self) -> Agent:
        return Agent(
            config=self.agents_config['researcher'],
            tools=[SerperDevTool()],
            verbose=True
        )
    
    @agent
    def planner(self) -> Agent:
        return Agent(
            config=self.agents_config['planner'],
            verbose=True
        )
    
    @agent
    def writer(self) -> Agent:
        return Agent(
            config=self.agents_config['writer'],
            verbose=True
        )
    
    @agent
    def editor(self) -> Agent:
        return Agent(
            config=self.agents_config['editor'],
            verbose=True
        )
    
    @agent
    def translator(self) -> Agent:
        return Agent(
            config=self.agents_config['translator'],
            verbose=True
        )

    @task
    def research_task(self) -> Task:
        return Task(
            config=self.tasks_config['research_task'],
            agent=self.researcher()
        )

    @task
    def planning_task(self) -> Task:
        return Task(
            config=self.tasks_config['planning_task'],
            agent=self.planner()
        )

    @task
    def writing_task(self) -> Task:
        return Task(
            config=self.tasks_config['writing_task'],
            agent=self.writer()
        )

    @task
    def editing_task(self) -> Task:
        return Task(
            config=self.tasks_config['editing_task'],
            agent=self.editor()
        )
    
    @task
    def translation_task(self) -> Task:
        return Task(
            config=self.tasks_config['translation_task'],
            agent=self.translator()
        )

    @crew
    def crew(self) -> Crew:
        """Creates the Book Writing crew"""
        os.makedirs("./output", exist_ok=True)
        
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )