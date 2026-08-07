import { Activity, ChevronDown, RefreshCw } from "lucide-react";
import type { ReadinessSnapshot } from "../api/types";
import { StatusBadge } from "./StatusBadge";

interface ProviderStatusProps {
  readiness?: ReadinessSnapshot;
  loading: boolean;
  error?: string;
  onRefresh: () => void;
}

export function ProviderStatus({ readiness, loading, error, onRefresh }: ProviderStatusProps) {
  const label = loading
    ? "Checking services"
    : error
      ? "Service status unavailable"
      : readiness?.ready
        ? "Services ready"
        : "Service attention needed";
  const tone = loading ? "neutral" : error || !readiness?.ready ? "danger" : "success";

  return (
    <details className="provider-status">
      <summary>
        <StatusBadge label={label} tone={tone} busy={loading} />
        <ChevronDown aria-hidden="true" size={18} />
      </summary>
      <div className="provider-status__menu">
        <div className="provider-status__heading">
          <span><Activity aria-hidden="true" size={19} /> Live services</span>
          <button className="icon-button icon-button--small" type="button" onClick={onRefresh} aria-label="Refresh service status" title="Refresh service status">
            <RefreshCw aria-hidden="true" size={18} />
          </button>
        </div>
        {error ? <p className="inline-error" role="status">{error}</p> : null}
        {!error && readiness?.capabilities.length === 0 ? <p className="muted">No provider details were returned.</p> : null}
        {readiness?.capabilities.map((capability) => {
          const available = capability.configured && capability.reachable && capability.authorized;
          const configured = capability.configured && !capability.errorCode;
          const status = available ? "Ready" : configured ? "Configured" : capability.errorCode ?? "Unavailable";
          return (
            <div className="provider-row" key={capability.name}>
              <span className="provider-row__name" title={capability.detail}>{capability.name}</span>
              <span className={available || configured ? "provider-ok" : "provider-bad"}>{status}</span>
            </div>
          );
        })}
      </div>
    </details>
  );
}
