import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Hosted, Bootstrap } from "./Hosted";

vi.mock("@simplewebauthn/browser", () => ({
  startRegistration: vi.fn().mockResolvedValue({ id: "synthetic" }),
  startAuthentication: vi.fn().mockResolvedValue({ id: "synthetic" }),
}));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

test("bootstrap selects multiuser mode from server configuration", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(
          String(url).endsWith("/config") ? { multiuser: true } : {},
        ),
        { status: String(url).endsWith("/account") ? 401 : 200 },
      ),
  );
  render(<Bootstrap />);
  expect(
    await screen.findByRole("button", { name: "Sign in with passkey" }),
  ).toBeInTheDocument();
});

test("hosted signup requests verified email, not a password or email login", async () => {
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (url) =>
      String(url).endsWith("/account")
        ? new Response("{}", { status: 401 })
        : new Response(
            JSON.stringify({ ok: true, message: "Check your email" }),
          ),
    );
  render(<Hosted />);
  await userEvent.click(
    await screen.findByRole("button", { name: "Create account" }),
  );
  await userEvent.type(
    screen.getByLabelText("Email"),
    "athlete@example.invalid",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Send verification email" }),
  );
  expect(await screen.findByText("Check your email")).toBeInTheDocument();
  expect(
    fetcher.mock.calls.some(([url]) => String(url).endsWith("/auth/signup")),
  ).toBe(true);
  expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
});

test("verification is explicit and passkey enrollment is a separate action", async () => {
  window.history.replaceState({}, "", "/#verify=synthetic-token");
  const fetcher = vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (url) =>
      String(url).endsWith("/account")
        ? new Response("{}", { status: 401 })
        : new Response("{}"),
    );
  render(<Hosted />);
  await userEvent.click(
    await screen.findByRole("button", { name: "Verify email" }),
  );
  expect(
    await screen.findByRole("button", { name: "Create passkey" }),
  ).toBeInTheDocument();
  expect(
    fetcher.mock.calls.some(([url]) =>
      String(url).endsWith("/auth/register/finish"),
    ),
  ).toBe(false);
  expect(window.location.hash).toBe("");
});

test("verification links work when opened in the existing sign-in tab", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response("{}", { status: 401 }),
  );
  render(<Hosted />);
  await screen.findByRole("button", { name: "Sign in with passkey" });
  window.history.replaceState({}, "", "/#verify=new-verification");
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  expect(
    await screen.findByRole("button", { name: "Verify email" }),
  ).toBeInTheDocument();
});

test("account shows plan, schedule and invite without an admin tab for members", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(
          String(url).endsWith("/account")
            ? {
                email: "member@example.invalid",
                admin: false,
                passkeys: 1,
                entitlements: { plan: "free", interval: 10800 },
                invite_url: "https://bridge.example/?invite=synthetic",
                schedule: { status: "waiting", next_due: 1900000000 },
              }
            : {
                sources: [],
                connections: [],
                syncs: [],
                plans: [],
                history: [],
              },
        ),
      ),
  );
  render(<Hosted />);
  await userEvent.click(await screen.findByRole("button", { name: "Account" }));
  expect(await screen.findByText("Every 3 hours")).toBeInTheDocument();
  expect(
    screen.getByRole("option", { name: "Every 15 minutes · Supporter" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("option", { name: "Every 6 hours" }),
  ).not.toBeDisabled();
  expect(
    screen.getByDisplayValue("https://bridge.example/?invite=synthetic"),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Admin" }),
  ).not.toBeInTheDocument();
});

test("administrator can inspect aggregate health and open a gift form", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(
          String(url).endsWith("/account")
            ? {
                admin: true,
                email: "owner@example.invalid",
                entitlements: { plan: "supporter", interval: 900 },
                passkeys: 1,
                invite_url: "",
              }
            : String(url).endsWith("/admin")
              ? {
                  totals: { users: 1, verified: 1, syncs: 2, blocked: 0 },
                  users: [
                    {
                      id: "u",
                      email: "member@example.invalid",
                      verified: 1,
                      entitlements: { plan: "free" },
                      usage: { syncs: 2 },
                      destinations: 1,
                    },
                  ],
                  grants: [],
                  audit: [],
                }
              : {
                  sources: [],
                  connections: [],
                  syncs: [],
                  plans: [],
                  history: [],
                },
        ),
      ),
  );
  render(<Hosted />);
  await userEvent.click(await screen.findByRole("button", { name: "Admin" }));
  expect(await screen.findByText("member@example.invalid")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Gift Supporter" }));
  expect(screen.getByLabelText("Reason")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Grant access" }),
  ).toBeInTheDocument();
});

test("account offers Stripe plans and billing management without requiring GitHub", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(
          String(url).endsWith("/account")
            ? {
                email: "member@example.invalid",
                passkeys: 1,
                entitlements: { plan: "supporter", interval: 900 },
                invite_url: "",
                billing: { enabled: true, connected: true, status: "none" },
              }
            : {
                sources: [],
                connections: [],
                syncs: [],
                plans: [],
                history: [],
              },
        ),
      ),
  );
  render(<Hosted />);
  await userEvent.click(await screen.findByRole("button", { name: "Account" }));
  expect(
    await screen.findByText(/No payment details needed for the 30-day trial/),
  ).toBeInTheDocument();
  await userEvent.selectOptions(
    screen.getByLabelText("Subscription plan"),
    "yearly",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Continue to Stripe" }),
  );
  expect(
    fetcher.mock.calls.some(
      ([url, options]) =>
        String(url).endsWith("/billing/checkout") &&
        JSON.parse(String(options?.body)).plan === "yearly",
    ),
  ).toBe(true);
  expect(
    screen.getByRole("button", { name: "Manage billing" }),
  ).toBeInTheDocument();
});

