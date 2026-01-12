import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";

export default function Register() {
  const { login, register } = useAuth() as any; // ensure register exists in your AuthProvider
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      await register(email, password);  // your backend register call
      await login(email, password);     // auto-login after registration
      navigate("/recs");                // same default as login
    } catch (err: any) {
      setError(err?.message || "Unable to create your account.");
    } finally {
      setLoading(false);
    }
  }

  // same background as login, but patched size + position
  const outerStyle: React.CSSProperties = {
    minHeight: "100vh",
    width: "100%",
    backgroundImage: 'url("/loginBG3.png")',
    backgroundSize: "cover",                          // 25% smaller
    backgroundRepeat: "no-repeat",
    backgroundPosition: "centre",
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
    maxWidth: "420px",
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
    marginTop: "0.3rem",
    background:
      "linear-gradient(135deg, #2563eb 0%, #38bdf8 50%, #6366f1 100%)",
    color: "white",
    fontWeight: 600,
    fontSize: "1rem",
    cursor: "pointer",
  };

  const disabledButtonStyle = { ...buttonStyle, opacity: 0.6, cursor: "default" };

  const errorBoxStyle: React.CSSProperties = {
    marginBottom: "1rem",
    padding: "0.6rem 0.8rem",
    borderRadius: "10px",
    border: "1px solid rgba(248,113,113,0.6)",
    backgroundColor: "rgba(248,113,113,0.1)",
    fontSize: "0.85rem",
    color: "#fecaca",
  };

  return (
    <div style={outerStyle}>
      <div style={overlayStyle}>
        <div style={cardStyle}>
          <h1 style={titleStyle}>Create account</h1>

          {error && <div style={errorBoxStyle}>{error}</div>}

          <form onSubmit={onSubmit} style={{ display: "grid", gap: "1.1rem" }}>
            <div>
              <label style={labelStyle}>Email</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                style={inputStyle}
              />
            </div>

            <div>
              <label style={labelStyle}>Password</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                style={inputStyle}
              />
            </div>

            <div>
              <label style={labelStyle}>Confirm password</label>
              <input
                type="password"
                required
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="••••••••"
                style={inputStyle}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              style={loading ? disabledButtonStyle : buttonStyle}
            >
              {loading ? "Creating…" : "Create account"}
            </button>
          </form>

          <p
            style={{
              marginTop: "1rem",
              textAlign: "center",
              fontSize: "0.85rem",
              color: "#9ca3af",
            }}
          >
            Already have an account?{" "}
            <a href="/login" style={{ color: "#60a5fa" }}>
              Sign in
            </a>
          </p>
        </div>
      </div>
    </div>
  );
}
