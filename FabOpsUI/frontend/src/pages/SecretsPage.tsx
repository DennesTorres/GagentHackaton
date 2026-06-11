import { FormEvent, useEffect, useState } from "react";

const BACKEND = import.meta.env.VITE_BACKEND_URL ?? "";

interface SecretsData {
  tenant_id: string | null;
  client_id: string | null;
  client_secret_set: boolean;
}

export default function SecretsPage() {
  const [data, setData] = useState<SecretsData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [tenantId, setTenantId] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch(`${BACKEND}/api/secrets`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<SecretsData>;
      })
      .then((d) => {
        setData(d);
        setTenantId(d.tenant_id ?? "");
        setClientId(d.client_id ?? "");
      })
      .catch((err: Error) => setLoadError(err.message));
  }, []);

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    setSaved(false);

    const payload: Record<string, string> = {};
    if (tenantId) payload.tenant_id = tenantId;
    if (clientId) payload.client_id = clientId;
    if (clientSecret) payload.client_secret = clientSecret;

    try {
      const r = await fetch(`${BACKEND}/api/secrets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSaved(true);
      setClientSecret("");
      if (clientSecret) setData((d) => d ? { ...d, client_secret_set: true } : d);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loadError) {
    return (
      <div className="secrets-page">
        <div className="secrets-card">
          <p className="msg-error">Failed to load secrets: {loadError}</p>
          <p className="hint">Make sure the backend is running and GOOGLE_CLOUD_PROJECT is set.</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="secrets-page">
        <div className="secrets-card">
          <p className="hint">Loading…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="secrets-page">
      <div className="secrets-card">
        <h2>Azure Authentication</h2>
        <p className="secrets-description">
          Values are stored in Google Secret Manager and used by the Fabric MCP proxies.
          Tenant ID and Client ID are identifiers — they are readable and displayed here.
          The Client Secret is write-only; this page only indicates whether a value has been set.
        </p>

        <form onSubmit={handleSave}>
          <div className="form-group">
            <label htmlFor="tenant-id">Tenant ID</label>
            <input
              id="tenant-id"
              type="text"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            />
          </div>

          <div className="form-group">
            <label htmlFor="client-id">Azure Client ID</label>
            <input
              id="client-id"
              type="text"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            />
          </div>

          <div className="form-group">
            <label htmlFor="client-secret">
              Azure Client Secret
              <span className={`badge ${data.client_secret_set ? "badge-set" : "badge-unset"}`}>
                {data.client_secret_set ? "Set" : "Not set"}
              </span>
            </label>
            <input
              id="client-secret"
              type="password"
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              placeholder={
                data.client_secret_set ? "Enter a new value to replace the current secret" : "Enter secret value"
              }
            />
          </div>

          {saveError && <p className="msg-error">{saveError}</p>}
          {saved && <p className="msg-success">Secrets saved successfully.</p>}

          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? "Saving…" : "Save secrets"}
          </button>
        </form>
      </div>
    </div>
  );
}
