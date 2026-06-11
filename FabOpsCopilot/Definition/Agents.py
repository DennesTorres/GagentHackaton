import os

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools import agent_tool
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.adk.tools import url_context

_prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt.md")
with open(_prompt_path) as _f:
    _PROMPT = _f.read()

frl_copilot_google_search_agent = LlmAgent(
    name='FRL_Copilot_google_search_agent',
    model='gemini-2.5-flash',
    description='Agent specialized in performing Google searches.',
    sub_agents=[],
    instruction='Use the GoogleSearchTool to find information on the web.',
    tools=[GoogleSearchTool()],
)

frl_copilot_url_context_agent = LlmAgent(
    name='FRL_Copilot_url_context_agent',
    model='gemini-2.5-flash',
    description='Agent specialized in fetching content from URLs.',
    sub_agents=[],
    instruction='Use the UrlContextTool to retrieve content from provided URLs.',
    tools=[url_context],
)

root_agent = LlmAgent(
    name='FRL_Copilot',
    model='gemini-2.5-flash',
    description='This agent helps producing code on the FRL language, a language used to write Microsoft Fabric governance rules',
    sub_agents=[],
    instruction=_PROMPT,
    tools=[
        agent_tool.AgentTool(agent=frl_copilot_google_search_agent),
        agent_tool.AgentTool(agent=frl_copilot_url_context_agent),
        McpToolset(
            connection_params=StreamableHTTPConnectionParams(
                url='https://elaticmcp-775857968226.europe-west1.run.app?secret=Wmhapx4696',
            ),
            errlog=None,
        ),
    ],
)
