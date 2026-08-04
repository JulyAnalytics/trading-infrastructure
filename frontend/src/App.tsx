import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import CommandDeck from "./pages/CommandDeck";
import MarcusPage from "./pages/MarcusPage";
import SarahPage from "./pages/SarahPage";
import JordanPage from "./pages/JordanPage";
import PriyaPage from "./pages/PriyaPage";
import ParamsPage from "./pages/ParamsPage";
import JobsPage from "./pages/JobsPage";
import ReportsPage from "./pages/ReportsPage";
import { THEMES, useTheme } from "./theme";

const nav = ({ isActive }: { isActive: boolean }) =>
  "navlink" + (isActive ? " active" : "");

export default function App() {
  const [theme, applyTheme] = useTheme();
  return (
    <div className="app">
      <nav className="sidenav">
        <h1>Leopold</h1>
        <NavLink to="/" end className={nav}>Command Deck</NavLink>
        <div className="section">Workspaces</div>
        <NavLink to="/marcus" className={nav}>Marcus · Macro</NavLink>
        <NavLink to="/sarah" className={nav}>Sarah · Vol</NavLink>
        <NavLink to="/priya" className={nav}>Priya · Research</NavLink>
        <NavLink to="/jordan" className={nav}>Jordan · Risk</NavLink>
        <div className="section">Platform</div>
        <NavLink to="/params" className={nav}>Parameters</NavLink>
        <NavLink to="/jobs" className={nav}>Jobs & Health</NavLink>
        <NavLink to="/reports" className={nav}>Reports</NavLink>
        <div className="theme-select">
          <div className="section">Theme</div>
          <select value={theme} onChange={(e) => applyTheme(e.target.value as any)}>
            {THEMES.map((t) => (
              <option key={t.id} value={t.id}>{t.label}</option>
            ))}
          </select>
        </div>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<CommandDeck />} />
          <Route path="/marcus" element={<MarcusPage />} />
          <Route path="/sarah" element={<SarahPage />} />
          <Route path="/priya" element={<PriyaPage />} />
          <Route path="/jordan" element={<JordanPage />} />
          <Route path="/params" element={<ParamsPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
