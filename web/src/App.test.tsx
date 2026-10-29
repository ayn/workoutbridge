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

test("race entries explain why they are not published and do not need attention", async () => {
  const race = {
    event: {title: "Run: Coastal Half Marathon", description: "Race day", date: "2030-01-04"},
    draft: {steps: [], unresolved: []}, skipped: "race", error: "Not published — race",
  };
  const request = vi.fn().mockResolvedValue({...initial, plans: [{...initial.plans[0], items: [race]}]});
  render(<App request={request} />);
  expect(await screen.findByText("Not published — race")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", {name: "Select Run: Coastal Half Marathon"})).toBeDisabled();
  await userEvent.click(screen.getByRole("button", {name: /Coastal Half Marathon/}));
  expect(screen.getByText("Race events stay on your source calendar and are not sent as structured workouts.")).toBeInTheDocument();
  expect(screen.queryByText("Needs review")).not.toBeInTheDocument();
  expect(screen.getByText("Needs attention").previousElementSibling).toHaveTextContent("0");
});

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
  await userEvent.selectOptions(screen.getByRole("combobox", {name: "Unspecified distances"}), "km");
  await userEvent.type(
    screen.getByLabelText("Calendar link or iCal URL"),
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
  const sourceRequest = fetcher.mock.calls.find(([url]) => url === "/api/v1/sources")!;
  expect(JSON.parse(sourceRequest[1]!.body as string).distance_unit).toBe("km");
});

test("existing source distance defaults can be changed without replacing its feed", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify(initial)));
  render(<App />);
  await screen.findByText("Upcoming workouts");
  await userEvent.click(screen.getByRole("button", {name: "Sources"}));
  await userEvent.selectOptions(screen.getByLabelText(`Unspecified distances for ${initial.sources[0].name}`), "mi");
  await waitFor(() => expect(fetcher.mock.calls.some(([url, options]) => url === `/api/v1/sources/${initial.sources[0].id}/distance-unit` && JSON.parse(options!.body as string).unit === "mi")).toBe(true));
});

test("new sources can inherit the hosted account distance default", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify(initial)));
  render(<App defaultDistanceUnit="mi" />);
  await screen.findByText("Upcoming workouts");
  await userEvent.click(screen.getByRole("button", {name: "Sources"}));
  await userEvent.click(screen.getByRole("button", {name: "Add source"}));
  expect(screen.getByRole("combobox", {name: "Unspecified distances"})).toHaveValue("mi");
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
  const codeField = await screen.findByLabelText("Verification code");
  expect(codeField).toHaveAttribute("id", "garmin-mfa-code");
  expect(codeField.closest("label")).toBeNull();
  expect(codeField.closest("form")).toHaveAttribute("method", "post");
  await userEvent.type(
    codeField,
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


test.each(["Garmin", "COROS"])("%s profile name pattern works with modern Unicode validation", async provider => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(initial)));
  render(<App />);
  await userEvent.click(await screen.findByRole("button", {name: "Connections"}));
  await userEvent.click(screen.getByRole("button", {name: provider === "Garmin" ? "Connect another Garmin account" : "Connect COROS"}));
  const input = screen.getByLabelText("Profile name") as HTMLInputElement;
  const pattern = new RegExp(`^(?:${input.pattern})$`, "v");
  expect(pattern.test("synthetic-profile_2")).toBe(true);
  expect(pattern.test("a".repeat(64))).toBe(true);
  for (const invalid of ["", "-leading", "two words", "slash/name", "a".repeat(65)]) expect(pattern.test(invalid)).toBe(false);
});


test("pending Garmin sign-in leaves room between status requests", async () => {
  vi.useFakeTimers();
  try {
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async url => new Response(JSON.stringify(String(url).endsWith("/garmin/login") ? {status: "signing_in"} : initial)));
    await act(async () => { render(<App />); });
    await act(async () => { screen.getByRole("button", {name: "Connections"}).click(); });
    await act(async () => { screen.getByRole("button", {name: "Connect another Garmin account"}).click(); });
    const reads = () => fetcher.mock.calls.filter(([url]) => String(url).endsWith("/garmin/login")).length;
    expect(reads()).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(reads()).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(reads()).toBe(2);
  } finally { cleanup(); vi.useRealTimers(); }
});


test("workspace brand links to the app home", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({sources: [], connections: [], syncs: [], plans: [], history: []})));
  render(<App multiuser brand="Prescribed.FIT" />);
  expect(await screen.findByRole("link", {name: "Prescribed.FIT"})).toHaveAttribute("href", "/");
});


test("source form explains iCloud subscriptions without exposing other calendar events", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(initial)));
  render(<App />);
  await userEvent.click(await screen.findByRole("button", {name: "Sources"}));
  await userEvent.click(screen.getByRole("button", {name: "Add source"}));
  expect(screen.getByRole("option", {name: "iCal / ICS feed"})).toHaveValue("generic");
  expect(screen.getByLabelText("Calendar link or iCal URL")).toHaveAccessibleDescription(/iCloud.*subscription link/);
});


