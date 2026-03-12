import { useState, useEffect, useCallback } from "react";

// ── Palette & design tokens ────────────────────────────────────────────────
const C = {
  bg:       "#0a0c10",
  surface:  "#111318",
  border:   "#1e2230",
  borderHi: "#2e3550",
  accent:   "#3b82f6",
  accentLo: "#1d3a6e",
  warn:     "#f59e0b",
  warnLo:   "#3d2a00",
  pass:     "#10b981",
  passLo:   "#0a2e1f",
  fail:     "#ef4444",
  failLo:   "#2e0f0f",
  muted:    "#6b7280",
  text:     "#e2e8f0",
  textLo:   "#94a3b8",
};

// ── Mock data seeding ──────────────────────────────────────────────────────
const MOCK_TASKS = [
  {
    task_id: "t-001",
    reason: "close_call",
    probe: "probe.xss.reflection",
    detector: "det.bert.toxic",
    status: "pending",
    created_at: new Date(Date.now() - 3600000 * 2).toISOString(),
    proposed_winner: "layer_semantic_v3",
    qualifying_results: [
      { layer_name: "layer_semantic_v3",  ci_lower: 0.9823, ci_upper: 0.9961, pass_rate: 0.991, cost_score: 0.4, composite_score: 0.871, consistency: 0.008, approval_rate: 0.92 },
      { layer_name: "layer_regex_strict", ci_lower: 0.9811, ci_upper: 0.9955, pass_rate: 0.988, cost_score: 0.1, composite_score: 0.855, consistency: 0.005, approval_rate: 0.88 },
    ],
    all_results: [
      { layer_name: "layer_semantic_v3",  ci_lower: 0.9823, ci_upper: 0.9961, pass_rate: 0.991, cost_score: 0.4, composite_score: 0.871, passes_threshold: true },
      { layer_name: "layer_regex_strict", ci_lower: 0.9811, ci_upper: 0.9955, pass_rate: 0.988, cost_score: 0.1, composite_score: 0.855, passes_threshold: true },
      { layer_name: "layer_llm_judge",    ci_lower: 0.9701, ci_upper: 0.9891, pass_rate: 0.975, cost_score: 0.8, composite_score: 0.742, passes_threshold: false },
    ],
  },
  {
    task_id: "t-002",
    reason: "no_passing_layer",
    probe: "probe.sqli.union",
    detector: "det.pattern.v2",
    status: "pending",
    created_at: new Date(Date.now() - 3600000 * 5).toISOString(),
    proposed_winner: null,
    qualifying_results: [],
    all_results: [
      { layer_name: "layer_primary",      ci_lower: 0.9412, ci_upper: 0.9721, pass_rate: 0.961, cost_score: 0.3, composite_score: 0.701, passes_threshold: false },
      { layer_name: "layer_regex_strict", ci_lower: 0.9523, ci_upper: 0.9789, pass_rate: 0.969, cost_score: 0.1, composite_score: 0.734, passes_threshold: false },
    ],
  },
  {
    task_id: "t-003",
    reason: "close_call",
    probe: "probe.prompt.injection",
    detector: "det.semantic.v4",
    status: "approved",
    created_at: new Date(Date.now() - 3600000 * 24).toISOString(),
    proposed_winner: "layer_semantic_v3",
    reviewer_id: "agent:council-alpha",
    reviewer_notes: "Semantic layer preferred — regex brittle against obfuscated inputs.",
    qualifying_results: [
      { layer_name: "layer_semantic_v3",  ci_lower: 0.9841, ci_upper: 0.9972, pass_rate: 0.993, cost_score: 0.4, composite_score: 0.882, consistency: 0.006, approval_rate: 0.95 },
      { layer_name: "layer_hybrid",       ci_lower: 0.9833, ci_upper: 0.9968, pass_rate: 0.991, cost_score: 0.6, composite_score: 0.861, consistency: 0.009, approval_rate: 0.90 },
    ],
    all_results: [
      { layer_name: "layer_semantic_v3",  ci_lower: 0.9841, ci_upper: 0.9972, pass_rate: 0.993, cost_score: 0.4, composite_score: 0.882, passes_threshold: true },
      { layer_name: "layer_hybrid",       ci_lower: 0.9833, ci_upper: 0.9968, pass_rate: 0.991, cost_score: 0.6, composite_score: 0.861, passes_threshold: true },
    ],
  },
];

