import { useEffect, useState, type FormEvent } from "react";
import { startAuthentication, startRegistration } from "@simplewebauthn/browser";
import { ArrowRight, Check, Github, Gift, KeyRound, LoaderCircle, LogOut, Route, X } from "lucide-react";
import { App } from "./App";

type Account = {
  id: string; email: string; admin: boolean; passkeys: number; invite_url: string;
  free_provider: string | null;
  entitlements: { plan: string; interval: number; until?: number | null; multiple_destinations?: boolean };
  schedule?: { next_due: number; status: string; interval?: number; completed?: number; checked: number; failed: number } | null;
};
type Report = {
  totals: Record<string, number>;
  users: { id: string; email: string; verified: number; admin?: number; entitlements: Account["entitlements"]; destinations: number; usage: Record<string, number> }[];
  grants: { id: string; user: string; kind: string; until: number | null; revoked: number }[];
  audit: { id: number; actor: string; target: string; action: string; reason: string; at: number }[];
};
async function api<T = { ok?: boolean; message?: string }>(path: string, body?: unknown): Promise<T> {
  const response = await fetch("/api/v1/" + path, { credentials: "same-origin", ...(body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });
  const result = await response.json();
  if (!response.ok) throw new Error(response.status === 401 ? "Sign in required" : typeof result.detail === "string" ? result.detail : "Request could not be completed");
  return result;
}
function stamp(value?: number | null) { return value ? new Date(value * 1000).toLocaleString(undefined, { hour12: false }) : "Not yet"; }

export function Hosted() {
  const [account, setAccount] = useState<Account | null>(null);
  const [ready, setReady] = useState(false);
  const [panel, setPanel] = useState("Workouts");
  const [signup, setSignup] = useState(false);
  const [enroll, setEnroll] = useState(false);
  const [token, setToken] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get("verify"));
  const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [gift, setGift] = useState<string | null>(null);
  async function refresh() { setAccount(await api<Account>("account")); }
  useEffect(() => {
    function verificationLink() {
      const next = new URLSearchParams(window.location.hash.slice(1)).get("verify");
      if (!next) return;
      setToken(next); setVerified(false); setEnroll(false);
      window.history.replaceState({}, "", window.location.pathname + window.location.search);
    }
    window.addEventListener("hashchange", verificationLink);
    if (token) window.history.replaceState({}, "", window.location.pathname + window.location.search);
    refresh().catch((e: Error) => { if (e.message !== "Sign in required") setError(e.message); }).finally(() => setReady(true));
    return () => window.removeEventListener("hashchange", verificationLink);
  }, []);
  async function perform(action: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : "Operation failed"); } finally { setBusy(false); }
  }
  async function addPasskey() {
    const options = await api<Parameters<typeof startRegistration>[0]["optionsJSON"]>("auth/register/options", {});
    const credential = await startRegistration({ optionsJSON: options });
    await api("auth/register/finish", { credential });
    setEnroll(false); await refresh(); setMessage("Passkey saved");
  }
  async function login() {
    const options = await api<Parameters<typeof startAuthentication>[0]["optionsJSON"]>("auth/login/options", {});
    const credential = await startAuthentication({ optionsJSON: options });
    await api("auth/login/finish", { credential }); await refresh();
  }
  async function register(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const data = new FormData(e.currentTarget);
    const email = data.get("email");
    await perform(async () => {
      const invite = new URLSearchParams(window.location.search).get("invite");
      const result = await api("auth/signup", { email, ...(invite ? { invite } : {}) });
      setMessage(result.message || "Check your email to continue");
    });
  }
  const feedback = <>{busy && <p role="status" className="progress-status"><LoaderCircle size={17} className="spin" /> Working...</p>}{error && <p role="alert" className="error">{error}</p>}{message && <p role="status" className="success">{message}</p>}</>;
  if (!ready) return <main className="login"><p role="status">Connecting...</p></main>;
  if (!account) return <main className="login hosted-login">
    <div className="login-brand"><Route size={30} /><h1>Prescribed</h1></div>
    <p>Your coach’s words. Your next workout.</p>
    {feedback}
    {token && !verified ? <section><h2>Verify your email</h2><button className="primary" disabled={busy} onClick={() => perform(async () => { await api("auth/verify", { token }); setVerified(true); setEnroll(true); })}>Verify email <Check size={16} /></button></section>
      : enroll ? <section><h2>Secure your account</h2><button className="primary" disabled={busy} onClick={() => perform(addPasskey)}><KeyRound size={17} /> Create passkey</button></section>
      : signup ? <form onSubmit={register}><h2>Create your account</h2><label>Email<input name="email" type="email" autoComplete="email" required maxLength={254} /></label><button className="primary" disabled={busy}>Send verification email <ArrowRight size={16} /></button><button type="button" disabled={busy} onClick={() => setSignup(false)}>Back to sign in</button></form>
      : <section><h2>Welcome back</h2><button className="primary" disabled={busy} onClick={() => perform(login)}><KeyRound size={17} /> Sign in with passkey</button><button disabled={busy} onClick={() => setSignup(true)}>Create account</button></section>}
    <p className="independence-disclaimer">Independent of Garmin, COROS, Final Surge, Suunto, Google, and Apple.</p>
    <a href="https://github.com/ayn/workoutbridge" target="_blank" rel="noreferrer"><Github size={15} /> Open source</a>
    <a href="mailto:support@prescribed.fit">Contact support</a>
  </main>;
  async function openAdmin() { setPanel("Admin"); await perform(async () => { setReport(await api<Report>("admin")); }); }
  async function grant(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const data = new FormData(e.currentTarget);
    await perform(async () => {
      await api("admin/gifts", { user: gift, days: data.get("permanent") ? null : Number(data.get("days")), reason: data.get("reason") });
      setGift(null); setReport(await api<Report>("admin")); await refresh();
    });
  }
  return <div className="hosted-shell">
    <header className="hosted-header"><strong>Prescribed</strong><nav aria-label="Workspace"><button aria-pressed={panel === "Workouts"} onClick={() => setPanel("Workouts")}>Workouts</button><button aria-pressed={panel === "Account"} onClick={() => { setPanel("Account"); perform(refresh); }}>Account</button>{account.admin && <button aria-pressed={panel === "Admin"} onClick={openAdmin}>Admin</button>}</nav><button title="Sign out" aria-label="Sign out" disabled={busy} onClick={() => perform(async () => { await api("logout", {}); setAccount(null); })}><LogOut size={17} /></button></header>
    {panel === "Workouts" ? <App brand="Prescribed" multiuser suggestedEmail={account.email} onLogout={() => setAccount(null)} /> : <main className="hosted-content">{feedback}
      {panel === "Account" ? <>
        <h1>Account</h1><p>{account.email}</p>
        <section><h2>Access</h2><dl><dt>Plan</dt><dd>{account.entitlements.plan}</dd><dt>Minimum interval</dt><dd>{account.entitlements.interval / 60} minutes</dd><dt>Supporter until</dt><dd>{account.entitlements.plan === "supporter" ? account.entitlements.until ? stamp(account.entitlements.until) : "No expiry" : "—"}</dd><dt>Next check</dt><dd>{stamp(account.schedule?.next_due)}</dd><dt>Last completed</dt><dd>{stamp(account.schedule?.completed)}</dd><dt>Status</dt><dd>{account.schedule?.status || "Waiting for scheduler"}</dd></dl>
          <label>Check frequency<select disabled={busy} value={account.schedule?.interval || account.entitlements.interval} onChange={(e) => { const seconds = Number(e.target.value); perform(async () => { await api("account/frequency", { seconds }); await refresh(); }); }}>{[[900, "Every 15 minutes"], [1800, "Every 30 minutes"], [3600, "Every hour"], [10800, "Every 3 hours"], [21600, "Every 6 hours"], [43200, "Every 12 hours"], [86400, "Every day"]].map(([seconds, label]) => <option key={seconds} value={seconds} disabled={Number(seconds) < account.entitlements.interval}>{label}{Number(seconds) < account.entitlements.interval ? " · Supporter" : ""}</option>)}</select></label>
          {account.entitlements.plan === "free" && <p>Supporter unlocks 15-minute checks and multiple destination services. <a href="mailto:support@prescribed.fit?subject=Supporter%20access">Ask about upgrading</a></p>}
          {account.schedule?.status === "review_required" && <button disabled={busy} onClick={() => perform(async () => { await api("account/resume", { acknowledge_review: true }); await refresh(); })}>I reviewed sync history; resume scheduling</button>}
          <label>Free destination service<select value={account.free_provider || ""} onChange={(e) => { const provider = e.target.value; perform(async () => { await api("account/provider", { provider }); await refresh(); }); }}><option value="" disabled>Choose a connected service</option><option value="garmin">Garmin</option><option value="coros">COROS</option></select></label>
        </section>
        <section><h2>Passkeys</h2><p>{account.passkeys} registered</p><button disabled={busy} onClick={() => perform(addPasskey)}><KeyRound size={16} /> Add passkey</button></section>
        <section><h2>Invite a training partner</h2><label>Invitation link<input readOnly value={account.invite_url} onFocus={(e) => e.target.select()} /></label><p>Both of you receive 30 days of Supporter after their first verified workout publication. Up to three successful referrals.</p></section>
        <footer><a href="mailto:support@prescribed.fit">Support</a><a href="mailto:work@andrewng.com">Private deployment or consulting</a><a href="https://github.com/ayn/workoutbridge">GitHub</a></footer>
      </> : <>
        <h1>Administration</h1>{report && <><div className="admin-totals">{Object.entries(report.totals).map(([key, value]) => <div key={key}><strong>{value}</strong><span>{key.replaceAll("_", " ")}</span></div>)}</div>
          <div className="table-scroll"><table><thead><tr><th>User</th><th>Email</th><th>Plan</th><th>Services</th><th>Syncs</th><th>Action</th></tr></thead><tbody>{report.users.map((user) => <tr key={user.id}><td>{user.email}</td><td>{user.verified ? "Verified" : "Pending"}</td><td>{user.entitlements.plan}</td><td>{user.destinations}</td><td>{user.usage.syncs}</td><td><button onClick={() => setGift(user.id)}><Gift size={15} /> Gift Supporter</button></td></tr>)}</tbody></table></div>
          <h2>Access grants</h2><div className="table-scroll"><table><thead><tr><th>User</th><th>Source</th><th>Until</th><th>Status</th><th>Action</th></tr></thead><tbody>{report.grants.map((entry) => <tr key={entry.id}><td>{report.users.find((u) => u.id === entry.user)?.email || entry.user}</td><td>{entry.kind}</td><td>{entry.until ? stamp(entry.until) : "Permanent"}</td><td>{entry.revoked ? "Revoked" : "Granted"}</td><td>{!entry.revoked && <button disabled={busy} onClick={() => perform(async () => { await api(`admin/gifts/${entry.id}/revoke`, {}); setReport(await api<Report>("admin")); })}>Revoke</button>}</td></tr>)}</tbody></table></div>
          <h2>Audit log</h2><div className="table-scroll"><table><thead><tr><th>Time</th><th>Action</th><th>Reason</th></tr></thead><tbody>{report.audit.map((entry) => <tr key={entry.id}><td>{stamp(entry.at)}</td><td>{entry.action}</td><td>{entry.reason}</td></tr>)}</tbody></table></div>
        </>}
      </>}
    </main>}
    {gift && <div className="backdrop" onClick={(e) => { if (e.target === e.currentTarget && !busy) setGift(null); }}><section role="dialog" aria-modal="true" aria-label="Gift Supporter" className="modal"><button className="close" aria-label="Close" disabled={busy} onClick={() => setGift(null)}><X size={18} /></button><h2>Gift Supporter</h2><form onSubmit={grant}><label>Days<input name="days" type="number" min={1} max={3650} defaultValue={30} required /></label><label><input name="permanent" type="checkbox" /> Permanent access</label><label>Reason<input name="reason" required maxLength={300} /></label>{feedback}<button className="primary" disabled={busy}>Grant access</button></form></section></div>}
  </div>;
}

export function Bootstrap() {
  const [mode, setMode] = useState<"loading" | "hosted" | "private" | "error">("loading");
  useEffect(() => {
    fetch("/api/v1/config", { credentials: "same-origin" }).then(async (response) => {
      if (response.status === 401 || response.status === 404) { setMode("private"); return; }
      if (!response.ok) throw new Error("Configuration unavailable");
      const config = await response.json();
      setMode(config.multiuser === true ? "hosted" : "private");
    }).catch(() => setMode("error"));
  }, []);
  if (mode === "hosted") return <Hosted />;
  if (mode === "private") return <App />;
  return <main className="login"><p role="status">{mode === "error" ? "Unable to connect. Please try again shortly." : "Connecting..."}</p></main>;
}
