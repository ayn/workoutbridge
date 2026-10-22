import {expect, test} from "vitest";
import {readApiResponse} from "./response";

test("HTML security blocks show recovery instructions without exposing the body", async () => {
  const response = new Response("<!DOCTYPE html><p>PRIVATE</p>", {status: 403});
  await expect(readApiResponse(response)).rejects.toThrow("Wait a minute");
});
test("HTML gateway failures give a temporary service error", async () => {
  await expect(readApiResponse(new Response("<!DOCTYPE html>PRIVATE", {status: 502}))).rejects.toThrow("temporarily unavailable");
});
test("an HTML success response is rejected clearly", async () => {
  await expect(readApiResponse(new Response("<!DOCTYPE html>PRIVATE"))).rejects.toThrow("unexpected response");
});
test("authentication and JSON permission failures preserve their meaning", async () => {
  await expect(readApiResponse(new Response("<!DOCTYPE html>", {status: 401}))).rejects.toThrow("Sign in required");
  await expect(readApiResponse(new Response(JSON.stringify({detail: "This action is not permitted"}), {status: 403}))).rejects.toThrow("This action is not permitted");
  expect(await readApiResponse(new Response(JSON.stringify({ok: true})))).toEqual({ok: true});
});
