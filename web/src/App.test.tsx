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
