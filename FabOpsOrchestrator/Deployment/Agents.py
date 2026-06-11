import os

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools import agent_tool
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.adk.tools import url_context

_here = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_here, "prompt_orchestrator.md")) as _f:
    _PROMPT_ORCHESTRATOR = _f.read()

with open(os.path.join(_here, "prompt_rules_manager.md")) as _f:
    _PROMPT_RULES_MANAGER = _f.read()

with open(os.path.join(_here, "prompt_rule_processor.md")) as _f:
    _PROMPT_RULE_PROCESSOR = _f.read()

# ── Rules Generator and Manager ────────────────────────────────────────────────

rules_generator_and_manager_google_search_agent = LlmAgent(
    name='Rules_Generator_and_Manager_google_search_agent',
    model='gemini-2.5-pro',
    description='Agent specialized in performing Google searches.',
    sub_agents=[],
    instruction='Use the GoogleSearchTool to find information on the web.',
    tools=[GoogleSearchTool()],
)

rules_generator_and_manager_url_context_agent = LlmAgent(
    name='Rules_Generator_and_Manager_url_context_agent',
    model='gemini-2.5-pro',
    description='Agent specialized in fetching content from URLs.',
    sub_agents=[],
    instruction='Use the UrlContextTool to retrieve content from provided URLs.',
    tools=[url_context],
)

rules_generator_and_manager = LlmAgent(
    name='rules_generator_and_manager',
    model='gemini-2.5-pro',
    description='Generates and Manage new and existing rules',
    sub_agents=[],
    instruction='',
    static_instruction=_PROMPT_RULES_MANAGER,
    tools=[
        agent_tool.AgentTool(agent=rules_generator_and_manager_google_search_agent),
        agent_tool.AgentTool(agent=rules_generator_and_manager_url_context_agent),
        McpToolset(
            connection_params=StreamableHTTPConnectionParams(
                url='https://elaticmcp-775857968226.europe-west1.run.app?secret=Wmhapx4696',
            ),
            errlog=None,
        ),
    ],
)

# ── Rule Processor ─────────────────────────────────────────────────────────────

rule_processor_google_search_agent = LlmAgent(
    name='Rule_Processor_google_search_agent',
    model='gemini-2.5-pro',
    description='Agent specialized in performing Google searches.',
    sub_agents=[],
    instruction='Use the GoogleSearchTool to find information on the web.',
    tools=[GoogleSearchTool()],
)

rule_processor_url_context_agent = LlmAgent(
    name='Rule_Processor_url_context_agent',
    model='gemini-2.5-pro',
    description='Agent specialized in fetching content from URLs.',
    sub_agents=[],
    instruction='Use the UrlContextTool to retrieve content from provided URLs.',
    tools=[url_context],
)

rule_processor = LlmAgent(
    name='rule_processor',
    model='gemini-2.5-pro',
    description='Process the rules in Microsoft Fabric and generates the result',
    sub_agents=[],
    instruction='',
    static_instruction=_PROMPT_RULE_PROCESSOR,
    tools=[
        agent_tool.AgentTool(agent=rule_processor_google_search_agent),
        agent_tool.AgentTool(agent=rule_processor_url_context_agent),
        McpToolset(
            connection_params=StreamableHTTPConnectionParams(
                url='https://fabricore-775857968226.europe-west1.run.app?secret=Wmhapx4696',
            ),
            errlog=None,
        ),
    ],
)

# ── FabOps Orchestrator (root) ─────────────────────────────────────────────────

fab_ops_orchestrator_google_search_agent = LlmAgent(
    name='FabOps_Orchestrator_google_search_agent',
    model='gemini-2.5-pro',
    description='Agent specialized in performing Google searches.',
    sub_agents=[],
    instruction='Use the GoogleSearchTool to find information on the web.',
    tools=[GoogleSearchTool()],
)

fab_ops_orchestrator_url_context_agent = LlmAgent(
    name='FabOps_Orchestrator_url_context_agent',
    model='gemini-2.5-pro',
    description='Agent specialized in fetching content from URLs.',
    sub_agents=[],
    instruction='Use the UrlContextTool to retrieve content from provided URLs.',
    tools=[url_context],
)

root_agent = LlmAgent(
    name='FabOps_Orchestrator',
    model='gemini-2.5-pro',
    description='Manage the creation and storage of best practice rules for Microsoft Fabric and also the execution of the rules',
    sub_agents=[rules_generator_and_manager, rule_processor],
    instruction='',
    static_instruction=_PROMPT_ORCHESTRATOR,
    tools=[
        agent_tool.AgentTool(agent=fab_ops_orchestrator_google_search_agent),
        agent_tool.AgentTool(agent=fab_ops_orchestrator_url_context_agent),
    ],
)
