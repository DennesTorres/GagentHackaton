import { FormEvent, useEffect, useRef, useState } from "react";
import { HttpAgent } from "@ag-ui/client";
import { EventType } from "@ag-ui/core";

// ── Skill instruction attached per-session via context[] ───────────────────────
// An AG-UI runtime in the path injects this into the agent's system prompt so the
// agent calls render tools instead of producing markdown for structured data.
const SKILL_INSTRUCTION =
  "Whenever you would present / show / display / list / summarize structured " +
  "data to the user — a rule, a list of rules, a run's per-object results, " +
  "counts or ratios — do it by calling one of the render tools (render_table, " +
  "render_donut, render_chart, render_card, render_badge, render_code, render_kpi), " +
  "shaping the data to that tool's input. Do not produce a markdown table, " +
  "bullets, or raw JSON for structured results while these tools are available " +
  "— render them. Free-form prose, a short answer, or a question stays plain text. " +
  "Never emit **bold** or ``` fences — send raw values; render_code takes the " +
  "raw code string. Call only exact tool names; never invent a render tool. " +
  "After rendering, one short text takeaway is fine — do not restate in prose.";

// ── AG-UI tool schemas — names/params must match component registrations exactly ─

const RENDER_TOOLS = [
  {
    name: "render_table",
    description:
      "Use when the answer is a set of items to compare side by side: per-item " +
      "compliance-scan results (each Fabric item — workspace, lakehouse, semantic model, " +
      "capacity, pipeline — with pass/fail/error and the reason), the rule catalog, or a " +
      "rule's version history.",
    parameters: {
      type: "object" as const,
      properties: {
        title: { type: "string" },
        columns: {
          type: "array",
          items: {
            type: "object",
            properties: {
              key: { type: "string" },
              label: { type: "string" },
              align: { type: "string", enum: ["left", "right", "center"] },
            },
            required: ["key", "label"],
          },
        },
        rows: {
          type: "array",
          items: { type: "object" },
          description: "Each row has keys matching columns[].key, plus optional _status",
        },
        emphasizeStatus: { type: "boolean" },
      },
      required: ["columns", "rows"],
    },
  },
  {
    name: "render_donut",
    description:
      "Use to show, at a glance, how a single compliance run split across passed / failed / " +
      "errored — the proportion of items in each outcome; the 'how compliant are we' headline.",
    parameters: {
      type: "object" as const,
      properties: {
        title: { type: "string" },
        centerLabel: { type: "string" },
        segments: {
          type: "array",
          items: {
            type: "object",
            properties: {
              label: { type: "string" },
              value: { type: "number" },
              tone: { type: "string", enum: ["pass", "fail", "error", "neutral"] },
            },
            required: ["label", "value"],
          },
        },
      },
      required: ["segments"],
    },
  },
  {
    name: "render_chart",
    description:
      "Use to compare quantities across categories (violations by severity, failing items per " +
      "workspace, rules per domain) or change over time (compliance rate week over week, new " +
      "violations across a release).",
    parameters: {
      type: "object" as const,
      properties: {
        type: { type: "string", enum: ["bar", "line", "pie"] },
        title: { type: "string" },
        xLabel: { type: "string" },
        yLabel: { type: "string" },
        series: {
          type: "array",
          items: {
            type: "object",
            properties: {
              name: { type: "string" },
              points: {
                type: "array",
                items: {
                  type: "object",
                  properties: { x: { type: "string" }, y: { type: "number" } },
                  required: ["x", "y"],
                },
              },
            },
            required: ["name", "points"],
          },
        },
      },
      required: ["type", "series"],
    },
  },
  {
    name: "render_card",
    description:
      "Use to spotlight one subject with a verdict and a few facts: a completed run's summary, " +
      "a rule-saved confirmation, or one rule's identity (name, severity, version, " +
      "current/superseded).",
    parameters: {
      type: "object" as const,
      properties: {
        title: { type: "string" },
        subtitle: { type: "string" },
        status: { type: "string", enum: ["pass", "fail", "error", "info"] },
        fields: {
          type: "array",
          items: {
            type: "object",
            properties: {
              label: { type: "string" },
              value: { type: "string" },
            },
            required: ["label", "value"],
          },
        },
        body: { type: "string" },
      },
      required: ["title", "fields"],
    },
  },
  {
    name: "render_badge",
    description:
      "Use for a single short status read inline: a rule's lifecycle state " +
      "(current/superseded), its severity, or one pass / fail / error verdict.",
    parameters: {
      type: "object" as const,
      properties: {
        label: { type: "string" },
        status: { type: "string", enum: ["pass", "fail", "error", "info", "neutral"] },
      },
      required: ["label"],
    },
  },
  {
    name: "render_code",
    description:
      "Use to show the exact rule definition in Fabric Rule Language (FRL), or a structured " +
      "spec — above all, a rule's proposed FRL before the user approves saving it.",
    parameters: {
      type: "object" as const,
      properties: {
        code: { type: "string" },
        language: { type: "string" },
        title: { type: "string" },
        copyable: { type: "boolean" },
      },
      required: ["code"],
    },
  },
  {
    name: "render_kpi",
    description:
      "Use to surface headline numbers as visual tiles: a single key metric or a small set " +
      "of related counts (up to ~5) where the value itself is the point and colour signals " +
      "significance — pass (green), fail (red), error (amber), info (cyan), highlight " +
      "(indigo), or neutral (no colour). Examples: total items evaluated, passed, failed, " +
      "errored counts from a compliance run; number of rules in the catalog; a single " +
      "percentage score. Prefer this over a table when there are few numbers and no " +
      "per-item breakdown is needed.",
    parameters: {
      type: "object" as const,
      properties: {
        items: {
          type: "array",
          items: {
            type: "object",
            properties: {
              label:    { type: "string" },
              value:    { type: "string" },
              sublabel: { type: "string" },
              tone: {
                type: "string",
                enum: ["pass", "fail", "error", "info", "highlight", "neutral"],
              },
            },
            required: ["label", "value"],
          },
        },
      },
      required: ["items"],
    },
  },
];

