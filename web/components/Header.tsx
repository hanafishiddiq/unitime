"use client";

import React, { useEffect, useState } from "react";
import {
  Activity,
  CheckCircle2,
  XCircle,
  FileText,
  RefreshCw,
  ExternalLink,
  Layers,
  Lock,
  ShieldCheck,
  LogOut,
} from "lucide-react";
import { checkHealth, HealthResponse, getApiBaseUrl } from "@/lib/api";

interface HeaderProps {
  onOpenReports?: () => void;
  isAdminRequired?: boolean;
  isAuthenticated?: boolean;
  onOpenAdminModal?: () => void;
  onLogout?: () => void;
}

export function Header({
  onOpenReports,
  isAdminRequired = false,
  isAuthenticated = false,
  onOpenAdminModal,
  onLogout,
}: HeaderProps) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [apiUrl, setApiUrl] = useState("");

  const refreshHealth = async () => {
    setIsLoading(true);
    try {
      const data = await checkHealth();
      setHealth(data);
    } catch {
      setHealth(null);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    setApiUrl(getApiBaseUrl());
    refreshHealth();
    const timer = setInterval(refreshHealth, 30000); // 30s heartbeat
    return () => clearInterval(timer);
  }, []);

  const isConnected = health?.status === "ok";
  const isUniTimeConnected = health?.unitime?.connected ?? false;

  return (
    <header className="sticky top-0 z-40 border-b border-border/80 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        {/* Logo & Title */}
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-emerald-600/10 border border-emerald-500/20 flex items-center justify-center text-emerald-600 dark:text-emerald-400">
            <Layers className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-base tracking-tight text-foreground">
                UniTime
              </span>
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20">
                AI Smart Ingestion
              </span>
            </div>
            <p className="text-xs text-muted-foreground hidden sm:block">
              Autonomous Timetable Extraction & Semantic Validation
            </p>
          </div>
        </div>

        {/* Right Actions & Health Status */}
        <div className="flex items-center gap-3">
          {/* Audit Reports Action */}
          <button
            onClick={onOpenReports}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-border bg-card hover:bg-accent hover:text-accent-foreground transition-colors"
            title="View Executive Audit Reports"
          >
            <FileText className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="hidden md:inline">Audit Reports</span>
          </button>

          {/* Gateway Status Pill */}
          <div
            className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
              isConnected
                ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/20"
                : "bg-rose-500/10 text-rose-700 dark:text-rose-300 border-rose-500/20"
            }`}
            title={`Gateway URL: ${apiUrl}\nUniTime Server: ${
              isUniTimeConnected ? "Connected" : "Disconnected"
            }`}
          >
            <span
              className={`h-2 w-2 rounded-full ${
                isConnected
                  ? "bg-emerald-500 animate-pulse-slow"
                  : "bg-rose-500"
              }`}
            />
            <span className="hidden sm:inline">
              {isConnected ? (
                <>
                  Gateway Online
                  {health?.provider ? ` • ${health.provider}` : ""}
                </>
              ) : (
                "Gateway Offline"
              )}
            </span>
            <span className="sm:hidden">
              {isConnected ? "Online" : "Offline"}
            </span>

            {/* UniTime DB Indicator */}
            {isConnected && (
              <span
                className={`ml-1 px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                  isUniTimeConnected
                    ? "bg-emerald-600/20 text-emerald-800 dark:text-emerald-300"
                    : "bg-amber-500/20 text-amber-800 dark:text-amber-300"
                }`}
                title={health?.unitime?.url}
              >
                {isUniTimeConnected ? "UniTime 4.8" : "UniTime Unreachable"}
              </span>
            )}

            <button
              onClick={(e) => {
                e.stopPropagation();
                refreshHealth();
              }}
              disabled={isLoading}
              className="hover:opacity-75 disabled:opacity-40 ml-0.5"
              aria-label="Refresh status"
            >
              <RefreshCw
                className={`h-3 w-3 ${isLoading ? "animate-spin" : ""}`}
              />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
