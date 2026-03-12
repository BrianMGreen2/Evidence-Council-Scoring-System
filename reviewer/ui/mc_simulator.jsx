import { useState, useEffect, useCallback, useRef } from "react";

// ── Design tokens ─────────────────────────────────────────────────────────
const T = {
  bg:       "#07090f",
  surface:  "#0e1118",
  card:     "#131720",
  border:   "#1c2235",
  borderHi: "#2a3350",
  accent:   "#60a5fa",
  accentLo: "#0f2040",
  teal:     "#2dd4bf",
  tealLo:   "#0a2420",
  amber:    "#fbbf24",
  amberLo:  "#2a1f00",
  red:      "#f87171",
  redLo:    "#2a0f0f",
  green:    "#4ade80",
  greenLo:  "#0a2010",
  muted:    "#4b5675",
  text:     "#dde3f0",
  textLo:   "#7b8ab0",
  mono:     "'JetBrains Mono', 'Fira Code', monospace",
  sans:     "'DM Sans', system-ui, sans-serif",
};

const THRESHOLD = 0.98;
const BOUNDARY_MARGIN = 0.02;
const SIGMA_MULT = 3.0;

// ── Bootstrap simulation (pure JS) ────────────────────────────────────────
function seededRandom(seed) {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) & 0xffffffff;
    return (s >>> 0) / 0xffffffff;
  };
}

function binomialSample(n, p, rand) {
  let k = 0;
  for (let i = 0; i < n; i++) if (rand() < p) k++;
  return k;
}

function bootstrapCI(passes, fails, nBoot, ciLevel, seed) {
  const total = passes + fails;
  if (total === 0) return { lower: 0, upper: 0, observedRate: 0 };
  const observedRate = passes / total;
  const rand = seededRandom(seed ?? Math.floor(Math.random() * 1e9));
  const samples = Array.from({ length: nBoot }, () =>
    binomialSample(total, observedRate, rand) / total
  ).sort((a, b) => a - b);
  const alpha = 1 - ciLevel;
  const lower = samples[Math.floor(nBoot * (alpha / 2))];
  const upper = samples[Math.floor(nBoot * (1 - alpha / 2))];
  return { lower, upper, observedRate, total, nBoot };
}

function estimateMCError(passes, fails, nBoot, nRepeats, baseSeed) {
  const lowers = [];
  for (let i = 0; i < nRepeats; i++) {
    const { lower } = bootstrapCI(passes, fails, nBoot, THRESHOLD, (baseSeed ?? 42) + i * 997);
    lowers.push(lower);
  }
  const mean = lowers.reduce((a, b) => a + b, 0) / lowers.length;
  const variance = lowers.reduce((a, b) => a + (b - mean) ** 2, 0) / lowers.length;
  return { mcErrorLower: Math.sqrt(variance), lowers, mean };
}

function classifyBoundary(ciLower, ciUpper, mcErrorLower) {
  if (ciLower >= THRESHOLD + BOUNDARY_MARGIN) return "CLEAR_PASS";
  if (ciUpper < THRESHOLD - BOUNDARY_MARGIN)  return "CLEAR_FAIL";
  const sigmaDist = mcErrorLower > 0
    ? Math.abs(ciLower - THRESHOLD) / mcErrorLower
    : Infinity;
  if (sigmaDist < SIGMA_MULT) return "HARD_BOUNDARY";
  return ciLower >= THRESHOLD ? "SOFT_BOUNDARY_PASS" : "SOFT_BOUNDARY_FAIL";
}

const STATUS_META = {
  CLEAR_PASS:         { label: "Clear Pass",         color: T.green,  bg: T.greenLo,  escalate: false },
  CLEAR_FAIL:         { label: "Clear Fail",          color: T.red,    bg: T.redLo,    escalate: false },
  SOFT_BOUNDARY_PASS: { label: "Soft Boundary Pass",  color: T.teal,   bg: T.tealLo,   escalate: false },
  SOFT_BOUNDARY_FAIL: { label: "Soft Boundary Fail",  color: T.amber,  bg: T.amberLo,  escalate: true  },
  HARD_BOUNDARY:      { label: "Hard Boundary",        color: T.red,    bg: T.redLo,    escalate: true  },
};

