import { FormEvent, useEffect, useState } from 'react';

const BACKEND = import.meta.env.VITE_BACKEND_URL ?? '';

type Tab = 'sample' | 'custom';

interface SecretsData {
  tenant_id: string | null;
  client_id: string | null;
  client_secret_set: boolean;
}

export default function ConfigPage() {
  const [tab, setTab] = useState<Tab>('sample');
  const [data, setData] = useState<SecretsData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [tenantId, setTenantId] = useState('');
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch(`${BACKEND}/api/secrets`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() as Promise<SecretsData>; })
      .then(d => {
        setData(d);
        setTenantId(d.tenant_id ?? '');
        setClientId(d.client_id ?? '');
      })
      .catch((e: Error) => setLoadError(e.message));
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
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSaved(true);
      setClientSecret('');
      if (clientSecret) setData(d => d ? { ...d, client_secret_set: true } : d);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  if (loadError) {
    return (
      <div className="page-centered">
        <div className="info-card">
          <p className="msg-error">Failed to load configuration: {loadError}</p>
          <p className="msg-hint">Make sure the backend is running and GOOGLE_CLOUD_PROJECT is set.</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="page-centered">
        <div className="info-card"><p className="msg-hint">Loading…</p></div>
      </div>
    );
  }

  return (
    <div className="page-centered">
      <div className="cfg-card">
        <div className="cfg-card-header">
          <h2>Azure Configuration</h2>
          <p>Manage the Azure AD credentials used by the Fabric MCP proxies to access your tenant.</p>
        </div>

        <div className="tabs">
          <button
            type="button"
            className={`tab-btn${tab === 'sample' ? ' active' : ''}`}
            onClick={() => setTab('sample')}
          >
            Sample
          </button>
          <button
            type="button"
            className={`tab-btn${tab === 'custom' ? ' active' : ''}`}
            onClick={() => setTab('custom')}
          >
            Custom Authentication
          </button>
        </div>

        {tab === 'sample' ? (
          <div className="sample-view">
            <p className="msg-hint">
              Pre-configured credentials stored in Google Secret Manager.
              These are used by the Fabric MCP proxies to authenticate to Microsoft Fabric on behalf of the app.
            </p>
            <div className="sample-info">
              <div className="sample-row">
                <span className="sample-label">Tenant ID</span>
                <code className="sample-val">{data.tenant_id ?? '—'}</code>
              </div>
              <div className="sample-row">
                <span className="sample-label">Client ID</span>
                <code className="sample-val">{data.client_id ?? '—'}</code>
              </div>
              <div className="sample-row">
                <span className="sample-label">Client Secret</span>
                <span className={`badge ${data.client_secret_set ? 'badge-set' : 'badge-unset'}`}>
                  {data.client_secret_set ? 'Configured' : 'Not set'}
                </span>
              </div>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSave} className="cfg-form">
            <p className="msg-hint">
              Enter custom Azure AD credentials. All values are saved to Google Secret Manager.
              Tenant ID and Client ID are readable identifiers. Client Secret is write-only.
            </p>
            <div className="form-group">
              <label htmlFor="cfg-tenant">Tenant ID</label>
              <input
                id="cfg-tenant"
                type="text"
                value={tenantId}
                onChange={e => setTenantId(e.target.value)}
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              />
            </div>
            <div className="form-group">
              <label htmlFor="cfg-client">Client ID</label>
              <input
                id="cfg-client"
                type="text"
                value={clientId}
                onChange={e => setClientId(e.target.value)}
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              />
            </div>
            <div className="form-group">
              <label htmlFor="cfg-secret">
                Client Secret
                <span className={`badge ${data.client_secret_set ? 'badge-set' : 'badge-unset'}`}>
                  {data.client_secret_set ? 'Configured' : 'Not set'}
                </span>
              </label>
              <input
                id="cfg-secret"
                type="password"
                value={clientSecret}
                onChange={e => setClientSecret(e.target.value)}
                placeholder={data.client_secret_set ? 'Enter a new value to replace' : 'Enter secret value'}
              />
            </div>

            {saveError && <p className="msg-error">{saveError}</p>}
            {saved && <p className="msg-success">Configuration saved successfully.</p>}

            <button type="submit" className="btn-primary" disabled={saving}>
              {saving ? 'Saving…' : 'Save configuration'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
