import type { LiveDashboardMarket } from "../types/api";
import { MARKET_OPTIONS, marketDescription } from "../utils/markets";

type MarketTabsProps = {
  value: LiveDashboardMarket;
  onChange: (market: LiveDashboardMarket) => void;
  /** Accessible name for the tablist. */
  ariaLabel?: string;
  /** Optional short note under the tabs. */
  showDescription?: boolean;
  /** Disable clicks while a refetch is in flight. */
  disabled?: boolean;
  className?: string;
};

/** Single-market selector: never aggregates Match / 1° set / O/U KPIs. */
export function MarketTabs({
  value,
  onChange,
  ariaLabel = "Mercato",
  showDescription = true,
  disabled = false,
  className
}: MarketTabsProps) {
  return (
    <article className={`panel live-market-panel${className ? ` ${className}` : ""}`}>
      <div className="panel-header">
        <div>
          <h3>Mercato</h3>
          <p className="note">Un mercato alla volta: le metriche non vengono mischiate.</p>
        </div>
      </div>
      <div className="tab-list live-market-tabs" role="tablist" aria-label={ariaLabel}>
        {MARKET_OPTIONS.map((option) => (
          <button
            key={option.value}
            id={`market-tab-${option.value}`}
            type="button"
            role="tab"
            aria-selected={value === option.value}
            className={value === option.value ? "active" : undefined}
            disabled={disabled}
            onClick={() => {
              if (option.value !== value) onChange(option.value);
            }}
          >
            {option.label}
          </button>
        ))}
      </div>
      {showDescription ? (
        <p className="live-market-description">{marketDescription(value)}</p>
      ) : null}
    </article>
  );
}
