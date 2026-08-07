import { Globe, Lock, RotateCw, ShieldCheck } from "lucide-react";
import type { AgentRun } from "../api/types";

interface BrowserFrameProps {
  run?: AgentRun;
  liveViewUrl?: string;
  taskName: string;
  connecting: boolean;
  error?: string;
  onRetry: () => void;
}

/**
 * Wraps the managed browser in familiar browser chrome.
 *
 * The address bar is deliberately read-only and shows the origin plus a redacted path:
 * the real page lives in a cloud browser, and query strings there can carry personal
 * details that should not be mirrored into this UI.
 */
export function BrowserFrame({ run, liveViewUrl, taskName, connecting, error, onRetry }: BrowserFrameProps) {
  const origin = run?.origin;
  const host = origin ? origin.replace(/^https?:\/\//, "") : undefined;
  const secure = origin?.startsWith("https://") ?? true;
  const tabLabel = run?.pageTitle ?? taskName;
  const working = run?.state === "running";

  return (
    <section aria-label="Browser" className="browser-frame">
      <div className="browser-frame__tabs">
        <span aria-hidden="true" className="browser-frame__lights">
          <i /><i /><i />
        </span>
        <div className={`browser-tab${working ? " browser-tab--working" : ""}`}>
          {working ? <span aria-hidden="true" className="spinner spinner--tab" /> : <Globe aria-hidden="true" size={16} />}
          <span className="browser-tab__label">{tabLabel}</span>
        </div>
        <span className="browser-frame__managed">
          <ShieldCheck aria-hidden="true" size={15} /> Managed
        </span>
      </div>

      <div className="browser-frame__bar">
        <button aria-label="Reload the page" className="browser-frame__nav" disabled title="The task controls this page" type="button">
          <RotateCw aria-hidden="true" size={17} />
        </button>
        <div className="browser-frame__address">
          {secure ? <Lock aria-hidden="true" size={14} /> : <Globe aria-hidden="true" size={14} />}
          {host ? (
            <span><strong>{host}</strong>{run?.redactedPath && run.redactedPath !== "/" ? run.redactedPath : ""}</span>
          ) : (
            <span className="browser-frame__address--empty">about:blank</span>
          )}
        </div>
        {working ? <span className="browser-frame__progress" aria-hidden="true" /> : null}
      </div>

      <div className="browser-frame__viewport">
        {liveViewUrl ? (
          <iframe
            allow="clipboard-read; clipboard-write; fullscreen"
            aria-label={`Live browser running ${taskName}`}
            className="fade-in"
            referrerPolicy="no-referrer"
            src={liveViewUrl}
            title="Live browser"
          />
        ) : connecting ? (
          <div className="browser-frame__placeholder" role="status">
            <span className="spinner spinner--large" />
            <h3>Opening a browser</h3>
            <p>Starting a private cloud browser for this task.</p>
          </div>
        ) : error ? (
          <div className="browser-frame__placeholder browser-frame__placeholder--error" role="alert">
            <h3>The browser could not open</h3>
            <p>{error}</p>
            <button className="button button--secondary" onClick={onRetry} type="button">
              <RotateCw aria-hidden="true" size={18} /> Try again
            </button>
          </div>
        ) : (
          <div className="browser-frame__placeholder">
            <Globe aria-hidden="true" size={38} />
            <h3>Nothing open yet</h3>
            <p>Pick a task and the browser will appear here.</p>
          </div>
        )}
      </div>
    </section>
  );
}
