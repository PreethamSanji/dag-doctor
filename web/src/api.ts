import type { CardDetail, CardSummary, EvalReport, FeedbackRequest } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    // FastAPI puts the reason in `detail`; surface it rather than a bare status.
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const listCards = () =>
  request<{ cards: CardSummary[] }>("/api/cards").then((body) => body.cards);

export const getCard = (cardId: string) =>
  request<CardDetail>(`/api/cards/${encodeURIComponent(cardId)}`);

export const getLatestEval = () => request<EvalReport>("/api/eval/latest");

export const sendFeedback = (cardId: string, feedback: FeedbackRequest) =>
  request<{ case_id: string; root_cause: string; label: string }>(
    `/api/cards/${encodeURIComponent(cardId)}/feedback`,
    { method: "POST", body: JSON.stringify(feedback) },
  );
