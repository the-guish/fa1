// Reviews' root component, as oneberth's shell loads it (docs/specs/review-app.md, "Screens").
// A left panel with Pending and Closed, and a main panel with a list of changelists or one
// changelist's changes, file by file, side by side.
import { type AppProps, detailOf, getJson, hasRole, postJson, useSession } from "@oneberth/ui";
import { useCallback, useEffect, useMemo, useState } from "react";

import { type Row, sideBySide } from "./diff";
import "./reviews.css";

const API = "/reviews/api";
const APPROVER = "reviews/approver";

type State = "pending" | "closed";
type Status = "open" | "submitted" | "approved";

interface Listed {
  name: string;
  status: Status;
  created_at: string;
}

interface Changelist extends Listed {
  submitted_at: string | null;
  approved_at: string | null;
  files: { path: string; old: string | null; new: string }[];
}

/** What a route of the application shows. */
type Shown = { list: State } | { changelist: string };

function shownBy(route: string): Shown {
  const opened = /^\/changelists\/(.+)$/.exec(route);
  if (opened?.[1] !== undefined) return { changelist: decodeURIComponent(opened[1]) };
  return { list: route === "/closed" ? "closed" : "pending" };
}

function listOf(status: Status): State {
  return status === "approved" ? "closed" : "pending";
}

function when(stamp: string): string {
  return new Date(stamp).toLocaleString();
}

export default function ReviewsApp({ route, navigate }: AppProps) {
  const shown = shownBy(route);
  const current = "list" in shown ? shown.list : null;
  return (
    <main className="reviews-area">
      <nav className="reviews-side" aria-label="Changelists">
        {(["pending", "closed"] as const).map((state) => (
          <button
            key={state}
            type="button"
            className="reviews-entry"
            data-state={state}
            aria-current={current === state ? "page" : undefined}
            onClick={() => navigate(state === "pending" ? "" : "/closed")}
          >
            {state === "pending" ? "Pending" : "Closed"}
          </button>
        ))}
      </nav>
      <section className="reviews-main" aria-label="Reviews">
        {"list" in shown ? (
          <ChangelistList
            state={shown.list}
            onOpen={(name) => navigate(`/changelists/${encodeURIComponent(name)}`)}
          />
        ) : (
          <ChangelistView
            name={shown.changelist}
            onBack={(status) => navigate(listOf(status) === "closed" ? "/closed" : "")}
          />
        )}
      </section>
    </main>
  );
}