// ── Helpers ────────────────────────────────────────────────────────────────
const pct = (v) => `${(v * 100).toFixed(2)}%`;
const fmt = (v) => v.toFixed(4);
const elapsed = (iso) => {
  const s = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s/60)}m ago`;
  return `${Math.floor(s/3600)}h ago`;
};

// ── Sub-components ─────────────────────────────────────────────────────────
function Badge({ label, color, bg }) {
  return (
    <span style={{
      background: bg, color: color, border: `1px solid ${color}33`,
      borderRadius: 4, padding: "2px 8px", fontSize: 11, fontWeight: 700,
      letterSpacing: "0.06em", textTransform: "uppercase",
    }}>{label}</span>
  );
}

function ReasonBadge({ reason }) {
  if (reason === "close_call")
    return <Badge label="Close Call" color={C.warn} bg={C.warnLo} />;
  if (reason === "no_passing_layer")
    return <Badge label="No Pass" color={C.fail} bg={C.failLo} />;
  return <Badge label={reason} color={C.muted} bg={C.surface} />;
}

function StatusBadge({ status }) {
  const map = {
    pending:  [C.warn, C.warnLo],
    approved: [C.pass, C.passLo],
    rejected: [C.fail, C.failLo],
    deferred: [C.muted, C.surface],
  };
  const [c, b] = map[status] ?? [C.muted, C.surface];
  return <Badge label={status} color={c} bg={b} />;
}

function CIBar({ lower, upper, threshold = 0.98 }) {
  const w = 180;
  const toX = v => ((v - 0.90) / 0.12) * w;
  const lx = Math.max(0, toX(lower));
  const ux = Math.min(w, toX(upper));
  const tx = toX(threshold);
  const passes = lower >= threshold;
  return (
    <div style={{ position: "relative", height: 22, width: w }}>
      <svg width={w} height={22}>
        <rect x={0} y={8} width={w} height={6} rx={3} fill={C.border} />
        <rect x={lx} y={8} width={Math.max(0, ux - lx)} height={6} rx={3}
          fill={passes ? C.pass : C.fail} opacity={0.7} />
        <line x1={tx} y1={2} x2={tx} y2={20} stroke={C.warn} strokeWidth={1.5} strokeDasharray="3,2" />
        <circle cx={lx} cy={11} r={4} fill={passes ? C.pass : C.fail} />
        <circle cx={ux} cy={11} r={4} fill={passes ? C.pass : C.fail} opacity={0.5} />
      </svg>
      <div style={{ fontSize: 10, color: C.textLo, marginTop: 2, display: "flex", justifyContent: "space-between" }}>
        <span>{fmt(lower)}</span><span>{fmt(upper)}</span>
      </div>
    </div>
  );
}

function LayerRow({ r, isWinner, isChosen, onChoose, canChoose }) {
  const qualifies = r.passes_threshold;
  return (
    <tr style={{
      background: isChosen ? C.accentLo : isWinner ? "#0f1e14" : "transparent",
      borderBottom: `1px solid ${C.border}`,
      transition: "background 0.15s",
    }}>
      <td style={{ padding: "10px 12px", fontFamily: "monospace", fontSize: 13, color: qualifies ? C.text : C.muted }}>
        {r.layer_name}
        {isWinner && !isChosen && <span style={{ marginLeft: 8, fontSize: 10, color: C.pass }}>▲ proposed</span>}
        {isChosen && <span style={{ marginLeft: 8, fontSize: 10, color: C.accent }}>● selected</span>}
      </td>
      <td style={{ padding: "10px 12px" }}>
        <CIBar lower={r.ci_lower} upper={r.ci_upper} />
      </td>
      <td style={{ padding: "10px 12px", textAlign: "right", fontSize: 13, color: qualifies ? C.pass : C.fail, fontVariantNumeric: "tabular-nums" }}>
        {pct(r.pass_rate)}
      </td>
      <td style={{ padding: "10px 12px", textAlign: "right", fontSize: 13, color: C.textLo, fontVariantNumeric: "tabular-nums" }}>
        {fmt(r.composite_score)}
      </td>
      <td style={{ padding: "10px 12px", textAlign: "right", fontSize: 12, color: C.textLo }}>
        {pct(r.cost_score)}
      </td>
      <td style={{ padding: "10px 12px", textAlign: "center" }}>
        {qualifies ? <Badge label="✓ Pass" color={C.pass} bg={C.passLo} /> : <Badge label="✗ Fail" color={C.fail} bg={C.failLo} />}
      </td>
      <td style={{ padding: "10px 12px", textAlign: "center" }}>
        {canChoose && qualifies && (
          <button onClick={() => onChoose(r.layer_name)} style={{
            background: isChosen ? C.accent : C.border,
            color: isChosen ? "#fff" : C.textLo,
            border: "none", borderRadius: 4, padding: "4px 12px",
            fontSize: 12, cursor: "pointer", transition: "all 0.15s",
          }}>
            {isChosen ? "Selected" : "Select"}
          </button>
        )}
      </td>
    </tr>
  );
}

function TaskCard({ task, onDecide }) {
  const [expanded, setExpanded]   = useState(false);
  const [chosen, setChosen]       = useState(task.proposed_winner);
  const [notes, setNotes]         = useState("");
  const [reviewer, setReviewer]   = useState("human:reviewer-1");
  const isPending = task.status === "pending";

  return (
    <div style={{
      background: C.surface, border: `1px solid ${C.border}`,
      borderRadius: 8, marginBottom: 16, overflow: "hidden",
    }}>
      {/* Header */}
      <div
        onClick={() => setExpanded(e => !e)}
        style={{
          display: "flex", alignItems: "center", gap: 12,
          padding: "14px 18px", cursor: "pointer",
          borderBottom: expanded ? `1px solid ${C.border}` : "none",
        }}
      >
        <ReasonBadge reason={task.reason} />
        <StatusBadge status={task.status} />
        <div style={{ flex: 1, marginLeft: 4 }}>
          <span style={{ fontFamily: "monospace", fontSize: 13, color: C.text }}>{task.probe}</span>
          <span style={{ color: C.muted, margin: "0 6px" }}>×</span>
          <span style={{ fontFamily: "monospace", fontSize: 13, color: C.textLo }}>{task.detector}</span>
        </div>
        <div style={{ fontSize: 12, color: C.muted }}>{elapsed(task.created_at)}</div>
        <div style={{ color: C.muted, fontSize: 12 }}>{expanded ? "▲" : "▼"}</div>
      </div>

      {expanded && (
        <div style={{ padding: "18px 18px" }}>
          {/* Layer table */}
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${C.borderHi}` }}>
                  {["Layer", "CI [0.98]", "Pass Rate", "Composite ↓", "Cost", "Status", ""].map(h => (
                    <th key={h} style={{ padding: "8px 12px", textAlign: h === "Layer" ? "left" : "right", color: C.muted, fontWeight: 600, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {task.all_results.map(r => (
                  <LayerRow
                    key={r.layer_name}
                    r={r}
                    isWinner={r.layer_name === task.proposed_winner}
                    isChosen={r.layer_name === chosen}
                    canChoose={isPending}
                    onChoose={setChosen}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* Reviewer controls */}
          {isPending && (
            <div style={{ marginTop: 20, padding: 16, background: C.bg, borderRadius: 6, border: `1px solid ${C.border}` }}>
              <div style={{ fontSize: 12, color: C.muted, marginBottom: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                Reviewer Decision
              </div>
              <div style={{ display: "flex", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 180 }}>
                  <label style={{ fontSize: 11, color: C.muted, display: "block", marginBottom: 4 }}>Reviewer ID</label>
                  <input
                    value={reviewer}
                    onChange={e => setReviewer(e.target.value)}
                    style={{
                      width: "100%", background: C.surface, border: `1px solid ${C.border}`,
                      borderRadius: 4, padding: "6px 10px", color: C.text, fontSize: 13, boxSizing: "border-box",
                    }}
                  />
                </div>
                <div style={{ flex: 2, minWidth: 240 }}>
                  <label style={{ fontSize: 11, color: C.muted, display: "block", marginBottom: 4 }}>Notes (optional)</label>
                  <input
                    value={notes}
                    onChange={e => setNotes(e.target.value)}
                    placeholder="Rationale for decision..."
                    style={{
                      width: "100%", background: C.surface, border: `1px solid ${C.border}`,
                      borderRadius: 4, padding: "6px 10px", color: C.text, fontSize: 13, boxSizing: "border-box",
                    }}
                  />
                </div>
              </div>
              <div style={{ fontSize: 12, color: C.textLo, marginBottom: 10 }}>
                Selected layer: <span style={{ color: C.accent, fontFamily: "monospace" }}>{chosen ?? "— none —"}</span>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {[
                  ["approve",  "Approve",  C.pass, C.passLo],
                  ["reject",   "Reject",   C.fail, C.failLo],
                  ["defer",    "Defer",    C.warn, C.warnLo],
                ].map(([verdict, label, col, bg]) => (
                  <button
                    key={verdict}
                    onClick={() => onDecide(task.task_id, verdict, chosen, reviewer, notes)}
                    style={{
                      background: bg, color: col, border: `1px solid ${col}44`,
                      borderRadius: 5, padding: "8px 18px", fontSize: 13, fontWeight: 600,
                      cursor: "pointer", transition: "all 0.15s",
                    }}
                  >{label}</button>
                ))}
              </div>
            </div>
          )}

          {/* Resolved info */}
          {!isPending && task.reviewer_id && (
            <div style={{ marginTop: 16, padding: "12px 16px", background: C.bg, borderRadius: 6, border: `1px solid ${C.border}` }}>
              <span style={{ fontSize: 12, color: C.muted }}>Reviewed by </span>
              <span style={{ fontSize: 12, fontFamily: "monospace", color: C.textLo }}>{task.reviewer_id}</span>
              {task.reviewer_notes && (
                <p style={{ margin: "6px 0 0", fontSize: 13, color: C.text }}>{task.reviewer_notes}</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Sidebar stats ──────────────────────────────────────────────────────────
function Stat({ label, value, color }) {
  return (
    <div style={{ padding: "14px 16px", borderBottom: `1px solid ${C.border}` }}>
      <div style={{ fontSize: 11, color: C.muted, textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color: color ?? C.text, fontVariantNumeric: "tabular-nums" }}>{value}</div>
    </div>
  );
}

// ── Main app ───────────────────────────────────────────────────────────────
export default function GovernanceReviewer() {
  const [tasks, setTasks] = useState([]);
  const [filter, setFilter] = useState("all");

  // Seed from storage or use mock
  useEffect(() => {
    (async () => {
      try {
        const stored = await window.storage.get("governance:tasks");
        if (stored) {
          setTasks(JSON.parse(stored.value));
        } else {
          setTasks(MOCK_TASKS);
          await window.storage.set("governance:tasks", JSON.stringify(MOCK_TASKS));
        }
      } catch {
        setTasks(MOCK_TASKS);
      }
    })();
  }, []);

  const persist = useCallback(async (updated) => {
    setTasks(updated);
    try { await window.storage.set("governance:tasks", JSON.stringify(updated)); } catch {}
  }, []);

  const onDecide = useCallback((task_id, verdict, chosen, reviewer_id, notes) => {
    persist(tasks.map(t =>
      t.task_id !== task_id ? t : {
        ...t,
        status: verdict === "approve" ? "approved" : verdict === "reject" ? "rejected" : "deferred",
        proposed_winner: chosen,
        reviewer_id,
        reviewer_notes: notes,
      }
    ));
  }, [tasks, persist]);

  const pending   = tasks.filter(t => t.status === "pending");
  const resolved  = tasks.filter(t => t.status !== "pending");
  const closeCalls= tasks.filter(t => t.reason === "close_call");
  const noPass    = tasks.filter(t => t.reason === "no_passing_layer");

  const visible = filter === "all" ? tasks
    : filter === "pending" ? pending
    : filter === "resolved" ? resolved
    : tasks.filter(t => t.reason === filter);

  return (
    <div style={{
      background: C.bg, minHeight: "100vh", color: C.text,
      fontFamily: "'IBM Plex Mono', 'Fira Code', monospace",
      display: "flex",
    }}>
      {/* Sidebar */}
      <div style={{
        width: 220, flexShrink: 0, borderRight: `1px solid ${C.border}`,
        background: C.surface,
      }}>
        <div style={{ padding: "20px 16px", borderBottom: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 11, color: C.accent, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase" }}>
            Governance
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, color: C.text, marginTop: 2 }}>
            Review Council
          </div>
        </div>

        <Stat label="Pending"    value={pending.length}   color={pending.length > 0 ? C.warn : C.pass} />
        <Stat label="Close Calls" value={closeCalls.length} color={C.warn} />
        <Stat label="No-Pass"    value={noPass.length}    color={C.fail} />
        <Stat label="Resolved"   value={resolved.length}  color={C.pass} />

        <div style={{ padding: "16px 8px" }}>
          {[
            ["all",           "All Tasks"],
            ["pending",       "Pending"],
            ["close_call",    "Close Calls"],
            ["no_passing_layer","No Pass"],
            ["resolved",      "Resolved"],
          ].map(([key, label]) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              style={{
                display: "block", width: "100%", textAlign: "left",
                background: filter === key ? C.accentLo : "transparent",
                color: filter === key ? C.accent : C.textLo,
                border: "none", borderRadius: 4,
                padding: "8px 10px", fontSize: 12, cursor: "pointer",
                marginBottom: 2, transition: "all 0.1s",
              }}
            >{label}</button>
          ))}
        </div>
      </div>

      {/* Main */}
      <div style={{ flex: 1, padding: "24px 28px", overflowY: "auto" }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 24, gap: 12 }}>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: C.text }}>
            Evidence Layer Review Queue
          </h1>
          <Badge label={`CI ≥ 0.98`} color={C.accent} bg={C.accentLo} />
          <div style={{ marginLeft: "auto", fontSize: 12, color: C.muted }}>
            {visible.length} task{visible.length !== 1 ? "s" : ""}
          </div>
        </div>

        {visible.length === 0 && (
          <div style={{ textAlign: "center", padding: "60px 0", color: C.muted, fontSize: 14 }}>
            No tasks in this view.
          </div>
        )}

        {visible.map(task => (
          <TaskCard key={task.task_id} task={task} onDecide={onDecide} />
        ))}
      </div>
    </div>
  );
}