// ── Tone / status colour map ───────────────────────────────────────────────────

const TONE: Record<string, string> = {
  pass:    "#10b981",
  fail:    "#f87171",
  error:   "#fbbf24",
  info:    "#22d3ee",
  neutral: "#3d5272",
};

const CHART_COLORS = ["#6366f1", "#22d3ee", "#10b981", "#f87171", "#fbbf24", "#a78bfa"];

// ── render_badge ───────────────────────────────────────────────────────────────

function RenderBadge({ label = "", status = "neutral" }: { label?: string; status?: string }) {
  const icons: Record<string, string> = { pass: "✅", fail: "❌", error: "⚠️", info: "ℹ️" };
  const icon = icons[status] ?? "";
  return (
    <span className={`render-badge render-badge-${status}`}>
      {icon && <>{icon} </>}{label}
    </span>
  );
}

// ── render_table ───────────────────────────────────────────────────────────────

type ColDef = { key: string; label: string; align?: "left" | "right" | "center" };
type RowData = Record<string, unknown>;

function RenderTable({ title, columns = [], rows = [], emphasizeStatus }: {
  title?: string;
  columns?: ColDef[];
  rows?: RowData[];
  emphasizeStatus?: boolean;
}) {
  if (!columns.length || !rows.length) return null;

  const sorted = emphasizeStatus
    ? [...rows].sort((a, b) => {
        const rank = (s: unknown) => s === "fail" ? 0 : s === "error" ? 1 : 2;
        return rank(a._status) - rank(b._status);
      })
    : rows;

  return (
    <div className="render-table">
      {title && <div className="render-table-title">{title}</div>}
      <table className="render-table-grid">
        <thead>
          <tr>
            {columns.map(c => (
              <th key={c.key} style={{ textAlign: c.align ?? "left" }}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => {
            const st = String(row._status ?? "");
            return (
              <tr key={i} className={st ? `row-${st}` : ""}>
                {columns.map(c => (
                  <td key={c.key} style={{ textAlign: c.align ?? "left" }}>
                    {c.key === "_status"
                      ? <span className={`render-status-${st}`}>{
                          st === "pass" ? "✅ pass" : st === "fail" ? "❌ fail" : st === "error" ? "⚠️ error" : st
                        }</span>
                      : String(row[c.key] ?? "—")}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── render_donut ───────────────────────────────────────────────────────────────

type Segment = { label: string; value: number; tone?: string };

function RenderDonut({ title, centerLabel, segments = [] }: {
  title?: string;
  centerLabel?: string;
  segments?: Segment[];
}) {
  const total = segments.reduce((s, seg) => s + seg.value, 0);
  if (!total) return null;

  const R = 54, CX = 70, CY = 70, SW = 18;
  const circ = 2 * Math.PI * R;
  let cum = 0;
  const arcs = segments.map((seg, i) => {
    const dash = (seg.value / total) * circ;
    const arc = {
      ...seg,
      color: TONE[seg.tone ?? "neutral"] ?? CHART_COLORS[i % CHART_COLORS.length],
      dasharray: `${dash} ${circ - dash}`,
      dashoffset: -cum,
    };
    cum += dash;
    return arc;
  });

  return (
    <div className="render-donut">
      {title && <div className="render-chart-title">{title}</div>}
      <div className="render-donut-body">
        <svg viewBox="0 0 140 140" width={140} style={{ flexShrink: 0 }}>
          <g transform={`rotate(-90 ${CX} ${CY})`}>
            <circle cx={CX} cy={CY} r={R} fill="none" stroke="var(--border)" strokeWidth={SW} />
            {arcs.map((a, i) => (
              <circle key={i} cx={CX} cy={CY} r={R} fill="none"
                stroke={a.color} strokeWidth={SW}
                strokeDasharray={a.dasharray}
                strokeDashoffset={a.dashoffset}
              />
            ))}
          </g>
          {centerLabel && (
            <text x={CX} y={CY + 5} textAnchor="middle"
              fill="var(--text-bright)" fontSize={12} fontWeight={700}>{centerLabel}</text>
          )}
        </svg>
        <div className="render-legend">
          {arcs.map((a, i) => (
            <div key={i} className="render-legend-row">
              <span className="render-legend-dot" style={{ background: a.color }} />
              <span className="render-legend-label">{a.label}</span>
              <span className="render-legend-val">{a.value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── render_chart ───────────────────────────────────────────────────────────────

type ChartSeries = { name: string; points: Array<{ x: string; y: number }> };

const VW = 300, VH = 180, P = { t: 14, r: 12, b: 36, l: 38 };
const IW = VW - P.l - P.r, IH = VH - P.t - P.b;

function Axes() {
  return (
    <>
      <line x1={P.l} y1={P.t} x2={P.l} y2={P.t + IH} stroke="var(--border-bright)" strokeWidth={1} />
      <line x1={P.l} y1={P.t + IH} x2={P.l + IW} y2={P.t + IH} stroke="var(--border-bright)" strokeWidth={1} />
    </>
  );
}

function BarChart({ title, xLabel, yLabel, series }: { title?: string; xLabel?: string; yLabel?: string; series: ChartSeries[] }) {
  const all = series.flatMap(s => s.points);
  const xs = [...new Set(all.map(p => p.x))];
  const maxY = Math.max(...all.map(p => p.y), 1);
  const gw = IW / xs.length;
  const bw = Math.max(4, (gw / series.length) * 0.7);

  return (
    <div className="render-chart">
      {title && <div className="render-chart-title">{title}</div>}
      <svg viewBox={`0 0 ${VW} ${VH}`} width="100%">
        <Axes />
        {series.map((s, si) =>
          s.points.map((p, pi) => {
            const xi = xs.indexOf(p.x);
            const bx = P.l + xi * gw + si * (bw + 2) + (gw - series.length * (bw + 2)) / 2;
            const bh = (p.y / maxY) * IH;
            return <rect key={`${si}-${pi}`} x={bx} y={P.t + IH - bh}
              width={bw} height={bh} fill={CHART_COLORS[si % CHART_COLORS.length]} rx={2} />;
          })
        )}
        {xs.map((x, i) => (
          <text key={x} x={P.l + i * gw + gw / 2} y={VH - (xLabel ? 20 : 8)}
            textAnchor="middle" fill="var(--muted-light)" fontSize={9}>{x}</text>
        ))}
        {xLabel && <text x={VW / 2} y={VH - 4} textAnchor="middle" fill="var(--muted-light)" fontSize={9}>{xLabel}</text>}
        {yLabel && <text x={12} y={P.t + IH / 2} textAnchor="middle" fill="var(--muted-light)" fontSize={9}
          transform={`rotate(-90 12 ${P.t + IH / 2})`}>{yLabel}</text>}
        {series.length > 1 && series.map((s, i) => (
          <g key={s.name}>
            <rect x={P.l + i * 75} y={3} width={8} height={8} rx={2} fill={CHART_COLORS[i % CHART_COLORS.length]} />
            <text x={P.l + i * 75 + 12} y={10} fill="var(--muted-light)" fontSize={9}>{s.name}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function LineChart({ title, xLabel, yLabel, series }: { title?: string; xLabel?: string; yLabel?: string; series: ChartSeries[] }) {
  const all = series.flatMap(s => s.points);
  const xs = [...new Set(all.map(p => p.x))];
  const maxY = Math.max(...all.map(p => p.y), 1);
  const step = IW / Math.max(xs.length - 1, 1);
  const toXY = (p: { x: string; y: number }) => ({
    x: P.l + xs.indexOf(p.x) * step,
    y: P.t + IH - (p.y / maxY) * IH,
  });

  return (
    <div className="render-chart">
      {title && <div className="render-chart-title">{title}</div>}
      <svg viewBox={`0 0 ${VW} ${VH}`} width="100%">
        <Axes />
        {series.map((s, si) => {
          const pts = s.points.map(toXY);
          const color = CHART_COLORS[si % CHART_COLORS.length];
          return (
            <g key={s.name}>
              <polyline points={pts.map(p => `${p.x},${p.y}`).join(" ")}
                fill="none" stroke={color} strokeWidth={2} />
              {pts.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={3} fill={color} />)}
            </g>
          );
        })}
        {xs.map((x, i) => (
          <text key={x} x={P.l + i * step} y={VH - (xLabel ? 20 : 8)}
            textAnchor="middle" fill="var(--muted-light)" fontSize={9}>{x}</text>
        ))}
        {xLabel && <text x={VW / 2} y={VH - 4} textAnchor="middle" fill="var(--muted-light)" fontSize={9}>{xLabel}</text>}
        {yLabel && <text x={12} y={P.t + IH / 2} textAnchor="middle" fill="var(--muted-light)" fontSize={9}
          transform={`rotate(-90 12 ${P.t + IH / 2})`}>{yLabel}</text>}
      </svg>
    </div>
  );
}

function PieChart({ title, series }: { title?: string; series: ChartSeries[] }) {
  const pts = series[0]?.points ?? [];
  const total = pts.reduce((s, p) => s + p.y, 0);
  if (!total) return null;

  const CX = 70, CY = 70, R = 62;
  const toXY = (r: number, a: number) => ({ x: CX + r * Math.cos(a), y: CY + r * Math.sin(a) });

  let ang = -Math.PI / 2;
  const slices = pts.map((p, i) => {
    const sweep = (p.y / total) * 2 * Math.PI;
    const s = toXY(R, ang);
    const e = toXY(R, ang + sweep);
    const large = sweep > Math.PI ? 1 : 0;
    const slice = { x: p.x, y: p.y, color: CHART_COLORS[i % CHART_COLORS.length],
      d: `M ${CX} ${CY} L ${s.x} ${s.y} A ${R} ${R} 0 ${large} 1 ${e.x} ${e.y} Z` };
    ang += sweep;
    return slice;
  });

  return (
    <div className="render-chart render-chart-pie">
      {title && <div className="render-chart-title">{title}</div>}
      <div className="render-donut-body">
        <svg viewBox="0 0 140 140" width={140} style={{ flexShrink: 0 }}>
          {slices.map((s, i) => <path key={i} d={s.d} fill={s.color} stroke="var(--bg-card)" strokeWidth={1} />)}
        </svg>
        <div className="render-legend">
          {slices.map((s, i) => (
            <div key={i} className="render-legend-row">
              <span className="render-legend-dot" style={{ background: s.color }} />
              <span className="render-legend-label">{s.x}</span>
              <span className="render-legend-val">{s.y}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function RenderChart({ type, title, xLabel, yLabel, series = [] }: {
  type?: "bar" | "line" | "pie";
  title?: string;
  xLabel?: string;
  yLabel?: string;
  series?: ChartSeries[];
}) {
  if (type === "pie")  return <PieChart title={title} series={series} />;
  if (type === "line") return <LineChart title={title} xLabel={xLabel} yLabel={yLabel} series={series} />;
  return <BarChart title={title} xLabel={xLabel} yLabel={yLabel} series={series} />;
}

// ── render_card ────────────────────────────────────────────────────────────────

function RenderCard({ title = "", subtitle, status, fields = [], body }: {
  title?: string;
  subtitle?: string;
  status?: string;
  fields?: Array<{ label: string; value: string | number }>;
  body?: string;
}) {
  return (
    <div className="render-card">
      <div className="render-card-header">
        <div>
          <div className="render-card-title">{title}</div>
          {subtitle && <div className="render-card-subtitle">{subtitle}</div>}
        </div>
        {status && <RenderBadge label={status} status={status} />}
      </div>
      {fields.length > 0 && (
        <div className="render-card-fields">
          {fields.map((f, i) => (
            <div key={i} className="render-card-field">
              <span className="render-card-field-label">{f.label}</span>
              <span className="render-card-field-value">{f.value}</span>
            </div>
          ))}
        </div>
      )}
      {body && <div className="render-card-body">{body}</div>}
    </div>
  );
}

// ── render_code ────────────────────────────────────────────────────────────────

function RenderCode({ code = "", language = "frl", title, copyable = true }: {
  code?: string;
  language?: string;
  title?: string;
  copyable?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="render-code">
      <div className="render-code-header">
        <span className="render-code-lang">{title || language.toUpperCase()}</span>
        {copyable !== false && (
          <button className="render-code-copy" onClick={copy}>{copied ? "Copied!" : "Copy"}</button>
        )}
      </div>
      <pre className="render-code-body"><code>{code}</code></pre>
    </div>
  );
}

// ── render_kpi ─────────────────────────────────────────────────────────────────

function RenderKpi({ items = [] }: {
  items?: { label: string; value: string; sublabel?: string; tone?: string }[];
}) {
  return (
    <div className="render-kpi">
      {items.map((item, i) => (
        <div key={i} className={`render-kpi-tile render-kpi-tile-${item.tone ?? "neutral"}`}>
          <div className="render-kpi-value">{item.value}</div>
          <div className="render-kpi-label">{item.label}</div>
          {item.sublabel && <div className="render-kpi-sublabel">{item.sublabel}</div>}
        </div>
      ))}
    </div>
  );
}

// ── Message model ──────────────────────────────────────────────────────────────

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming: boolean;
  isToolCall?: boolean;
  renderType?: string;
  renderArgs?: Record<string, unknown>;
}

interface AgentState {
  vertexSessionId?: string;
}

interface PendingToolCall {
  id: string;
  name: string;
  argsBuffer: string;
}

// ── Chat page ──────────────────────────────────────────────────────────────────

export default function ChatPage() {
  const [ready, setReady] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [currentStep, setCurrentStep] = useState<string | null>(null);
  const threadIdRef = useRef(crypto.randomUUID());
  const agentStateRef = useRef<AgentState | null>(null);
  const pendingToolCallRef = useRef<PendingToolCall | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch("/api/config")
      .then(r => r.json())
      .then((data: { agent_url: string | null }) => {
        if (!data.agent_url) throw new Error("FABOPS environment variable not set.");
        setReady(true);
      })
      .catch((e: Error) => setConfigError(e.message));
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, currentStep]);

  const sendMessage = (e: FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || !ready || isRunning) return;

    setInput("");
    setIsRunning(true);
    setCurrentStep("Thinking…");

    const userMsgId = crypto.randomUUID();
    const history = [
      ...messages
        .filter(m => !m.renderType && !m.isToolCall)
        .map(m => ({ id: m.id, role: m.role, content: m.content })),
      { id: userMsgId, role: "user" as const, content: text },
    ];

    setMessages(prev => [...prev, { id: userMsgId, role: "user", content: text, isStreaming: false }]);
    pendingToolCallRef.current = null;

    const agent = new HttpAgent({ url: "/api/agent", fetch: window.fetch.bind(window) });
    let activeMsgId: string | null = null;

    agent
      .run({
        runId: crypto.randomUUID(),
        threadId: threadIdRef.current,
        messages: history,
        tools: RENDER_TOOLS,
        context: [{ description: "ui-rendering-skill", value: SKILL_INSTRUCTION }],
        state: agentStateRef.current,
      })
      .subscribe({
        next: (event) => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const e = event as any;

          switch (event.type) {

            case EventType.TEXT_MESSAGE_START:
              setCurrentStep(null);
              activeMsgId = e.messageId as string;
              setMessages(prev => [...prev, {
                id: activeMsgId!, role: "assistant", content: "", isStreaming: true,
              }]);
              break;

            case EventType.TEXT_MESSAGE_CONTENT: {
              const mid = (e.messageId as string) || activeMsgId;
              setMessages(prev => prev.map(m =>
                m.id === mid ? { ...m, content: m.content + (e.delta as string || "") } : m
              ));
              break;
            }

            case EventType.TEXT_MESSAGE_END: {
              const mid = (e.messageId as string) || activeMsgId;
              setMessages(prev => prev.map(m => m.id === mid ? { ...m, isStreaming: false } : m));
              break;
            }

            case EventType.TOOL_CALL_START: {
              const toolName = e.toolCallName as string || "tool";
              const callId  = e.toolCallId  as string || crypto.randomUUID();
              const isRender = toolName.startsWith("render_");

              if (isRender) {
                pendingToolCallRef.current = { id: callId, name: toolName, argsBuffer: "" };
                setMessages(prev => [...prev, {
                  id: callId, role: "assistant", content: "",
                  isStreaming: true, renderType: toolName, renderArgs: undefined,
                }]);
              } else {
                setCurrentStep(`Calling: ${toolName}`);
                setMessages(prev => [...prev, {
                  id: callId, role: "assistant",
                  content: `Calling tool: ${toolName}`, isStreaming: false, isToolCall: true,
                }]);
              }
              break;
            }

            case EventType.TOOL_CALL_ARGS: {
              const callId = e.toolCallId as string;
              if (pendingToolCallRef.current?.id === callId) {
                pendingToolCallRef.current.argsBuffer += (e.delta as string || "");
              }
              break;
            }

            case EventType.TOOL_CALL_END: {
              const callId  = e.toolCallId as string;
              const pending = pendingToolCallRef.current;
              if (pending?.id === callId) {
                let renderArgs: Record<string, unknown> = {};
                try { renderArgs = JSON.parse(pending.argsBuffer); } catch { /* empty args */ }
                setMessages(prev => prev.map(m =>
                  m.id === callId ? { ...m, renderArgs, isStreaming: false } : m
                ));
                setCurrentStep(null);
                pendingToolCallRef.current = null;
              }
              break;
            }

            case EventType.RUN_FINISHED:
              setCurrentStep(null);
              setIsRunning(false);
              break;

            case EventType.RUN_ERROR: {
              const errText = (e.message as string) || "Agent reported an error";
              setCurrentStep(null);
              if (activeMsgId) {
                setMessages(prev => prev.map(m =>
                  m.id === activeMsgId ? { ...m, content: errText, isStreaming: false } : m
                ));
              } else {
                setMessages(prev => [...prev, {
                  id: crypto.randomUUID(), role: "assistant", content: errText, isStreaming: false,
                }]);
              }
              setIsRunning(false);
              break;
            }

            case EventType.STATE_SNAPSHOT: {
              const snapshot = e.snapshot as AgentState | undefined;
              if (snapshot?.vertexSessionId) {
                agentStateRef.current = { vertexSessionId: snapshot.vertexSessionId };
              }
              break;
            }
          }
        },
        error: (err: Error) => {
          setCurrentStep(null);
          setMessages(prev => [...prev, {
            id: crypto.randomUUID(), role: "assistant",
            content: `Connection error: ${err.message}`, isStreaming: false,
          }]);
          setIsRunning(false);
        },
        complete: () => {
          setCurrentStep(null);
          setIsRunning(false);
          setMessages(prev => {
            const last = prev[prev.length - 1];
            if (!last || last.role !== "assistant" || last.isToolCall) {
              return [...prev, {
                id: crypto.randomUUID(), role: "assistant",
                content: "Stream ended without a response. The agent may have timed out — check Cloud Run logs.",
                isStreaming: false,
              }];
            }
            return prev;
          });
        },
      });
  };

  const clearChat = () => {
    setMessages([]);
    setCurrentStep(null);
    threadIdRef.current = crypto.randomUUID();
    agentStateRef.current = null;
    pendingToolCallRef.current = null;
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const renderComponent = (type: string, args: any) => {
    switch (type) {
      case "render_table":  return <RenderTable  {...args} />;
      case "render_donut":  return <RenderDonut  {...args} />;
      case "render_chart":  return <RenderChart  {...args} />;
      case "render_card":   return <RenderCard   {...args} />;
      case "render_badge":  return <RenderBadge  {...args} />;
      case "render_code":   return <RenderCode   {...args} />;
      case "render_kpi":    return <RenderKpi    {...args} />;
      default: return null;
    }
  };

  return (
    <div className="chat-page">
      <div className="chat-area">
        <div className="messages-container">
          {configError && (
            <div className="empty-state">
              <strong>Agent not configured</strong>
              {configError}
            </div>
          )}

          {!configError && messages.length === 0 && !isRunning && (
            <div className="empty-state">
              <strong>Ready to evaluate</strong>
              Try: "every lakehouse in production must be assigned to a capacity" — or ask FabOps to list existing rules.
            </div>
          )}

          {messages.map(msg => (
            <div
              key={msg.id}
              className={
                msg.renderType
                  ? "render-message"
                  : `message message-${msg.role}${msg.isToolCall ? " message-tool" : ""}`
              }
            >
              {msg.renderType ? (
                msg.isStreaming
                  ? <div className="render-loading"><span className="thinking-dots"><span /><span /><span /></span></div>
                  : msg.renderArgs && renderComponent(msg.renderType, msg.renderArgs)
              ) : (
                <>
                  <div className="message-role">{msg.role === "user" ? "You" : msg.isToolCall ? "Tool" : "Agent"}</div>
                  <div className="message-content">
                    {msg.content}
                    {msg.isStreaming && <span className="cursor" />}
                  </div>
                </>
              )}
            </div>
          ))}

          {currentStep && (
            <div className="message message-assistant">
              <div className="message-role">Agent</div>
              <div className="message-content thinking-bubble">
                <span className="thinking-label">{currentStep}</span>
                <span className="thinking-dots"><span /><span /><span /></span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        <form className="input-bar" onSubmit={sendMessage}>
          <input
            type="text"
            placeholder={isRunning ? "Agent is working…" : "Describe a rule or ask about your Fabric governance…"}
            value={input}
            onChange={e => setInput(e.target.value)}
            disabled={!ready || isRunning}
          />
          <button type="submit" disabled={!input.trim() || !ready || isRunning}>
            {isRunning ? "…" : "Send"}
          </button>
        </form>

        <div className="chat-actions">
          <button className="btn-secondary" onClick={clearChat}>Clear conversation</button>
        </div>
      </div>
    </div>
  );
}
