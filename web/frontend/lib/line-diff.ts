/**
 * §11 S5 — a line diff, so a proposal can be read before it is accepted.
 *
 * The mind rewrites the whole buffer, so "what changed" is not in the answer —
 * it has to be computed. Standard LCS over lines: small buffers (a pattern is
 * a few hundred bytes), so the quadratic table is free and the result is the
 * minimal edit rather than a first-difference-onwards smear, which matters
 * when the mind moves one layer and leaves three alone.
 */

export type DiffOp = "same" | "add" | "del";

export interface DiffLine {
  op: DiffOp;
  text: string;
}

export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split("\n");
  const b = after.split("\n");

  // lcs[i][j] = length of the longest common subsequence of a[i:] and b[j:].
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0),
  );
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] =
        a[i] === b[j]
          ? lcs[i + 1][j + 1] + 1
          : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ op: "same", text: a[i] });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      out.push({ op: "del", text: a[i] });
      i++;
    } else {
      out.push({ op: "add", text: b[j] });
      j++;
    }
  }
  while (i < a.length) out.push({ op: "del", text: a[i++] });
  while (j < b.length) out.push({ op: "add", text: b[j++] });

  return out;
}

/** Whether anything actually changed — an empty diff is not worth showing. */
export function hasChanges(diff: DiffLine[]): boolean {
  return diff.some((l) => l.op !== "same");
}

/** Counts for a one-line summary: "+3 −1". */
export function diffCounts(diff: DiffLine[]): { added: number; removed: number } {
  return {
    added: diff.filter((l) => l.op === "add").length,
    removed: diff.filter((l) => l.op === "del").length,
  };
}
