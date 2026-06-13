import os
from typing import Optional
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
# ── UI render tools ───────────────────────────────────────────────────────────
# These are passthrough tools: the model calls them to signal the frontend to
# render a visual component. The backend emits TOOL_CALL_ARGS so the frontend
# receives the arguments and can render the appropriate React component.

def render_table(
    rule_name: str,
    rows: list,
    summary: Optional[dict] = None,
) -> dict:
    """Render a compliance results table in the chat UI.
    Call this after evaluating a rule to display per-object pass/fail results.
    rows is a list of objects each with: object_name, object_type,
    status ('pass'|'fail'|'error'), and optional finding string.
    summary (optional) has keys: total, passed, failed.
    """
    return {"rendered": True}


def render_code(
    code: str,
    title: Optional[str] = None,
    language: str = "frl",
) -> dict:
    """Render a code block in the chat UI with syntax highlighting.
    Use this to display FRL rule code or any code snippet.
    code: the raw source string — do NOT wrap in markdown fences.
    title: optional heading shown above the block.
    language: syntax hint, defaults to 'frl'.
    """
    return {"rendered": True}


def render_card(
    rule_id: str,
    name: str,
    description: Optional[str] = None,
    severity: Optional[str] = None,
    tags: Optional[list] = None,
) -> dict:
    """Render a rule information card in the chat UI.
    Use this to highlight one specific rule's metadata (id, name, description,
    severity, tags). Pair with render_code to also show its FRL.
    severity should be 'high', 'medium', or 'low'.
    """
    return {"rendered": True}


def render_badge(
    label: str,
    status: str,
) -> dict:
    """Render a small status or severity badge inline in the chat.
    status should be one of: pass, fail, error, high, medium, low, info.
    """
    return {"rendered": True}


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
    sub_agents=[],                                  # ← was [rules_generator_and_manager, rule_processor]
    instruction='',
    static_instruction=_PROMPT_ORCHESTRATOR,
    tools=[
        agent_tool.AgentTool(agent=rules_generator_and_manager),   # ← now a tool (call/return)
        agent_tool.AgentTool(agent=rule_processor),                # ← now a tool (call/return)
        agent_tool.AgentTool(agent=fab_ops_orchestrator_google_search_agent),
        agent_tool.AgentTool(agent=fab_ops_orchestrator_url_context_agent),
        render_table,
        render_code,
        render_card,
        render_badge,
    ],
)
