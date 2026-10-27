import type {
  CustomerProfile,
  DirectoryResponse,
  GameCase,
  GameReveal,
  MonitoringReport,
  ParadoxPair,
  PipelineRun,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      headers: { Accept: "application/json", ...init?.headers },
      ...init,
    });
  } catch {
    throw new Error(
      "Could not connect to the API. Check that FastAPI is running.",
    );
  }

  if (!response.ok) {
    const error = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new Error(error.detail || `Request failed (${response.status}).`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  directory: (
    parameters: {
      q?: string;
      limit?: number;
      offset?: number;
      sort?: string;
    },
    signal?: AbortSignal,
  ) =>
    request<DirectoryResponse>(
      `/explorer/directory?${new URLSearchParams(
        Object.entries(parameters)
          .filter(([, value]) => value !== undefined && value !== "")
          .map(([key, value]) => [key, String(value)]),
      )}`,
      { signal },
    ),
  customer: (key: string, signal?: AbortSignal) =>
    request<CustomerProfile>(`/explorer/dna/${encodeURIComponent(key)}`, {
      signal,
    }),
  paradoxes: (signal?: AbortSignal) =>
    request<ParadoxPair[]>("/explorer/paradoxes?limit=10", { signal }),
  newGame: (signal?: AbortSignal) =>
    request<GameCase>("/explorer/game", { signal }),
  guess: (day: number, key: string, probability: number) =>
    request<GameReveal>(
      `/explorer/game/${day}/${encodeURIComponent(key)}/guess`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ predicted_probability: probability }),
      },
    ),
  monitoring: (signal?: AbortSignal) =>
    request<MonitoringReport>("/monitoring/latest", { signal }),
  runs: (signal?: AbortSignal) =>
    request<PipelineRun[]>("/pipeline/runs?limit=8", { signal }),
};
