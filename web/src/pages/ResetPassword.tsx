import React, { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

export default function ResetPassword() {
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const token = useMemo(() => params.get("token") || "", [params]);

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    if (!token) {
      setError("This reset link is missing or invalid.");
      return;
    }

    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }

    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);

    try {
      const res = await fetch("/api/auth/password-reset/confirm", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          token,
          password,
        }),
      });

      const data = await res.json().catch(() => null);

      if (!res.ok) {
        throw new Error(data?.detail || "Unable to reset password.");
      }

      setDone(true);
      setTimeout(() => {
        navigate("/login", { replace: true });
      }, 1500);
    } catch (err: any) {
      setError(err?.message || "Unable to reset password.");
    } finally {
      setLoading(false);
    }
  }

  const outerStyle: React.CSSProperties = {
    minHeight: "100vh",
    width: "100%",
    backgroundImage: 'url("/LoginBG2.png")',
    backgroundSize: "cover",
    backgroundPosition: "center",
    backgroundRepeat: "no-repeat",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontFamily:
      '-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif',
    color: "#e5e7eb",
  };

  const overlayStyle: React.CSSProperties = {
    position: "relative",
    width: "100%",
    minHeight: "100vh",
    background:
      "radial-gradient(circle at top, rgba(15,23,42,0.3), rgba(15,23,42,0.85))",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "1rem",
  };

  const cardStyle: React.CSSProperties = {
    width: "100%",
    maxWidth: "460px",
    background: "rgba(15,23,42,0.92)",
    borderRadius: "18px",
    border: "1px solid #374151",
    boxShadow: "0 24px 60px rgba(0,0,0,0.75)",
    padding: "2.25rem 2rem",
  };

  const titleStyle: React.CSSProperties = {
    fontSize: "1.9rem",
    fontWeight: 700,
    textAlign: "center",
    marginBottom: "0.75rem",
  };

  const introStyle: React.CSSProperties = {
    fontSize: "0.95rem",
    lineHeight: 1.6,
    color: "#cbd5e1",
    textAlign: "center",
    marginBottom: "1.5rem",
  };

  const labelStyle: React.CSSProperties = {
    fontSize: "0.9rem",
    fontWeight: 600,
    marginBottom: "0.35rem",
    color: "#e5e7eb",
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    padding: "0.75rem 0.9rem",
    borderRadius: "10px",
    border: "1px solid #4b5563",
    backgroundColor: "#020617",
    color: "#e5e7eb",
    fontSize: "0.95rem",
    outline: "none",
    boxSizing: "border-box",
  };

  const buttonStyle: React.CSSProperties = {
    width: "100%",
    padding: "0.8rem 1rem",
    borderRadius: "9999px",
    border: "none",
    marginTop: "0.25rem",
    background:
      "linear-gradient(135deg, #2563eb 0%, #38bdf8 50%, #6366f1 100%)",
    color: "white",
    fontWeight: 600,
    fontSize: "1rem",
    cursor: "pointer",
  };

  const buttonDisabledStyle: React.CSSProperties = {
    ...buttonStyle,
    opacity: 0.6,
    cursor: "default",
  };

  const errorBoxStyle: React.CSSProperties = {
    marginBottom: "1rem",
    padding: "0.6rem 0.8rem",
    borderRadius: "10px",
    border: "1px solid rgba(248,113,113,0.6)",
    backgroundColor: "rgba(248,113,113,0.1)",
    fontSize: "0.85rem",
    color: "#fecaca",
  };

  const successBoxStyle: React.CSSProperties = {
    marginBottom: "1rem",
    padding: "0.9rem 1rem",
    borderRadius: "12px",
    border: "1px solid rgba(74,222,128,0.45)",
    backgroundColor: "rgba(34,197,94,0.12)",
    fontSize: "0.92rem",
    color: "#dcfce7",
    lineHeight: 1.6,
  };

  const linkStyle: React.CSSProperties = {
    color: "#60a5fa",
    textDecoration: "none",
  };

  return (
    <div style={outerStyle}>
      <div style={overlayStyle}>
        <div style={cardStyle}>
          <h1 style={titleStyle}>Choose a new password</h1>
          <p style={introStyle}>
            Enter your new password below to finish resetting your account.
          </p>

          {error && <div style={errorBoxStyle}>{error}</div>}

          {done ? (
            <>
              <div style={successBoxStyle}>
                Your password has been updated. Redirecting you to sign in…
              </div>
              <p style={{ textAlign: "center", marginTop: "1rem", fontSize: "0.9rem" }}>
                <Link to="/login" style={linkStyle}>
                  Go to sign in now
                </Link>
              </p>
            </>
          ) : (
            <>
              <form onSubmit={onSubmit} style={{ display: "grid", gap: "1.1rem" }}>
                <div>
                  <label style={labelStyle}>New password</label>
                  <input
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    style={inputStyle}
                    autoComplete="new-password"
                  />
                </div>

                <div>
                  <label style={labelStyle}>Confirm new password</label>
                  <input
                    type="password"
                    required
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    placeholder="••••••••"
                    style={inputStyle}
                    autoComplete="new-password"
                  />
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  style={loading ? buttonDisabledStyle : buttonStyle}
                >
                  {loading ? "Updating…" : "Update password"}
                </button>
              </form>

              <p style={{ textAlign: "center", marginTop: "1rem", fontSize: "0.9rem", color: "#9ca3af" }}>
                <Link to="/login" style={linkStyle}>
                  Back to sign in
                </Link>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}