const ACTIONS = {
  CLEAR_PASS:         ["NONE"],
  CLEAR_FAIL:         ["NONE"],
  SOFT_BOUNDARY_PASS: ["INCREASE_N_BOOTSTRAP", "ATTACH_MC_ERROR", "COMMIT_AS_UNSTABLE"],
  SOFT_BOUNDARY_FAIL: ["INCREASE_N_BOOTSTRAP", "ATTACH_MC_ERROR", "ESCALATE_TO_COUNCIL", "COMMIT_AS_UNSTABLE"],
  HARD_BOUNDARY:      ["INCREASE_N_BOOTSTRAP", "ATTACH_MC_ERROR", "REQUIRE_MORE_TRIALS", "ESCALATE_TO_COUNCIL", "COMMIT_AS_UNSTABLE"],
};

const ACTION_DESC = {
  NONE:                 "No action required. Proceed with composite ranking.",
  INCREASE_N_BOOTSTRAP: "Re-run with 50,000 resamples to reduce MC noise.",
  ATTACH_MC_ERROR:      "Commit mc_error_lower / mc_error_upper to KnowledgeRecord.",
  ESCALATE_TO_COUNCIL:  "Emit ReviewTask(reason='boundary_instability') to review queue.",
  REQUIRE_MORE_TRIALS:  "Flag layer as needing more evaluation trials.",
  COMMIT_AS_UNSTABLE:   "Commit with is_boundary=True — consistency score accumulates.",
};

// ── Sub-components ────────────────────────────────────────────────────────

function Badge({ label, color, bg, small }) {
  return (
    <span style={{
      background: bg, color, border: `1px solid ${color}44`,
      borderRadius: 4, padding: small ? "1px 7px" : "3px 10px",
      fontSize: small ? 10 : 11, fontWeight: 700,
      letterSpacing: "0.07em", textTransform: "uppercase",
      fontFamily: T.mono,
    }}>{label}</span>
  );
}

function Slider({ label, value, min, max, step, onChange, format, color }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <span style={{ fontSize: 11, color: T.textLo, textTransform: "uppercase", letterSpacing: "0.07em" }}>{label}</span>
        <span style={{ fontSize: 13, color: color ?? T.accent, fontFamily: T.mono, fontWeight: 700 }}>
          {format ? format(value) : value}
        </span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(Number(e.target.value))}
        style={{ width: "100%", accentColor: color ?? T.accent, cursor: "pointer" }}
      />
    </div>
  );
}

function CIBar({ lower, upper, threshold = THRESHOLD, margin = BOUNDARY_MARGIN, width = 300 }) {
  const domain = [0.88, 1.0];
  const toX = v => ((v - domain[0]) / (domain[1] - domain[0])) * width;
  const lx = Math.max(0, toX(lower));
  const ux = Math.min(width, toX(upper));
  const tx = toX(threshold);
  const hi = toX(threshold + margin);
  const lo = toX(threshold - margin);
  const passes = lower >= threshold;
  const inMargin = lower >= threshold - margin && upper >= threshold - margin;
  const barColor = lower >= threshold + margin ? T.green
    : lower >= threshold ? T.teal
    : lower >= threshold - margin ? T.amber
    : T.red;

  return (
    <svg width={width} height={44} style={{ overflow: "visible" }}>
      {/* Domain axis */}
      <rect x={0} y={16} width={width} height={5} rx={2.5} fill={T.border} />
      {/* Boundary zone shading */}
      <rect x={lo} y={10} width={hi - lo} height={17} fill={T.amber} opacity={0.10} rx={2} />
      {/* CI interval */}
      <rect x={lx} y={16} width={Math.max(2, ux - lx)} height={5} rx={2.5}
        fill={barColor} opacity={0.75} />
      {/* Threshold line */}
      <line x1={tx} y1={6} x2={tx} y2={36} stroke={T.amber} strokeWidth={1.5} strokeDasharray="3,2" />
      {/* Lower bound dot */}
      <circle cx={lx} cy={18.5} r={5} fill={barColor} stroke={T.bg} strokeWidth={1.5} />
      {/* Upper bound dot */}
      <circle cx={ux} cy={18.5} r={4} fill={barColor} opacity={0.5} stroke={T.bg} strokeWidth={1} />
      {/* Labels */}
      <text x={lx} y={42} textAnchor="middle" fill={barColor}
        fontSize={9} fontFamily={T.mono}>{lower.toFixed(4)}</text>
      <text x={tx} y={7} textAnchor="middle" fill={T.amber}
        fontSize={9} fontFamily={T.mono}>0.98</text>
      <text x={ux} y={42} textAnchor="middle" fill={barColor} opacity={0.6}
        fontSize={9} fontFamily={T.mono}>{upper.toFixed(4)}</text>
    </svg>
  );
}

