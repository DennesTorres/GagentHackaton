# FabricGuard

> Govern Microsoft Fabric by writing a rule in plain English. FabricGuard turns it into a language, stores it, and an agent enforces it against your live tenant.

Built for the **Google Cloud Rapid Agent Hackathon — Elastic Track** (June 2026). Powered by Gemini on Vertex AI Agent Engine, with Elastic Cloud Serverless as the system's memory.

![What FabricGuard does](illustrations/frl-overview-v01.html)

---

## What FabricGuard does

Every Microsoft Fabric tenant accumulates governance rules — naming conventions, capacity policies, access requirements, data-quality standards. They normally live in wiki pages nobody reads and audit scripts nobody maintains. FabricGuard makes them executable.

You describe a policy the way you'd say it out loud — *"every production lakehouse must be assigned to a capacity"* — and FabricGuard does three things. It **compiles your intent into a rule** expressed in a small purpose-built language. It **stores that rule** in Elastic, versioned and semantically searchable, so the rulebook is a managed asset rather than a pile of scripts. And it **enforces the rule** by sending an agent to walk your live Fabric tenant, evaluate each object, and report pass or fail with evidence.

The product is not a single chatbot. It is a governance *system*: a language for expressing rules, an interpreter that knows how to evaluate them, a memory that remembers them, and agents that run them.

---

## The core idea — a governance rule language and its interpreter

The intellectual center of FabricGuard is **FRL — the FabricGuard Rule Language** — and the agent that interprets it.

### Why a language, not free text

"Every workspace must have at least two admin groups" is not really a sentence; it is a rule with structure. It has a target type (`Workspace`), a property to inspect (admin role assignments), and a constraint (`count >= 2`). If governance lives only as free text, that structure is lost and nothing can be evaluated mechanically. FRL captures the structure while staying readable by a human. A rule names what it applies to, declares one or more `CHECK` conditions, and carries a finding message and a remediation hint.

![Anatomy of an FRL rule](illustrations/frl-anatomy-v01.html)

A real rule looks like this:

```
RULE ws-admin-groups-001 {
    NAME:       "Workspace must have designated Entra admin groups"
    VERSION:    "1.0.0"
    SEVERITY:   ERROR
    APPLIES_TO: Workspace

    PARAMS { admin_groups: List<EntraGroup> }

    CHECK SELF.PERMISSIONS(ADMIN) CONTAINS_ALL $admin_groups

    FINDING:     "Workspace {displayName} is missing required admin groups: {missing_groups}"
    REMEDIATION: "Add the missing groups as Workspace Administrators in Fabric settings"
}
```

The language is deliberately open. `APPLIES_TO` accepts any Fabric item-type string, so any new item type Microsoft introduces is valid in FRL with no language change. Properties are addressed as `SELF.<path>` — the language does not define what properties an object has; the object does. New fields that appear in Fabric's API are referenceable immediately.

### The interpreter's governing principle: the property decides the path

This is the idea that makes FRL more than syntax. **The rule author writes *what* to check; the interpreter decides *how* to evaluate it** — and the signal that decides "how" is the property's namespace.

![How the interpreter routes each check](illustrations/frl-interpreter-v01.html)

A check on `SELF.displayName` or `SELF.PERMISSIONS(ADMIN)` is answerable from Fabric's REST metadata, so the interpreter resolves it through MCP calls. A check on `SELF.LINEAGE.*` requires reading item definitions and reasoning about dependencies. A check on `SELF.delta.*` or `SELF.schema.*` needs Spark to read the data plane, so it routes to notebook execution. The author never states the mechanism — they write `CHECK SELF.delta.enableChangeDataFeed = true` and the interpreter knows that requires a notebook. An explicit `VIA NOTEBOOK` / `VIA MCP` qualifier exists for the rare case where the author needs to override the routing.

| Property form | How the interpreter evaluates it |
|---|---|
| `SELF.<top-level>` (displayName, type, capacityId…) | MCP — `get_item` / `get_workspace` |
| `SELF.PERMISSIONS(role)` | MCP — `list_workspace_roles` |
| `SELF.LINEAGE.*` | MCP — `get_item_definition` + agent reasoning |
| `SELF.delta.*`, `SELF.schema.*`, `SELF.access.*` | Notebook — Spark on the data plane |
| `CHECK … VIA NOTEBOOK` / `VIA MCP` | Explicit override |

The full language reference — object types, every namespace, the CHECK operators, derived arithmetic expressions, parameters — is in [`docs/frl-language.md`](frl-language.md).

> **Scope note (this submission).** The language *design* covers all of the above. At runtime, the **MCP-direct evaluation path is the stable, demonstrated path**; the **notebook execution path is experimental** and is excluded from the demo. The demo evaluates rules whose checks resolve through Fabric metadata.

---

## The main actors

Three agents carry the flow a user actually sees, end to end.

**FRL Copilot — the authoring face.** You talk to the Copilot in natural language. It reconciles your wording against real Fabric terminology (`MLV` ≈ `MaterializedLakeView`, `AD groups` ≈ `Entra security groups`), and before it writes anything it searches the existing rulebook in Elastic for a similar rule — so you don't silently create a duplicate. When the closest match is an older, superseded version of a rule, the Copilot recognises that and explains the version history rather than treating your request as brand new. It generates the FRL, and on your confirmation saves it. It never edits a rule in place: rules are immutable, and a change is always a new version.

**Compliance Orchestrator — the run conductor.** Given a rule and a scope, the Orchestrator retrieves the rule from Elastic, drives its evaluation across the target objects, collects the per-object outcomes, and persists the run's results back to Elastic. It is the component that turns "a stored rule" into "a compliance run with an auditable result."

