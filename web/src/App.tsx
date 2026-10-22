import { readApiResponse } from "./response";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  Github,
  History,
  Link2,
  LoaderCircle,
  LogOut,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Repeat2,
  Route,
  ShieldCheck,
  Watch,
  X,
} from "lucide-react";

type Step = {
  kind?: string;
  unit?: string;
  duration?: number | null;
  note?: string;
  label?: string;
  speed_min?: number;
  speed_max?: number;
  count?: number;
  steps?: Step[];
  skip_last_recovery?: boolean;
};
type Item = {
  event: { title: string; date: string; description: string };
  draft: { steps: Step[]; unresolved: string[] };
  error?: string;
};
type Plan = {
  id: string;
  account: string;
  hash: string;
  created: string;
  items: Item[];
};
type Source = { id: string; name: string; format: string; timezone: string };
type Sync = {
  id: string;
  source: string;
  profile: string;
  last_preview: string | null;
  error: string | null;
  paused?: boolean;
  automatic?: boolean;
  auto_blocked?: boolean;
  last_publish?: string;
};
type Connection = { id: string; provider: string; account: string };
type State = {
  sources: Source[];
  syncs: Sync[];
  connections: Connection[];
  plans: Plan[];
  history: {
    id: string;
    sync: string;
    at: string;
    status: string;
    upcoming_count?: number;
    results: { title: string; date: string; workout_id: string }[];
  }[];
};
export type View = "Workouts" | "Sources" | "Connections" | "Syncs" | "History";
const independenceDisclaimer =
  "WorkoutBridge is an independent project, not affiliated with, endorsed by, or sponsored by Garmin, Final Surge, COROS, Suunto, Google, Apple, or any other platform provider. All trademarks belong to their respective owners.";
const tabs = [
  { name: "Workouts", icon: CalendarDays },
  { name: "Sources", icon: CalendarDays },
  { name: "Connections", icon: Watch },
  { name: "Syncs", icon: Repeat2 },
  { name: "History", icon: History },
] as const;

const API_BASE = "/api/v1/";

async function defaultApi(path: string, data?: unknown) {
  let response: Response;
  try {
    response = await fetch(
      API_BASE + path,
      data === undefined
        ? { credentials: "same-origin" }
        : {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
          },
    );
  } catch {
    throw new Error(
      "Unable to connect. Check the instance connection before retrying.",
    );
  }
  return readApiResponse(response);
}

function dateLabel(date: string) {
  return new Date(date + "T12:00:00").toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}
function timestamp(value: string | null) {
  return value
    ? new Date(value).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : "Not yet refreshed";
}
function duration(step: Step) {
  if (step.unit === "lap_button") return "Until Lap";
  if (step.unit === "seconds")
    return `${Math.floor((step.duration || 0) / 60)}:${String((step.duration || 0) % 60).padStart(2, "0")}`;
  return `${Math.round((step.duration || 0) * 100) / 100} m`;
}
function pace(speed: number) {
  const sec = Math.round(1609.344 / speed);
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}
function Steps({ steps }: { steps: Step[] }) {
  return (
    <ol className="steps">
      {steps.map((step, i) =>
        step.steps ? (
          <li key={i} className="repeat">
            <div className="repeat-heading">
              <Repeat2 size={15} />
              <strong>Repeat {step.count} times</strong>
            </div>
            <Steps steps={step.steps} />
            {step.skip_last_recovery && <small>Final recovery omitted</small>}
          </li>
        ) : (
          <li key={i} className={`step ${step.kind}`}>
            <div>
              <strong>{(step.kind || "run").replaceAll("_", " ")}</strong>
              {step.label && <span className="effort">{step.label}</span>}
              {step.note && <p>{step.note}</p>}
              {step.speed_min && step.speed_max && (
                <p>
                  {pace(step.speed_max)}–{pace(step.speed_min)} min/mi
                </p>
              )}
            </div>
            <span className="duration">{duration(step)}</span>
          </li>
        ),
      )}
    </ol>
  );
}

function Progress({ label = "Working..." }: { label?: string }) {
  return <div className="progress-status" role="status" aria-label={label}>
    <LoaderCircle size={18} className="spin" aria-hidden="true" />
    <span>{label}</span>
  </div>;
}

const api = defaultApi;

