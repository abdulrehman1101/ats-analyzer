import { useState, useRef } from "react";

// ── Config ────────────────────────────────────────────────────────────────────
const API_BASE = "http://localhost:8000";

// ── Helpers ───────────────────────────────────────────────────────────────────
const verdictConfig = {
  HIRE:    { label: "Recommend Hire",    color: "#16a34a", bg: "#f0fdf4", border: "#86efac", emoji: "✓" },
  MAYBE:   { label: "Further Review",   color: "#d97706", bg: "#fffbeb", border: "#fcd34d", emoji: "?" },
  NO_HIRE: { label: "Not Recommended",  color: "#dc2626", bg: "#fef2f2", border: "#fca5a5", emoji: "✕" },
};

const ScoreBar = ({ value, label, color = "#6366f1" }) => (
  <div style={{ marginBottom: 12 }}>
    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
      <span style={{ fontSize: 13, color: "#6b7280" }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 600, color }}>{value}%</span>
    </div>
    <div style={{ height: 8, background: "#f3f4f6", borderRadius: 99 }}>
      <div style={{
        height: "100%", borderRadius: 99, background: color,
        width: `${value}%`, transition: "width 1s ease"
      }}/>
    </div>
  </div>
);

const Chip = ({ text, type }) => {
  const colors = {
    skill:   { bg: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe" },
    missing: { bg: "#fef2f2", color: "#b91c1c", border: "#fecaca" },
    strength:{ bg: "#f0fdf4", color: "#15803d", border: "#bbf7d0" },
    gap:     { bg: "#fff7ed", color: "#c2410c", border: "#fed7aa" },
  };
  const c = colors[type] || colors.skill;
  return (
    <span style={{
      display: "inline-block", padding: "3px 10px", borderRadius: 99,
      fontSize: 12, fontWeight: 500, margin: "3px 4px 3px 0",
      background: c.bg, color: c.color, border: `1px solid ${c.border}`
    }}>{text}</span>
  );
};

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [file, setFile] = useState(null);
  const [jd, setJd] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef();

  // ── File handling ──────────────────────────────────────────────────────────
  const handleFile = (f) => {
    if (!f) return;
    const allowed = [".pdf", ".docx", ".txt"];
    const ext = "." + f.name.split(".").pop().toLowerCase();
    if (!allowed.includes(ext)) {
      setError("Please upload a PDF, DOCX, or TXT file.");
      return;
    }
    setFile(f);
    setError("");
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    handleFile(e.dataTransfer.files[0]);
  };

  // ── Submit ─────────────────────────────────────────────────────────────────
  const handleAnalyze = async () => {
    if (!file) return setError("Please upload a resume.");
    if (!jd.trim()) return setError("Please paste a job description.");
    setError("");
    setResult(null);
    setLoading(true);

    try {
      const formData = new FormData();
      formData.append("resume", file);
      formData.append("job_description", jd);

      const res = await fetch(`${API_BASE}/analyze`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Server error ${res.status}`);
      }

      const data = await res.json();
      setResult(data);
    } catch (e) {
      setError(e.message || "Something went wrong. Is the backend running?");
    } finally {
      setLoading(false);
    }
  };

  // ── Reset ──────────────────────────────────────────────────────────────────
  const handleReset = () => {
    setFile(null);
    setJd("");
    setResult(null);
    setError("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const vc = result ? (verdictConfig[result.verdict] || verdictConfig.MAYBE) : null;

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div style={{
      minHeight: "100vh", background: "#f8fafc",
      fontFamily: "'Inter', system-ui, sans-serif", color: "#111827"
    }}>
      {/* Header */}
      <div style={{
        background: "#fff", borderBottom: "1px solid #e5e7eb",
        padding: "0 32px", display: "flex", alignItems: "center",
        justifyContent: "space-between", height: 60
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 8, background: "#4f46e5",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 18, color: "#fff"
          }}>⚡</div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 16 }}>ATS Resume Analyzer</div>
            <div style={{ fontSize: 11, color: "#9ca3af" }}>Powered by OpenAI · No data stored</div>
          </div>
        </div>
        <div style={{
          fontSize: 12, color: "#6b7280", background: "#f3f4f6",
          padding: "4px 12px", borderRadius: 99
        }}>
          🔒 Local AI · Privacy First
        </div>
      </div>

      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "32px 24px" }}>

        {/* Upload + JD panel */}
        {!result && (
          <div style={{
            display: "grid", gridTemplateColumns: "1fr 1fr",
            gap: 24, marginBottom: 24
          }}>
            {/* Resume upload */}
            <div style={{ background: "#fff", borderRadius: 12, padding: 24, border: "1px solid #e5e7eb" }}>
              <h2 style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 600 }}>Upload Resume</h2>
              <div
                onClick={() => fileInputRef.current?.click()}
                onDrop={handleDrop}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                style={{
                  border: `2px dashed ${dragOver ? "#4f46e5" : file ? "#22c55e" : "#d1d5db"}`,
                  borderRadius: 12, padding: "32px 20px", textAlign: "center",
                  cursor: "pointer", background: dragOver ? "#eef2ff" : file ? "#f0fdf4" : "#fafafa",
                  transition: "all 0.2s"
                }}
              >
                {file ? (
                  <>
                    <div style={{ fontSize: 32 }}>📄</div>
                    <div style={{ fontWeight: 600, color: "#15803d", marginTop: 8 }}>{file.name}</div>
                    <div style={{ fontSize: 12, color: "#6b7280", marginTop: 4 }}>
                      {(file.size / 1024).toFixed(1)} KB · Click to change
                    </div>
                  </>
                ) : (
                  <>
                    <div style={{ fontSize: 36 }}>📂</div>
                    <div style={{ fontWeight: 500, marginTop: 8 }}>Drop resume here</div>
                    <div style={{ fontSize: 12, color: "#9ca3af", marginTop: 4 }}>
                      PDF, DOCX, or TXT
                    </div>
                  </>
                )}
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.txt"
                style={{ display: "none" }}
                onChange={(e) => handleFile(e.target.files[0])}
              />
            </div>

            {/* Job Description */}
            <div style={{ background: "#fff", borderRadius: 12, padding: 24, border: "1px solid #e5e7eb" }}>
              <h2 style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 600 }}>Job Description</h2>
              <textarea
                value={jd}
                onChange={(e) => setJd(e.target.value)}
                placeholder="Paste the job description here...

Example:
We are looking for a Senior Software Engineer with 5+ years of experience in Python, REST APIs, and cloud infrastructure. Experience with AWS and Kubernetes is a plus. Strong communication skills required."
                style={{
                  width: "100%", height: 200, padding: "12px 14px",
                  border: "1px solid #e5e7eb", borderRadius: 8, fontSize: 13,
                  lineHeight: 1.6, resize: "vertical", outline: "none",
                  fontFamily: "inherit", color: "#374151",
                  boxSizing: "border-box"
                }}
              />
              <div style={{ fontSize: 12, color: "#9ca3af", marginTop: 6 }}>
                {jd.length} characters
              </div>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div style={{
            background: "#fef2f2", border: "1px solid #fca5a5", color: "#b91c1c",
            borderRadius: 8, padding: "12px 16px", marginBottom: 20, fontSize: 14
          }}>
            ⚠️ {error}
          </div>
        )}

        {/* Analyze button */}
        {!result && (
          <div style={{ textAlign: "center" }}>
            <button
              onClick={handleAnalyze}
              disabled={loading || !file || !jd.trim()}
              style={{
                background: loading ? "#a5b4fc" : "#4f46e5",
                color: "#fff", border: "none", borderRadius: 10,
                padding: "14px 48px", fontSize: 16, fontWeight: 600,
                cursor: loading || !file || !jd.trim() ? "not-allowed" : "pointer",
                transition: "background 0.2s", letterSpacing: 0.3
              }}
            >
              {loading ? "🤖 Analyzing with GPT-4o..." : "⚡ Analyze Resume"}
            </button>
            <div style={{ fontSize: 12, color: "#9ca3af", marginTop: 8 }}>
              Takes 10–30 seconds depending on your internet speed
            </div>
          </div>
        )}

        {/* Loading spinner */}
        {loading && (
          <div style={{ textAlign: "center", padding: "48px 0", color: "#6b7280" }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>🧠</div>
            <div style={{ fontWeight: 600, fontSize: 18, marginBottom: 8 }}>GPT-4o is thinking...</div>
            <div style={{ fontSize: 14 }}>Reading resume · Comparing with JD · Forming verdict</div>
          </div>
        )}

        {/* RESULTS PANEL */}
        {result && vc && (
          <div>
            {/* Verdict banner */}
            <div style={{
              background: vc.bg, border: `2px solid ${vc.border}`,
              borderRadius: 16, padding: "28px 32px", marginBottom: 24,
              display: "flex", alignItems: "center", gap: 24
            }}>
              <div style={{
                width: 72, height: 72, borderRadius: "50%",
                background: vc.color, color: "#fff",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 36, fontWeight: 700, flexShrink: 0
              }}>
                {vc.emoji}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, color: "#6b7280", fontWeight: 500, marginBottom: 2 }}>
                  {result.candidate_name || "Candidate"} · {result.filename}
                </div>
                <div style={{ fontSize: 26, fontWeight: 700, color: vc.color }}>
                  {vc.label}
                </div>
                <div style={{ fontSize: 14, color: "#374151", marginTop: 6, lineHeight: 1.6 }}>
                  {result.summary}
                </div>
              </div>
              <div style={{ textAlign: "center", flexShrink: 0 }}>
                <div style={{
                  fontSize: 48, fontWeight: 800, color: vc.color, lineHeight: 1
                }}>
                  {result.match_score}
                </div>
                <div style={{ fontSize: 13, color: "#6b7280" }}>Match Score</div>
                <div style={{
                  fontSize: 11, marginTop: 4, padding: "2px 8px",
                  background: "#f3f4f6", borderRadius: 99, color: "#374151"
                }}>
                  Confidence: {result.confidence}
                </div>
              </div>
            </div>

            {/* Details grid */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 20, marginBottom: 20 }}>

              {/* Skills found */}
              <div style={{ background: "#fff", borderRadius: 12, padding: 20, border: "1px solid #e5e7eb" }}>
                <h3 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 600, color: "#1d4ed8" }}>
                  ✅ Skills Found
                </h3>
                {(result.key_skills_found || []).map((s, i) => (
                  <Chip key={i} text={s} type="skill" />
                ))}
                {!result.key_skills_found?.length && <span style={{ fontSize: 13, color: "#9ca3af" }}>None identified</span>}
              </div>

              {/* Strengths */}
              <div style={{ background: "#fff", borderRadius: 12, padding: 20, border: "1px solid #e5e7eb" }}>
                <h3 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 600, color: "#15803d" }}>
                  💪 Strengths
                </h3>
                {(result.strengths || []).map((s, i) => (
                  <div key={i} style={{ fontSize: 13, color: "#374151", marginBottom: 6, lineHeight: 1.5 }}>
                    • {s}
                  </div>
                ))}
              </div>

              {/* Gaps */}
              <div style={{ background: "#fff", borderRadius: 12, padding: 20, border: "1px solid #e5e7eb" }}>
                <h3 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 600, color: "#b91c1c" }}>
                  ⚠️ Gaps
                </h3>
                {(result.gaps || []).map((g, i) => (
                  <div key={i} style={{ fontSize: 13, color: "#374151", marginBottom: 6, lineHeight: 1.5 }}>
                    • {g}
                  </div>
                ))}
                {result.missing_skills?.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    {result.missing_skills.map((s, i) => (
                      <Chip key={i} text={s} type="missing" />
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Scores + Recommendation + Interview Qs */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 24 }}>

              {/* Scores */}
              <div style={{ background: "#fff", borderRadius: 12, padding: 20, border: "1px solid #e5e7eb" }}>
                <h3 style={{ margin: "0 0 16px", fontSize: 14, fontWeight: 600 }}>📊 Match Analysis</h3>
                <ScoreBar value={result.match_score} label="Overall Match" color="#4f46e5" />
                <ScoreBar
                  value={result.experience_relevance === "HIGH" ? 85 : result.experience_relevance === "MEDIUM" ? 55 : 25}
                  label="Experience Relevance"
                  color="#0891b2"
                />
                <ScoreBar
                  value={result.verdict === "HIRE" ? 90 : result.verdict === "MAYBE" ? 55 : 20}
                  label="Hire Confidence"
                  color={vc.color}
                />
              </div>

              {/* Recommendation + Interview Qs */}
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <div style={{ background: "#fff", borderRadius: 12, padding: 20, border: "1px solid #e5e7eb" }}>
                  <h3 style={{ margin: "0 0 10px", fontSize: 14, fontWeight: 600 }}>💡 Recommendation</h3>
                  <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6, color: "#374151" }}>
                    {result.recommendation}
                  </p>
                  <div style={{ marginTop: 10, fontSize: 12, color: "#9ca3af" }}>
                    Model: {result.model_used}
                  </div>
                </div>

                <div style={{ background: "#fff", borderRadius: 12, padding: 20, border: "1px solid #e5e7eb" }}>
                  <h3 style={{ margin: "0 0 10px", fontSize: 14, fontWeight: 600 }}>🎤 Suggested Interview Questions</h3>
                  {(result.interview_questions || []).map((q, i) => (
                    <div key={i} style={{ fontSize: 13, color: "#374151", marginBottom: 8, lineHeight: 1.5 }}>
                      <span style={{ fontWeight: 600, color: "#6366f1" }}>Q{i + 1}.</span> {q}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Parse error notice */}
            {result.parse_error && (
              <div style={{
                background: "#fff7ed", border: "1px solid #fed7aa",
                borderRadius: 8, padding: 12, marginBottom: 20, fontSize: 13
              }}>
                ⚠️ The AI response couldn't be fully parsed. Raw output shown in recommendation field.
              </div>
            )}

            {/* Reset button */}
            <div style={{ textAlign: "center" }}>
              <button
                onClick={handleReset}
                style={{
                  background: "#fff", color: "#374151", border: "1px solid #d1d5db",
                  borderRadius: 10, padding: "12px 32px", fontSize: 15,
                  fontWeight: 500, cursor: "pointer"
                }}
              >
                ← Analyze Another Resume
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
