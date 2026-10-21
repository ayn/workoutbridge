import { afterEach, expect, test, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("embedding can supply an asynchronous request transport", async () => {
  const fallback = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", {status: 401}));
  const request = vi.fn().mockResolvedValue(initial);
  render(<App request={request} />);
  await waitFor(() => expect(request).toHaveBeenCalledWith("state"));
  expect(fallback).not.toHaveBeenCalled();
});
const initial = {
  sources: [
    { id: "s", name: "Training", format: "finalsurge", timezone: "UTC" },
  ],
  connections: [{ id: "test", provider: "Garmin Connect", account: "123" }],
  syncs: [
    { id: "r", source: "s", profile: "test", last_preview: null, error: null },
  ],
  plans: [
    {
      id: "r",
      account: "123",
      hash: "review-hash",
      created: "2030-01-01T00:00:00Z",
      items: [
        {
          event: {
            title: "Run: 4 strides",
            description: "Original prescription",
            date: "2030-01-02",
          },
          draft: {
            steps: [
              {
                count: 4,
                skip_last_recovery: false,
                steps: [
                  {
                    kind: "run",
                    unit: "lap_button",
                    duration: null,
                    note: "stride",
                  },
                  {
                    kind: "rest",
                    unit: "lap_button",
                    duration: null,
                    note: "",
                  },
                ],
              },
            ],
            unresolved: [],
          },
        },
        {
          event: {
            title: "Unclear workout",
            description: "Ambiguous",
            date: "2030-01-03",
          },
          draft: { steps: [], unresolved: ["Ambiguous"] },
          error: "Review required",
        },
      ],
    },
  ],
  history: [],
};

test("hosted setup checklist guides an empty workspace to sources, connections and syncs", async () => {
  const empty = {...initial, sources: [], connections: [], syncs: [], plans: []};
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(empty)));
  render(<App multiuser />);
  const checklist = await screen.findByRole("group", {name: "Setup checklist"});
  expect(checklist).toHaveTextContent("0 of 3 complete");
  expect(within(checklist).getByRole("progressbar", {name: "Setup progress"})).toHaveAttribute("value", "0");
  await userEvent.click(within(checklist).getByRole("button", {name: "Add a calendar source"}));
  expect(screen.getByRole("heading", {name: "Sources"})).toBeInTheDocument();
  await userEvent.click(within(checklist).getByRole("button", {name: "Connect Garmin or COROS"}));
  expect(screen.getByRole("heading", {name: "Connections"})).toBeInTheDocument();
  await userEvent.click(within(checklist).getByRole("button", {name: "Create your first sync"}));
  expect(screen.getByRole("heading", {name: "Syncs"})).toBeInTheDocument();
});

test("setup checklist strikes through saved progress and recognizes complete setup", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({...initial, syncs: []})));
  const {unmount} = render(<App multiuser />);
  const checklist = await screen.findByRole("group", {name: "Setup checklist"});
  expect(checklist).toHaveTextContent("2 of 3 complete");
  expect(within(checklist).getByText("Add a calendar source").tagName).toBe("S");
  expect(within(checklist).getByText("Connect Garmin or COROS").tagName).toBe("S");
  expect(within(checklist).getByRole("button", {name: "Create your first sync"})).toBeEnabled();
  unmount();
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(initial)));
  render(<App multiuser />);
  const complete = await screen.findByRole("group", {name: "Setup checklist"});
  expect(complete).toHaveTextContent("3 of 3 complete");
  expect(complete).toHaveTextContent("You’re all set");
  expect(complete.querySelector("details")).not.toHaveAttribute("open");
  await userEvent.click(within(complete).getByText("You’re all set"));
  expect(complete.querySelectorAll("s")).toHaveLength(3);
});

test("DIY workspaces do not show the hosted setup checklist", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(initial)));
  render(<App />);
  await screen.findByText("Upcoming workouts");
  expect(screen.queryByRole("group", {name: "Setup checklist"})).not.toBeInTheDocument();
});

test("setup checklist can be dismissed without changing setup or navigating", async () => {
  const request = vi.fn().mockResolvedValue(initial);
  render(<App multiuser request={request} />);
  const checklist = await screen.findByRole("group", {name: "Setup checklist"});
  await userEvent.click(within(checklist).getByRole("button", {name: "Dismiss getting started"}));
  expect(screen.queryByRole("group", {name: "Setup checklist"})).not.toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "Upcoming workouts"})).toBeInTheDocument();
  expect(request.mock.calls.every(([, body]) => body === undefined)).toBe(true);
});

