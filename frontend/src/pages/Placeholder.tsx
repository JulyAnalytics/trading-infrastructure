export default function Placeholder({ name, phase }: { name: string; phase: string }) {
  return (
    <div>
      <h2>{name}</h2>
      <div className="card">
        <p className="muted">
          This workspace ships in <b>{phase}</b> of the v1.0 build. Its engine
          may already be callable from Python — see the plan in
          <span className="mono"> docs/architecture/v1_architecture.md</span>.
        </p>
      </div>
    </div>
  );
}
