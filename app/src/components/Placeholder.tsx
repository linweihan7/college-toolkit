// Tabs not yet migrated render this. Their data still lives in localStorage
// untouched (the legacy app and this one share the same keys), so nothing is lost
// — the feature just hasn't been re-implemented in React yet.
export function Placeholder({ name }: { name: string }) {
  return (
    <div className="card">
      <h1 className="page-title">{name}</h1>
      <p className="page-sub">This tab is queued for a later migration increment.</p>
      <p className="empty-state">
        Your {name.toLowerCase()} data is safe in local storage and still available
        in the current live app.
      </p>
    </div>
  );
}