test("Garmin sign-in suggests a supplied email but stays editable and explains storage", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => new Response(JSON.stringify(String(url).endsWith("/garmin/login") ? { status: "idle" } : initial)));
  render(<App suggestedEmail="athlete@example.invalid" />);
  await userEvent.click(await screen.findByRole("button", { name: "Connections" }));
  await userEvent.click(screen.getByRole("button", { name: "Connect another Garmin account" }));
  const email = screen.getByLabelText("Garmin email");
  expect(email).toHaveValue("athlete@example.invalid");
  const select = vi.spyOn(HTMLInputElement.prototype, "select");
  fireEvent.focus(email);
  expect(select).toHaveBeenCalledOnce();
  await userEvent.clear(email);
  await userEvent.type(email, "different@example.invalid");
  expect(email).toHaveValue("different@example.invalid");
  const selections = select.mock.calls.length;
  fireEvent.blur(email);
  fireEvent.focus(email);
  expect(select.mock.calls.length).toBe(selections);
  expect(screen.getByLabelText("Garmin password")).toHaveValue("");
  expect(screen.getByText(/Your password isn.t stored/).closest("form")).not.toBeNull();
});

test("COROS browser sign-in saves a connection after authorization", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const path = String(url);
    if (path.endsWith("/coros/login")) return new Response(JSON.stringify({ id: "coros-job", status: "pending", login_url: "https://mcpus.coros.com/cli/login/synthetic" }));
    if (path.endsWith("/coros/login/finish")) return new Response(JSON.stringify({ status: "complete" }));
    return new Response(JSON.stringify(initial));
  });
  render(<App />);
  await screen.findByText("Upcoming workouts");
  await userEvent.click(screen.getByRole("button", { name: "Connections" }));
  await userEvent.click(screen.getByRole("button", { name: "Connect COROS" }));
  await userEvent.click(screen.getByRole("button", { name: "Continue to COROS" }));
  expect(await screen.findByRole("link", { name: "Open COROS sign-in" })).toHaveAttribute("href", "https://mcpus.coros.com/cli/login/synthetic");
  await userEvent.click(screen.getByRole("button", { name: "Finish connection" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/coros/login/finish"))).toBe(true);
});

test("COROS publication confirms the selected destination", async () => {
  const state = { ...initial, connections: [{ id: "test", provider: "COROS", account: "coros:us:synthetic" }] };
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(state)));
  render(<App />);
  await screen.findByText("Upcoming workouts");
  await userEvent.click(screen.getByLabelText("Select Run: 4 strides"));
  await userEvent.click(screen.getByRole("button", { name: "Review publication" }));
  expect(screen.getByRole("button", { name: "Publish to COROS" })).toBeInTheDocument();
  expect(screen.getByText("COROS · test")).toBeInTheDocument();
});

test.each([true, false])("publishing shows progress until request settles (success=%s)", async (success) => {
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) =>
    String(url).endsWith("/publish") ? pending : new Response(JSON.stringify(initial)),
  );
  render(<App />);
  await screen.findByText("Upcoming workouts");
  await userEvent.click(screen.getByLabelText("Select Run: 4 strides"));
  await userEvent.click(screen.getByRole("button", { name: "Review publication" }));
  await userEvent.click(screen.getByRole("button", { name: "Publish to Garmin" }));
  expect(screen.getByRole("button", { name: "Publishing..." })).toBeDisabled();
  expect(screen.getByRole("status", { name: "Working..." })).toBeInTheDocument();
  await act(async () => finish(new Response(JSON.stringify(success ? {} : { detail: "Publication failed" }), { status: success ? 200 : 409 })));
  await waitFor(() => expect(screen.queryByRole("status", { name: "Working..." })).not.toBeInTheDocument());
  if (!success) expect(screen.getByRole("button", { name: "Publish to Garmin" })).toBeEnabled();
});

test("feed refresh displays shared progress until complete", async () => {
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) =>
    String(url).endsWith("/preview") ? pending : new Response(JSON.stringify(initial)),
  );
  render(<App />);
  await screen.findByText("Upcoming workouts");
  await userEvent.click(screen.getByRole("button", { name: "Refresh feed" }));
  expect(screen.getByRole("status", { name: "Working..." })).toBeInTheDocument();
  await act(async () => finish(new Response("{}")));
  await waitFor(() => expect(screen.queryByRole("status", { name: "Working..." })).not.toBeInTheDocument());
});