function MCDistribution({ lowers, threshold, width = 300, height = 80 }) {
  if (!lowers || lowers.length === 0) return null;
  const min = Math.min(...lowers) - 0.002;
  const max = Math.max(...lowers) + 0.002;
  const range = max - min || 0.01;
  const bins = 20;
  const counts = Array(bins).fill(0);
  lowers.forEach(v => {
    const idx = Math.min(bins - 1, Math.floor(((v - min) / range) * bins));
    counts[idx]++;
  });
  const maxCount = Math.max(...counts);
  const barW = width / bins;
  const toX = v => ((v - min) / range) * width;
  const tx = toX(threshold);

  return (
    <svg width={width} height={height} style={{ overflow: "visible" }}>
      {counts.map((c, i) => {
        const x = i * barW;
        const bh = maxCount > 0 ? (c / maxCount) * (height - 16) : 0;
        const binCenter = min + (i + 0.5) * range / bins;
        const color = binCenter >= threshold ? T.green : T.red;
        return (
          <rect key={i} x={x + 1} y={height - 14 - bh} width={barW - 2} height={bh}
            fill={color} opacity={0.65} rx={1} />
        );
      })}
      <line x1={tx} y1={0} x2={tx} y2={height - 14} stroke={T.amber}
        strokeWidth={1.5} strokeDasharray="3,2" />
      <text x={tx} y={height} textAnchor="middle" fill={T.amber}
        fontSize={9} fontFamily={T.mono}>0.98</text>
    </svg>
  );
}

