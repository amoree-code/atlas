export type TicketLinkCandidate = {
  id: string;
  projectId: string;
  state: string;
  updatedAt: string;
  keywords: string[];
  relationships: string[];
};

export type TicketLinkRequest = {
  projectId?: string;
  state?: string;
  keywords?: string[];
  relationshipIds?: string[];
  limit?: number;
};

export type TicketLinkResult = TicketLinkCandidate & {
  score: number;
  reasons: string[];
};

// Metadata-first ticket linking. No body reads, embeddings, or fuzzy guesses. A candidate
// only gains points from explicit metadata supplied by the caller, then stable recency.
export function rankTicketCandidates(
  candidates: TicketLinkCandidate[],
  request: TicketLinkRequest,
): TicketLinkResult[] {
  const wantedKeywords = new Set(
    (request.keywords ?? []).map((value) => value.toLowerCase()),
  );
  const wantedRelationships = new Set(request.relationshipIds ?? []);
  const now = Date.now();
  const scored = candidates.map((candidate) => {
    const reasons: string[] = [];
    let score = 0;
    if (request.projectId && candidate.projectId === request.projectId) {
      score += 100;
      reasons.push("project match");
    }
    if (request.state && candidate.state === request.state) {
      score += 30;
      reasons.push("state match");
    }
    const relationshipMatches = candidate.relationships.filter((id) =>
      wantedRelationships.has(id),
    );
    if (relationshipMatches.length) {
      score += 80 * relationshipMatches.length;
      reasons.push("explicit relationship match");
    }
    const keywordMatches = candidate.keywords.filter((keyword) =>
      wantedKeywords.has(keyword.toLowerCase()),
    );
    if (keywordMatches.length) {
      score += 10 * keywordMatches.length;
      reasons.push("keyword match");
    }
    const ageDays = Math.max(
      0,
      (now - Date.parse(candidate.updatedAt)) / 86_400_000,
    );
    if (Number.isFinite(ageDays)) {
      score += Math.max(0, 5 - Math.floor(ageDays / 7));
      reasons.push("recency considered");
    }
    return { ...candidate, score, reasons };
  });
  scored.sort(
    (left, right) =>
      right.score - left.score || left.id.localeCompare(right.id),
  );
  return scored.slice(0, Math.max(1, Math.min(20, request.limit ?? 20)));
}