function SetupChecklist({state, navigate, dismiss, busy}: {state: State; navigate: (view: View) => void; dismiss: () => void; busy: boolean}) {
  const steps: {label: string; detail: string; done: boolean; view: View}[] = [
    {label: "Add a calendar source", detail: "Bring in the workouts your coach prescribed.", done: state.sources.length > 0, view: "Sources"},
    {label: "Connect Garmin or COROS", detail: "Choose where your workouts will go.", done: state.connections.length > 0, view: "Connections"},
    {label: "Create your first sync", detail: "Link a source and destination, then review your workouts.", done: state.syncs.some(sync => state.sources.some(source => source.id === sync.source) && state.connections.some(connection => connection.id === sync.profile)), view: "Syncs"},
  ];
  const count = steps.filter(step => step.done).length;
  return <section className="setup-checklist" role="group" aria-label="Setup checklist">
    <button type="button" className="setup-dismiss" aria-label="Dismiss getting started" title="Dismiss getting started" disabled={busy} onClick={dismiss}><X size={18} aria-hidden="true" /></button>
    <details open={count < steps.length}>
      <summary>
        <div><p className="eyebrow">GETTING STARTED</p><h2>{count === steps.length ? "You’re all set" : "Let’s connect your workouts"}</h2></div>
        <span className="setup-count" aria-live="polite">{count} of {steps.length} complete <ChevronDown size={16} aria-hidden="true" /></span>
        <progress aria-label="Setup progress" value={count} max={steps.length} />
      </summary>
      <ol>{steps.map((step, index) => <li key={step.view} className={step.done ? "complete" : ""}>
        <span className="setup-step" aria-label={step.done ? "Completed" : `Step ${index + 1}`}>{step.done ? <Check size={16} aria-hidden="true" /> : index + 1}</span>
        <div>{step.done ? <s>{step.label}</s> : <button onClick={() => navigate(step.view)}>{step.label}<ArrowRight size={15} aria-hidden="true" /></button>}<p>{step.detail}</p></div>
      </li>)}</ol>
    </details>
  </section>;
}

