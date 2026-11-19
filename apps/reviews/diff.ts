// The side-by-side rows of a file's change: a line diff of the old version and the new one, by
// their longest common subsequence.

/** One row of the two columns. A side without a line is `null`. */
export interface Row {
  kind: "same" | "changed" | "removed" | "added";
  left: { number: number; text: string } | null;
  right: { number: number; text: string } | null;
}

/** Beyond this many cells, the table of the longest common subsequence is not built. */
const MOST_CELLS = 4_000_000;

export function linesOf(text: string | null): string[] {
  if (text === null || text === "") return [];
  const lines = text.split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  return lines;
}

type Step = { op: "same" | "removed" | "added"; text: string };

function steps(old: string[], next: string[]): Step[] {
  // The lines both versions start and end with need no table.
  let start = 0;
  while (start < old.length && start < next.length && old[start] === next[start]) start += 1;
  let end = 0;
  while (
    end < old.length - start &&
    end < next.length - start &&
    old[old.length - 1 - end] === next[next.length - 1 - end]
  ) {
    end += 1;
  }
  const a = old.slice(start, old.length - end);
  const b = next.slice(start, next.length - end);
  const middle: Step[] = [];
  if ((a.length + 1) * (b.length + 1) > MOST_CELLS) {
    for (const text of a) middle.push({ op: "removed", text });
    for (const text of b) middle.push({ op: "added", text });
  } else {
    // lengths[i][j]: the longest common subsequence of a[i:] and b[j:].
    const width = b.length + 1;
    const lengths = new Uint32Array((a.length + 1) * width);
    for (let i = a.length - 1; i >= 0; i -= 1) {
      for (let j = b.length - 1; j >= 0; j -= 1) {
        lengths[i * width + j] =
          a[i] === b[j]
            ? (lengths[(i + 1) * width + j + 1] ?? 0) + 1
            : Math.max(lengths[(i + 1) * width + j] ?? 0, lengths[i * width + j + 1] ?? 0);
      }
    }
    let i = 0;
    let j = 0;
    while (i < a.length && j < b.length) {
      if (a[i] === b[j]) {
        middle.push({ op: "same", text: a[i] ?? "" });
        i += 1;
        j += 1;
      } else if ((lengths[(i + 1) * width + j] ?? 0) >= (lengths[i * width + j + 1] ?? 0)) {
        middle.push({ op: "removed", text: a[i] ?? "" });
        i += 1;
      } else {
        middle.push({ op: "added", text: b[j] ?? "" });
        j += 1;
      }
    }
    for (; i < a.length; i += 1) middle.push({ op: "removed", text: a[i] ?? "" });
    for (; j < b.length; j += 1) middle.push({ op: "added", text: b[j] ?? "" });
  }
  const same = (text: string): Step => ({ op: "same", text });
  return [...old.slice(0, start).map(same), ...middle, ...old.slice(old.length - end).map(same)];
}

/** The rows of the change from `old` to `next`. A run of removed lines faces the run of added
 * lines after it, row by row. */
export function sideBySide(old: string | null, next: string): Row[] {
  const rows: Row[] = [];
  let left = 0;
  let right = 0;
  let removed: string[] = [];
  let added: string[] = [];
  const flush = () => {
    for (let k = 0; k < Math.max(removed.length, added.length); k += 1) {
      const gone = removed[k];
      const come = added[k];
      rows.push({
        kind:
          gone !== undefined && come !== undefined
            ? "changed"
            : gone !== undefined
              ? "removed"
              : "added",
        left: gone !== undefined ? { number: (left += 1), text: gone } : null,
        right: come !== undefined ? { number: (right += 1), text: come } : null,
      });
    }
    removed = [];
    added = [];
  };
  for (const step of steps(linesOf(old), linesOf(next))) {
    if (step.op === "removed") removed.push(step.text);
    else if (step.op === "added") added.push(step.text);
    else {
      flush();
      rows.push({
        kind: "same",
        left: { number: (left += 1), text: step.text },
        right: { number: (right += 1), text: step.text },
      });
    }
  }
  flush();
  return rows;
}
