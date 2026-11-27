export interface Piece { text: string; count: number }

// Split a segment's text into pieces by how many verified quote spans cover each character.
// Spans are absolute offsets in the policy text; the segment starts at `offset`.
export function highlightPieces(text: string, offset: number, spans: [number, number][]): Piece[] {
  const n = text.length;
  const delta = new Array<number>(n + 1).fill(0);
  for (const [s, e] of spans) {
    const a = Math.max(0, s - offset);
    const b = Math.min(n, e - offset);
    if (a < b) {
      delta[a] += 1;
      delta[b] -= 1;
    }
  }
  const pieces: Piece[] = [];
  let depth = 0;
  let start = 0;
  let current = 0;
  for (let i = 0; i < n; i++) {
    depth += delta[i];
    if (i === 0) {
      current = depth;
      continue;
    }
    if (depth !== current) {
      pieces.push({ text: text.slice(start, i), count: current });
      start = i;
      current = depth;
    }
  }
  if (n > 0) pieces.push({ text: text.slice(start), count: current });
  return pieces;
}