export function App({ brand = "WorkoutBridge", multiuser = false, suggestedEmail = "", onLogout, request = defaultApi, view: externalView, onViewChange, showSetupChecklist = true, onDismissSetup }: { brand?: string; multiuser?: boolean; suggestedEmail?: string; onLogout?: () => void; request?: typeof defaultApi; view?: View; onViewChange?: (view: View) => void; showSetupChecklist?: boolean; onDismissSetup?: () => Promise<void> }) {
  const api = request;
  const [setupDismissed, setSetupDismissed] = useState(false);
  const [state, setState] = useState<State | null>(null);
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [localView, setLocalView] = useState<View>("Workouts");
  const view = externalView ?? localView;
  function setView(next: View) { setLocalView(next); onViewChange?.(next); }
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [active, setActive] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [expanded, setExpanded] = useState<number | null>(0);
  const [confirm, setConfirm] = useState(false);
  const [sourceForm, setSourceForm] = useState(false);
  const [syncForm, setSyncForm] = useState(false);
  const [garminForm, setGarminForm] = useState<string | null>(null);
  const [corosForm, setCorosForm] = useState<string | null>(null);
  const [autoConfirm, setAutoConfirm] = useState<Sync | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  async function load() {
    const value = await api("state");
    setState(value);
    setSignedIn(true);
    setActive((previous) => previous || value.syncs[0]?.id || "");
  }
  useEffect(() => {
    load().catch((e: Error) => {
      if (e.message === "Sign in required") setSignedIn(false);
      else setError(e.message);
    });
  }, []);
  async function perform(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (e) {
      const text = e instanceof Error ? e.message : "Operation failed";
      setError(text);
      if (text === "Sign in required") setSignedIn(false);
    } finally {
      setBusy(false);
    }
  }
  const rule = state?.syncs.find((s) => s.id === active);
  const plan = state?.plans.find((p) => p.id === active);
  const source = state?.sources.find((s) => s.id === rule?.source);
  const connection = state?.connections.find((c) => c.id === rule?.profile);
  function availableProfile(base: string) {
    const used = new Set(state?.connections.map(c => c.id));
    if (!used.has(base)) return base;
    let index = 2;
    while (used.has(`${base}-${index}`)) index++;
    return `${base}-${index}`;
  }
  const destinationName = connection?.provider === "COROS" ? "COROS" : "Garmin";
  const item = plan?.items[expanded ?? -1];
  const ready = plan?.items.filter((i) => !i.error).length || 0;
  function changeSync(value: string) {
    setActive(value);
    setSelected([]);
    setExpanded(0);
    setConfirm(false);
  }
  async function login(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    await perform(async () => {
      await api("login", { password: data.get("password") });
      form.reset();
      await load();
    });
  }
  const alert = error && (
    <div className="alert" role="alert">
      {error}
      <button
        title="Dismiss error"
        aria-label="Dismiss error"
        onClick={() => setError("")}
      >
        <X size={16} />
      </button>
    </div>
  );
  if (signedIn !== true)
    return (
      <main className="login">
        {busy && <Progress label="Signing in..." />}
        <div className="login-brand">
          <Route size={30} />
          <h1>{brand}</h1>
        </div>
        <span className="badge">Private instance</span>
        {alert}
        {signedIn === false ? (
          <form id="instance-login-form" method="post" onSubmit={login}>
            <h2>Welcome back</h2>
            <div className="form-field">
              <label htmlFor="instance-login-password">Access password</label>
              <input id="instance-login-password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </div>
            <button className="primary" disabled={busy}>
              Sign in {busy ? <LoaderCircle size={16} className="spin" /> : <ArrowRight size={16} />}
            </button>
          </form>
        ) : (
          error ? <p role="status">Connection unavailable</p> : <Progress label="Connecting..." />
        )}
        <p className="independence-disclaimer">{independenceDisclaimer}</p>
      </main>
    );
  return (
    <div className="shell">
      {busy && <Progress />}
      <aside className="sidebar">
        <a className="brand" href="/">
          <Route size={24} aria-hidden="true" />
          <strong>{brand}</strong>
        </a>
        <div className="workspace">
          <span className="avatar">WB</span>
          <div>
            Personal workspace<small>{multiuser ? "Your account" : "Private instance"}</small>
          </div>
          <ShieldCheck size={17} />
        </div>
        <nav aria-label="Main navigation">
          {tabs.map(({ name, icon: Icon }) => (
            <button
              key={name}
              className={view === name ? "active" : ""}
              onClick={() => setView(name)}
            >
              <Icon size={18} />
              {name}
              {name === "Workouts" && (
                <span className="nav-count">{plan?.items.length || 0}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="dot" />{" "}
          {state?.syncs.some((s) => s.automatic && !s.paused && !s.auto_blocked)
            ? (multiuser ? "Scheduled publishing" : "Hourly publishing")
            : "Manual publishing"}
          <button
            title="Sign out"
            aria-label="Sign out"
            onClick={() =>
              perform(async () => {
                await api("logout", {});
                setState(null);
                setSignedIn(false);
                onLogout?.();
              })
            }
          >
            <LogOut size={16} />
          </button>
        </div>
      </aside>
      <div className="main">
        <header>
          <span>
            Workspace <ChevronRight size={14} /> {view}
          </span>
          <span className="private">
            <ShieldCheck size={14} /> Private pilot
          </span>
        </header>
        <main className="content">
          {alert}
          {multiuser && state && showSetupChecklist && !setupDismissed && <SetupChecklist state={state} navigate={setView} busy={busy} dismiss={() => void perform(async () => { await onDismissSetup?.(); setSetupDismissed(true); })} />}
          {message && (
            <div className="success" role="status">
              <CheckCircle2 size={16} />
              {message}
            </div>
          )}
          <div className="page-heading">
            <div>
              <p className="eyebrow">CALENDAR TO WATCH</p>
              <h1>{view === "Workouts" ? "Upcoming workouts" : view}</h1>
            </div>
            {view === "Workouts" && (
              <button
                className="secondary"
                disabled={busy || !rule}
                onClick={() =>
                  perform(async () => {
                    await api(`syncs/${active}/preview`, {});
                    setSelected([]);
                    setExpanded(0);
                    await load();
                  })
                }
              >
                <RefreshCw size={16} className={busy ? "spin" : ""} />
                Refresh feed
              </button>
            )}
            {view === "Sources" && (
              <button className="primary" onClick={() => setSourceForm(true)}>
                <Plus size={16} />
                Add source
              </button>
            )}
            {view === "Connections" && (
              <div className="provider-actions" role="group" aria-label="Connect a destination">
                <button className="primary" onClick={() => setGarminForm(availableProfile("personal"))}><Plus size={16} /> {state?.connections.some(c => c.provider !== "COROS") ? "Connect another Garmin account" : "Connect Garmin"}</button>
                <button className="primary" onClick={() => setCorosForm(availableProfile("coros"))}><Plus size={16} /> {state?.connections.some(c => c.provider === "COROS") ? "Connect another COROS account" : "Connect COROS"}</button>
              </div>
            )}
            {view === "Syncs" && (
              <button
                className="primary"
                onClick={() => setSyncForm(true)}
                disabled={!state?.sources.length || !state.connections.length}
              >
                <Plus size={16} />
                Add sync
              </button>
            )}
          </div>
          {view === "Workouts" && (
            <>
              <div className="toolbar">
                <label className="select-label">
                  Sync
                  <select
                    aria-label="Active sync"
                    value={active}
                    onChange={(e) => changeSync(e.target.value)}
                  >
                    {state?.syncs.map((s) => (
                      <option key={s.id} value={s.id}>
                        {state.sources.find((a) => a.id === s.source)?.name} →{" "}
                        {s.profile}
                      </option>
                    ))}
                  </select>
                </label>
                <span className="muted">
                  <Clock3 size={14} />
                  {timestamp(rule?.last_preview || null)}
                </span>
              </div>
              {rule?.error && <p className="warning">{rule.error}</p>}
              {rule?.paused && <p className="warning">Sync paused</p>}
              {rule?.auto_blocked && (
                <p className="warning">
                  Automatic publishing stopped. Reconcile History before
                  resuming in Syncs.
                </p>
              )}
              <div className="metrics">
                <div>
                  <strong>{plan?.items.length || 0}</strong>
                  <span>Upcoming</span>
                </div>
                <div>
                  <strong>{ready}</strong>
                  <span>Ready to review</span>
                </div>
                <div>
                  <strong>{(plan?.items.length || 0) - ready}</strong>
                  <span>Needs attention</span>
                </div>
                <span className="period">Today + 14 days</span>
              </div>
              {!rule ? (
                <div className="empty">
                  <CalendarDays size={36} />
                  <h2>No syncs connected</h2>
                  <button
                    className="secondary"
                    onClick={() =>
                      setView(state?.sources.length ? "Syncs" : "Sources")
                    }
                  >
                    Manage {state?.sources.length ? "syncs" : "sources"}
                    <ArrowRight size={16} />
                  </button>
                </div>
              ) : !plan ? (
                <div className="empty">
                  <RefreshCw size={30} />
                  <h2>Awaiting first refresh</h2>
                </div>
              ) : plan.items.length === 0 ? (
                <div className="empty">
                  <CalendarDays size={32} />
                  <h2>No upcoming workouts</h2>
                </div>
              ) : (
                <div className="review-layout">
                  <section className="workout-list">
                    <div className="list-heading">
                      <span>WORKOUT</span>
                      <span>STATUS</span>
                    </div>
                    {plan.items.map((entry, i) => (
                      <div
                        className={`workout-row ${expanded === i ? "current" : ""}`}
                        key={i}
                      >
                        <input
                          type="checkbox"
                          aria-label={"Select " + entry.event.title}
                          checked={selected.includes(i)}
                          disabled={!!entry.error || busy || rule.paused}
                          onChange={(e) =>
                            setSelected(
                              e.target.checked
                                ? [...selected, i]
                                : selected.filter((v) => v !== i),
                            )
                          }
                        />
                        <button
                          className="workout-title"
                          onClick={() => setExpanded(i)}
                        >
                          <small>{dateLabel(entry.event.date)}</small>
                          <strong>{entry.event.title}</strong>
                        </button>
                        <span
                          className={`status ${entry.error ? "attention" : "ready"}`}
                        >
                          {entry.error ? "Review needed" : "Ready"}
                        </span>
                        <ChevronRight size={16} />
                      </div>
                    ))}
                    <div className="selection">
                      <span>{selected.length} selected</span>
                      <button
                        className="primary"
                        disabled={!selected.length || busy || rule.paused}
                        onClick={() => setConfirm(true)}
                      >
                        Review publication
                        <ArrowRight size={15} />
                      </button>
                    </div>
                  </section>
                  <section className="details" aria-label="Workout details">
                    {item && (
                      <>
                        <div className="detail-heading">
                          <span className="eyebrow">WORKOUT DETAILS</span>
                          <span className="badge">
                            {source?.format === "finalsurge"
                              ? "Final Surge"
                              : "Calendar"}
                          </span>
                        </div>
                        <h2>{item.event.title}</h2>
                        <p className="muted">{dateLabel(item.event.date)}</p>
                        {item.error ? (
                          <div className="warning">
                            <strong>Needs review</strong>
                            <p>{item.draft.unresolved.join("; ")}</p>
                          </div>
                        ) : (
                          <Steps steps={item.draft.steps} />
                        )}
                        <details className="original">
                          <summary>
                            Original prescription <ChevronDown size={14} />
                          </summary>
                          <pre>
                            {item.event.description || item.event.title}
                          </pre>
                        </details>
                      </>
                    )}
                  </section>
                </div>
              )}
            </>
          )}
          {view === "Sources" && (
            <section className="records">
              {!state?.sources.length && (
                <div className="empty">
                  <CalendarDays size={32} />
                  <h2>No calendar sources</h2>
                </div>
              )}
              {state?.sources.map((s) => (
                <article className="record" key={s.id}>
                  <div className="record-icon">
                    <CalendarDays size={22} />
                  </div>
                  <div>
                    <h2>{s.name}</h2>
                    <p>
                      {s.format === "finalsurge"
                        ? "Final Surge"
                        : "iCal calendar"}{" "}
                      · {s.timezone}
                    </p>
                  </div>
                  <span className="badge">
                    <ShieldCheck size={13} />
                    Private feed
                  </span>
                </article>
              ))}
            </section>
          )}
          {view === "Connections" && (
            <section className="records">
              {!state?.connections.length && (
                <div className="empty">
                  <Watch size={32} />
                  <h2>No accounts connected</h2>
                </div>
              )}
              {state?.connections.map((c) => (
                <article className="record" key={c.id}>
                  <div className="record-icon">
                    <Watch size={23} />
                  </div>
                  <div>
                    <h2>{c.id}</h2>
                    <p>
                      {c.provider} · Account {c.account}
                    </p>
                  </div>
                  <button
                    className="secondary"
                    onClick={() => c.provider === "COROS" ? setCorosForm(c.id) : setGarminForm(c.id)}
                  >
                    <RefreshCw size={16} /> Sign in again
                  </button>
                </article>
              ))}

            </section>
          )}
          {view === "Syncs" && (
            <section className="records">
              {!state?.syncs.length && (
                <div className="empty">
                  <Repeat2 size={32} />
                  <h2>No sync rules</h2>
                </div>
              )}
              {state?.syncs.map((s) => (
                <article className="record" key={s.id}>
                  <div className="record-icon">
                    <Repeat2 size={22} />
                  </div>
                  <div>
                    <h2>
                      {state.sources.find((a) => a.id === s.source)?.name}{" "}
                      <ArrowRight size={15} /> {s.profile}
                    </h2>
                    <p>
                      {s.paused ? "Paused" : multiuser ? "Scheduled refresh" : "Hourly refresh"} ·{" "}
                      {s.auto_blocked
                        ? "Publishing stopped: review required"
                        : s.automatic
                          ? "Automatic publishing"
                          : "Manual publishing"}
                    </p>
                    {s.last_publish && (
                      <p>Last published {timestamp(s.last_publish)}</p>
                    )}
                    {s.error && <p className="error-text">{s.error}</p>}
                    <label className="inline-check">
                      <input
                        type="checkbox"
                        aria-label={`Automatic publishing for ${s.profile}`}
                        checked={!!s.automatic && !s.auto_blocked}
                        disabled={busy}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setAcknowledged(false);
                            setAutoConfirm(s);
                          } else
                            perform(async () => {
                              await api(`syncs/${s.id}/automatic`, {
                                enabled: false,
                              });
                              await load();
                            });
                        }}
                      />
                      {multiuser ? "Automatic publishing" : "Publish hourly"}
                    </label>
                  </div>
                  <button
                    className="icon"
                    title={s.paused ? "Resume sync" : "Pause sync"}
                    aria-label={s.paused ? "Resume sync" : "Pause sync"}
                    disabled={busy}
                    onClick={() =>
                      perform(async () => {
                        await api(`syncs/${s.id}/pause`, { paused: !s.paused });
                        await load();
                      })
                    }
                  >
                    {s.paused ? <Play size={18} /> : <Pause size={18} />}
                  </button>
                </article>
              ))}
            </section>
          )}
          {view === "History" && (
            <section className="records">
              {!state?.history.length && (
                <div className="empty">
                  <History size={32} />
                  <h2>No activity yet</h2>
                </div>
              )}
              {[...(state?.history || [])].reverse().map((h) => (
                <article className="record" key={h.id}>
                  <div className="record-icon">
                    {h.status === "Feed check failed" || h.status === "Review required" ? (
                      <AlertTriangle size={22} />
                    ) : (
                      <CheckCircle2 size={22} />
                    )}
                  </div>
                  <div>
                    <h2>{h.status}</h2>
                    <p>
                      {timestamp(h.at)}
                      {h.upcoming_count !== undefined
                        ? ` · ${h.upcoming_count} upcoming workouts`
                        : h.status !== "Feed check failed"
                          ? ` · ${h.results.length} verified workouts`
                          : ""}
                    </p>
                    {h.results.map((r, i) => (
                      <p key={i}>
                        {r.date} · {r.title} · #{r.workout_id}
                      </p>
                    ))}
                  </div>
                </article>
              ))}
            </section>
          )}
        </main>
        <footer>
          <Route size={14} />
          <span>WorkoutBridge</span>
          <a href="https://github.com/ayn/workoutbridge" target="_blank" rel="noopener noreferrer">
            <Github size={14} aria-hidden="true" /> GitHub
          </a>
          <span className="footer-status">
            <span className="dot" />
            Private instance
          </span>
          <p className="independence-disclaimer">{independenceDisclaimer}</p>
        </footer>
      </div>
      {sourceForm && (
        <Modal title="Add calendar source" close={() => setSourceForm(false)}>
          <form id="calendar-source-form" method="post"
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              perform(async () => {
                await api("sources", Object.fromEntries(f));
                await load();
                setSourceForm(false);
              });
            }}
          >
            <div className="form-field">
              <label htmlFor="calendar-source-name">Name</label>
              <input autoComplete="off" data-1p-ignore id="calendar-source-name"
                name="name"
                maxLength={80}
                required
                placeholder="Training calendar"
              />
            </div>
            <div className="form-field">
              <label htmlFor="calendar-source-format">Calendar</label>
              <select id="calendar-source-format" name="format">
                <option value="finalsurge">Final Surge iCal</option>
                <option value="generic">iCal / ICS feed</option>
              </select>
            </div>
            <div className="form-field">
              <label htmlFor="calendar-source-url">Calendar link or iCal URL</label>
              <input data-1p-ignore id="calendar-source-url"
                name="url"
                aria-describedby="calendar-link-help"
                type="url"
                required
                autoComplete="off"
                placeholder="https://log.finalsurge.com/delivery/ical/…"
              />
            </div>
            <p id="calendar-link-help" className="field-help">Supported sources: Final Surge, Google Calendar and iCloud. Use a public iCloud subscription link or Google sharing link. For private Google calendars, use the Secret address in iCal format. Anyone with a public subscription link can read that calendar.</p>
            <div className="form-field">
              <label htmlFor="calendar-source-timezone">Timezone</label>
              <input autoComplete="off" data-1p-ignore id="calendar-source-timezone"
                name="timezone"
                defaultValue={Intl.DateTimeFormat().resolvedOptions().timeZone}
                required
              />
            </div>
            {alert}
            <button className="primary" disabled={busy}>
              Add source
              <Plus size={16} />
            </button>
          </form>
        </Modal>
      )}
      {syncForm && (
        <Modal title="Connect a sync" close={() => setSyncForm(false)}>
          <form id="sync-form" method="post"
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              perform(async () => {
                const result = await api("syncs", Object.fromEntries(f));
                await load();
                changeSync(result.id);
                setSyncForm(false);
                setView("Syncs");
                setAcknowledged(false);
                setAutoConfirm({
                  id: result.id,
                  source: String(f.get("source")),
                  profile: String(f.get("profile")),
                  last_preview: null,
                  error: null,
                });
              });
            }}
          >
            <div className="form-field">
              <label htmlFor="sync-source">Source</label>
              <select id="sync-source" name="source">
                {state?.sources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label htmlFor="sync-profile">Destination</label>
              <select id="sync-profile" name="profile">
                {state?.connections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.provider === "COROS" ? "COROS" : "Garmin"} - {c.id.charAt(0).toUpperCase() + c.id.slice(1)}
                  </option>
                ))}
              </select>
            </div>
            {alert}
            <button className="primary" disabled={busy}>
              Connect
              <Link2 size={16} />
            </button>
          </form>
        </Modal>
      )}
      {garminForm !== null && (
        <GarminForm
          suggestedEmail={suggestedEmail}
          profile={garminForm}
          close={() => setGarminForm(null)}
          complete={async () => {
            await load();
            setGarminForm(null);
            setMessage("Garmin connection saved. Choose its sync separately.");
          }}
        />
      )}
      {corosForm !== null && (
        <CorosForm profile={corosForm} close={() => setCorosForm(null)} complete={async () => {
          await load();
          setCorosForm(null);
          setMessage("COROS connection saved. Choose its sync separately.");
        }} />
      )}
      {autoConfirm && (
        <Modal title="Automatic publishing" close={() => !busy && setAutoConfirm(null)}>
          <p>
            {state?.sources.find((s) => s.id === autoConfirm.source)?.name} →{" "}
            <strong>{autoConfirm.profile}</strong>
          </p>
          <p>
            {state?.connections.find((c) => c.id === autoConfirm.profile)?.provider === "COROS" ? "COROS" : "Garmin"} account{" "}
            {
              state?.connections.find((c) => c.id === autoConfirm.profile)
                ?.account
            }
          </p>
          <p>
            Publish eligible workouts now, then {multiuser ? "on your account’s schedule" : "hourly"}. Paused syncs stay paused. Unresolved workouts stay in
            review. A failed or uncertain write stops automatic publishing.
          </p>
          {autoConfirm.auto_blocked && (
            <label className="inline-check">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(e) => setAcknowledged(e.target.checked)}
              />
              I have reconciled the previous publication in Garmin and History.
            </label>
          )}
          {alert}
          <button
            className="primary full"
            disabled={busy || (!!autoConfirm.auto_blocked && !acknowledged)}
            onClick={() =>
              perform(async () => {
                await api(`syncs/${autoConfirm.id}/automatic`, {
                  enabled: true,
                  account: state?.connections.find(
                    (c) => c.id === autoConfirm.profile,
                  )?.account,
                  acknowledge_review: acknowledged,
                });
                setAutoConfirm(null);
                await load();
              })
            }
          >
            {busy ? "Publishing..." : "Enable and publish now"}
            {busy && <LoaderCircle size={16} className="spin" aria-hidden="true" />}
          </button>
          <button className="full" disabled={busy} onClick={() => setAutoConfirm(null)}>
            Keep manual publishing
          </button>
        </Modal>
      )}
      {confirm && plan && (
        <Modal
          title="Confirm publication"
          close={() => !busy && setConfirm(false)}
        >
          <div className="destination">
            <Watch size={22} />
            <div>
              <strong>{connection?.provider || "Garmin Connect"} · {rule?.profile}</strong>
              <p>Account {plan.account}</p>
            </div>
          </div>
          <ul className="confirm-list">
            {selected.map((i) => (
              <li key={i}>
                <Check size={15} />
                {plan.items[i].event.title}
                <small>{dateLabel(plan.items[i].event.date)}</small>
              </li>
            ))}
          </ul>
          {alert}
          <button
            className="primary full"
            disabled={busy}
            onClick={() =>
              perform(async () => {
                await api(`syncs/${active}/publish`, {
                  hash: plan.hash,
                  selected,
                });
                setConfirm(false);
                setSelected([]);
                await load();
                setMessage("Publication verified in Garmin Connect.");
              })
            }
          >
            {busy ? "Publishing..." : `Publish to ${destinationName}`}
            {busy ? <LoaderCircle size={16} className="spin" aria-hidden="true" /> : <ArrowRight size={16} />}
          </button>
        </Modal>
      )}
    </div>
  );
}
type LoginJob = {
  id?: string;
  status: string;
  profile?: string;
  error?: string;
};

