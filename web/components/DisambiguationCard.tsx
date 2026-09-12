"use client";

import React, { useState } from "react";
import {
  HelpCircle,
  AlertOctagon,
  Check,
  CheckCheck,
  ArrowRight,
  ShieldAlert,
  Edit3,
} from "lucide-react";
import { AmbiguityItem } from "@/lib/api";
import { AiResponseParser } from "@/components/AiResponseParser";

interface DisambiguationCardProps {
  jobId: string;
  ambiguities: AmbiguityItem[];
  onResolve: (resolutions: Record<string, string>) => void;
  isResolving: boolean;
}

export function DisambiguationCard({
  ambiguities,
  onResolve,
  isResolving,
}: DisambiguationCardProps) {
  // Store chosen option for each ambiguity id
  const [selectedResolutions, setSelectedResolutions] = useState<
    Record<string, string>
  >(() => {
    const initial: Record<string, string> = {};
    ambiguities.forEach((amb) => {
      // Pick suggested_resolution or first option as default
      if (amb.suggested_resolution) {
        initial[amb.id] = amb.suggested_resolution;
      } else if (amb.options && amb.options.length > 0) {
        initial[amb.id] = amb.options[0];
      }
    });
    return initial;
  });

  const [customResolutions, setCustomResolutions] = useState<
    Record<string, string>
  >({});
  const [activeCustomInput, setActiveCustomInput] = useState<string | null>(
    null
  );

  const handleSelectOption = (ambId: string, option: string) => {
    setSelectedResolutions((prev) => ({
      ...prev,
      [ambId]: option,
    }));
  };

  const handleCustomChange = (ambId: string, text: string) => {
    setCustomResolutions((prev) => ({
      ...prev,
      [ambId]: text,
    }));
    setSelectedResolutions((prev) => ({
      ...prev,
      [ambId]: text,
    }));
  };

  const handleApplyAllDefaults = () => {
    const defaults: Record<string, string> = {};
    ambiguities.forEach((amb) => {
      defaults[amb.id] =
        amb.suggested_resolution ||
        (amb.options && amb.options.length > 0 ? amb.options[0] : "Approved");
    });
    setSelectedResolutions(defaults);
    onResolve(defaults);
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onResolve(selectedResolutions);
  };

  const getBadgeColor = (type: string) => {
    switch (type.toLowerCase()) {
      case "room_capacity":
        return "bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/20";
      case "time_conflict":
        return "bg-rose-500/10 text-rose-700 dark:text-rose-300 border-rose-500/20";
      case "instructor_disambiguation":
        return "bg-purple-500/10 text-purple-700 dark:text-purple-300 border-purple-500/20";
      default:
        return "bg-sky-500/10 text-sky-700 dark:text-sky-300 border-sky-500/20";
    }
  };

  return (
    <div className="bg-card border-2 border-amber-500/40 rounded-xl shadow-md overflow-hidden animate-in fade-in slide-in-from-top-4 duration-300">
      {/* Alert Header */}
      <div className="bg-amber-500/10 border-b border-amber-500/20 px-6 py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-amber-500/20 text-amber-600 dark:text-amber-400 flex items-center justify-center shrink-0">
            <ShieldAlert className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-foreground">
              Human-in-the-Loop Disambiguation Required
            </h3>
            <p className="text-xs text-muted-foreground">
              {ambiguities.length} conflict{ambiguities.length > 1 ? "s" : ""}{" "}
              identified. Please choose a resolution strategy to continue.
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={handleApplyAllDefaults}
          disabled={isResolving}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-amber-500/30 bg-background hover:bg-amber-500/10 text-amber-800 dark:text-amber-300 text-xs font-semibold transition-colors disabled:opacity-50"
        >
          <CheckCheck className="h-3.5 w-3.5" />
          <span>Accept All Defaults</span>
        </button>
      </div>

      {/* Ambiguity Questions Form */}
      <form onSubmit={handleFormSubmit} className="p-6 space-y-6">
        {ambiguities.map((amb, index) => {
          const currentChoice = selectedResolutions[amb.id] || "";
          const options = amb.options && amb.options.length > 0 ? amb.options : ["Approve", "Reject"];
          const isCustom = activeCustomInput === amb.id;

          return (
            <div
              key={amb.id}
              className="p-5 rounded-xl border border-border bg-muted/20 space-y-4 hover:border-amber-500/30 transition-colors"
            >
              {/* Header */}
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-muted-foreground">
                    #{index + 1}
                  </span>
                  <span
                    className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${getBadgeColor(
                      amb.type
                    )}`}
                  >
                    {amb.type.replace(/_/g, " ").toUpperCase()}
                  </span>
                </div>
                <span className="text-[11px] font-mono text-muted-foreground">
                  {amb.id}
                </span>
              </div>

              {/* Question Text */}
              <div className="text-sm font-medium text-foreground leading-relaxed">
                <AiResponseParser content={amb.question} />
              </div>

              {/* Context preview pills */}
              {amb.context && (
                <div className="flex flex-wrap gap-2 text-[11px]">
                  {Boolean(amb.context.room_name) && (
                    <span className="px-2 py-0.5 rounded bg-muted border border-border text-foreground">
                      Room: <strong>{String(amb.context.room_name)}</strong>
                    </span>
                  )}
                  {amb.context.actual_capacity !== undefined && (
                    <span className="px-2 py-0.5 rounded bg-muted border border-border text-foreground">
                      Capacity: <strong>{String(amb.context.actual_capacity)} seats</strong>
                    </span>
                  )}
                  {amb.context.deficit !== undefined && (
                    <span className="px-2 py-0.5 rounded bg-rose-500/10 border border-rose-500/20 text-rose-700 dark:text-rose-300 font-semibold">
                      Deficit: -{String(amb.context.deficit)} seats
                    </span>
                  )}
                  {Boolean(amb.context.conflict_type) && (
                    <span className="px-2 py-0.5 rounded bg-muted border border-border text-foreground">
                      Conflict: <strong>{String(amb.context.conflict_type)}</strong>
                    </span>
                  )}
                </div>
              )}

              {/* Interactive Option Pills */}
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5 pt-1">
                {options.map((opt) => {
                  const isSelected = currentChoice === opt;
                  return (
                    <button
                      key={opt}
                      type="button"
                      onClick={() => {
                        setActiveCustomInput(null);
                        handleSelectOption(amb.id, opt);
                      }}
                      className={`flex items-center justify-between p-3 rounded-lg border text-left text-xs transition-all ${
                        isSelected
                          ? "border-emerald-500 bg-emerald-500/10 text-emerald-900 dark:text-emerald-200 font-medium ring-1 ring-emerald-500/30"
                          : "border-border bg-card hover:bg-muted text-foreground"
                      }`}
                    >
                      <span className="pr-2">{opt}</span>
                      <div
                        className={`h-4 w-4 rounded-full border flex items-center justify-center shrink-0 ${
                          isSelected
                            ? "border-emerald-500 bg-emerald-500 text-white"
                            : "border-muted-foreground/30"
                        }`}
                      >
                        {isSelected && <Check className="h-2.5 w-2.5" />}
                      </div>
                    </button>
                  );
                })}

                {/* Custom Resolution Toggle */}
                <button
                  type="button"
                  onClick={() => setActiveCustomInput(isCustom ? null : amb.id)}
                  className={`flex items-center justify-between p-3 rounded-lg border text-left text-xs transition-all ${
                    isCustom
                      ? "border-primary bg-primary/10 text-primary font-medium"
                      : "border-dashed border-border bg-card hover:bg-muted text-muted-foreground"
                  }`}
                >
                  <span className="inline-flex items-center gap-1.5">
                    <Edit3 className="h-3.5 w-3.5" />
                    <span>Custom directive...</span>
                  </span>
                </button>
              </div>

              {/* Custom Input Field */}
              {isCustom && (
                <div className="pt-2 animate-in fade-in duration-200">
                  <input
                    type="text"
                    value={customResolutions[amb.id] || ""}
                    onChange={(e) => handleCustomChange(amb.id, e.target.value)}
                    placeholder="Enter custom resolution instruction for the agent..."
                    className="w-full text-xs rounded-lg border border-input bg-background px-3 py-2 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                    autoFocus
                  />
                </div>
              )}
            </div>
          );
        })}

        {/* Submit Action */}
        <div className="flex items-center justify-end gap-3 pt-4 border-t border-border">
          <button
            type="submit"
            disabled={isResolving}
            className="inline-flex items-center justify-center gap-2 px-6 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-sm shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isResolving ? (
              <>
                <span className="h-4 w-4 rounded-full border-2 border-white/20 border-t-white animate-spin" />
                <span>Resuming Pipeline...</span>
              </>
            ) : (
              <>
                <span>Apply Resolutions &amp; Resume</span>
                <ArrowRight className="h-4 w-4" />
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
