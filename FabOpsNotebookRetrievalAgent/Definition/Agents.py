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

fab_ops_notebook_retrieval_google_search_agent = LlmAgent(
    name='FabOps_Notebook_Retrieval_google_search_agent',
    model='gemini-2.5-pro',
    description='Agent specialized in performing Google searches.',
    sub_agents=[],
    instruction='Use the GoogleSearchTool to find information on the web.',
    tools=[GoogleSearchTool()],
)

fab_ops_notebook_retrieval_url_context_agent = LlmAgent(
    name='FabOps_Notebook_Retrieval_url_context_agent',
    model='gemini-2.5-pro',
    description='Agent specialized in fetching content from URLs.',
    sub_agents=[],
    instruction='Use the UrlContextTool to retrieve content from provided URLs.',
    tools=[url_context],
)

root_agent = LlmAgent(
    name='FabOps_Notebook_Retrieval',
    model='gemini-2.5-pro',
    description='Retrieves governance information using notebook execution to transverse the environment',
    sub_agents=[],
    instruction=_PROMPT,
    tools=[
        agent_tool.AgentTool(agent=fab_ops_notebook_retrieval_google_search_agent),
        agent_tool.AgentTool(agent=fab_ops_notebook_retrieval_url_context_agent),
        McpToolset(
            connection_params=StreamableHTTPConnectionParams(
                url='https://fabric-mcp-proxy-775857968226.europe-west1.run.app?secret=Wmhapx4696',
            ),
            errlog=None,
        ),
    ],
)
