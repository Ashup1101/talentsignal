// Typed client for the TalentSignal API (src/api/main.py). Types come from web/openapi.json
// (npm run gen:api), so a changed endpoint breaks the type-check, not the page.
import type { components } from "./api-types";

type Schemas = components["schemas"];
export type Options = Schemas["Options"];
export type Overview = Schemas["Overview"];
export type Analysis = Schemas["Analysis"];
export type MissingSkill = Schemas["MissingSkill"];
export type MatchingPosting = Schemas["MatchingPosting"];
export type SalaryBand = Schemas["SalaryBand"];
export type SkillDemand = Schemas["SkillDemand"];
export type Forecast = Schemas["Forecast"];
export type Insights = Schemas["Insights"];

// Empty in production: the static site calls /api/ on its own origin (nginx proxies it).
// `npm run dev` reads http://localhost:8000 from .env.development.
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

/** An error the API explained: HTTP status, a sentence for the user, a machine-readable code. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as { detail?: unknown; code?: unknown };
    if (typeof body.detail === "string") {
      return new ApiError(response.status, body.detail, typeof body.code === "string" ? body.code : "error");
    }
  } catch {
    // not JSON: fall through to a generic message
  }
  return new ApiError(response.status, "Something went wrong. Please try again in a minute.", "error");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError(0, "Can't reach the TalentSignal service. Check your connection and try again.", "network");
  }
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}

function query(params: Record<string, string | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export interface AnalyzeParams {
  role: string;
  level: string;
  state?: string | null;
  remote: boolean;
}

export const api = {
  options: () => request<Options>("/api/options"),
  overview: () => request<Overview>("/api/overview"),
  salaries: (level?: string | null, state?: string | null) =>
    request<SalaryBand[]>(`/api/salaries${query({ level, state })}`),
  skills: (role: string) => request<SkillDemand>(`/api/skills${query({ role })}`),
  forecast: (role: string, skill: string) => request<Forecast>(`/api/forecast${query({ role, skill })}`),
  insights: () => request<Insights>("/api/insights"),
  /** Sends the PDF as the raw request body: the API reads it in memory and never stores it. */
  analyze: (pdf: Blob, params: AnalyzeParams) =>
    request<Analysis>(`/api/analyze${query({ ...params })}`, {
      method: "POST",
      headers: { "Content-Type": "application/pdf" },
      body: pdf,
    }),
};
