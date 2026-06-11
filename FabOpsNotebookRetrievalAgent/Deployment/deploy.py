import argparse
import os
import sys

import vertexai
from vertexai import agent_engines

# Validate required environment variables
_project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
if not _project:
    sys.exit("Error: GOOGLE_CLOUD_PROJECT environment variable is not set or empty.")

_staging_bucket = os.environ.get("STAGING_BUCKET", "")
if not _staging_bucket:
    sys.exit("Error: STAGING_BUCKET environment variable is not set or empty.")

# Import root_agent from the Definition folder, relative to this file
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
from Agents import root_agent  # noqa: E402

# Read requirements from the sibling requirements.txt at runtime
_req_path = os.path.join(_here, "requirements.txt")
with open(_req_path) as _f:
    _requirements = [line.strip() for line in _f if line.strip() and not line.startswith("#")]

_extra_packages = [
    os.path.abspath(os.path.join(_here, "Agents.py")),
    os.path.abspath(os.path.join(_here, "prompt.md")),
]

# Initialize Vertex AI
vertexai.init(
    project=_project,
    location="europe-west1",
    staging_bucket=_staging_bucket,
)

# CLI
parser = argparse.ArgumentParser(description="Deploy FabOps Notebook Retrieval Agent to Vertex AI Agent Engine")
parser.add_argument("--display-name", default=None, help="Display name for the deployment (defaults to agent name)")
parser.add_argument("--resource-name", default=None, help="Existing resource name to update instead of creating a new deployment")
args = parser.parse_args()

display_name = args.display_name or root_agent.name

if args.resource_name:
    result = agent_engines.update(
        resource_name=args.resource_name,
        agent_engine=root_agent,
        requirements=_requirements,
        extra_packages=_extra_packages,
    )
    print(f"Updated resource name: {result.resource_name}")
else:
    result = agent_engines.create(
        agent_engine=root_agent,
        requirements=_requirements,
        extra_packages=_extra_packages,
        display_name=display_name,
    )
    print(f"Deployed resource name: {result.resource_name}")
