import React, { useEffect, useState, useCallback } from "react";
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

const AdminDashboard: React.FC = () => {
  const { user, loading } = useAuth();

  const [stats, setStats] = useState<AdminStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);

  const [users, setUsers] = useState<AdminUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(true);
  const [usersError, setUsersError] = useState<string | null>(null);

  const [resetUser, setResetUser] = useState<AdminUser | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetBusy, setResetBusy] = useState(false);
  const [deleteBusyId, setDeleteBusyId] = useState<number | null>(null);

  // Load stats
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

  // Load users
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

  // Guards with visible white text
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

  // Handlers
  const handleDelete = async (u: AdminUser) => {
    if (!window.confirm(`Delete user ${u.email}? This cannot be undone.`)) {
      return;
    }
    try {
      setDeleteBusyId(u.id);
      await adminDeleteUser(u.id);
      await reloadUsers();
    } catch (err) {
      console.error("Failed to delete user", err);
      alert("Failed to delete user");
    } finally {
      setDeleteBusyId(null);
    }
  };

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

  return (
    <div
      className="min-h-screen bg-slate-950"
      style={{ color: "#f9fafb" }}  // ← force white-ish text
    >
      <div className="max-w-6xl mx-auto px-4 py-6 space-y-8">
        {/* Header */}
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

        {/* Stats */}
        <section>
          <h2 className="text-sm font-semibold text-slate-300 mb-3">
            App overview
          </h2>
          {statsLoading ? (
            <div className="text-slate-400 text-sm">Loading stats…</div>
          ) : !stats ? (
            <div className="text-slate-400 text-sm">No stats available.</div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">
                  Total users
                </div>
                <div className="text-xl font-semibold">
                  {stats.total_users}
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">
                  New (7 days)
                </div>
                <div className="text-xl font-semibold">
                  {stats.new_users_last_7_days}
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">
                  Total favourites
                </div>
                <div className="text-xl font-semibold">
                  {stats.total_favorites}
                </div>
                <div className="text-[11px] text-slate-500 mt-1">
                  Used by {stats.users_with_favorites} users
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">
                  Total ratings
                </div>
                <div className="text-xl font-semibold">
                  {stats.total_ratings}
                </div>
                <div className="text-[11px] text-slate-500 mt-1">
                  Used by {stats.users_with_ratings} users
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">
                  Not-interested flags
                </div>
                <div className="text-xl font-semibold">
                  {stats.total_not_interested}
                </div>
              </div>
            </div>
          )}
        </section>

        {/* Users */}
        <section>
          <div className="flex items-center justify-between mb-3 gap-2">
            <h2 className="text-sm font-semibold text-slate-300">
              Users ({users.length})
            </h2>
            <button
              onClick={reloadUsers}
              className="text-xs px-3 py-1 rounded-full border border-slate-700 bg-slate-900 hover:bg-slate-800 transition"
            >
              Refresh
            </button>
          </div>

          {usersLoading ? (
            <div className="text-slate-400 text-sm">Loading users…</div>
          ) : usersError ? (
            <div className="text-red-400 text-sm">{usersError}</div>
          ) : users.length === 0 ? (
            <div className="text-slate-400 text-sm">No users found.</div>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/50">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-900/80">
                  <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2 font-medium">ID</th>
                    <th className="px-3 py-2 font-medium">Email</th>
                    <th className="px-3 py-2 font-medium">Username</th>
                    <th className="px-3 py-2 font-medium">Created</th>
                    <th className="px-3 py-2 font-medium text-center">Admin</th>
                    <th className="px-3 py-2 font-medium text-right">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr
                      key={u.id}
                      className="border-t border-slate-800/80 hover:bg-slate-900/70"
                    >
                      <td className="px-3 py-2 text-slate-300">{u.id}</td>
                      <td className="px-3 py-2 text-slate-100">{u.email}</td>
                      <td className="px-3 py-2 text-slate-300">
                        {u.username || (
                          <span className="text-slate-500">—</span>
                        )}
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
                          <span className="inline-flex items-center rounded-full bg-slate-700/40 px-2 py-0.5 text-[11px] font-medium text-slate-300 border border-slate-700">
                            User
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <div className="inline-flex items-center gap-2">
                          <button
                            onClick={() => openResetModal(u)}
                            className="text-xs px-2 py-1 rounded-full border border-slate-700 bg-slate-900 hover:bg-slate-800 transition"
                          >
                            Reset password
                          </button>
                          <button
                            onClick={() => handleDelete(u)}
                            disabled={deleteBusyId === u.id}
                            className="text-xs px-2 py-1 rounded-full border border-red-700/70 bg-red-900/20 text-red-300 hover:bg-red-900/40 disabled:opacity-60 disabled:cursor-not-allowed transition"
                          >
                            {deleteBusyId === u.id ? "Deleting…" : "Delete"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {/* Reset password modal */}
      {resetUser && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-950 p-5 shadow-xl">
            <h3 className="text-lg font-semibold mb-1">Reset password</h3>
            <p className="text-sm text-slate-400 mb-4">
              Set a new password for{" "}
              <span className="font-medium text-slate-100">
                {resetUser.email}
              </span>
              .
            </p>
            <label className="block mb-3">
              <span className="block text-xs font-medium text-slate-400 mb-1">
                New password
              </span>
              <input
                type="password"
                value={resetPassword}
                onChange={(e) => setResetPassword(e.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                placeholder="At least 6 characters"
              />
            </label>
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setResetUser(null)}
                disabled={resetBusy}
                className="px-3 py-1.5 text-xs rounded-full border border-slate-700 bg-slate-900 hover:bg-slate-800 disabled:opacity-60"
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
    </div>
  );
};

export default AdminDashboard;
