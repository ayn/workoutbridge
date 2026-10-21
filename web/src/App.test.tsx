import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
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
  expect(fetcher.mock.calls[1][0]).toBe("/api/login");
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
      fetcher.mock.calls.some(([url]) => url === "/api/syncs/r/publish"),
    ).toBe(true),
  );
  const request = fetcher.mock.calls.find(
    ([url]) => url === "/api/syncs/r/publish",
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
    expect(fetcher.mock.calls.some(([url]) => url === "/api/sources")).toBe(
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
    fetcher.mock.calls.some(([url]) => url === "/api/syncs/r/automatic"),
  ).toBe(false);
  await userEvent.click(
    screen.getByRole("button", { name: "Enable and publish now" }),
  );
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([url]) => url === "/api/syncs/r/automatic"),
    ).toBe(true),
  );
  const request = fetcher.mock.calls.find(
    ([url]) => url === "/api/syncs/r/automatic",
  )![1];
  expect(JSON.parse(request!.body as string)).toEqual({
    enabled: true,
    account: "123",
    acknowledge_review: false,
  });
});

test("new sync offers automatic publishing with an explicit manual choice", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) =>
    new Response(JSON.stringify(url === "/api/syncs" ? { id: "new" } : initial)),
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
      if (url === "/api/garmin/login" && options?.method === "POST")
        return new Response(
          JSON.stringify({ id: "job", status: "mfa", profile: "personal" }),
        );
      if (url === "/api/garmin/login/mfa")
        return new Response(
          JSON.stringify({
            id: "job",
            status: "complete",
            profile: "personal",
            account: "456",
          }),
        );
      if (url === "/api/garmin/login")
        return new Response(JSON.stringify({ status: "idle" }));
      return new Response(JSON.stringify(initial));
    });
  render(<App />);
  await screen.findByText("Upcoming workouts");
  await userEvent.click(screen.getByRole("button", { name: "Connections" }));
  await userEvent.click(screen.getByRole("button", { name: "Connect Garmin" }));
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
      fetcher.mock.calls.some(([url]) => url === "/api/garmin/login/mfa"),
    ).toBe(true),
  );
  expect(localStorage.length).toBe(0);
});
