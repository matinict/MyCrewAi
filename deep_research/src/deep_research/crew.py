
"""
CrewAI Deep Research Crew Definition
Author: Abdul Matin (PlayOwnAi)
"""
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai_tools import SerperDevTool
from typing import List

@CrewBase
class DeepResearch():
    """Deep Research crew for comprehensive topic analysis"""
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'
    
    agents: List[BaseAgent]
    tasks: List[Task]

    # def __init__(self):
    #     super().__init__()
    #     # Initialize search tool for web research
    #     self.search_tool = SerperDevTool()
    
    @agent
    def researcher(self) -> Agent:
        """Senior Research Lead - Conducts comprehensive research"""
        search_tool = SerperDevTool()
        return Agent( config=self.agents_config['researcher'],verbose=True, allow_delegation=False   )
    @agent
    def reporting_analyst(self) -> Agent:
        """Reporting Analyst - Creates detailed reports"""
        return Agent(config=self.agents_config['reporting_analyst'],verbose=True, allow_delegation=False )
  
    @task
    def research_task(self) -> Task:
        """Research task - Deep investigation of the topic"""
        return Task( config=self.tasks_config['research_task'],agent=self.researcher()  )
  
    @task
    def reporting_task(self) -> Task:
        """Reporting task - Generate comprehensive markdown report"""
        return Task( config=self.tasks_config['reporting_task'], agent=self.reporting_analyst(), context=[self.research_task()]
    )

     
    @crew
    def crew(self) -> Crew:
        """Creates the Deep Research crew with sequential process"""
        # Get first word from topic for filename
        topic = self.inputs.get('topic', 'research') if hasattr(self, 'inputs') else 'research'
        first_word = topic.split()[0].lower().replace(',', '')
        
        # Update output file dynamically
        self.reporting_task().output_file = f'output/report_{first_word}.md'
        
        return Crew( agents=self.agents, tasks=self.tasks, process=Process.sequential, verbose=True,  memory=True )