test.each([true, false])("independence disclaimer is visible with signedIn=%s", async (signedIn) => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
    signedIn ? new Response(JSON.stringify(initial)) : new Response("{}", { status: 401 }),
  );
  render(<App />);
  if (signedIn) await screen.findByText("Upcoming workouts");
  else await screen.findByLabelText("Access password");
  expect(await screen.findByText(
    "WorkoutBridge is an independent project, not affiliated with, endorsed by, or sponsored by Garmin, Final Surge, COROS, Suunto, Google, Apple, or any other platform provider. All trademarks belong to their respective owners.",
  )).toBeInTheDocument();
});

test("history distinguishes an empty feed check from failed checks and publications", async () => {
  const history = [
    { id: "1", at: "2030-01-01T00:00:00Z", status: "Checked successfully", upcoming_count: 0, results: [] },
    { id: "2", at: "2030-01-01T01:00:00Z", status: "Feed check failed", results: [] },
  ];
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({ ...initial, history })));
  render(<App />);
  await screen.findByText("Upcoming workouts");
  await userEvent.click(screen.getByRole("button", { name: "History" }));
  expect(screen.getByText(/0 upcoming workouts/)).toBeInTheDocument();
  expect(screen.getByText("Feed check failed")).toBeInTheDocument();
  expect(screen.queryByText(/verified workouts/)).not.toBeInTheDocument();
});

test("sign in does not store credentials in browser storage", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response("{}", { status: 401 }))
    .mockResolvedValueOnce(new Response("{}"))
    .mockResolvedValue(new Response(JSON.stringify(initial)));
  render(<App />);
  await userEvent.type(
    await screen.findByLabelText("Access password"),
    "synthetic",
  );
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await screen.findByText("Upcoming workouts");
  expect(fetcher.mock.calls[1][0]).toBe("/api/v1/login");
  expect(localStorage.length).toBe(0);
});

test("footer keeps voluntary dependency acknowledgments in the README", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async () => new Response(JSON.stringify(initial)),
  );
  render(<App />);
  await screen.findByText("Upcoming workouts");
  expect(screen.queryByRole("link", { name: "python-garminconnect" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Credits" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "GitHub" })).toHaveAttribute(
    "href", "https://github.com/ayn/workoutbridge",
  );
});

test("review shows native repeats and requires confirmation before publishing", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async () => new Response(JSON.stringify(initial)));
  render(<App />);
  await screen.findByText("Upcoming workouts");
  expect(screen.getByLabelText("Select Unclear workout")).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: /Run: 4 strides/ }));
  expect(screen.getByText("stride")).toBeInTheDocument();
  expect(screen.getAllByText("Until Lap").length).toBe(2);
  await userEvent.click(screen.getByLabelText("Select Run: 4 strides"));
  await userEvent.click(
    screen.getByRole("button", { name: "Review publication" }),
  );
  expect(fetcher.mock.calls.length).toBe(1);
  await userEvent.click(
    screen.getByRole("button", { name: "Publish to Garmin" }),
  );
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) => url === "/api/v1/syncs/r/publish"),
    ).toBe(true),
  );
  const request = fetcher.mock.calls.find(
    ([url]) => url === "/api/v1/syncs/r/publish",
  )![1];
  expect(JSON.parse(request!.body as string)).toEqual({
    hash: "review-hash",
    selected: [0],
  });
});

test("network failure is visible and never triggers a publish retry", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(
    new Error("Network unavailable"),
  );
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Unable to connect",
  );
  expect(
    screen.queryByRole("button", { name: "Publish to Garmin" }),
  ).not.toBeInTheDocument();
});

test("calendar source dialog receives focus and submits a private URL", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async () => new Response(JSON.stringify(initial)));
  render(<App />);
  await screen.findByText("Upcoming workouts");
  await userEvent.click(screen.getByRole("button", { name: "Sources" }));
  await userEvent.click(screen.getByRole("button", { name: "Add source" }));
  expect(screen.getByRole("button", { name: "Close dialog" })).toHaveFocus();
  await userEvent.type(screen.getByLabelText("Name"), "Example feed");
  await userEvent.type(
    screen.getByLabelText("Private feed URL"),
    "https://log.finalsurge.com/delivery/ical/EXAMPLE",
  );
  await userEvent.click(
    screen.getAllByRole("button", { name: "Add source" }).at(-1)!,
  );
  await waitFor(() =>
    expect(fetcher.mock.calls.some(([url]) => url === "/api/v1/sources")).toBe(
      true,
    ),
  );
});