test.each([
  ["Connections", "Connect another Garmin account", "garmin-login-form", ["Profile name", "Garmin email", "Garmin password"]],
  ["Connections", "Connect COROS", "coros-login-form", ["Profile name", "Account region"]],
  ["Sources", "Add source", "calendar-source-form", ["Name", "Calendar", "Calendar link or iCal URL", "Timezone"]],
  ["Syncs", "Add sync", "sync-form", ["Source", "Destination"]],
])("%s / %s uses explicit labels and stable autofill identities", async (view, action, formId, labels) => {
  const request = vi.fn().mockImplementation(async path => path === "garmin/login" ? {status: "idle"} : initial);
  render(<App request={request} />);
  await userEvent.click(await screen.findByRole("button", {name: view as string}));
  await userEvent.click(screen.getByRole("button", {name: action as string}));
  const dialog = screen.getByRole("dialog");
  const form = dialog.querySelector("form")!;
  expect(form).toHaveAttribute("id", formId);
  expect(form).toHaveAttribute("method", "post");
  for (const label of labels as string[]) {
    const input = within(dialog).getByLabelText(label) as HTMLInputElement;
    expect(input.id).not.toBe("");
    expect(input.closest("label")).toBeNull();
    expect(dialog.querySelector(`label[for="${input.id}"]`)).not.toBeNull();
    if (input.tagName === "INPUT") {
      if (label === "Garmin email" || label === "Garmin password") {
        expect(input).not.toHaveAttribute("data-1p-ignore");
        expect(input).toHaveAttribute("autocomplete", label === "Garmin email" ? "username" : "current-password");
      } else expect(input).toHaveAttribute("data-1p-ignore");
      await userEvent.click(input);
      expect(input).toHaveFocus();
    }
  }
});


test("cycling sport is visible in workout list and detail before publishing", async () => {
  const state = {...initial, plans: [{...initial.plans[0], items: [{...initial.plans[0].items[0], event: {title: "Recovery session", date: "2030-01-02", description: "Ride 30 min easy", sport: "cycling"}}]}]};
  const request = vi.fn().mockResolvedValue(state);
  render(<App request={request} />);
  await screen.findByRole("heading", {name: "Recovery session"});
  expect(screen.getAllByText(/Cycling/).length).toBeGreaterThanOrEqual(2);
});


test("progression suggestion requires explicit approval of the displayed plan", async () => {
  const draft = {steps: [
    {kind: "warm_up", duration: 1609.344, unit: "meters"},
    {kind: "run", duration: null, unit: "lap_button", label: "easy"},
    {kind: "run", duration: 6437.376, unit: "meters", note: "Progression: gradually build toward the faster pace.", speed_min: 3.5, speed_max: 3.8},
    {kind: "cool_down", duration: 1609.344, unit: "meters"},
  ], unresolved: []};
  const unresolved = {event: {title: "Run: progression", date: "2030-04-03", description: "Original coach notes"}, draft: {steps: [], unresolved: ["Review progression"]}, error: "Review required", suggestion: {policy: "pace_range_lap", draft}};
  let approved = false;
  const request = vi.fn(async (path: string, body?: unknown) => {
    if (path.endsWith("/review-progression")) {approved = true; return {ok: true};}
    return {...initial, plans: [{...initial.plans[0], items: [approved ? {...unresolved, draft, error: undefined, suggestion: undefined} : unresolved]}]};
  });
  render(<App request={request} />);
  const approve = await screen.findByRole("button", {name: "Approve progression conversion"});
  expect(screen.getByText(/Added easy running until Lap/)).toBeInTheDocument();
  expect(screen.getByText(/gradually build toward the faster pace/)).toBeInTheDocument();
  expect(request.mock.calls.some(([path]) => path.endsWith("/review-progression"))).toBe(false);
  await userEvent.click(approve);
  expect(request).toHaveBeenCalledWith("syncs/r/review-progression", {hash: "review-hash", index: 0, choice: "pace_range_lap"});
  expect(await screen.findByText("Progression conversion approved")).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "Approve progression conversion"})).not.toBeInTheDocument();
  expect(screen.getByLabelText("Select Run: progression")).not.toBeDisabled();
});


test("workout details preserve mile, kilometer and track-meter display units", async () => {
  const steps = [
    {kind: "warm_up", duration: 2011.68, unit: "meters", display_unit: "mi"},
    {kind: "run", duration: null, unit: "lap_button"},
    {count: 3, steps: [{kind: "run", duration: 800, unit: "meters", display_unit: "km"}, {kind: "rest", duration: 60, unit: "seconds"}]},
    {kind: "run", duration: 400, unit: "meters", display_unit: "m"},
    {kind: "cool_down", duration: 1500, unit: "meters", display_unit: "km"},
    {kind: "run", duration: 600, unit: "meters"},
  ];
  render(<App request={vi.fn().mockResolvedValue({...initial, plans: [{...initial.plans[0], items: [{...initial.plans[0].items[0], draft: {steps, unresolved: []}}]}]})} />);
  await screen.findByText("1.25 mi");
  for (const text of ["Until Lap", "0.8 km", "1:00", "400 m", "1.5 km", "600 m"]) {
    expect(screen.getByText(text, {exact: true})).toBeInTheDocument();
  }
  expect(screen.queryByText("2011.68 m")).not.toBeInTheDocument();
});
