import React from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";

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
  { to: "/watchlist", label: "Watchlist", key: "watchlist" },
  { to: "/recs", label: "Recommendations", key: "recs" },
  { to: "/wrapped", label: "Profile", key: "wrapped" },
  { to: "/HowToUse", label: "HowToUse", key: "HowToUse" },
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

export default function PageHeader({ title, subtitle }: PageHeaderProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [mobileMenuOpen, setMobileMenuOpen] = React.useState(false);
  const isMobile = useIsMobile(768);

  const brandTitle = "WhatNext";
  const displaySubtitle = subtitle ?? title;
  const authLabel = user ? "Sign out" : "Sign in";

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

  const pillBaseStyle: React.CSSProperties = {
    padding: "6px 10px",
    backgroundColor: "rgba(15,23,42,0.95)",
    border: "1px solid rgba(33, 200, 242, 0.9)",
    boxShadow: "0 0 10px rgba(15,23,42,0.9)",
    whiteSpace: "nowrap",
    color: "#ffffff",
    textDecoration: "none",
  };

  const pillActiveStyle: React.CSSProperties = {
    backgroundColor: "rgba(33, 200, 242, 0.9)",
    boxShadow: "0 0 18px rgba(33, 200, 242, 0.9)",
  };

  return (
    <header
      className="fixed inset-x-0 top-0 z-50 wn-header-fixed"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        width: "100%",
        maxWidth: "100%",
      }}
    >
      <div
        className="wn-header-outer"
        style={{
          width: "100%",
          maxWidth: "100%",
          margin: 0,
          paddingLeft: 0,
          paddingRight: 0,
        }}
      >
        <div
          className="wn-header-inner"
          style={{
            width: "100%",
            maxWidth: "100%",
            margin: 0,
            borderRadius: 0,
          }}
        >
          <div
            className="wn-header-grid"
            style={{
              width: "100%",
              maxWidth: "100%",
              paddingTop: isMobile ? 10 : 12,
              paddingBottom: isMobile ? 10 : 12,
              paddingLeft: isMobile ? 12 : 16,
              paddingRight: isMobile ? 12 : 16,
            }}
          >
            <div className="wn-header-left">
              <div className="relative">
                <div className="pointer-events-none wn-logo-glow" />
                <div
                  className="relative overflow-hidden transition-transform duration-200 hover:scale-[1.03] wn-logo-box"
                  style={{
                    height: isMobile ? 64 : 84,
                    width: isMobile ? 64 : 84,
                  }}
                >
                  <img
                    src={"/logo1.png"}
                    alt="WhatNext"
                    style={{
                      width: "100%",
                      height: "100%",
                      objectFit: "contain",
                      display: "block",
                      padding: 2,
                    }}
                  />
                </div>
              </div>
            </div>

            <div className="wn-header-center">
              <h1 className="wn-header-title">{brandTitle}</h1>
              {!isMobile && displaySubtitle && (
                <p className="wn-header-subtitle">{displaySubtitle}</p>
              )}
            </div>

            <div className="wn-header-right">
              {isMobile ? (
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={handleAuthClick}
                    className="wn-pill wn-auth"
                    style={{
                      padding: "7px 12px",
                      backgroundColor: user ? "#ffffff" : "rgba(15,23,42,0.95)",
                      color: user ? "#000000" : "#e5e7eb",
                      border: user
                        ? "1px solid rgba(148,163,184,0.8)"
                        : "1px solid rgba(148,163,184,0.6)",
                      boxShadow: "0 0 10px rgba(15,23,42,0.9)",
                      borderRadius: 9999,
                      whiteSpace: "nowrap",
                      fontWeight: 800,
                      fontSize: 13,
                    }}
                  >
                    {authLabel}
                  </button>

                  <button
                    type="button"
                    onClick={() => setMobileMenuOpen((v) => !v)}
                    aria-label="Toggle navigation menu"
                    className="wn-pill"
                    style={{
                      padding: "7px 12px",
                      backgroundColor: "rgba(15,23,42,0.95)",
                      color: "#e5e7eb",
                      border: "1px solid rgba(148,163,184,0.7)",
                      boxShadow: "0 0 10px rgba(15,23,42,0.9)",
                      borderRadius: 9999,
                      whiteSpace: "nowrap",
                      fontWeight: 700,
                      fontSize: 13,
                    }}
                  >
                    {mobileMenuOpen ? "Close" : "Menu"}
                  </button>
                </div>
              ) : (
                <div className="wn-desktop-navwrap">
                  <nav className="wn-nav no-scrollbar">
                    {NAV_LINKS.map((link) => {
                      const isActive = location.pathname === link.to;
                      return (
                        <Link
                          key={link.key}
                          to={link.to}
                          className="wn-pill"
                          style={{
                            ...pillBaseStyle,
                            ...(isActive ? pillActiveStyle : null),
                            fontSize: 14,
                            borderRadius: 9999,
                            fontWeight: 700,
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
                    className="wn-pill wn-auth"
                    style={{
                      padding: "8px 16px",
                      backgroundColor: user ? "#ffffff" : "rgba(15,23,42,0.95)",
                      color: user ? "#000000" : "#e5e7eb",
                      border: user
                        ? "1px solid rgba(148,163,184,0.8)"
                        : "1px solid rgba(148,163,184,0.6)",
                      boxShadow: "0 0 12px rgba(15,23,42,0.9)",
                      whiteSpace: "nowrap",
                      borderRadius: 9999,
                      fontSize: 14,
                      fontWeight: 800,
                    }}
                  >
                    {authLabel}
                  </button>
                </div>
              )}
            </div>
          </div>

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
        </div>
      </div>
    </header>
  );
}