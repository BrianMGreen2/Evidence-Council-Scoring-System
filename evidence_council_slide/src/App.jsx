import { useState, useEffect } from "react";

const DATA = {
  thresholds: [
    {
      ci: "0.90",
      label: "90% CI",
      missRate: "1 in 10",
      missRateNum: 10,
      color: "#ef4444",
      tagColor: "#7f1d1d",
      tag: "RESEARCH / EXPLORATORY",
      policy: "Permits 1 failure per 10 cases evaluated.",
    },
    {
      ci: "0.95",
      label: "95% CI",
      missRate: "1 in 27",
      missRateNum: 27,
      color: "#f97316",
      tagColor: "#7c2d12",
      tag: "GENERAL PRODUCTION",
      policy: "Permits 1 failure per 27 cases evaluated.",
    },
    {
      ci: "0.98",
      label: "98% CI",
      missRate: "1 in 125",
      missRateNum: 125,
      color: "#22d3ee",
      tagColor: "#164e63",
      tag: "CLINICAL / REGULATED",
      policy: "Permits 1 failure per 125 cases evaluated.",
    },
    {
      ci: "0.99",
      label: "99% CI",
      missRate: "1 in 500",
      missRateNum: 500,
      color: "#4ade80",
      tagColor: "#14532d",
      tag: "SAFETY-CRITICAL",
      policy: "Permits 1 failure per 500 cases evaluated.",
    },
  ],
  trials: [
    {
      n: 100,
      label: "n = 100",
      step: "±1%",
      stepNote: "Each trial = 1.0pp resolution",
      reliable: false,
      warning: "Boundary zone spans ~15 trials. Result unstable.",
    },
    {
      n: 500,
      label: "n = 500",
      step: "±0.2%",
      stepNote: "Each trial = 0.2pp resolution",
      reliable: false,
      warning: "6-trial gap separates never-certifies from always-certifies.",
      highlight: true,
    },
    {
      n: 1000,
      label: "n = 1,000",
      step: "±0.1%",
      stepNote: "Each trial = 0.1pp resolution",
      reliable: false,
      warning: "9-trial gap. Boundary still discrete.",
    },
    {
      n: 5000,
      label: "n = 5,000",
      step: "±0.02%",
      stepNote: "Each trial = 0.02pp resolution",
      reliable: true,
      warning: "MC error zone: 0.9842 obs rate passes in ~78% of seeds.",
      highlight: true,
    },
    {
      n: 10000,
      label: "n = 10,000",
      step: "±0.01%",
      stepNote: "Each trial = 0.01pp resolution",
      reliable: true,
      warning: "Boundary well-characterized. MC error quantifiable.",
    },
  ],
};

const MONO = "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace";
const DISPLAY = "'DM Serif Display', 'Playfair Display', Georgia, serif";
const BODY = "'DM Sans', 'Outfit', system-ui, sans-serif";