test("hourly publishing requires destination confirmation", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async () => new Response(JSON.stringify(initial)));
  render(<App />);
  await screen.findByText("Upcoming workouts");
  await userEvent.click(screen.getByRole("button", { name: "Syncs" }));
  await userEvent.click(screen.getByLabelText("Automatic publishing for test"));
  expect(
    fetcher.mock.calls.some(([url]) => url === "/api/v1/syncs/r/automatic"),
  ).toBe(false);
  await userEvent.click(
    screen.getByRole("button", { name: "Enable and publish now" }),
  );
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) => url === "/api/v1/syncs/r/automatic"),
    ).toBe(true),
  );
  const request = fetcher.mock.calls.find(
    ([url]) => url === "/api/v1/syncs/r/automatic",
  )![1];
  expect(JSON.parse(request!.body as string)).toEqual({
    enabled: true,
    account: "123",
    acknowledge_review: false,
  });
});

test("dialog dismisses on backdrop taps but not inside taps", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify(initial)));
  render(<App />);
  await screen.findByText("Upcoming workouts");
  await userEvent.click(screen.getByRole("button", { name: "Syncs" }));
  await userEvent.click(screen.getByLabelText("Automatic publishing for test"));
  const dialog = screen.getByRole("dialog");
  await userEvent.click(screen.getByText("Garmin account 123"));
  expect(dialog).toBeInTheDocument();
  await userEvent.click(dialog.parentElement!);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("new sync offers automatic publishing with an explicit manual choice", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) =>
    new Response(JSON.stringify(url === "/api/v1/syncs" ? { id: "new" } : initial)),
  );
  render(<App />);
  await screen.findByText("Upcoming workouts");
  await userEvent.click(screen.getByRole("button", { name: "Syncs" }));
  await userEvent.click(screen.getByRole("button", { name: /Add sync/ }));
  await userEvent.click(screen.getByRole("button", { name: "Connect" }));
  expect(await screen.findByRole("button", { name: "Enable and publish now" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Keep manual publishing" }));
  expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/automatic"))).toBe(false);
});

test("Garmin web sign-in clears credentials and accepts requested MFA", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (url, options) => {
      if (url === "/api/v1/garmin/login" && options?.method === "POST")
        return new Response(
          JSON.stringify({ id: "job", status: "mfa", profile: "personal" }),
        );
      if (url === "/api/v1/garmin/login/mfa")
        return new Response(
          JSON.stringify({
            id: "job",
            status: "complete",
            profile: "personal",
            account: "456",
          }),
        );
      if (url === "/api/v1/garmin/login")
        return new Response(JSON.stringify({ status: "idle" }));
      return new Response(JSON.stringify(initial));
    });
  render(<App />);
  await screen.findByText("Upcoming workouts");
  await userEvent.click(screen.getByRole("button", { name: "Connections" }));
  await userEvent.click(screen.getByRole("button", { name: "Connect another Garmin account" }));
  await userEvent.type(
    await screen.findByLabelText("Garmin email"),
    "example@example.invalid",
  );
  await userEvent.type(
    screen.getByLabelText("Garmin password"),
    "synthetic-password",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Sign in to Garmin" }),
  );
  await userEvent.type(
    await screen.findByLabelText("Verification code"),
    "123456",
  );
  expect(
    screen.queryByDisplayValue("synthetic-password"),
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Verify code" }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) => url === "/api/v1/garmin/login/mfa"),
    ).toBe(true),
  );
  expect(localStorage.length).toBe(0);
});


test("sync destinations show the actual provider and stay on Syncs after creation", async () => {
  const state = {...initial, connections: [{id: "coros", provider: "COROS", account: "synthetic-coros"}]};
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async url => new Response(JSON.stringify(String(url).endsWith("/syncs") ? {id: "new-sync"} : state)));
  render(<App multiuser />);
  await userEvent.click(await screen.findByRole("button", {name: "Syncs"}));
  await userEvent.click(screen.getByRole("button", {name: "Add sync"}));
  expect(screen.getByRole("option", {name: "COROS - Coros"})).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", {name: "Connect"}));
  await screen.findByRole("button", {name: "Keep manual publishing"});
  expect(screen.getByText("COROS account synthetic-coros")).toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "Syncs"})).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => String(url).includes("/automatic"))).toBe(false);
});

