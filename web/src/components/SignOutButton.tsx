import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { clearToken } from "../api";

/**
 * Drop-in sign out button.
 * - Clears the stored access token
 * - Navigates to /login
 * - (Optional) full reload to reset all in-memory state
 */
export default function SignOutButton({
  className = "rounded-md border px-3 py-1.5 text-sm hover:bg-gray-50",
  reload = false,
  onSignedOut,
}: {
  className?: string;
  /** Set to true to force a hard reload after sign out */
  reload?: boolean;
  /** Optional callback after sign out (before navigation/reload) */
  onSignedOut?: () => void;
}) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);

  async function handleClick() {
    if (busy) return;
    setBusy(true);
    try {
      // Remove token so subsequent requests are unauthenticated
      clearToken();
      onSignedOut?.();
      if (reload) {
        // Hard reload to clear any in-memory state
        window.location.assign("/login");
      } else {
        navigate("/login");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className={className}
      disabled={busy}
      title="Sign out"
    >
      {busy ? "Signing out…" : "Sign out"}
    </button>
  );
}
