import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Users,
  Star,
  ThumbsUp,
  EyeOff,
  UserPlus,
  RefreshCw,
  Search,
  Shield,
  Trash2,
  KeyRound,
  TrendingUp,
  ArrowLeft,
  ArrowRight,
} from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import {
  adminListUsers,
  adminDeleteUser,
  adminResetPassword,
  getAdminStats,
  type AdminUser,
  type AdminStats,
} from "../api";
import GlassStatCard from "../pages/GlassStatCard";
import GlassModal from "../pages/GlassModal";

function formatDate(value?: string | null) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

const PAGE_SIZE = 10;

const AdminDashboard: React.FC = () => {
  const { user, loading } = useAuth() as any;

  const [stats, setStats] = useState<AdminStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);

  const [users, setUsers] = useState<AdminUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(true);
  const [usersError, setUsersError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState<"all" | "admin" | "user">("all");
  const [page, setPage] = useState(1);

  const [resetUser, setResetUser] = useState<AdminUser | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetBusy, setResetBusy] = useState(false);

  const [deleteUser, setDeleteUser] = useState<AdminUser | null>(null);
  const [deleteBusyId, setDeleteBusyId] = useState<number | null>(null);

  const loadStats = useCallback(async () => {
    if (!user?.is_admin) return;

    try {
      setStatsLoading(true);
      const res = await getAdminStats();
      setStats(res);
    } catch (err) {
      console.error("Failed to load admin stats", err);
    } finally {
      setStatsLoading(false);
    }
  }, [user?.is_admin]);

  const reloadUsers = useCallback(async () => {
    if (!user?.is_admin) return;

    try {
      setUsersLoading(true);
      setUsersError(null);
      const res = await adminListUsers();
      setUsers(Array.isArray(res) ? res : []);
    } catch (err) {
      console.error("Failed to load users", err);
      setUsersError("Failed to load users.");
    } finally {
      setUsersLoading(false);
    }
  }, [user?.is_admin]);

  useEffect(() => {
    if (!user?.is_admin) return;
    loadStats();
  }, [user?.is_admin, loadStats]);

  useEffect(() => {
    if (!user?.is_admin) return;
    reloadUsers();
  }, [user?.is_admin, reloadUsers]);

  useEffect(() => {
    setPage(1);
  }, [query, roleFilter]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();

    return users
      .filter((u) => {
        if (roleFilter === "admin" && !u.is_admin) return false;
        if (roleFilter === "user" && u.is_admin) return false;
        if (!q) return true;

        return (
          (u.email || "").toLowerCase().includes(q) ||
          (u.username || "").toLowerCase().includes(q) ||
          String(u.id).includes(q)
        );
      })
      .sort((a, b) => b.favorites_count - a.favorites_count);
  }, [users, query, roleFilter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageSafe = Math.min(Math.max(1, page), totalPages);

  const pageItems = useMemo(() => {
    const start = (pageSafe - 1) * PAGE_SIZE;
    return filtered.slice(start, start + PAGE_SIZE);
  }, [filtered, pageSafe]);

  const engagement = useMemo(() => {
    const standard = users.filter((u) => !u.is_admin);

    return {
      fav5: standard.filter((u) => u.favorites_count >= 5).length,
      fav10: standard.filter((u) => u.favorites_count >= 10).length,
      fav20: standard.filter((u) => u.favorites_count >= 20).length,
      returned: standard.filter((u) => {
        if (!u.last_seen_at || !u.created_at) return false;
        return new Date(u.last_seen_at).getTime() - new Date(u.created_at).getTime() > 60000;
      }).length,
    };
  }, [users]);

  const handleRefresh = async () => {
    await Promise.all([loadStats(), reloadUsers()]);
  };

  const handleResetPassword = async () => {
    if (!resetUser || !resetPassword.trim()) return;

    try {
      setResetBusy(true);
      await adminResetPassword(resetUser.id, resetPassword.trim());
      setResetUser(null);
      setResetPassword("");
    } catch (err) {
      console.error("Failed to reset password", err);
      alert("Failed to reset password.");
    } finally {
      setResetBusy(false);
    }
  };

  const handleDeleteUser = async () => {
    if (!deleteUser) return;

    try {
      setDeleteBusyId(deleteUser.id);
      await adminDeleteUser(deleteUser.id);
      setDeleteUser(null);
      await Promise.all([reloadUsers(), loadStats()]);
    } catch (err) {
      console.error("Failed to delete user", err);
      alert("Failed to delete user.");
    } finally {
      setDeleteBusyId(null);
    }
  };

  if (loading) {
    return (
      <div className="admin-page">
        <div className="admin-shell">
          <div className="glass-card admin-empty">Loading...</div>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="admin-page">
        <div className="admin-shell">
          <div className="glass-card admin-empty">
            You need to be logged in to view this page.
          </div>
        </div>
      </div>
    );
  }

  if (!user.is_admin) {
    return (
      <div className="admin-page">
        <div className="admin-shell">
          <div className="glass-card admin-empty">
            You do not have permission to view this page.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <div className="admin-bg-orb admin-bg-orb--left" />
      <div className="admin-bg-orb admin-bg-orb--right" />

      <div className="admin-shell">
        <header className="admin-header glass-card">
          <div className="admin-header__left">
            <div className="admin-title-row">
              <Shield size={22} className="admin-title-icon" />
              <h1 className="admin-title">Admin Dashboard</h1>
            </div>
            <p className="admin-subtitle">Monitor usage and manage user accounts</p>
          </div>

          <div className="admin-header__right">
            <span className="admin-logged-in">
              Logged in as <strong>{user.email}</strong>
            </span>

            <button type="button" className="glass-button" onClick={handleRefresh}>
              <RefreshCw size={14} />
              <span>{statsLoading || usersLoading ? "Refreshing..." : "Refresh"}</span>
            </button>
          </div>
        </header>

        {usersError && (
          <div className="glass-card admin-empty" style={{ marginBottom: 16 }}>
            {usersError}
          </div>
        )}

        <section className="admin-section">
          <div className="admin-section__label">App Overview</div>

          <div className="admin-stats-grid admin-stats-grid--top">
            <GlassStatCard label="Total users" value={stats?.total_users ?? 0} icon={Users} glow />
            <GlassStatCard
              label="New (7 days)"
              value={stats?.new_users_last_7_days ?? 0}
              icon={UserPlus}
            />
            <GlassStatCard
              label="Total favourites"
              value={stats?.total_favorites ?? 0}
              icon={Star}
              sub={`Used by ${stats?.users_with_favorites ?? 0} users`}
            />
            <GlassStatCard
              label="Total ratings"
              value={stats?.total_ratings ?? 0}
              icon={ThumbsUp}
              sub={`Used by ${stats?.users_with_ratings ?? 0} users`}
            />
            <GlassStatCard
              label="Not interested"
              value={stats?.total_not_interested ?? 0}
              icon={EyeOff}
            />
          </div>

          <div className="admin-stats-grid admin-stats-grid--bottom">
            <GlassStatCard label="5+ favourites" value={engagement.fav5} icon={TrendingUp} />
            <GlassStatCard label="10+ favourites" value={engagement.fav10} />
            <GlassStatCard label="20+ favourites" value={engagement.fav20} />
            <GlassStatCard
              label="Returned users"
              value={engagement.returned}
              sub="Based on last login"
            />
          </div>
        </section>

        <section className="admin-section">
          <div className="admin-users-header">
            <div>
              <div className="admin-section__label">
                Users ({usersLoading ? "..." : filtered.length})
              </div>
              <p className="admin-users-subtitle">Search by ID, email, or username</p>
            </div>

            <div className="admin-filters">
              <div className="admin-search-wrap">
                <Search size={14} className="admin-search-icon" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search users..."
                  className="glass-input admin-search-input"
                />
              </div>

              <select
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value as "all" | "admin" | "user")}
                className="glass-input admin-role-select"
              >
                <option value="all">All roles</option>
                <option value="admin">Admins</option>
                <option value="user">Users</option>
              </select>
            </div>
          </div>

          <div className="glass-card admin-table-card">
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Email</th>
                    <th>Username</th>
                    <th className="is-center">Favs</th>
                    <th className="is-center">Ratings</th>
                    <th className="is-center">Hidden</th>
                    <th>Created</th>
                    <th>Last seen</th>
                    <th className="is-center">Role</th>
                    <th className="is-right">Actions</th>
                  </tr>
                </thead>

                <tbody>
                  {pageItems.map((u) => (
                    <tr key={u.id}>
                      <td className="admin-table__mono">{u.id}</td>
                      <td>{u.email}</td>
                      <td className="admin-table__muted">
                        {u.username || <span className="admin-dash">—</span>}
                      </td>
                      <td className="is-center admin-table__muted">{u.favorites_count}</td>
                      <td className="is-center admin-table__muted">{u.ratings_count}</td>
                      <td className="is-center admin-table__muted">{u.not_interested_count}</td>
                      <td className="admin-table__muted">{formatDate(u.created_at)}</td>
                      <td className="admin-table__muted">
                        {u.last_seen_at ? formatDate(u.last_seen_at) : <span className="admin-dash">—</span>}
                      </td>
                      <td className="is-center">
                        {u.is_admin ? (
                          <span className="admin-badge admin-badge--admin">
                            <Shield size={10} />
                            <span>Admin</span>
                          </span>
                        ) : (
                          <span className="admin-badge admin-badge--user">User</span>
                        )}
                      </td>
                      <td className="is-right">
                        <div className="admin-actions">
                          <button
                            type="button"
                            onClick={() => {
                              setResetUser(u);
                              setResetPassword("");
                            }}
                            className="glass-button"
                          >
                            <KeyRound size={12} />
                            <span>Reset</span>
                          </button>

                          <button
                            type="button"
                            onClick={() => setDeleteUser(u)}
                            className="glass-button-destructive"
                            disabled={deleteBusyId === u.id}
                          >
                            <Trash2 size={12} />
                            <span>{deleteBusyId === u.id ? "Deleting..." : "Delete"}</span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}

                  {!usersLoading && pageItems.length === 0 && (
                    <tr>
                      <td colSpan={10}>
                        <div className="admin-empty">No users found.</div>
                      </td>
                    </tr>
                  )}

                  {usersLoading && (
                    <tr>
                      <td colSpan={10}>
                        <div className="admin-empty">Loading users...</div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="admin-pagination">
              <div className="admin-pagination__info">
                Page {pageSafe} of {totalPages}
              </div>

              <div className="admin-pagination__buttons">
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={pageSafe <= 1}
                  className="glass-button"
                >
                  <ArrowLeft size={12} />
                  <span>Prev</span>
                </button>

                <button
                  type="button"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={pageSafe >= totalPages}
                  className="glass-button"
                >
                  <span>Next</span>
                  <ArrowRight size={12} />
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>

      <GlassModal
        open={!!resetUser}
        onClose={() => {
          if (!resetBusy) {
            setResetUser(null);
            setResetPassword("");
          }
        }}
        title="Reset Password"
      >
        <p className="admin-modal-copy">
          Set a new password for <span className="admin-modal-strong">{resetUser?.email}</span>
        </p>

        <label className="admin-form-row">
          <span className="admin-form-label">New password</span>
          <input
            type="password"
            value={resetPassword}
            onChange={(e) => setResetPassword(e.target.value)}
            className="glass-input admin-form-input"
            placeholder="At least 6 characters"
          />
        </label>

        <div className="admin-modal-actions">
          <button
            type="button"
            onClick={() => {
              setResetUser(null);
              setResetPassword("");
            }}
            className="glass-button"
            disabled={resetBusy}
          >
            Cancel
          </button>
          <button
            type="button"
            className="glass-button-primary"
            onClick={handleResetPassword}
            disabled={resetBusy || !resetPassword.trim()}
          >
            {resetBusy ? "Saving..." : "Save password"}
          </button>
        </div>
      </GlassModal>

      <GlassModal
        open={!!deleteUser}
        onClose={() => {
          if (deleteBusyId == null) {
            setDeleteUser(null);
          }
        }}
        title="Delete User"
        titleClassName="admin-modal-title--danger"
      >
        <p className="admin-modal-copy">
          This will permanently delete{" "}
          <span className="admin-modal-strong">{deleteUser?.email}</span> and all associated data.
        </p>

        <div className="admin-modal-actions">
          <button
            type="button"
            onClick={() => setDeleteUser(null)}
            className="glass-button"
            disabled={deleteBusyId === deleteUser?.id}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleDeleteUser}
            className="glass-button-destructive"
            disabled={deleteBusyId === deleteUser?.id}
          >
            {deleteBusyId === deleteUser?.id ? "Deleting..." : "Delete user"}
          </button>
        </div>
      </GlassModal>
    </div>
  );
};

export default AdminDashboard;