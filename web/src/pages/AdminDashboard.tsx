import React, { useEffect, useMemo, useState, useCallback } from "react";
import { useAuth } from "../auth/AuthProvider";
import {
  adminListUsers,
  adminDeleteUser,
  adminResetPassword,
  getAdminStats,
  type AdminUser,
  type AdminStats,
} from "../api";

function formatDate(value?: string | null) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

const PAGE_SIZE = 25;

const AdminDashboard: React.FC = () => {
  const { user, loading } = useAuth();

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

  useEffect(() => {
    if (!user?.is_admin) return;
    (async () => {
      try {
        setStatsLoading(true);
        const res = await getAdminStats();
        setStats(res);
      } catch (err) {
        console.error("Failed to load admin stats", err);
      } finally {
        setStatsLoading(false);
      }
    })();
  }, [user?.is_admin]);

  const reloadUsers = useCallback(async () => {
    if (!user?.is_admin) return;
    try {
      setUsersLoading(true);
      setUsersError(null);
      const res = await adminListUsers();
      setUsers(res);
    } catch (err) {
      console.error("Failed to load users", err);
      setUsersError("Failed to load users");
    } finally {
      setUsersLoading(false);
    }
  }, [user?.is_admin]);

  useEffect(() => {
    reloadUsers();
  }, [reloadUsers]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return users
      .filter((u) => {
        if (roleFilter === "admin" && !u.is_admin) return false;
        if (roleFilter === "user" && u.is_admin) return false;
        if (!q) return true;
        const e = (u.email || "").toLowerCase();
        const un = (u.username || "").toLowerCase();
        return e.includes(q) || un.includes(q) || String(u.id).includes(q);
      })
      .sort((a, b) => {
        const ad = a.created_at ? new Date(a.created_at).getTime() : 0;
        const bd = b.created_at ? new Date(b.created_at).getTime() : 0;
        if (bd !== ad) return bd - ad;
        return (b.id || 0) - (a.id || 0);
      });
  }, [users, query, roleFilter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageSafe = Math.min(Math.max(1, page), totalPages);

  useEffect(() => {
    setPage(1);
  }, [query, roleFilter]);

  const pageItems = useMemo(() => {
    const start = (pageSafe - 1) * PAGE_SIZE;
    return filtered.slice(start, start + PAGE_SIZE);
  }, [filtered, pageSafe]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950">
        <p className="text-slate-100 text-lg font-medium">Loading…</p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950">
        <p className="text-slate-100 text-lg font-medium">
          You need to be logged in to view this page.
        </p>
      </div>
    );
  }

  if (!user.is_admin) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950">
        <p className="text-slate-100 text-lg font-medium">
          You do not have permission to view this page.
        </p>
      </div>
    );
  }

  const openResetModal = (u: AdminUser) => {
    setResetUser(u);
    setResetPassword("");
  };

  const handleResetPassword = async () => {
    if (!resetUser) return;
    if (!resetPassword || resetPassword.length < 6) {
      alert("Password must be at least 6 characters");
      return;
    }
    try {
      setResetBusy(true);
      await adminResetPassword(resetUser.id, resetPassword);
      setResetUser(null);
      setResetPassword("");
    } catch (err) {
      console.error("Failed to reset password", err);
      alert("Failed to reset password");
    } finally {
      setResetBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteUser) return;
    try {
      setDeleteBusyId(deleteUser.id);
      await adminDeleteUser(deleteUser.id);
      setDeleteUser(null);
      await reloadUsers();
    } catch (err) {
      console.error("Failed to delete user", err);
      alert("Failed to delete user");
    } finally {
      setDeleteBusyId(null);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-50">
      <div className="max-w-6xl mx-auto px-4 py-6 space-y-8">
        <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              Admin Dashboard
            </h1>
            <p className="text-sm text-slate-400">
              Monitor WhatNext usage and manage user accounts.
            </p>
          </div>
          <div className="text-xs text-slate-400">
            Logged in as{" "}
            <span className="font-medium text-slate-100">{user.email}</span>
          </div>
        </header>

        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-slate-300">App overview</h2>
            <button
              onClick={async () => {
                await reloadUsers();
                try {
                  setStatsLoading(true);
                  const res = await getAdminStats();
                  setStats(res);
                } catch (e) {
                  console.error(e);
                } finally {
                  setStatsLoading(false);
                }
              }}
              className="text-xs px-3 py-1 rounded-full border border-slate-700 bg-slate-900 text-slate-100 hover:bg-slate-800 transition"
            >
              Refresh all
            </button>
          </div>

          {statsLoading ? (
            <div className="text-slate-400 text-sm">Loading stats…</div>
          ) : !stats ? (
            <div className="text-slate-400 text-sm">No stats available.</div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              <StatCard label="Total users" value={stats.total_users} />
              <StatCard label="New (7 days)" value={stats.new_users_last_7_days} />
              <StatCard label="Total favourites" value={stats.total_favorites} sub={`Used by ${stats.users_with_favorites} users`} />
              <StatCard label="Total ratings" value={stats.total_ratings} sub={`Used by ${stats.users_with_ratings} users`} />
              <StatCard label="Not-interested" value={stats.total_not_interested} />
            </div>
          )}
        </section>

        <section>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 className="text-sm font-semibold text-slate-300">
                Users ({filtered.length})
              </h2>
              <p className="text-xs text-slate-500">
                Search by id, email, or username.
              </p>
            </div>

            <div className="flex flex-col sm:flex-row gap-2">
              <div className="flex items-center gap-2">
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search users…"
                  className="w-full sm:w-64 rounded-xl border border-slate-800 bg-slate-900 text-slate-100/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                />
                <select
                  value={roleFilter}
                  onChange={(e) => setRoleFilter(e.target.value as any)}
                  className="rounded-xl border border-slate-800 bg-slate-900 text-slate-100/60 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                >
                  <option value="all">All</option>
                  <option value="admin">Admins</option>
                  <option value="user">Users</option>
                </select>
              </div>
              <button
                onClick={reloadUsers}
                className="text-xs px-3 py-2 rounded-xl border border-slate-700 bg-slate-900 text-slate-100 hover:bg-slate-800 transition"
              >
                Refresh
              </button>
            </div>
          </div>

          <div className="mt-3">
            {usersLoading ? (
              <div className="text-slate-400 text-sm">Loading users…</div>
            ) : usersError ? (
              <div className="text-red-400 text-sm">{usersError}</div>
            ) : filtered.length === 0 ? (
              <div className="text-slate-400 text-sm">No users found.</div>
            ) : (
              <div className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900 text-slate-100/40">
                <table className="min-w-full text-sm">
                  <thead className="bg-slate-900 text-slate-100/80">
                    <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                      <th className="px-3 py-2 font-medium">ID</th>
                      <th className="px-3 py-2 font-medium">Email</th>
                      <th className="px-3 py-2 font-medium">Username</th>
                      <th className="px-3 py-2 font-medium">Created</th>
                      <th className="px-3 py-2 font-medium text-center">Role</th>
                      <th className="px-3 py-2 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pageItems.map((u) => (
                      <tr
                        key={u.id}
                        className="border-t border-slate-800/80 hover:bg-slate-900 text-slate-100/60"
                      >
                        <td className="px-3 py-2 text-slate-300">{u.id}</td>
                        <td className="px-3 py-2 text-slate-100">{u.email}</td>
                        <td className="px-3 py-2 text-slate-300">
                          {u.username || <span className="text-slate-500">—</span>}
                        </td>
                        <td className="px-3 py-2 text-slate-400">
                          {formatDate(u.created_at)}
                        </td>
                        <td className="px-3 py-2 text-center">
                          {u.is_admin ? (
                            <span className="inline-flex items-center rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-300 border border-emerald-500/40">
                              Admin
                            </span>
                          ) : (
                            <span className="inline-flex items-center rounded-full bg-slate-700/40 px-2 py-0.5 text-[11px] font-medium text-slate-200 border border-slate-700">
                              User
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right">
                          <div className="inline-flex items-center gap-2">
                            <button
                              onClick={() => openResetModal(u)}
                              className="text-xs px-2 py-1 rounded-full border border-slate-700 bg-slate-900 text-slate-100 hover:bg-slate-800 transition"
                            >
                              Reset password
                            </button>
                            <button
                              onClick={() => setDeleteUser(u)}
                              disabled={deleteBusyId === u.id}
                              className="text-xs px-2 py-1 rounded-full border border-red-700/70 bg-red-900/20 text-red-300 hover:bg-red-900/40 disabled:opacity-60 disabled:cursor-not-allowed transition"
                            >
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                <div className="flex items-center justify-between px-3 py-3 border-t border-slate-800/80">
                  <div className="text-xs text-slate-400">
                    Page {pageSafe} of {totalPages}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={pageSafe <= 1}
                      className="text-xs px-3 py-1 rounded-full border border-slate-700 bg-slate-900 text-slate-100 hover:bg-slate-800 disabled:opacity-60"
                    >
                      Prev
                    </button>
                    <button
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      disabled={pageSafe >= totalPages}
                      className="text-xs px-3 py-1 rounded-full border border-slate-700 bg-slate-900 text-slate-100 hover:bg-slate-800 disabled:opacity-60"
                    >
                      Next
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </section>
      </div>

      {resetUser && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-950 p-5 shadow-xl">
            <h3 className="text-lg font-semibold mb-1">Reset password</h3>
            <p className="text-sm text-slate-400 mb-4">
              Set a new password for{" "}
              <span className="font-medium text-slate-100">{resetUser.email}</span>.
            </p>
            <label className="block mb-3">
              <span className="block text-xs font-medium text-slate-400 mb-1">
                New password
              </span>
              <input
                type="password"
                value={resetPassword}
                onChange={(e) => setResetPassword(e.target.value)}
                className="w-full rounded-xl border border-slate-800 bg-slate-900 text-slate-100 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                placeholder="At least 6 characters"
              />
            </label>
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setResetUser(null)}
                disabled={resetBusy}
                className="px-3 py-1.5 text-xs rounded-full border border-slate-700 bg-slate-900 text-slate-100 hover:bg-slate-800 disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                onClick={handleResetPassword}
                disabled={resetBusy}
                className="px-3 py-1.5 text-xs rounded-full bg-emerald-600 hover:bg-emerald-500 text-white font-medium disabled:opacity-60"
              >
                {resetBusy ? "Saving…" : "Save password"}
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteUser && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-950 p-5 shadow-xl">
            <h3 className="text-lg font-semibold mb-1 text-red-200">Delete user</h3>
            <p className="text-sm text-slate-400 mb-4">
              This will permanently delete{" "}
              <span className="font-medium text-slate-100">{deleteUser.email}</span>{" "}
              and their favourites/ratings/not-interested rows.
            </p>

            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setDeleteUser(null)}
                disabled={deleteBusyId === deleteUser.id}
                className="px-3 py-1.5 text-xs rounded-full border border-slate-700 bg-slate-900 text-slate-100 hover:bg-slate-800 disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleteBusyId === deleteUser.id}
                className="px-3 py-1.5 text-xs rounded-full bg-red-600 hover:bg-red-500 text-white font-medium disabled:opacity-60"
              >
                {deleteBusyId === deleteUser.id ? "Deleting…" : "Delete user"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

function StatCard({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900 text-slate-100/60 p-3">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-xl font-semibold">{value}</div>
      {sub ? <div className="text-[11px] text-slate-500 mt-1">{sub}</div> : null}
    </div>
  );
}

export default AdminDashboard;
