import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from './auth/AuthProvider';
import LandingPage from './pages/LandingPage';
import ChatPage from './pages/ChatPage';
import ConfigPage from './pages/ConfigPage';

const HexLogo = ({ id, size = 28 }: { id: string; size?: number }) => (
  <svg viewBox="0 0 40 46" fill="none" width={size} height={size} style={{ flexShrink: 0 }}>
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

function AppShell() {
  const { account, isInitializing, logout } = useAuth();

  if (isInitializing) {
    return (
      <div className="loading-screen">
        <div className="loading-brand">
          <HexLogo id="load-logo" size={48} />
          <span>FabOps</span>
        </div>
        <div className="loading-spinner" />
      </div>
    );
  }

  if (!account) return <LandingPage />;

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <HexLogo id="app-logo" size={28} />
          <span className="header-brand">FabOps</span>
        </div>

        <nav className="header-nav">
          <NavLink to="/" end className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            Chat
          </NavLink>
          <NavLink to="/config" className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}>
            Configuration
          </NavLink>
        </nav>

        <div className="header-right">
          <span className="header-user" title={account.username}>
            {account.name ?? account.username}
          </span>
          <button className="btn-signout" onClick={logout}>Sign out</button>
        </div>
      </header>

      <main className="main">
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="/config" element={<ConfigPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  );
}
