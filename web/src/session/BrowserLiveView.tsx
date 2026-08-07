import { ExternalLink, MonitorUp, RefreshCw, ShieldCheck } from "lucide-react";

interface BrowserLiveViewProps {
  liveViewUrl?: string;
  taskName?: string;
  loading: boolean;
  error?: string;
  onRetry: () => void;
}

export function BrowserLiveView({ liveViewUrl, taskName, loading, error, onRetry }: BrowserLiveViewProps) {
  return (
    <section className="browser-surface" aria-labelledby="browser-title">
      <header className="browser-toolbar">
        <div className="browser-toolbar__title">
          <span className="browser-dot" aria-hidden="true" />
          <div>
            <h2 id="browser-title">Browser</h2>
            <p>{taskName ?? "Active session"}</p>
          </div>
        </div>
        <span className="secure-session"><ShieldCheck aria-hidden="true" size={18} /> Managed session</span>
      </header>

      <div className="browser-viewport">
        {liveViewUrl ? (
          <iframe
            allow="clipboard-read; clipboard-write; fullscreen"
            aria-label="Interactive Browserbase browser"
            referrerPolicy="no-referrer"
            src={liveViewUrl}
            title="Interactive browser"
          />
        ) : null}
        {!liveViewUrl && loading ? (
          <div className="browser-placeholder" role="status">
            <span className="large-spinner" />
            <h3>Opening the browser</h3>
            <p>The managed session is connecting.</p>
          </div>
        ) : null}
        {!liveViewUrl && !loading && error ? (
          <div className="browser-placeholder browser-placeholder--error" role="alert">
            <MonitorUp aria-hidden="true" size={42} />
            <h3>Browser unavailable</h3>
            <p>{error}</p>
            <button className="button button--secondary" onClick={onRetry} type="button"><RefreshCw aria-hidden="true" size={20} /> Try again</button>
          </div>
        ) : null}
        {!liveViewUrl && !loading && !error ? (
          <div className="browser-placeholder">
            <ExternalLink aria-hidden="true" size={40} />
            <h3>No Live View yet</h3>
            <p>The provider has not returned an interactive browser URL.</p>
          </div>
        ) : null}
      </div>
    </section>
  );
}
