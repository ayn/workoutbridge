/** Parse API replies without exposing gateway HTML or JSON parser internals. */
export async function readApiResponse(response: Response): Promise<any> {
  if (response.status === 401) throw new Error("Sign in required");
  let result: any;
  try { result = await response.json(); }
  catch {
    if (response.status === 403 || response.status === 429)
      throw new Error("A security check blocked the request. Wait a minute, then reload the page.");
    if (response.status >= 500)
      throw new Error("The service is temporarily unavailable. Please try again shortly.");
    throw new Error("The server returned an unexpected response. Reload the page and try again.");
  }
  if (!response.ok)
    throw new Error(typeof result?.detail === "string" ? result.detail : "Request could not be completed");
  if (result === null || typeof result !== "object")
    throw new Error("The server returned an unexpected response. Reload the page and try again.");
  return result;
}