function CorosForm({ profile, close, complete }: { profile: string; close: () => void; complete: () => Promise<void> }) {
  const [job, setJob] = useState<{ id: string; login_url: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  async function request(path: string, body: object) {
    setBusy(true);
    setError("");
    try {
      const result = await api(path, body);
      if (result.status === "complete") await complete();
      else if (result.login_url) setJob(result);
      else setPending(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "COROS sign-in failed");
    } finally {
      setBusy(false);
    }
  }
  return <Modal title="Connect COROS" close={() => !busy && close()}>
    {job ? <div>
      <a className="coros-auth-link" href={job.login_url} target="_blank" rel="noopener noreferrer">Open COROS sign-in <ArrowRight size={16} /></a>
      {pending && <p role="status">Waiting for COROS authorization</p>}
      {error && <p role="alert">{error}</p>}
      <button className="primary full" disabled={busy} onClick={() => void request("coros/login/finish", { id: job.id })}>
        {busy ? "Connecting..." : "Finish connection"} {busy && <LoaderCircle size={16} className="spin" />}
      </button>
    </div> : <form id="coros-login-form" method="post" onSubmit={(e) => {
      e.preventDefault();
      void request("coros/login", Object.fromEntries(new FormData(e.currentTarget)));
    }}>
      <div className="form-field">
        <label htmlFor="coros-login-profile">Profile name</label>
        <input autoComplete="off" data-1p-ignore id="coros-login-profile" name="profile" defaultValue={profile} required pattern={"[A-Za-z0-9][A-Za-z0-9_\\-]{0,63}"} /></div>
      <div className="form-field">
        <label htmlFor="coros-login-region">Account region</label>
        <select id="coros-login-region" name="region" defaultValue="us"><option value="us">United States / Global</option><option value="eu">Europe</option><option value="cn">China</option></select></div>
      {error && <p role="alert">{error}</p>}
      <button className="primary" disabled={busy}>{busy ? "Connecting..." : "Continue to COROS"} {busy ? <LoaderCircle size={16} className="spin" /> : <ArrowRight size={16} />}</button>
    </form>}
  </Modal>;
}

function GarminForm({
  suggestedEmail,
  profile,
  close,
  complete,
}: {
  suggestedEmail: string;
  profile: string;
  close: () => void;
  complete: () => Promise<void>;
}) {
  const [job, setJob] = useState<LoginJob>({ status: "idle" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const completed = useRef(false);
  const emailEdited = useRef(false);
  useEffect(() => {
    let active = true;
    api("garmin/login")
      .then((value) => {
        if (active && ["signing_in", "mfa"].includes(value.status))
          setJob(value);
      })
      .catch(() => {
        if (active) setError("Unable to check Garmin login status");
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    if (job.status === "complete" && !completed.current) {
      completed.current = true;
      complete().catch(() =>
        setError("Connection saved; refresh Connections."),
      );
    }
    if (!["signing_in", "mfa"].includes(job.status)) return;
    let active = true;
    const timer = setTimeout(() => {
      api("garmin/login")
        .then((value) => {
          if (active) {
            if (value && ["idle", "failed", "cancelled", "signing_in", "mfa", "complete"].includes(value.status)) setJob(value);
            else { setJob({status: "failed"}); setError("Unexpected Garmin sign-in response. Please try again."); }
          }
        })
        .catch(() => {
          if (active) setError("Unable to check Garmin login status");
        });
    }, 6000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [job]);
  async function request(path: string, body: object) {
    setBusy(true);
    setError("");
    try {
      const result = await api(path, body);
      if (!result || !["idle", "failed", "cancelled", "signing_in", "mfa", "complete"].includes(result.status)) {
        setJob({status: "failed"});
        throw new Error("Unexpected Garmin sign-in response. Please try again.");
      }
      setJob(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }
  async function dismiss() {
    if (busy) return;
    if (job.id && ["signing_in", "mfa"].includes(job.status)) {
      try {
        await api("garmin/login/cancel", { id: job.id });
      } catch {
        setError(
          "Unable to cancel. The sign-in attempt expires after five minutes.",
        );
        return;
      }
    }
    close();
  }
  const connected = job.status === "complete";
  const statusTitle = connected ? "Garmin connected" : job.status === "mfa" ? "Verifying your code" : "Connecting to Garmin";
  const statusDetail = connected
    ? error ? "Your connection is saved. Close this dialog and refresh Connections." : "Refreshing your connections…"
    : "This may take a moment. If Garmin needs a verification code, we’ll ask for it here.";
  return (
    <Modal
      title="Connect Garmin"
      close={() => {
        void dismiss();
      }}
    >
      {(busy || job.status === "signing_in" || connected) && (
        <div className="connection-status" role="status" aria-label={statusTitle}>
          {connected ? <CheckCircle2 size={24} aria-hidden="true" /> : <LoaderCircle size={24} className="spin" aria-hidden="true" />}
          <div><strong>{statusTitle}</strong><p>{statusDetail}</p></div>
        </div>
      )}
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
      {job.error && (
        <p role="alert" className="error-text">
          {job.error}
        </p>
      )}
      {!busy && ["idle", "failed", "cancelled"].includes(job.status) && (
        <form id="garmin-login-form" method="post"
          onSubmit={(e) => {
            e.preventDefault();
            const form = e.currentTarget;
            const data = new FormData(form);
            const body = {
              profile: data.get("profile"),
              email: data.get("email"),
              password: data.get("password"),
            };
            form.reset();
            void request("garmin/login", body);
          }}
        >
          <p className="form-help">Your password isn’t stored. We save your account ID and session tokens for syncing.</p>
          <div className="form-field">
            <label htmlFor="garmin-login-profile">Profile name</label>
            <input autoComplete="off" data-1p-ignore id="garmin-login-profile"
              name="profile"
              defaultValue={profile}
              pattern={"[A-Za-z0-9][A-Za-z0-9_\\-]{0,63}"}
              required
            />
          </div>
          <div className="form-field">
            <label htmlFor="garmin-login-email">Garmin email</label>
            <input autoCapitalize="none" spellCheck={false} id="garmin-login-email"
              name="email"
              type="email"
              defaultValue={suggestedEmail}
              onChange={() => { emailEdited.current = true; }}
              onFocus={(e) => {
                if (!emailEdited.current && suggestedEmail && e.currentTarget.value === suggestedEmail) e.currentTarget.select();
              }}
              autoComplete="username"
              maxLength={254}
              required
            />
          </div>
          <div className="form-field">
            <label htmlFor="garmin-login-password">Garmin password</label>
            <input id="garmin-login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              maxLength={1024}
              required
            />
          </div>
          <button className="primary full" disabled={busy}>
            Sign in to Garmin
          </button>
        </form>
      )}
      {!busy && job.status === "mfa" && (
        <form id="garmin-mfa-form" method="post"
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            const code = data.get("code");
            e.currentTarget.reset();
            void request("garmin/login/mfa", { id: job.id, code });
          }}
        >
          <div className="form-field">
            <label htmlFor="garmin-mfa-code">Verification code</label>
            <input id="garmin-mfa-code"
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              required
            />
          </div>
          <button className="primary full" disabled={busy}>
            Verify code
          </button>
        </form>
      )}
    </Modal>
  );
}

function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
}) {
  const dialog = useRef<HTMLElement>(null);
  const onClose = useRef(close);
  onClose.current = close;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    const focusable = () =>
      Array.from(
        dialog.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input,select,[tabindex="0"]',
        ) || [],
      );
    focusable()[0]?.focus();
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose.current();
      if (e.key === "Tab") {
        const targets = focusable();
        const first = targets[0],
          last = targets.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
      previous?.focus();
    };
  }, []);
  return (
    <div className="overlay" onClick={(event) => {
      if (event.target === event.currentTarget) close();
    }}>
      <section
        ref={dialog}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-heading">
          <h2>{title}</h2>
          <button
            className="icon"
            aria-label="Close dialog"
            title="Close"
            onClick={close}
          >
            <X size={20} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}
