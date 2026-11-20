// What the page shows when the shell's own render throws. A page that throws while it renders
// goes blank, with nothing to say so: this says so, and offers a reload. oneberth's shell
// catches an application's error first, and the rest of the shell stays. The console is the
// one place this reports to. A class, since React has no hook for an error boundary.
import { Component, type ErrorInfo, type ReactNode } from "react";

import "./fallback.css";

interface Caught {
  failure: Error | null;
}

export class Fallback extends Component<{ children: ReactNode }, Caught> {
  override state: Caught = { failure: null };

  static getDerivedStateFromError(failure: unknown): Caught {
    return { failure: failure instanceof Error ? failure : new Error(String(failure)) };
  }

  override componentDidCatch(failure: Error, info: ErrorInfo): void {
    console.error("FA1's interface failed to render", failure, info.componentStack);
  }

  override render(): ReactNode {
    const { failure } = this.state;
    if (failure === null) return this.props.children;
    return (
      <main className="fa1-fallback">
        <h1 className="fa1-fallback-title">Something went wrong</h1>
        <p role="alert" className="fa1-fallback-failed">
          {failure.message}
        </p>
        <p>
          <button
            type="button"
            className="fa1-fallback-button"
            onClick={() => {
              location.reload();
            }}
          >
            Reload
          </button>
        </p>
      </main>
    );
  }
}
