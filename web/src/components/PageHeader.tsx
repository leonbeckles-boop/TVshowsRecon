import React from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import logo1 from "../assets/logo1.png";

export type PageHeaderProps = {
  title: string;
  subtitle?: string;
  centered?: boolean;
};

type NavLinkDef = {
  to: string;
  label: string;
  key: string;
};

const NAV_LINKS: NavLinkDef[] = [
  { to: "/discover", label: "Discover", key: "discover" },
  { to: "/search", label: "Search", key: "search" },
  { to: "/favorites", label: "Favourites", key: "favourites" },
  { to: "/recs", label: "Recommendations", key: "recs" },
  { to: "/wrapped", label: "Profile", key: "wrapped" },
];

function useIsMobile(breakpoint: number = 768): boolean {
  const [isMobile, setIsMobile] = React.useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.innerWidth < breakpoint;
  });

  React.useEffect(() => {
    function handleResize() {
      setIsMobile(window.innerWidth < breakpoint);
    }
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [breakpoint]);

  return isMobile;
}

const PageHeader: React.FC<PageHeaderProps> = ({ title, subtitle, centered }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [mobileMenuOpen, setMobileMenuOpen] = React.useState(false);
  const isMobile = useIsMobile(768);

  const handleAuthClick = async () => {
    if (user) {
      try {
        await logout?.();
      } catch (err) {
        console.error("Logout failed:", err);
      }
    } else {
      navigate("/login");
    }
    setMobileMenuOpen(false);
  };

  const handleNavClick = (to: string) => {
    navigate(to);
    setMobileMenuOpen(false);
  };

  const authLabel = user ? "Sign out" : "Sign in";

  return (
    <header
      className="fixed inset-x-0 top-0 z-50"
      style={{
        width: "100%",
        background:
          "radial-gradient(circle at top, #020617 0%, #020617 55%, #020617 100%)",
        boxShadow: "0 18px 40px rgba(15,23,42,0.9)",
        backdropFilter: "blur(18px)",
      }}
    >
      {/* MAIN ROW */}
      <div
        className="flex w-full items-center justify-between gap-3 px-4 md:px-8"
        style={{
          paddingTop: isMobile ? 8 : 12,
          paddingBottom: isMobile ? 8 : 12,
          color: "#e5e7eb",
        }}
      >
        {/* LEFT: LOGO + NAME */}
        <div className="flex items-center gap-3 min-w-[140px] md:min-w-[220px]">
          <div className="relative">
            <div
              className="pointer-events-none absolute -inset-2 md:-inset-3 rounded-full opacity-80 blur-2xl"
              style={{
                background:
                  "radial-gradient(circle at 30% 10%, rgba(56,189,248,0.9), transparent 60%)",
              }}
            />
            <div
              className="relative overflow-hidden rounded-full"
              style={{
                height: isMobile ? 34 : 48,
                width: isMobile ? 34 : 48,
                backgroundColor: "#020617",
                boxShadow: "0 0 18px rgba(56,189,248,0.85)",
              }}
            >
              <img
                src={logo1}
                alt="WhatNext logo"
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "cover",
                  display: "block",
                }}
              />
            </div>
          </div>

          <div className="flex flex-col">
            <span
              style={{
                fontSize: isMobile ? 18 : 24,
                fontWeight: 800,
                letterSpacing: isMobile ? "0.1em" : "0.06em",
                textTransform: "uppercase",
                color: "#e0f2fe",
                textShadow: "0 0 10px rgba(56,189,248,0.8)",
              }}
            >
              {isMobile ? "WN" : "WHATNEXT"}
            </span>
          </div>
        </div>

        {/* CENTER: TITLE + SUBTITLE (subtitle desktop only) */}
        <div
          className="px-2"
          style={{
            flex: 1,
            textAlign: "center",
            lineHeight: 1.25,
            maxWidth: centered ? 760 : 640,
          }}
        >
          <h1
            style={{
              margin: 0,
              fontSize: isMobile ? 18 : 24,
              fontWeight: 800,
              letterSpacing: "0.05em",
              color: "#f9fafb",
              textShadow:
                "0 0 14px rgba(15,23,42,0.9), 0 0 26px rgba(56,189,248,0.7)",
            }}
          >
            {title}
          </h1>

          {!isMobile && subtitle && (
            <p
              style={{
                marginTop: 4,
                marginBottom: 0,
                fontSize: 13,
                color: "#cbd5f5",
              }}
            >
              {subtitle}
            </p>
          )}
        </div>

        {/* RIGHT: NAV / AUTH */}
        {isMobile ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleAuthClick}
              className="inline-flex items-center justify-center rounded-full text-xs font-semibold select-none transition-colors duration-200"
              style={{
                padding: "6px 12px",
                backgroundColor: user ? "#ffffff" : "rgba(15,23,42,0.95)",
                color: user ? "#000000" : "#e5e7eb",
                border: user
                  ? "1px solid rgba(148,163,184,0.8)"
                  : "1px solid rgba(148,163,184,0.6)",
                boxShadow: "0 0 10px rgba(15,23,42,0.9)",
                whiteSpace: "nowrap",
              }}
            >
              {authLabel}
            </button>

            <button
              type="button"
              onClick={() => setMobileMenuOpen((v) => !v)}
              aria-label="Toggle navigation menu"
              className="inline-flex items-center justify-center rounded-full border text-xs font-semibold select-none transition-colors duration-200"
              style={{
                padding: "6px 10px",
                backgroundColor: "rgba(15,23,42,0.95)",
                color: "#e5e7eb",
                borderColor: "rgba(148,163,184,0.7)",
                boxShadow: "0 0 10px rgba(15,23,42,0.9)",
              }}
            >
              {mobileMenuOpen ? "Close" : "Menu"}
            </button>
          </div>
        ) : (
          <div className="flex items-center justify-end md:min-w-[420px] pr-4">
            <nav className="flex items-center gap-2 pr-2">
              {NAV_LINKS.map((link) => {
                const isActive = location.pathname === link.to;
                return (
                  <Link
                    key={link.key}
                    to={link.to}
                    className="inline-flex items-center justify-center rounded-full text-[14px] md:text-[16px] font-semibold no-underline select-none transition-all duration-200"
                    style={{
                      padding: "10px 22px",
                      backgroundColor: isActive
                        ? "rgba(33, 200, 242, 0.9)"
                        : "rgba(15,23,42,0.95)",
                      border: "1px solid rgba(33, 200, 242, 0.9)",
                      boxShadow: isActive
                        ? "0 0 20px rgba(33, 200, 242, 0.9)"
                        : "0 0 10px rgba(15,23,42,0.9)",
                      whiteSpace: "nowrap",
                      color: "#ffffff",
                      textDecoration: "none",
                    }}
                  >
                    {link.label}
                  </Link>
                );
              })}
            </nav>

            <button
              type="button"
              onClick={handleAuthClick}
              className="inline-flex items-center justify-center rounded-full text-[14px] md:text-[16px] font-semibold select-none transition-colors duration-200"
              style={{
                padding: "10px 22px",
                backgroundColor: user ? "#ffffff" : "rgba(15,23,42,0.95)",
                color: user ? "#000000" : "#e5e7eb",
                border: user
                  ? "1px solid rgba(148,163,184,0.8)"
                  : "1px solid rgba(148,163,184,0.6)",
                boxShadow: "0 0 12px rgba(15,23,42,0.9)",
                whiteSpace: "nowrap",
              }}
            >
              {authLabel}
            </button>
          </div>
        )}
      </div>

      {/* MOBILE DROPDOWN NAV */}
      {isMobile && mobileMenuOpen && (
        <div
          className="border-t border-slate-700 md:hidden"
          style={{
            background:
              "linear-gradient(to bottom, rgba(15,23,42,0.98), rgba(15,23,42,0.96))",
          }}
        >
          <nav className="flex flex-col px-4 py-3 gap-2">
            {NAV_LINKS.map((link) => {
              const isActive = location.pathname === link.to;
              return (
                <button
                  key={link.key}
                  type="button"
                  onClick={() => handleNavClick(link.to)}
                  className="w-full inline-flex items-center justify-between rounded-xl text-sm font-semibold px-3 py-2 transition-all duration-200"
                  style={{
                    backgroundColor: isActive
                      ? "rgba(33, 200, 242, 0.15)"
                      : "rgba(15,23,42,0.95)",
                    border: "1px solid rgba(148,163,184,0.7)",
                    color: "#e5e7eb",
                  }}
                >
                  <span>{link.label}</span>
                  {isActive && (
                    <span
                      style={{
                        fontSize: 11,
                        textTransform: "uppercase",
                        letterSpacing: "0.1em",
                        opacity: 0.8,
                      }}
                    >
                      Active
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>
      )}
    </header>
  );
};

export default PageHeader;