test("Garmin completion stays visible while the connection list refreshes", async () => {
  let reads = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url, options) => {
    if (String(url).endsWith("/garmin/login")) return new Response(JSON.stringify(
      options?.method === "POST" ? {status: "complete", profile: "personal"} : {status: "idle"}
    ));
    if (String(url).endsWith("/state") && reads++ > 0) return new Promise<Response>(() => {});
    return new Response(JSON.stringify(initial));
  });
  render(<App />);
  await userEvent.click(await screen.findByRole("button", {name: "Connections"}));
  await userEvent.click(screen.getByRole("button", {name: "Connect another Garmin account"}));
  await userEvent.type(screen.getByLabelText("Garmin email"), "member@example.invalid");
  await userEvent.type(screen.getByLabelText("Garmin password"), "synthetic-password");
  await userEvent.click(screen.getByRole("button", {name: "Sign in to Garmin"}));
  const status = await screen.findByRole("status", {name: "Garmin connected"});
  expect(status).toHaveTextContent("Refreshing your connections");
  expect(screen.queryByDisplayValue("synthetic-password")).not.toBeInTheDocument();
});

test("Garmin and COROS connect actions are peers in one provider group", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(initial)));
  render(<App />);
  await userEvent.click(await screen.findByRole("button", {name: "Connections"}));
  const group = screen.getByRole("group", {name: "Connect a destination"});
  expect(within(group).getByRole("button", {name: "Connect another Garmin account"})).toHaveClass("primary");
  expect(within(group).getByRole("button", {name: "Connect COROS"})).toHaveClass("primary");
  expect(screen.getAllByRole("button", {name: "Connect COROS"})).toHaveLength(1);
});

test("embedding can control workspace navigation", async () => {
  const change = vi.fn();
  const request = vi.fn().mockResolvedValue(initial);
  const {rerender} = render(<App request={request} view="Connections" onViewChange={change} />);
  await screen.findByRole("button", {name: "Connect another Garmin account"});
  await userEvent.click(screen.getByRole("button", {name: "Sources"}));
  expect(change).toHaveBeenCalledWith("Sources");
  rerender(<App request={request} view="History" onViewChange={change} />);
  expect(await screen.findByRole("heading", {name: "History"})).toBeInTheDocument();
});

test("Garmin unexpected responses retain a usable form and visible error", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url, options) => new Response(JSON.stringify(String(url).endsWith("/garmin/login") ? options?.method === "POST" ? {status: "unexpected"} : {status: "idle"} : initial)));
  render(<App />);
  await userEvent.click(await screen.findByRole("button", {name: "Connections"}));
  await userEvent.click(screen.getByRole("button", {name: "Connect another Garmin account"}));
  await userEvent.type(screen.getByLabelText("Garmin email"), "member@example.invalid");
  await userEvent.type(screen.getByLabelText("Garmin password"), "synthetic-password");
  await userEvent.click(screen.getByRole("button", {name: "Sign in to Garmin"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Unexpected Garmin sign-in response");
  expect(screen.getByLabelText("Garmin email")).toBeInTheDocument();
});


test("connected providers offer another account with an unused profile name", async () => {
  const state = {...initial, connections: [{id: "personal", provider: "Garmin Connect", account: "synthetic-garmin"}, {id: "coros", provider: "COROS", account: "synthetic-coros"}]};
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(state)));
  render(<App />);
  await userEvent.click(await screen.findByRole("button", {name: "Connections"}));
  expect(screen.getByRole("button", {name: "Connect another Garmin account"})).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", {name: "Connect another COROS account"}));
  expect(screen.getByLabelText("Profile name")).toHaveValue("coros-2");
});


test("setup dismissal waits for persistence and remains available after failure", async () => {
  const persist = vi.fn().mockRejectedValueOnce(new Error("Could not save preference" )).mockResolvedValueOnce(undefined);
  const request = vi.fn().mockResolvedValue(initial);
  render(<App multiuser request={request} onDismissSetup={persist} />);
  await userEvent.click(await screen.findByRole("button", {name: "Dismiss getting started"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not save preference");
  expect(screen.getByRole("group", {name: "Setup checklist"})).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", {name: "Dismiss getting started"}));
  await waitFor(() => expect(screen.queryByRole("group", {name: "Setup checklist"})).not.toBeInTheDocument());
  expect(persist).toHaveBeenCalledTimes(2);
});
