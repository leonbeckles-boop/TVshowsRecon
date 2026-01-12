import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthProvider";

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  // While auth state is being resolved, don't redirect yet.
  if (loading) {
    return <div className="p-6 text-sm text-gray-600">Checking authentication…</div>;
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <>{children}</>;
}