test("signing out after same-tab signup returns to passkey sign-in", async () => {
  let signed = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const path = String(url);
    if (path.endsWith("/auth/register/finish")) signed = true;
    if (path.endsWith("/logout")) signed = false;
    return new Response(
      JSON.stringify(
        path.endsWith("/account")
          ? {
              email: "member@example.invalid",
              entitlements: { plan: "supporter", interval: 900 },
            }
          : { sources: [], connections: [], syncs: [], plans: [], history: [] },
      ),
      { status: path.endsWith("/account") && !signed ? 401 : 200 },
    );
  });
  render(<Hosted />);
  await userEvent.click(
    await screen.findByRole("button", { name: "Create account" }),
  );
  window.history.replaceState({}, "", "/#verify=synthetic");
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  await userEvent.click(
    await screen.findByRole("button", { name: "Verify email" }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Create passkey" }),
  );
  await userEvent.click(
    (await screen.findAllByRole("button", { name: "Sign out" }))[0],
  );
  expect(
    await screen.findByRole("button", { name: "Sign in with passkey" }),
  ).toBeInTheDocument();
});

test("paid accounts change plans through Stripe rather than buying a duplicate", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(
          String(url).endsWith("/account")
            ? {
                email: "member@example.invalid",
                passkeys: 1,
                entitlements: { plan: "supporter", interval: 900 },
                invite_url: "",
                billing: {
                  enabled: true,
                  connected: true,
                  status: "active",
                  plan: "monthly",
                },
              }
            : {
                sources: [],
                connections: [],
                syncs: [],
                plans: [],
                history: [],
              },
        ),
      ),
  );
  render(<Hosted />);
  await userEvent.click(await screen.findByRole("button", { name: "Account" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Change plan" }),
  );
  expect(
    fetcher.mock.calls.some(([url]) =>
      String(url).endsWith("/billing/change-plan"),
    ),
  ).toBe(true);
  expect(
    screen.queryByRole("button", { name: "Continue to Stripe" }),
  ).not.toBeInTheDocument();
});

test("access badges distinguish paid and gifted support without a referral badge", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(
          String(url).endsWith("/account")
            ? {
                email: "member@example.invalid",
                passkeys: 1,
                entitlements: {
                  plan: "supporter",
                  interval: 900,
                  badges: ["paid", "gifted"],
                },
                invite_url: "",
              }
            : {
                sources: [],
                connections: [],
                syncs: [],
                plans: [],
                history: [],
              },
        ),
      ),
  );
  render(<Hosted />);
  await userEvent.click(await screen.findByRole("button", { name: "Account" }));
  expect(await screen.findByText("Paid")).toBeInTheDocument();
  expect(screen.getByText("Gifted")).toBeInTheDocument();
  expect(screen.queryByText("Referral")).not.toBeInTheDocument();
});

test("account shows referral progress and remaining reward allowance", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(
          String(url).endsWith("/account")
            ? {
                email: "member@example.invalid",
                passkeys: 1,
                entitlements: { plan: "supporter", interval: 900 },
                invite_url: "https://bridge.example/?invite=SYNTHETIC",
                referrals: {
                  invited: 2,
                  earned_months: 1,
                  remaining: 2,
                  cap: 3,
                  referrals: [
                    { number: 1, joined: 1900000000, status: "reward_applied" },
                    {
                      number: 2,
                      joined: 1900000000,
                      status: "sync_first_workout",
                    },
                  ],
                },
              }
            : {
                sources: [],
                connections: [],
                syncs: [],
                plans: [],
                history: [],
              },
        ),
      ),
  );
  render(<Hosted />);
  await userEvent.click(await screen.findByRole("button", { name: "Account" }));
  expect(
    await screen.findByText("1 month earned · 2 remaining"),
  ).toBeInTheDocument();
  expect(screen.getByText("Reward applied")).toBeInTheDocument();
  expect(
    screen.getByText("Waiting for first workout sync"),
  ).toBeInTheDocument();
});

test("admin sees queued referral billing adjustments rather than claiming Stripe applied them", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async (url) =>
      new Response(
        JSON.stringify(
          String(url).endsWith("/account")
            ? {
                admin: true,
                email: "owner@example.invalid",
                entitlements: { plan: "supporter", interval: 900 },
                passkeys: 1,
                invite_url: "",
              }
            : String(url).endsWith("/admin")
              ? {
                  totals: {},
                  users: [
                    {
                      id: "u",
                      email: "member@example.invalid",
                      verified: 1,
                      entitlements: { plan: "supporter", badges: ["paid"] },
                      usage: { syncs: 0 },
                      destinations: 1,
                    },
                  ],
                  grants: [],
                  audit: [],
                  billing_adjustments: [
                    {
                      id: "reward",
                      user: "u",
                      status: "pending",
                      desired_until: 1900000000,
                    },
                  ],
                }
              : {
                  sources: [],
                  connections: [],
                  syncs: [],
                  plans: [],
                  history: [],
                },
        ),
      ),
  );
  render(<Hosted />);
  await userEvent.click(await screen.findByRole("button", { name: "Admin" }));
  expect(
    await screen.findByRole("heading", {
      name: "Referral billing adjustments",
    }),
  ).toBeInTheDocument();
  expect(screen.getByText("Pending Stripe adjustment")).toBeInTheDocument();
});
