import { NavLink, Route, Routes } from "react-router-dom";
import ChatPage from "./pages/ChatPage";
import SecretsPage from "./pages/SecretsPage";

export default function App() {
  return (
    <div className="app">
      <header className="header">
        <span className="header-brand">FabOps UI</span>
        <nav className="header-nav">
          <NavLink to="/" end className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}>
            Chat
          </NavLink>
          <NavLink to="/secrets" className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}>
            Secrets
          </NavLink>
        </nav>
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="/secrets" element={<SecretsPage />} />
        </Routes>
      </main>
    </div>
  );
}
