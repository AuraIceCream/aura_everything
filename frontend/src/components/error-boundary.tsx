import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * A crash in one part of the tree must not blank the whole page.
 *
 * The CitationDrawer null-score crash demonstrated this: a single unguarded
 * field turned the entire app into a blank screen with no on-page signal,
 * recoverable only by reading the console. This boundary keeps the app
 * navigable and gives the user a way back, without hiding that something
 * broke.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("AURA-Bio: unhandled render error", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="app-crash">
          <h1>Something went wrong displaying this</h1>
          <p>{this.state.error.message}</p>
          <button type="button" onClick={() => { this.setState({ error: null }); window.location.assign("/"); }}>
            Back to start
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
