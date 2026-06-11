import os
from functools import cached_property

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.genai import Client
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools import agent_tool
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.adk.tools import url_context

_prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt.md")
with open(_prompt_path) as _f:
    _PROMPT = _f.read()


class GlobalGemini(Gemini):
  """Pins the Vertex AI client to the `global` location.

  gemini-3 series models are only served from `global`; the default ADK
  `Gemini` integration constructs a `google.genai.Client` whose location
  defaults to the AgentEngine instance's region (e.g. `us-central1`) and
  fails with model-not-found for these models. Subclassing per the override
  pattern documented on `google.adk.models.google_llm.Gemini` lets the agent
  keep running in its regional AgentEngine instance while routing the model
  request to the global endpoint.
  """

  @cached_property
  def api_client(self) -> Client:
    return Client(vertexai=True, location="global")


fab_ops_policy_check_google_search_agent = LlmAgent(
  name='FabOps_Policy_Check_google_search_agent',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description='Agent specialized in performing Google searches.',
  sub_agents=[],
  instruction='Use the GoogleSearchTool to find information on the web.',
  tools=[
    GoogleSearchTool()
  ],
)

fab_ops_policy_check_url_context_agent = LlmAgent(
  name='FabOps_Policy_Check_url_context_agent',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description='Agent specialized in fetching content from URLs.',
  sub_agents=[],
  instruction='Use the UrlContextTool to retrieve content from provided URLs.',
  tools=[
    url_context
  ],
)

root_agent = LlmAgent(
  name='FabOps_Policy_Check',
  model=GlobalGemini(model='gemini-3.5-flash'),
  description='This agent uses Microsoft Fabric MCP to make policy checks in Microsoft Fabric',
  sub_agents=[],
  instruction='',
  static_instruction=_PROMPT,
  tools=[
    agent_tool.AgentTool(agent=fab_ops_policy_check_google_search_agent),
    agent_tool.AgentTool(agent=fab_ops_policy_check_url_context_agent),
    McpToolset(
      connection_params=StreamableHTTPConnectionParams(
        url='https://fabricore-775857968226.europe-west1.run.app?secret=Wmhapx4696',
      ),
      errlog=None,
    ),
  ],
)
