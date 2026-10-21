import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowRight,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  History,
  Link2,
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
    results: { title: string; date: string; workout_id: string }[];
  }[];
};
type View = "Workouts" | "Sources" | "Connections" | "Syncs" | "History";
const tabs = [
  { name: "Workouts", icon: CalendarDays },
  { name: "Sources", icon: CalendarDays },
  { name: "Connections", icon: Watch },
  { name: "Syncs", icon: Repeat2 },
  { name: "History", icon: History },
] as const;

async function api(path: string, data?: unknown) {
  let response: Response;
  try {
    response = await fetch(
      "/api/" + path,
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
  if (response.status === 401) throw new Error("Sign in required");
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "Check the supplied values.",
    );
  return result;
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

export function App() {
  const [state, setState] = useState<State | null>(null);
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [view, setView] = useState<View>("Workouts");
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
        <div className="login-brand">
          <Route size={30} />
          <h1>WorkoutBridge</h1>
        </div>
        <span className="badge">Private instance</span>
        {alert}
        {signedIn === false ? (
          <form onSubmit={login}>
            <h2>Welcome back</h2>
            <label>
              Access password
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </label>
            <button className="primary" disabled={busy}>
              Sign in <ArrowRight size={16} />
            </button>
          </form>
        ) : (
          <p role="status">
            {error ? "Connection unavailable" : "Connecting…"}
          </p>
        )}
      </main>
    );
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <Route size={24} />
          <strong>WorkoutBridge</strong>
        </div>
        <div className="workspace">
          <span className="avatar">WB</span>
          <div>
            Personal workspace<small>Private instance</small>
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
            ? "Hourly publishing"
            : "Manual publishing"}
          <button
            title="Sign out"
            aria-label="Sign out"
            onClick={() =>
              perform(async () => {
                await api("logout", {});
                setState(null);
                setSignedIn(false);
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
              <button
                className="primary"
                onClick={() => setGarminForm("personal")}
              >
                <Plus size={16} /> Connect Garmin
              </button>
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
                        : "Google Calendar"}{" "}
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
                  <h2>No Garmin profiles connected</h2>
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
                    onClick={() => setGarminForm(c.id)}
                  >
                    <RefreshCw size={16} /> Sign in again
                  </button>
                </article>
              ))}
              <article className="record disabled">
                <div className="record-icon">
                  <Watch size={23} />
                </div>
                <div>
                  <h2>COROS</h2>
                  <p>Not available yet</p>
                </div>
              </article>
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
                      {s.paused ? "Paused" : "Hourly refresh"} ·{" "}
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
                      Publish hourly
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
                  <h2>No publications yet</h2>
                </div>
              )}
              {[...(state?.history || [])].reverse().map((h) => (
                <article className="record" key={h.id}>
                  <div className="record-icon">
                    <CheckCircle2 size={22} />
                  </div>
                  <div>
                    <h2>{h.status}</h2>
                    <p>
                      {timestamp(h.at)} · {h.results.length} verified workouts
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
          <span className="footer-status">
            <span className="dot" />
            Private instance
          </span>
        </footer>
      </div>
      {sourceForm && (
        <Modal title="Add calendar source" close={() => setSourceForm(false)}>
          <form
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
            <label>
              Name
              <input
                name="name"
                maxLength={80}
                required
                placeholder="Training calendar"
              />
            </label>
            <label>
              Calendar
              <select name="format">
                <option value="finalsurge">Final Surge</option>
                <option value="generic">Google Calendar</option>
              </select>
            </label>
            <label>
              Private feed URL
              <input
                name="url"
                type="url"
                required
                autoComplete="off"
                placeholder="https://log.finalsurge.com/delivery/ical/…"
              />
            </label>
            <label>
              Timezone
              <input
                name="timezone"
                defaultValue={Intl.DateTimeFormat().resolvedOptions().timeZone}
                required
              />
            </label>
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
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              perform(async () => {
                const result = await api("syncs", Object.fromEntries(f));
                await load();
                changeSync(result.id);
                setSyncForm(false);
                setView("Workouts");
              });
            }}
          >
            <label>
              Source
              <select name="source">
                {state?.sources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Destination
              <select name="profile">
                {state?.connections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.id} · Garmin {c.account}
                  </option>
                ))}
              </select>
            </label>
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
          profile={garminForm}
          close={() => setGarminForm(null)}
          complete={async () => {
            await load();
            setGarminForm(null);
            setMessage("Garmin connection saved. Choose its sync separately.");
          }}
        />
      )}
      {autoConfirm && (
        <Modal title="Automatic publishing" close={() => setAutoConfirm(null)}>
          <p>
            {state?.sources.find((s) => s.id === autoConfirm.source)?.name} →{" "}
            <strong>{autoConfirm.profile}</strong>
          </p>
          <p>
            Garmin account{" "}
            {
              state?.connections.find((c) => c.id === autoConfirm.profile)
                ?.account
            }
          </p>
          <p>
            Publish eligible workouts hourly. Unresolved workouts stay in
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
            Enable hourly publishing
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
              <strong>Garmin Connect · {rule?.profile}</strong>
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
            Publish to Garmin
            <ArrowRight size={16} />
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

function GarminForm({
  profile,
  close,
  complete,
}: {
  profile: string;
  close: () => void;
  complete: () => Promise<void>;
}) {
  const [job, setJob] = useState<LoginJob>({ status: "idle" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const completed = useRef(false);
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
          if (active) setJob(value);
        })
        .catch(() => {
          if (active) setError("Unable to check Garmin login status");
        });
    }, 1000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [job]);
  async function request(path: string, body: object) {
    setBusy(true);
    setError("");
    try {
      setJob(await api(path, body));
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
  return (
    <Modal
      title="Connect Garmin"
      close={() => {
        void dismiss();
      }}
    >
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
      {["idle", "failed", "cancelled"].includes(job.status) && (
        <form
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
          <label>
            Profile name
            <input
              name="profile"
              defaultValue={profile}
              pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
              required
            />
          </label>
          <label>
            Garmin email
            <input
              name="email"
              type="email"
              autoComplete="username"
              maxLength={254}
              required
            />
          </label>
          <label>
            Garmin password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              maxLength={1024}
              required
            />
          </label>
          <button className="primary full" disabled={busy}>
            Sign in to Garmin
          </button>
        </form>
      )}
      {job.status === "signing_in" && (
        <p role="status">Signing in to Garmin…</p>
      )}
      {job.status === "mfa" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const data = new FormData(e.currentTarget);
            const code = data.get("code");
            e.currentTarget.reset();
            void request("garmin/login/mfa", { id: job.id, code });
          }}
        >
          <label>
            Verification code
            <input
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              required
            />
          </label>
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
    <div className="overlay">
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
