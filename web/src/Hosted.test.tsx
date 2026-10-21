import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Hosted, Bootstrap } from "./Hosted";

vi.mock("@simplewebauthn/browser", () => ({ startRegistration: vi.fn().mockResolvedValue({ id: "synthetic" }), startAuthentication: vi.fn().mockResolvedValue({ id: "synthetic" }) }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.history.replaceState({}, "", "/"); });

test("bootstrap selects multiuser mode from server configuration", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => new Response(JSON.stringify(String(url).endsWith("/config") ? { multiuser: true } : {}), { status: String(url).endsWith("/account") ? 401 : 200 }));
  render(<Bootstrap />);
  expect(await screen.findByRole("button", { name: "Sign in with passkey" })).toBeInTheDocument();
});

test("hosted signup requests verified email, not a password or email login", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => String(url).endsWith("/account") ? new Response("{}", { status: 401 }) : new Response(JSON.stringify({ ok: true, message: "Check your email" })));
  render(<Hosted />);
  await userEvent.click(await screen.findByRole("button", { name: "Create account" }));
  await userEvent.type(screen.getByLabelText("Email"), "athlete@example.invalid");
  await userEvent.click(screen.getByRole("button", { name: "Send verification email" }));
  expect(await screen.findByText("Check your email")).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/auth/signup"))).toBe(true);
  expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
});

test("verification is explicit and passkey enrollment is a separate action", async () => {
  window.history.replaceState({}, "", "/#verify=synthetic-token");
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => String(url).endsWith("/account") ? new Response("{}", { status: 401 }) : new Response("{}"));
  render(<Hosted />);
  await userEvent.click(await screen.findByRole("button", { name: "Verify email" }));
  expect(await screen.findByRole("button", { name: "Create passkey" })).toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/auth/register/finish"))).toBe(false);
  expect(window.location.hash).toBe("");
});

test("verification links work when opened in the existing sign-in tab", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 401 }));
  render(<Hosted />);
  await screen.findByRole("button", { name: "Sign in with passkey" });
  window.history.replaceState({}, "", "/#verify=new-verification");
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  expect(await screen.findByRole("button", { name: "Verify email" })).toBeInTheDocument();
});

test("account shows plan, schedule and invite without an admin tab for members", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => new Response(JSON.stringify(String(url).endsWith("/account") ? { email: "member@example.invalid", admin: false, passkeys: 1, entitlements: { plan: "free", interval: 10800 }, invite_url: "https://bridge.example/?invite=synthetic", schedule: { status: "waiting", next_due: 1900000000 } } : { sources: [], connections: [], syncs: [], plans: [], history: [] })));
  render(<Hosted />);
  await userEvent.click(await screen.findByRole("button", { name: "Account" }));
  expect(await screen.findByText("Every 3 hours")).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Every 15 minutes · Supporter" })).toBeDisabled();
  expect(screen.getByRole("option", { name: "Every 6 hours" })).not.toBeDisabled();
  expect(screen.getByDisplayValue("https://bridge.example/?invite=synthetic")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Admin" })).not.toBeInTheDocument();
});

test("administrator can inspect aggregate health and open a gift form", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => new Response(JSON.stringify(String(url).endsWith("/account") ? { admin: true, email: "owner@example.invalid", entitlements: { plan: "supporter", interval: 900 }, passkeys: 1, invite_url: "" } : String(url).endsWith("/admin") ? { totals: { users: 1, verified: 1, syncs: 2, blocked: 0 }, users: [{ id: "u", email: "member@example.invalid", verified: 1, entitlements: { plan: "free" }, usage: { syncs: 2 }, destinations: 1 }], grants: [], audit: [] } : { sources: [], connections: [], syncs: [], plans: [], history: [] })));
  render(<Hosted />);
  await userEvent.click(await screen.findByRole("button", { name: "Admin" }));
  expect(await screen.findByText("member@example.invalid")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Gift Supporter" }));
  expect(screen.getByLabelText("Reason")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Grant access" })).toBeInTheDocument();
});
