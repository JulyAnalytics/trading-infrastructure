import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import CommandDeck from "./pages/CommandDeck";
import MarcusPage from "./pages/MarcusPage";
import SarahPage from "./pages/SarahPage";
import JordanPage from "./pages/JordanPage";
import ParamsPage from "./pages/ParamsPage";
import JobsPage from "./pages/JobsPage";
import Placeholder from "./pages/Placeholder";

const nav = ({ isActive }: { isActive: boolean }) =>
  "navlink" + (isActive ? " active" : "");

export default function App() {
  return (
    <div className="app">
      <nav className="sidenav">
        <h1>
          Trading <span>Workstation</span>
        </h1>
        <NavLink to="/" end className={nav}>Command Deck</NavLink>
        <div className="section">Workspaces</div>
        <NavLink to="/marcus" className={nav}>Marcus · Macro</NavLink>
        <NavLink to="/sarah" className={nav}>Sarah · Vol</NavLink>
        <NavLink to="/priya" className={nav}>Priya · Research</NavLink>
        <NavLink to="/jordan" className={nav}>Jordan · Risk</NavLink>
        <div className="section">Platform</div>
        <NavLink to="/params" className={nav}>Parameters</NavLink>
        <NavLink to="/jobs" className={nav}>Jobs & Health</NavLink>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<CommandDeck />} />
          <Route path="/marcus" element={<MarcusPage />} />
          <Route path="/sarah" element={<SarahPage />} />
          <Route
            path="/priya"
            element={<Placeholder name="Priya — Research Workbench" phase="Phase 4" />}
          />
          <Route path="/jordan" element={<JordanPage />} />
          <Route path="/params" element={<ParamsPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
