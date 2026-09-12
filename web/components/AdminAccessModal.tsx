"use client";

import React, { useState } from "react";
import { Lock, KeyRound, Eye, EyeOff, ShieldCheck, AlertCircle } from "lucide-react";
import { loginAdmin } from "@/lib/api";

interface AdminAccessModalProps {
  isOpen: boolean;
  onSuccess: () => void;
  onClose?: () => void;
}

export function AdminAccessModal({
  isOpen,
  onSuccess,
  onClose,
}: AdminAccessModalProps) {
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim()) {
      setError("Please enter the admin password.");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const res = await loginAdmin(password);
      if (res.success) {
        setPassword("");
        onSuccess();
      } else {
        setError(res.detail || "Authentication failed.");
      }
    } catch (err: any) {
      setError(err?.detail || err?.message || "Invalid admin password. Access denied.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="bg-card border border-border rounded-2xl shadow-2xl w-full max-w-md overflow-hidden p-6 sm:p-8 space-y-6">
        {/* Shield Header */}
        <div className="text-center space-y-2">
          <div className="mx-auto h-12 w-12 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
            <Lock className="h-6 w-6" />
          </div>
          <h2 className="text-xl font-bold tracking-tight text-foreground">
            Admin Access Required
          </h2>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Enterprise Next.js BFF Security is enabled. Enter your administrator
            passcode to upload documents and synchronize with UniTime.
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-foreground flex items-center justify-between">
              <span>Admin Passcode</span>
              <span className="text-[10px] text-muted-foreground font-normal">
                Configured via ADMIN_ACCESS_PASSWORD
              </span>
            </label>
            <div className="relative">
              <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (error) setError(null);
                }}
                placeholder="Enter passcode..."
                autoFocus
                className="w-full text-sm rounded-xl border border-input bg-background pl-9 pr-10 py-2.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                {showPassword ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>

          {error && (
            <div className="flex items-center gap-2 p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-xs text-rose-700 dark:text-rose-300">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="flex items-center gap-3 pt-2">
            {onClose && (
              <button
                type="button"
                onClick={onClose}
                className="flex-1 px-4 py-2.5 rounded-xl border border-border text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              >
                Cancel
              </button>
            )}
            <button
              type="submit"
              disabled={isSubmitting}
              className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold shadow-sm transition-colors disabled:opacity-50"
            >
              <ShieldCheck className="h-4 w-4" />
              <span>{isSubmitting ? "Verifying..." : "Unlock Access"}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
