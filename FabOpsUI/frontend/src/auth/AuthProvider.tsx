import { createContext, useCallback, useContext, useEffect, useState, ReactNode } from 'react';
import { PublicClientApplication, AccountInfo, Configuration } from '@azure/msal-browser';

export interface AuthConfig {
  tenantId: string;
  clientId: string;
}

const STORAGE_KEY = 'fabops_auth_cfg';

function buildMsalConfig(cfg: AuthConfig): Configuration {
  return {
    auth: {
      clientId: cfg.clientId,
      authority: `https://login.microsoftonline.com/${cfg.tenantId}`,
      redirectUri: window.location.origin,
    },
    cache: { cacheLocation: 'sessionStorage', storeAuthStateInCookie: false },
  };
}

export interface AuthContextValue {
  account: AccountInfo | null;
  config: AuthConfig | null;
  isInitializing: boolean;
  error: string | null;
  login: (cfg: AuthConfig, saveToSecrets?: boolean) => Promise<void>;
  logout: () => void;
  clearError: () => void;
}

const AuthCtx = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [msalInst, setMsalInst] = useState<PublicClientApplication | null>(null);
  const [isInitializing, setIsInitializing] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // On mount: restore session from sessionStorage (handles redirect flow).
  useEffect(() => {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) { setIsInitializing(false); return; }
    (async () => {
      try {
        const cfg = JSON.parse(raw) as AuthConfig;
        const inst = new PublicClientApplication(buildMsalConfig(cfg));
        await inst.initialize();
        const result = await inst.handleRedirectPromise();
        if (result?.account) {
          setAccount(result.account);
          setConfig(cfg);
          setMsalInst(inst);
        } else {
          const accounts = inst.getAllAccounts();
          if (accounts.length > 0) {
            setAccount(accounts[0]);
            setConfig(cfg);
            setMsalInst(inst);
          }
        }
      } catch {
        sessionStorage.removeItem(STORAGE_KEY);
      } finally {
        setIsInitializing(false);
      }
    })();
  }, []);

  const login = useCallback(async (cfg: AuthConfig, saveToSecrets = false) => {
    setError(null);
    try {
      if (saveToSecrets) {
        const r = await fetch('/api/secrets', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tenant_id: cfg.tenantId, client_id: cfg.clientId }),
        });
        if (!r.ok) throw new Error(`Failed to save configuration: HTTP ${r.status}`);
      }

      // Store config before redirect so we can restore on return.
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(cfg));
      const inst = new PublicClientApplication(buildMsalConfig(cfg));
      await inst.initialize();
      setMsalInst(inst);
      setConfig(cfg);

      try {
        const resp = await inst.loginPopup({ scopes: ['openid', 'profile', 'email'] });
        setAccount(resp.account);
      } catch {
        // Popup blocked or dismissed — fall back to full-page redirect.
        await inst.loginRedirect({ scopes: ['openid', 'profile', 'email'] });
      }
    } catch (e: unknown) {
      sessionStorage.removeItem(STORAGE_KEY);
      setMsalInst(null);
      setConfig(null);
      setError(e instanceof Error ? e.message : 'Authentication failed');
    }
  }, []);

  const logout = useCallback(() => {
    sessionStorage.removeItem(STORAGE_KEY);
    msalInst?.logoutPopup().catch(() => msalInst?.logoutRedirect());
    setAccount(null);
    setConfig(null);
    setMsalInst(null);
  }, [msalInst]);

  const clearError = useCallback(() => setError(null), []);

  return (
    <AuthCtx.Provider value={{ account, config, isInitializing, error, login, logout, clearError }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