export default function Slide() {
  const [activeThreshold, setActiveThreshold] = useState(2); // 0.98 default
  const [activeTrial, setActiveTrial] = useState(1);         // n=500 default
  const [revealed, setRevealed] = useState(false);
  const [showDoc, setShowDoc] = useState(false); 

  useEffect(() => {
    const t = setTimeout(() => setRevealed(true), 100);
    return () => clearTimeout(t);
  }, []);

  const thr = DATA.thresholds[activeThreshold];
  const tri = DATA.trials[activeTrial];

  // Visual bar: how wide is "acceptable failure zone" relative to perfect
  const barFill = (1 - 1 / thr.missRateNum) * 100;

  return (
    <div style={{
      background: "#080c12",
      minHeight: "100vh",
      display: "flex",
      flexDirection: "column",
      fontFamily: BODY,
      color: "#c8d4e8",
      padding: "0",
      overflow: "hidden",
      position: "relative",
    }}>

      {/* Grid texture overlay */}
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        backgroundImage: `
          linear-gradient(rgba(34,211,238,0.03) 1px, transparent 1px),
          linear-gradient(90deg, rgba(34,211,238,0.03) 1px, transparent 1px)
        `,
        backgroundSize: "40px 40px",
        zIndex: 0,
      }} />

      {/* Slide frame */}
      <div style={{
        position: "relative", zIndex: 1,
        maxWidth: 1100, margin: "0 auto",
        width: "100%", padding: "36px 48px 32px",
        display: "flex", flexDirection: "column", gap: 0,
        opacity: revealed ? 1 : 0,
        transition: "opacity 0.5s ease",
      }}>

        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <div style={{
            fontFamily: MONO, fontSize: 10, letterSpacing: "0.18em",
            color: "#22d3ee", textTransform: "uppercase", marginBottom: 8,
            opacity: 0.8,
          }}>
            Evidence Council · Governance Primer
          </div>
          <h1 style={{
            fontFamily: DISPLAY, fontSize: 28, fontWeight: 400,
            color: "#f0f4ff", margin: 0, lineHeight: 1.2,
            letterSpacing: "-0.01em",
          }}>
            The Threshold Encodes Your Risk Tolerance.
            <br />
            <span style={{ color: "#22d3ee" }}>The Trial Count Is Your Measurement Precision.</span>
          </h1>
          <div style={{
            marginTop: 10, fontFamily: BODY, fontSize: 13,
            color: "#5a6a88", lineHeight: 1.6, maxWidth: 640,
          }}>
            These are two independent decisions. Conflating them is the most common
            governance mistake in AI evaluation pipelines.
          </div>
        </div>

        {/* Two-column body */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>

          {/* LEFT: Threshold = Risk Policy */}
          <div style={{
            background: "#0c1220",
            border: "1px solid #1a2540",
            borderRadius: 8,
            padding: "20px 22px",
            display: "flex", flexDirection: "column", gap: 14,
          }}>
            <div style={{
              display: "flex", alignItems: "baseline", gap: 10,
              borderBottom: "1px solid #1a2540", paddingBottom: 12,
            }}>
              <span style={{
                fontFamily: MONO, fontSize: 10, letterSpacing: "0.14em",
                textTransform: "uppercase", color: "#5a6a88",
              }}>01 /</span>
              <span style={{
                fontFamily: DISPLAY, fontSize: 17, color: "#f0f4ff",
                fontWeight: 400,
              }}>Threshold = Risk Policy</span>
            </div>

            <div style={{
              fontFamily: BODY, fontSize: 12, color: "#7a8aa8", lineHeight: 1.6,
            }}>
              The CI threshold is not a statistical preference.
              It is an explicit statement of how many failures per
              N cases your system is permitted to allow.{" "}
              <strong style={{ color: "#c8d4e8" }}>
                Choosing a threshold is a governance decision.
              </strong>
            </div>

            {/* Threshold selector */}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {DATA.thresholds.map((t, i) => (
                <button
                  key={t.ci}
                  onClick={() => setActiveThreshold(i)}
                  style={{
                    display: "flex", alignItems: "center", gap: 10,
                    padding: "9px 12px",
                    background: activeThreshold === i ? t.tagColor + "55" : "transparent",
                    border: `1px solid ${activeThreshold === i ? t.color + "66" : "#1a2540"}`,
                    borderRadius: 5, cursor: "pointer",
                    transition: "all 0.15s ease",
                    textAlign: "left",
                  }}
                >
                  <span style={{
                    fontFamily: MONO, fontSize: 14, fontWeight: 700,
                    color: activeThreshold === i ? t.color : "#3a4a60",
                    minWidth: 44,
                    transition: "color 0.15s ease",
                  }}>{t.ci}</span>
                  <span style={{
                    fontFamily: MONO, fontSize: 10,
                    color: activeThreshold === i ? t.color + "aa" : "#2a3a50",
                    flex: 1, letterSpacing: "0.08em",
                    transition: "color 0.15s ease",
                  }}>{t.tag}</span>
                  <span style={{
                    fontFamily: MONO, fontSize: 11,
                    color: activeThreshold === i ? t.color : "#2a3a50",
                    transition: "color 0.15s ease",
                  }}>{t.missRate}</span>
                </button>
              ))}
            </div>

            {/* Active threshold callout */}
            <div style={{
              background: thr.tagColor + "44",
              border: `1px solid ${thr.color}44`,
              borderRadius: 6, padding: "12px 14px",
              transition: "all 0.2s ease",
            }}>
              <div style={{
                fontFamily: MONO, fontSize: 10, color: thr.color,
                textTransform: "uppercase", letterSpacing: "0.12em",
                marginBottom: 6,
              }}>
                Policy statement — {thr.label}
              </div>
              <div style={{
                fontFamily: BODY, fontSize: 13, color: "#c8d4e8",
                lineHeight: 1.55,
              }}>
                {thr.policy}
              </div>

              {/* Miss rate bar */}
              <div style={{ marginTop: 10 }}>
                <div style={{
                  display: "flex", justifyContent: "space-between",
                  fontFamily: MONO, fontSize: 9, color: "#3a4a60",
                  marginBottom: 4, letterSpacing: "0.06em",
                }}>
                  <span>FAILURE PERMITTED</span>
                  <span>REQUIRED PASS</span>
                </div>
                <div style={{
                  height: 6, background: "#0a1020",
                  borderRadius: 3, overflow: "hidden",
                  border: "1px solid #1a2540",
                }}>
                  <div style={{
                    height: "100%", width: `${barFill}%`,
                    background: `linear-gradient(90deg, ${thr.color}22, ${thr.color})`,
                    borderRadius: 3,
                    transition: "width 0.4s ease, background 0.3s ease",
                  }} />
                </div>
                <div style={{
                  display: "flex", justifyContent: "space-between",
                  fontFamily: MONO, fontSize: 9, color: "#3a4a60",
                  marginTop: 4,
                }}>
                  <span>0%</span>
                  <span style={{ color: thr.color }}>{(barFill).toFixed(1)}% required pass rate</span>
                  <span>100%</span>
                </div>
              </div>

              {activeThreshold === 1 && (
                <div style={{
                  marginTop: 10, padding: "7px 10px",
                  background: "#1a0a00", border: "1px solid #7c2d1266",
                  borderRadius: 4, fontFamily: BODY, fontSize: 11,
                  color: "#f97316aa", lineHeight: 1.5,
                }}>
                  ⚠ At n=500 trials, this threshold permits a detector that misses
                  1 in 27 cases. In a hospital routing 1,000 flagged records/day,
                  that is ~37 missed detections daily.
                </div>
              )}
              {activeThreshold === 2 && (
                <div style={{
                  marginTop: 10, padding: "7px 10px",
                  background: "#001a20", border: "1px solid #164e6366",
                  borderRadius: 4, fontFamily: BODY, fontSize: 11,
                  color: "#22d3eeaa", lineHeight: 1.5,
                }}>
                  At n=500, a detector needs 496/500 clean trials to certify at this
                  threshold. 495/500 (0.990 observed) never passes. That 1-trial gap
                  is the margin.
                </div>
              )}
            </div>
          </div>

          {/* RIGHT: Trial Count = Measurement Precision */}
          <div style={{
            background: "#0c1220",
            border: "1px solid #1a2540",
            borderRadius: 8,
            padding: "20px 22px",
            display: "flex", flexDirection: "column", gap: 14,
          }}>
            <div style={{
              display: "flex", alignItems: "baseline", gap: 10,
              borderBottom: "1px solid #1a2540", paddingBottom: 12,
            }}>
              <span style={{
                fontFamily: MONO, fontSize: 10, letterSpacing: "0.14em",
                textTransform: "uppercase", color: "#5a6a88",
              }}>02 /</span>
              <span style={{
                fontFamily: DISPLAY, fontSize: 17, color: "#f0f4ff",
                fontWeight: 400,
              }}>Trial Count = Measurement Precision</span>
            </div>

            <div style={{
              fontFamily: BODY, fontSize: 12, color: "#7a8aa8", lineHeight: 1.6,
            }}>
              More trials do not make a weak detector stronger.
              They sharpen the ruler you are using to measure it.
              A detector that barely clears threshold at n=10,000
              is{" "}
              <strong style={{ color: "#c8d4e8" }}>
                still barely clearing threshold.
              </strong>
            </div>

            {/* Trial selector */}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {DATA.trials.map((t, i) => (
                <button
                  key={t.n}
                  onClick={() => setActiveTrial(i)}
                  style={{
                    display: "flex", alignItems: "center", gap: 10,
                    padding: "9px 12px",
                    background: activeTrial === i
                      ? (t.reliable ? "#0a2010" : "#0f1a28")
                      : "transparent",
                    border: `1px solid ${activeTrial === i
                      ? (t.reliable ? "#4ade8066" : "#22d3ee66")
                      : "#1a2540"}`,
                    borderRadius: 5, cursor: "pointer",
                    transition: "all 0.15s ease",
                    textAlign: "left",
                  }}
                >
                  <span style={{
                    fontFamily: MONO, fontSize: 13, fontWeight: 700,
                    color: activeTrial === i
                      ? (t.reliable ? "#4ade80" : "#22d3ee")
                      : "#3a4a60",
                    minWidth: 70,
                    transition: "color 0.15s ease",
                  }}>{t.label}</span>
                  <span style={{
                    fontFamily: MONO, fontSize: 10,
                    color: activeTrial === i ? "#5a7a90" : "#1e2e42",
                    flex: 1, letterSpacing: "0.06em",
                    transition: "color 0.15s ease",
                  }}>{t.stepNote}</span>
                  <span style={{
                    fontFamily: MONO, fontSize: 12, fontWeight: 700,
                    color: activeTrial === i
                      ? (t.reliable ? "#4ade80" : "#22d3ee")
                      : "#1e2e42",
                    transition: "color 0.15s ease",
                  }}>{t.step}</span>
                </button>
              ))}
            </div>

            {/* Active trial callout */}
            <div style={{
              background: tri.reliable ? "#0a201066" : "#0a182866",
              border: `1px solid ${tri.reliable ? "#4ade8044" : "#22d3ee44"}`,
              borderRadius: 6, padding: "12px 14px",
              transition: "all 0.2s ease",
            }}>
              <div style={{
                fontFamily: MONO, fontSize: 10,
                color: tri.reliable ? "#4ade80" : "#22d3ee",
                textTransform: "uppercase", letterSpacing: "0.12em",
                marginBottom: 6,
              }}>
                Precision at {tri.label}
              </div>

              {/* Precision ruler visual */}
              <div style={{ marginBottom: 10 }}>
                <div style={{
                  display: "flex", justifyContent: "space-between",
                  fontFamily: MONO, fontSize: 9, color: "#3a4a60",
                  marginBottom: 4,
                }}>
                  <span>0.96</span>
                  <span style={{ color: "#f59e0b" }}>0.98 threshold</span>
                  <span>1.00</span>
                </div>
                <div style={{
                  position: "relative", height: 20,
                  background: "#060c18",
                  border: "1px solid #1a2540",
                  borderRadius: 3, overflow: "visible",
                }}>
                  {/* Tick marks at each step */}
                  {Array.from({ length: Math.min(40, Math.floor(0.04 * tri.n)) }).map((_, idx) => {
                    const pos = (idx / Math.min(40, Math.floor(0.04 * tri.n))) * 100;
                    return (
                      <div key={idx} style={{
                        position: "absolute", left: `${pos}%`,
                        top: 0, bottom: 0,
                        width: 1,
                        background: "#1a2540",
                      }} />
                    );
                  })}
                  {/* Threshold marker */}
                  <div style={{
                    position: "absolute", left: "50%",
                    top: -4, bottom: -4, width: 2,
                    background: "#f59e0b",
                    borderRadius: 1,
                  }} />
                  {/* Step indicator */}
                  <div style={{
                    position: "absolute",
                    left: "50%", top: "50%",
                    transform: "translate(-50%, -50%)",
                    fontFamily: MONO, fontSize: 9,
                    color: tri.reliable ? "#4ade80" : "#22d3ee",
                    whiteSpace: "nowrap",
                    fontWeight: 700,
                  }}>
                    {tri.step} per trial
                  </div>
                </div>
              </div>

              <div style={{
                fontFamily: BODY, fontSize: 12, color: "#8a9ab8",
                lineHeight: 1.6,
              }}>
                {tri.warning}
              </div>

              {!tri.reliable && (
                <div style={{
                  marginTop: 8, padding: "6px 10px",
                  background: "#0a0f1a", border: "1px solid #1a2540",
                  borderRadius: 4, fontFamily: BODY, fontSize: 11,
                  color: "#4a5a70", lineHeight: 1.5,
                }}>
                  Increasing trials here sharpens the measurement — it does not
                  change whether the detector actually meets your risk policy.
                </div>
              )}
              {tri.reliable && (
                <div style={{
                  marginTop: 8, padding: "6px 10px",
                  background: "#001a10", border: "1px solid #14532d66",
                  borderRadius: 4, fontFamily: BODY, fontSize: 11,
                  color: "#4ade80aa", lineHeight: 1.5,
                }}>
                  At this scale, Monte Carlo error in the bootstrap estimator becomes
                  quantifiable and auditable via sigma distance.
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer rule */}
        <div style={{
          marginTop: 20, padding: "14px 0 0",
          borderTop: "1px solid #1a2540",
          display: "grid", gridTemplateColumns: "1fr 1fr",
          gap: 20,
        }}>
          <div style={{
            fontFamily: MONO, fontSize: 11, color: "#3a4a60",
            lineHeight: 1.6,
          }}>
            <span style={{ color: "#22d3ee" }}>THRESHOLD</span> → what failure rate you accept
            &nbsp;&nbsp;·&nbsp;&nbsp;
            this is a <span style={{ color: "#c8d4e8" }}>policy decision</span>
          </div>
          <div style={{
            fontFamily: MONO, fontSize: 11, color: "#3a4a60",
            lineHeight: 1.6,
          }}>
            <span style={{ color: "#4ade80" }}>TRIAL COUNT</span> → how precisely you can measure it
            &nbsp;&nbsp;·&nbsp;&nbsp;
            this is an <span style={{ color: "#c8d4e8" }}>engineering decision</span>
          </div>
        </div>

        {/* Slide label */}
        <div style={{
          marginTop: 8, textAlign: "right",
          fontFamily: MONO, fontSize: 9,
          color: "#1e2e42", letterSpacing: "0.1em",
        }}>
          EVIDENCE COUNCIL · github.com/BrianMGreen2/evidence-council
        </div>
      </div>
{/* Documentation Overlay Toggle */}
const [showDoc, setShowDoc] = useState(false);

{/* Add this button in the bottom left */}
<button 
  onClick={() => setShowDoc(true)}
  style={{
    position: "absolute", bottom: 20, left: 20,
    background: "transparent", border: "1px solid #1a2540",
    color: "#5a6a88", fontFamily: MONO, fontSize: 10,
    padding: "6px 10px", borderRadius: 4, cursor: "pointer",
    zIndex: 10
  }}
>
  [ INFO / DOCS ]
</button>

{/* The Overlay Modal */}
{showDoc && (
  <div style={{
    position: "absolute", inset: 0, zIndex: 100,
    background: "rgba(8, 12, 18, 0.98)",
    padding: "60px", overflowY: "auto",
    color: "#c8d4e8", fontFamily: BODY
  }}>
    <button 
      onClick={() => setShowDoc(false)}
      style={{
        position: "absolute", top: 30, right: 30,
        background: "#22d3ee", border: "none", color: "#080c12",
        padding: "8px 16px", borderRadius: 4, fontFamily: MONO, fontWeight: 700,
        cursor: "pointer"
      }}
    >
      CLOSE
    </button>

    <div style={{ maxWidth: "800px", margin: "0 auto" }}>
      <h2 style={{ fontFamily: DISPLAY, fontSize: 32, color: "#f0f4ff" }}>The Evidence Council Framework</h2>
      <p style={{ fontSize: 16, lineHeight: 1.6, color: "#8a9ab8" }}>
        This interactive primer addresses the "Implementation Gap" in AI Governance. 
        Most organizations fail because they confuse a <strong>Policy Goal</strong> with 
        <strong>Measurement Precision</strong>.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "40px", marginTop: "40px" }}>
        <div>
          <h3 style={{ color: "#22d3ee", fontFamily: MONO, fontSize: 14 }}>1. THE THRESHOLD (POLICY)</h3>
          <p style={{ fontSize: 14, lineHeight: 1.5 }}>
            This is your <strong>Risk Tolerance</strong>. It is a humanistic and business decision. 
            A "Safety-Critical" threshold isn't just a high number; it is an explicit agreement 
            on the maximum allowable failure rate before a system is deemed unfit for clinical use.
          </p>
        </div>
        <div>
          <h3 style={{ color: "#4ade80", fontFamily: MONO, fontSize: 14 }}>2. TRIAL COUNT (PRECISION)</h3>
          <p style={{ fontSize: 14, lineHeight: 1.5 }}>
            This is your <strong>Ruler</strong>. It does not change the AI's performance; it only 
            changes how clearly you can see it. Using 100 trials to measure a 99% CI policy 
            is like trying to measure a hair's width with a yardstick.
          </p>
        </div>
      </div>

      <div style={{ marginTop: "40px", padding: "20px", border: "1px solid #1a2540", borderRadius: 8 }}>
        <h3 style={{ fontSize: 18, color: "#f0f4ff" }}>Integration with PolicyFingerprintAI</h3>
        <p style={{ fontSize: 14, color: "#8a9ab8" }}>
          These parameters form the "Governance DNA" that <strong>PolicyFingerprintAI</strong> 
          hashes and anchors. By defining these thresholds as immutable infrastructure, we move 
          away from "vibe-based" evaluation into deterministic, auditable governance.
        </p>
      </div>
    </div>
  </div>
)}
    </div>
  );
}
