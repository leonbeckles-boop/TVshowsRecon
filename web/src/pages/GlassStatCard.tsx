import React from "react";

interface Props {
  label: string;
  value: number | string;
  icon?: any;
  sub?: string;
  glow?: boolean;
}

const GlassStatCard: React.FC<Props> = ({ label, value, icon: Icon, sub, glow }) => {
  return (
    <div className={`wn-stat-card ${glow ? "wn-stat-card-glow" : ""}`}>
      <div className="wn-stat-header">
        {Icon && (
          <div className="wn-stat-icon">
            <Icon size={18} />
          </div>
        )}

        <span className="wn-stat-label">{label}</span>
      </div>

      <div className="wn-stat-value">{value}</div>

      {sub && <div className="wn-stat-sub">{sub}</div>}
    </div>
  );
};

export default GlassStatCard;