// ── Main simulator ────────────────────────────────────────────────────────
export default function MCSimulator() {
  const [passes, setPasses]       = useState(490);
  const [fails,  setFails]        = useState(10);
  const [nBoot,  setNBoot]        = useState(1000);
  const [nRep,   setNRep]         = useState(20);
  const [runs,   setRuns]         = useState([]);
  const [running, setRunning]     = useState(false);
  const [autoRun, setAutoRun]     = useState(false);
  const autoRef = useRef(null);

  const total = passes + fails;
  const observedRate = total > 0 ? passes / total : 0;

  const runSimulation = useCallback(() => {
    const baseSeed = Math.floor(Math.random() * 1e8);
    const ci = bootstrapCI(passes, fails, nBoot, THRESHOLD, baseSeed);
    const { mcErrorLower, lowers } = estimateMCError(passes, fails, nBoot, nRep, baseSeed);
    const status = classifyBoundary(ci.lower, ci.upper, mcErrorLower);
    const sigmaDist = mcErrorLower > 0
      ? Math.abs(ci.lower - THRESHOLD) / mcErrorLower
      : Infinity;
    const run = {
      id: Date.now() + Math.random(),
      ci, mcErrorLower, lowers, status, sigmaDist,
      actions: ACTIONS[status],
      meta: STATUS_META[status],
      timestamp: new Date().toLocaleTimeString(),
      nBoot, passes, fails,
    };
    setRuns(prev => [run, ...prev].slice(0, 50));
    return run;
  }, [passes, fails, nBoot, nRep]);

  useEffect(() => {
    if (autoRun) {
      autoRef.current = setInterval(runSimulation, 800);
    } else {
      clearInterval(autoRef.current);
    }
    return () => clearInterval(autoRef.current);
  }, [autoRun, runSimulation]);

  const latest = runs[0];
  const escalations = runs.filter(r => r.meta.escalate).length;
  const hardBoundary = runs.filter(r => r.status === "HARD_BOUNDARY").length;
  const passRate = runs.length > 0
    ? (runs.filter(r => r.ci.lower >= THRESHOLD).length / runs.length * 100).toFixed(0)
    : "—";

  return (
    <div style={{
      background: T.bg, minHeight: "100vh", color: T.text,
      fontFamily: T.sans, display: "flex", flexDirection: "column",
    }}>
      {/* Header */}
      <div style={{
        borderBottom: `1px solid ${T.border}`,
        padding: "16px 28px", display: "flex", alignItems: "center", gap: 16,
      }}>
        <div>
          <div style={{ fontSize: 11, color: T.accent, fontFamily: T.mono,
            textTransform: "uppercase", letterSpacing: "0.12em" }}>
            Evidence Council
          </div>
          <div style={{ fontSize: 18, fontWeight: 700, color: T.text, marginTop: 1 }}>
            Monte Carlo Error Simulator
          </div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 10 }}>
          <button onClick={runSimulation} style={{
            background: T.accentLo, color: T.accent, border: `1px solid ${T.accent}44`,
            borderRadius: 6, padding: "8px 18px", fontSize: 13, fontWeight: 600,
            cursor: "pointer", fontFamily: T.sans,
          }}>Run Once</button>
          <button onClick={() => setAutoRun(a => !a)} style={{
            background: autoRun ? T.amberLo : T.card, color: autoRun ? T.amber : T.textLo,
            border: `1px solid ${autoRun ? T.amber : T.border}44`,
            borderRadius: 6, padding: "8px 18px", fontSize: 13, fontWeight: 600,
            cursor: "pointer", fontFamily: T.sans,
          }}>{autoRun ? "⏹ Stop" : "▶ Auto"}</button>
          <button onClick={() => setRuns([])} style={{
            background: T.card, color: T.textLo, border: `1px solid ${T.border}`,
            borderRadius: 6, padding: "8px 14px", fontSize: 13,
            cursor: "pointer", fontFamily: T.sans,
          }}>Clear</button>
        </div>
      </div>

      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>

        {/* Left: controls */}
        <div style={{
          width: 280, flexShrink: 0, borderRight: `1px solid ${T.border}`,
          padding: "20px 20px", overflowY: "auto",
        }}>
          <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase",
            letterSpacing: "0.08em", marginBottom: 16 }}>Layer Parameters</div>

          <Slider label="Passes" value={passes} min={400} max={500} step={1}
            onChange={v => { setPasses(v); setRuns([]); }}
            format={v => `${v}`} color={T.green} />
          <Slider label="Fails" value={fails} min={0} max={100} step={1}
            onChange={v => { setFails(v); setRuns([]); }}
            format={v => `${v}`} color={T.red} />

          <div style={{ padding: "10px 12px", background: T.card, borderRadius: 6,
            border: `1px solid ${T.border}`, marginBottom: 20, fontFamily: T.mono }}>
            <div style={{ fontSize: 11, color: T.muted, marginBottom: 4 }}>
              Observed Rate
            </div>
            <div style={{ fontSize: 20, fontWeight: 700, color: observedRate >= THRESHOLD ? T.green : T.red }}>
              {(observedRate * 100).toFixed(2)}%
            </div>
            <div style={{ fontSize: 11, color: T.muted, marginTop: 2 }}>
              {total} total trials
            </div>
          </div>

          <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase",
            letterSpacing: "0.08em", marginBottom: 16 }}>Bootstrap Parameters</div>

          <Slider label="n_bootstrap" value={nBoot} min={100} max={10000} step={100}
            onChange={v => { setNBoot(v); setRuns([]); }}
            format={v => v.toLocaleString()} />
          <Slider label="MC Repeats" value={nRep} min={5} max={50} step={5}
            onChange={v => { setNRep(v); setRuns([]); }}
            format={v => `${v}×`} color={T.teal} />

          {/* Summary stats */}
          {runs.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase",
                letterSpacing: "0.08em", marginBottom: 12 }}>Run Summary</div>
              {[
                ["Total Runs",       runs.length,    T.text],
                ["Pass Rate",        `${passRate}%`, observedRate >= THRESHOLD ? T.green : T.red],
                ["Escalations",      escalations,    escalations > 0 ? T.amber : T.green],
                ["Hard Boundaries",  hardBoundary,   hardBoundary > 0 ? T.red : T.green],
              ].map(([label, val, color]) => (
                <div key={label} style={{
                  display: "flex", justifyContent: "space-between",
                  padding: "7px 0", borderBottom: `1px solid ${T.border}`,
                }}>
                  <span style={{ fontSize: 12, color: T.textLo }}>{label}</span>
                  <span style={{ fontSize: 13, fontWeight: 700, color, fontFamily: T.mono }}>{val}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Centre: latest result */}
        <div style={{ flex: 1, padding: "20px 24px", overflowY: "auto" }}>
          {!latest ? (
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "center",
              height: "100%", color: T.muted, fontSize: 14, flexDirection: "column", gap: 12,
            }}>
              <div style={{ fontSize: 40 }}>⚡</div>
              <div>Click <strong style={{ color: T.accent }}>Run Once</strong> or enable <strong style={{ color: T.amber }}>Auto</strong> to simulate</div>
            </div>
          ) : (
            <>
              {/* Status banner */}
              <div style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "14px 18px", background: latest.meta.bg,
                border: `1px solid ${latest.meta.color}44`, borderRadius: 8, marginBottom: 20,
              }}>
                <Badge label={latest.meta.label} color={latest.meta.color} bg={latest.meta.bg} />
                {latest.meta.escalate && (
                  <Badge label="→ Council Escalation" color={T.amber} bg={T.amberLo} />
                )}
                <span style={{ marginLeft: "auto", fontSize: 11, color: T.muted, fontFamily: T.mono }}>
                  {latest.timestamp}
                </span>
              </div>

              {/* CI bar */}
              <div style={{ background: T.card, border: `1px solid ${T.border}`,
                borderRadius: 8, padding: "18px 20px", marginBottom: 16 }}>
                <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase",
                  letterSpacing: "0.07em", marginBottom: 14 }}>
                  Bootstrap CI @ 0.98
                </div>
                <CIBar lower={latest.ci.lower} upper={latest.ci.upper} width={400} />
                <div style={{ display: "flex", gap: 24, marginTop: 16, fontFamily: T.mono }}>
                  {[
                    ["ci_lower",    latest.ci.lower.toFixed(5),  latest.meta.color],
                    ["ci_upper",    latest.ci.upper.toFixed(5),  T.textLo],
                    ["mc_error",    latest.mcErrorLower.toFixed(5), T.teal],
                    ["σ distance",  isFinite(latest.sigmaDist) ? latest.sigmaDist.toFixed(2) : "∞", T.amber],
                  ].map(([k, v, c]) => (
                    <div key={k}>
                      <div style={{ fontSize: 10, color: T.muted, marginBottom: 3 }}>{k}</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: c }}>{v}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* MC error distribution */}
              <div style={{ background: T.card, border: `1px solid ${T.border}`,
                borderRadius: 8, padding: "18px 20px", marginBottom: 16 }}>
                <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase",
                  letterSpacing: "0.07em", marginBottom: 14 }}>
                  ci_lower Distribution Across {nRep} Bootstrap Repeats
                </div>
                <MCDistribution lowers={latest.lowers} threshold={THRESHOLD} width={420} height={90} />
                <div style={{ fontSize: 11, color: T.textLo, marginTop: 10 }}>
                  <span style={{ color: T.green }}>■</span> ≥ 0.98 threshold &nbsp;
                  <span style={{ color: T.red }}>■</span> &lt; 0.98 threshold &nbsp;
                  <span style={{ color: T.amber }}>┆</span> threshold
                </div>
              </div>

              {/* Corrective actions */}
              <div style={{ background: T.card, border: `1px solid ${T.border}`,
                borderRadius: 8, padding: "18px 20px" }}>
                <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase",
                  letterSpacing: "0.07em", marginBottom: 14 }}>
                  Corrective Action Array
                </div>
                {latest.actions.map((action, i) => (
                  <div key={action} style={{
                    display: "flex", gap: 12, alignItems: "flex-start",
                    padding: "10px 0",
                    borderBottom: i < latest.actions.length - 1 ? `1px solid ${T.border}` : "none",
                  }}>
                    <div style={{
                      width: 22, height: 22, borderRadius: "50%",
                      background: action === "NONE" ? T.border : T.accentLo,
                      color: action === "NONE" ? T.muted : T.accent,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 11, fontWeight: 700, flexShrink: 0, fontFamily: T.mono,
                    }}>{i + 1}</div>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: T.text,
                        fontFamily: T.mono, marginBottom: 3 }}>{action}</div>
                      <div style={{ fontSize: 12, color: T.textLo, lineHeight: 1.5 }}>
                        {ACTION_DESC[action]}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Right: run history */}
        <div style={{
          width: 240, flexShrink: 0, borderLeft: `1px solid ${T.border}`,
          overflowY: "auto",
        }}>
          <div style={{ padding: "14px 16px", borderBottom: `1px solid ${T.border}` }}>
            <div style={{ fontSize: 11, color: T.muted, textTransform: "uppercase",
              letterSpacing: "0.07em" }}>Run History</div>
          </div>
          {runs.length === 0 && (
            <div style={{ padding: "20px 16px", fontSize: 12, color: T.muted }}>
              No runs yet
            </div>
          )}
          {runs.map((run, i) => (
            <div key={run.id} style={{
              padding: "10px 16px",
              borderBottom: `1px solid ${T.border}`,
              background: i === 0 ? run.meta.bg + "66" : "transparent",
              cursor: "default",
            }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                <Badge label={run.meta.label.split(" ").slice(-1)[0]} color={run.meta.color} bg={run.meta.bg} small />
                {run.meta.escalate && <span style={{ fontSize: 9, color: T.amber }}>↑ ESC</span>}
              </div>
              <div style={{ fontFamily: T.mono, fontSize: 11, color: run.meta.color }}>
                {run.ci.lower.toFixed(5)}
              </div>
              <div style={{ fontSize: 10, color: T.muted, marginTop: 2 }}>
                σ={isFinite(run.sigmaDist) ? run.sigmaDist.toFixed(1) : "∞"} · n={run.nBoot.toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