**Policy Check — the evaluator.** Policy Check is the agent that actually inspects the live Fabric tenant. It walks each object the rule applies to, reads the metadata each `CHECK` needs through the Fabric MCP layer, applies the condition, and returns a pass / fail / error verdict per object together with the reasoning behind it.

The round trip is: **you describe → Copilot compiles and stores (Elastic) → Orchestrator runs → Policy Check evaluates (Fabric) → results stored and visualised (Elastic)**. Each step is a distinct agent with a single responsibility, which keeps the audit trail legible — a failure is attributable to one agent and one tool call, not buried inside one monolithic prompt.

---

## Internal architecture (supporting cast)

These pieces make the main actors work but are not the point of the product.

**Sub-agents inside the Copilot.** The FRL Copilot ships with two small specialist sub-agents — a Google-Search specialist and a URL-fetch specialist — used only to ground terminology in Microsoft's Fabric documentation. They are an internal implementation detail packaged inside the Copilot's deployment, not actors the user interacts with.

**MCP proxies (Cloud Run).** Two thin proxies sit between the agents and the outside world. The **Elastic MCP proxy** brokers the `governance-rules` and `governance-results` indices and hybrid search; the agents' read tools come from Elastic's built-in Agent Builder MCP, and the **write tools (`save_rule`, `save_results`) are custom tools the proxy adds**, because the built-in MCP is read-only. The **Fabric MCP proxy** exposes Fabric REST as MCP tools and handles the Entra service-principal auth. The proxies exist because the agent runtime connects to HTTP-based MCP servers, and they keep all credentials out of the agent code.

**Runtime and deployment.** Each main agent is a Vertex AI Agent Engine (Reasoning Engine) deployment, invoked over its `:query` endpoint. Agents are deployed via the SDK rather than the Studio button, to work around a known packaging bug; that and the AI-Studio Preview issue are documented in [`docs/known-issues.md`](known-issues.md). The auth model and the secret-exposure trade-offs are in [`docs/security.md`](security.md).

![Main actors and internal architecture](illustrations/fabricguard-architecture-v01.html)

---

## Elastic — the system's memory

Elastic Cloud Serverless is where governance becomes a managed asset rather than a set of scripts.

The **`governance-rules`** index stores each rule with its natural-language intent in a `semantic_text` field backed by **ELSER v2**, so the Copilot's "is this a duplicate?" check is true hybrid retrieval — it catches a rule the user re-described in different words. Versioning is first-class: `rule_id` is stable across versions, `version` increments, and exactly one `is_current` document is true per rule, which is what lets the Copilot reason about rollbacks versus genuinely new rules.

The **`governance-results`** index stores the outcome of each compliance run — one document per evaluated object, carrying the rule, the object, the pass/fail/error status, and the agent's finding — so results are queryable, aggregatable, and chartable. The Orchestrator writes them through the proxy's `save_results` tool, and the results can be visualised both in the product's own UI and natively in Elastic.

---

## Technologies used

| Layer | Technology |
|---|---|
| Reasoning models | Gemini (Flash for authoring, Pro for code-heavy paths) |
| Agent runtime | Vertex AI Agent Engine (Reasoning Engine), Google ADK |
| Rule + result store | Elastic Cloud Serverless — `semantic_text` + ELSER v2, hybrid (BM25 + sparse vector) |
| Tool protocol | Model Context Protocol (MCP) over Streamable HTTP |
| MCP transport | Cloud Run (Elastic MCP proxy, Fabric MCP proxy) |
| Front end | AG-UI / CopilotKit |
| Target platform | Microsoft Fabric (Workspaces, Lakehouses, Tables, MLVs, Notebooks) |
| Language design | FabricGuard Rule Language (FRL) — declarative, interpreted, namespace-routed |

---

## Repository structure

```
.
├── FRLCopilot/          # authoring agent — Definition/ (Agents.py, prompt.md) + Deployment/
├── Orchestrator/        # Compliance Orchestrator — run conductor
├── PolicyCheck/         # Policy Check — live Fabric evaluator
├── proxies/
│   ├── elastic-mcp/     # Cloud Run: governance-rules + governance-results, save_rule/save_results
│   └── fabric-mcp/      # Cloud Run: Fabric REST as MCP
├── frontend/            # AG-UI / CopilotKit app — the public hosted face
├── docs/
│   ├── architecture.md
│   ├── frl-language.md  # the FRL reference
│   ├── known-issues.md
│   └── security.md
└── LICENSE              # Apache 2.0
```

---

## Findings and learnings

Treating FRL as an **interpreted** language — where the routing decision lives at runtime, per check, keyed on the property namespace — kept the language declarative while letting the interpreter own the mechanism. The author never thinks about REST versus Spark.

Elastic's **hybrid search plus the version model** made deduplication trivial in a way a plain database could not: ELSER caught semantically identical rules phrased differently, and `is_current` let the Copilot tell "you're proposing a rollback" apart from "you're proposing a new rule."

**MCP as the cross-system connector** let one Google-hosted agent reach both Microsoft Fabric and Elastic through the same pattern — a concrete demonstration of MCP's interop value.

What we'd build next: promote the per-check **Rule Router** into its own agent for cleaner explainability, stabilise the **notebook execution path** so data-plane checks join the demo, and split the lineage/definition evaluators into independently deployed agents.

## License

Apache 2.0. See [`LICENSE`](LICENSE).

---

_Track: Elastic · Built during the Google Cloud Rapid Agent Hackathon contest period._
