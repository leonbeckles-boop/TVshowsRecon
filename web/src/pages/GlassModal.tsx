import React from "react";

interface GlassModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  titleClassName?: string;
}

const GlassModal: React.FC<GlassModalProps> = ({
  open,
  onClose,
  title,
  children,
  titleClassName = "",
}) => {
  if (!open) return null;

  return (
    <div
      className="glass-modal-backdrop"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="glass-modal-panel glass-card"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="glass-modal-header">
          <h3 className={`glass-modal-title ${titleClassName}`.trim()}>{title}</h3>

          <button
            type="button"
            className="glass-modal-close"
            onClick={onClose}
            aria-label="Close modal"
          >
            ×
          </button>
        </div>

        <div className="glass-modal-body">{children}</div>
      </div>
    </div>
  );
};

export default GlassModal;