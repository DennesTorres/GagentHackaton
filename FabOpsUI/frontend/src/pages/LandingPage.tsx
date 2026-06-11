import { useEffect, useRef, useState } from 'react';
import { AuthConfig, useAuth } from '../auth/AuthProvider';

const HexLogo = ({ id, size = 40 }: { id: string; size?: number }) => (
  <svg viewBox="0 0 40 46" fill="none" width={size} height={size}>
    <path d="M20 2L37 11.5V28.5L20 38 3 28.5V11.5L20 2Z"
      fill={`url(#${id})`} stroke="rgba(99,102,241,.35)" strokeWidth="1" />
    <path d="M13 22l4.5 4.5L27 17"
      stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    <defs>
      <linearGradient id={id} x1="3" y1="2" x2="37" y2="38" gradientUnits="userSpaceOnUse">
        <stop stopColor="#6366f1" />
        <stop offset="1" stopColor="#22d3ee" />
      </linearGradient>
    </defs>
  </svg>
);

export default function LandingPage() {
  const { login, error, clearError } = useAuth();
  const [stage, setStage] = useState<'hero' | 'config' | 'signing-in'>('hero');
  const [cfg, setCfg] = useState<AuthConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const configRef = useRef<HTMLDivElement>(null);

  // Fetch credentials from backend as soon as the auth card appears.
  useEffect(() => {
    if (stage !== 'config') return;
    setCfg(null);
    setLoadError(null);
    fetch('/api/secrets')
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((data: { tenant_id: string | null; client_id: string | null }) => {
        if (!data.tenant_id || !data.client_id)
          throw new Error('Azure credentials not found in Secret Manager.');
        setCfg({ tenantId: data.tenant_id, clientId: data.client_id });
      })
      .catch((e: Error) => setLoadError(e.message));
  }, [stage]);

  useEffect(() => {
    if (stage === 'config')
      setTimeout(() => configRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 80);
  }, [stage]);

  const handleGetStarted = () => { clearError(); setStage('config'); };

  const handleSignIn = async () => {
    if (!cfg) return;
    clearError();
    setLoadError(null);
    setStage('signing-in');
    await login(cfg, false);
    setStage('config');
  };

  const authError = error || loadError;
  const ready = !!cfg && stage !== 'signing-in';

  return (
    <div className="landing">
      <div className="landing-grid" aria-hidden />

      {/* ── Hero ──────────────────────────────────── */}
      <section className="landing-hero">
        <div className="hero-glow hero-glow-l" aria-hidden />
        <div className="hero-glow hero-glow-r" aria-hidden />

        <div className="hero-inner">
          <div className="hero-copy">
            <div className="brand">
              <HexLogo id="hero-logo" size={40} />
              <span className="brand-name">FabOps</span>
            </div>

            <h1 className="hero-headline">
              Governance that<br />speaks{' '}
              <span className="hero-hl-accent">your language.</span><br />
              And enforces it.
            </h1>

            <p className="hero-sub">
              Describe a rule in plain English. FabOps Copilot compiles it into FRL —
              a versioned, immutable governance rule language — then deploys agents to
              verify every item in your Microsoft Fabric tenant, pass or fail, with evidence.
            </p>

            <div className="hero-pills">
              <span className="hero-pill">Gemini on Vertex AI</span>
              <span className="hero-pill">Elastic hybrid search</span>
              <span className="hero-pill">Microsoft Fabric API</span>
            </div>

            {stage === 'hero' && (
              <button className="btn-cta" onClick={handleGetStarted}>
                Get started
                <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
                  <path fillRule="evenodd" d="M3 10a.75.75 0 01.75-.75h10.638L10.23 5.29a.75.75 0 111.04-1.08l5.5 5.25a.75.75 0 010 1.08l-5.5 5.25a.75.75 0 11-1.04-1.08l4.158-3.96H3.75A.75.75 0 013 10z" clipRule="evenodd" />
                </svg>
              </button>
            )}
          </div>

          {/* Right: FRL demo card */}
          <div className="hero-demo" aria-hidden>
            <div className="demo-card">
              <div className="demo-card-hdr">
                <span className="demo-badge">FRL</span>
                <span className="demo-filename">lakehouse-capacity.frl</span>
                <span className="demo-dots"><span /><span /><span /></span>
              </div>
              <pre className="demo-code">{`rule LakehouseCapacityRequired {
  scope: workspace.items
    where type = "Lakehouse"
      and workspace.tier = "Production"

  check: item.capacity != null

  message: "Production lakehouses
    must have a capacity assigned"
}`}</pre>
            </div>
            <div className="demo-results">
              <div className="demo-result pass"><span className="res-dot" /><span className="res-name">LH_Sales_Prod</span><span className="res-status">PASS</span></div>
              <div className="demo-result pass"><span className="res-dot" /><span className="res-name">LH_Finance_Q4</span><span className="res-status">PASS</span></div>
              <div className="demo-result fail"><span className="res-dot" /><span className="res-name">LH_Marketing_New</span><span className="res-status">FAIL</span></div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Sign in ───────────────────────────────── */}
      {(stage === 'config' || stage === 'signing-in') && (
        <section className="auth-section" ref={configRef}>
          <div className="auth-card">
            <h2 className="auth-card-title">Sign in to FabOps</h2>
            <p className="auth-card-sub">
              {!cfg && !loadError ? 'Loading configuration…' : 'Authenticate with your Microsoft account'}
            </p>

            {authError && <p className="msg-error">{authError}</p>}

            <button className="btn-msft" disabled={!ready} onClick={handleSignIn}>
              <svg viewBox="0 0 21 21" width="18" height="18" xmlns="http://www.w3.org/2000/svg">
                <rect x="1" y="1" width="9" height="9" fill="#f25022" />
                <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
                <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
                <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
              </svg>
              {stage === 'signing-in' ? 'Signing in…' : 'Sign in with Microsoft'}
            </button>
          </div>
        </section>
      )}

      {/* ── How it works ─────────────────────────── */}
      <section className="features">
        <div className="features-inner">
          <div className="features-hdr">
            <h2>How FabOps works</h2>
            <p>Stop documenting governance. Start operating it.</p>
          </div>
          <div className="features-grid">
            <div className="feature-card">
              <div className="feature-num">01</div>
              <div className="feature-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="22" height="22">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
              </div>
              <h3>Define in plain English</h3>
              <p>Describe a governance rule naturally. FabOps Copilot reconciles your intent with Fabric terminology, prevents duplicates, and compiles it to FRL — versioned and immutable.</p>
            </div>
            <div className="feature-card">
              <div className="feature-num">02</div>
              <div className="feature-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="22" height="22">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
                </svg>
              </div>
              <h3>Deploy evaluation agents</h3>
              <p>Agents walk your live Fabric tenant — workspaces, items, capacities — through the Fabric API and notebooks. Each rule clause is routed to the agent best equipped to verify it.</p>
            </div>
            <div className="feature-card">
              <div className="feature-num">03</div>
              <div className="feature-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" width="22" height="22">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
                </svg>
              </div>
              <h3>Enforce with evidence</h3>
              <p>Every evaluation produces pass/fail with evidence. Every rule is versioned and auditable. Elastic hybrid search understands rule semantics so your rulebook stays clean as it grows.</p>
            </div>
          </div>
        </div>
      </section>

      <footer className="landing-footer">
        <div className="landing-footer-brand">
          <HexLogo id="footer-logo" size={24} />
          <span>FabOps</span>
        </div>
        <span className="landing-footer-tagline">Your rules, running.</span>
      </footer>
    </div>
  );
}