function ChangelistList({ state, onOpen }: { state: State; onOpen: (name: string) => void }) {
  const [items, setItems] = useState<Listed[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const aborted = new AbortController();
    setItems(null);
    setError(null);
    getJson<{ items: Listed[] }>(`${API}/changelists`, { state }, aborted.signal).then(
      (found) => setItems(found.items),
      (failure: unknown) => {
        if (!aborted.signal.aborted) setError(detailOf(failure));
      },
    );
    return () => aborted.abort();
  }, [state]);

  const title = state === "pending" ? "Pending" : "Closed";
  return (
    <>
      <header className="reviews-header">
        <h1>{title}</h1>
      </header>
      {error !== null ? <p className="reviews-error">{error}</p> : null}
      {items === null && error === null ? <p className="reviews-quiet">Loading…</p> : null}
      {items?.length === 0 ? (
        <p className="reviews-quiet">
          {state === "pending" ? "No changelist waits for review." : "No changelist is closed."}
        </p>
      ) : null}
      {items !== null && items.length > 0 ? (
        <table className="reviews-list">
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Created</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.name} data-changelist={item.name} onClick={() => onOpen(item.name)}>
                <td>
                  <button
                    type="button"
                    className="reviews-link"
                    onClick={(event) => {
                      event.stopPropagation();
                      onOpen(item.name);
                    }}
                  >
                    {item.name}
                  </button>
                </td>
                <td>{when(item.created_at)}</td>
                <td>
                  <span className="reviews-status" data-status={item.status}>
                    {item.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </>
  );
}

function ChangelistView({ name, onBack }: { name: string; onBack: (status: Status) => void }) {
  const session = useSession();
  const [changelist, setChangelist] = useState<Changelist | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);

  const load = useCallback(
    (signal?: AbortSignal) =>
      getJson<Changelist>(`${API}/changelists/${encodeURIComponent(name)}`, undefined, signal).then(
        setChangelist,
        (failure: unknown) => {
          if (!signal?.aborted) setError(detailOf(failure));
        },
      ),
    [name],
  );
  useEffect(() => {
    const aborted = new AbortController();
    setChangelist(null);
    setError(null);
    void load(aborted.signal);
    return () => aborted.abort();
  }, [load]);

  const approver = session.session !== null && hasRole(session.session, APPROVER);
  const approve = () => {
    setApproving(true);
    setError(null);
    postJson(`${API}/approve_changelist`, { changelist_name: name })
      .then(
        () => load(),
        (failure: unknown) => setError(detailOf(failure)),
      )
      .finally(() => setApproving(false));
  };

  return (
    <>
      <header className="reviews-header">
        <button
          type="button"
          className="reviews-button"
          data-action="back"
          onClick={() => onBack(changelist?.status ?? "open")}
        >
          ← Back
        </button>
        <h1>{name}</h1>
        {changelist !== null ? (
          <span className="reviews-status" data-status={changelist.status}>
            {changelist.status}
          </span>
        ) : null}
        <span className="reviews-grow" />
        {changelist?.status === "submitted" && approver ? (
          <button
            type="button"
            className="reviews-button reviews-approve"
            data-action="approve"
            disabled={approving}
            onClick={approve}
          >
            {approving ? "Approving…" : "Approve"}
          </button>
        ) : null}
      </header>
      {error !== null ? (
        <p className="reviews-error" role="alert">
          {error}
        </p>
      ) : null}
      {changelist === null && error === null ? <p className="reviews-quiet">Loading…</p> : null}
      {changelist !== null ? (
        <>
          <p className="reviews-quiet">
            Created {when(changelist.created_at)} · {changelist.files.length}{" "}
            {changelist.files.length === 1 ? "file" : "files"}
          </p>
          {changelist.files.map((file) => (
            <FilePanel key={file.path} path={file.path} old={file.old} next={file.new} />
          ))}
        </>
      ) : null}
    </>
  );
}

function FilePanel({ path, old, next }: { path: string; old: string | null; next: string }) {
  const rows = useMemo(() => sideBySide(old, next), [old, next]);
  const added = rows.filter((row) => row.right !== null && row.kind !== "same").length;
  const removed = rows.filter((row) => row.left !== null && row.kind !== "same").length;
  return (
    <details className="reviews-file" data-path={path} open>
      <summary>
        <span className="reviews-path">{path}</span>
        {old === null ? <span className="reviews-new">new file</span> : null}
        <span className="reviews-counts">
          <span className="reviews-plus">+{added}</span>{" "}
          <span className="reviews-minus">−{removed}</span>
        </span>
      </summary>
      <table className="reviews-diff">
        <colgroup>
          <col className="reviews-number" />
          <col />
          <col className="reviews-number" />
          <col />
        </colgroup>
        <tbody>
          {rows.map((row, index) => (
            <DiffRow key={index} row={row} />
          ))}
        </tbody>
      </table>
    </details>
  );
}

function DiffRow({ row }: { row: Row }) {
  const leftKind = row.left === null ? "empty" : row.kind === "same" ? "same" : "removed";
  const rightKind = row.right === null ? "empty" : row.kind === "same" ? "same" : "added";
  return (
    <tr>
      <td className="reviews-line-number" data-side={leftKind}>
        {row.left?.number}
      </td>
      <td className="reviews-line old" data-side={leftKind}>
        {row.left?.text}
      </td>
      <td className="reviews-line-number" data-side={rightKind}>
        {row.right?.number}
      </td>
      <td className="reviews-line new" data-side={rightKind}>
        {row.right?.text}
      </td>
    </tr>
  );
}
