import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "./api";

function respond(status: number, body: unknown) {
  return vi.fn<typeof fetch>(
    async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("api.analyze", () => {
  it("sends the PDF as the raw body with its content type and the choices as query parameters", async () => {
    const fetchMock = respond(200, { role: "data engineer" });
    vi.stubGlobal("fetch", fetchMock);
    const pdf = new Blob(["%PDF-1.4"], { type: "application/pdf" });

    await api.analyze(pdf, { role: "data engineer", level: "junior", state: null, remote: false });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/analyze?role=data+engineer&level=junior&remote=false");
    expect(init?.method).toBe("POST");
    expect(init?.headers).toEqual({ "Content-Type": "application/pdf" });
    expect(init?.body).toBe(pdf);
  });

  it("turns the API's error body into an ApiError the page can show", async () => {
    vi.stubGlobal("fetch", respond(422, { detail: "No text found in this PDF.", code: "no_text" }));

    const error = await api.analyze(new Blob(), { role: "data engineer", level: "unknown", remote: false }).catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, code: "no_text", message: "No text found in this PDF." });
  });
});

describe("api errors", () => {
  it("explains a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));

    await expect(api.overview()).rejects.toMatchObject({ status: 0, code: "network" });
  });

  it("falls back to a generic message when the body isn't the API's", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>bad gateway</html>", { status: 502 })));

    await expect(api.insights()).rejects.toMatchObject({ status: 502, code: "error" });
  });

  it("leaves out empty filters", async () => {
    const fetchMock = respond(200, []);
    vi.stubGlobal("fetch", fetchMock);

    await api.salaries(null, "NY");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/salaries?state=NY");
  });
});
