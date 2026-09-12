"use client";

import React, { useState, useMemo } from "react";
import {
  BookOpen,
  Search,
  CheckCircle,
  AlertCircle,
  Users,
  GraduationCap,
  Building,
  Calendar,
  Layers,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { CourseSummary, ValidationResult, CourseSummaryItem } from "@/lib/api";

interface CurriculumOfferingsTableProps {
  summary: CourseSummary;
  validationResult?: ValidationResult | null;
}

export function CurriculumOfferingsTable({
  summary,
  validationResult,
}: CurriculumOfferingsTableProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [showAllErrors, setShowAllErrors] = useState(false);

  // Filtered courses based on search query
  const filteredCourses = useMemo(() => {
    if (!searchQuery.trim()) return summary.courses;
    const q = searchQuery.toLowerCase();
    return summary.courses.filter(
      (c) =>
        c.course_number.toLowerCase().includes(q) ||
        c.title.toLowerCase().includes(q) ||
        c.instructors.some((ins) => ins.toLowerCase().includes(q))
    );
  }, [summary.courses, searchQuery]);

  // Derive estimated SKS/credits or instructional types
  const getCourseMeta = (course: CourseSummaryItem) => {
    // Look for SKS pattern in title (e.g. "4 SKS" or "3 sks")
    const sksMatch = course.title.match(/(\d+)\s*(?:sks|credit|sks)/i);
    const sks = sksMatch ? `${sksMatch[1]} SKS` : "3 SKS";

    // Determine common instructional types
    const types: string[] = ["Lec"];
    if (
      course.title.toLowerCase().includes("praktikum") ||
      course.title.toLowerCase().includes("lab") ||
      course.classes_count > 2
    ) {
      types.push("Lab");
    }
    if (course.configurations_count > 1) {
      types.push("Rec");
    }

    return { sks, types };
  };

  const hasValidationErrors =
    validationResult && validationResult.errors_count > 0;
  const hasValidationWarnings =
    validationResult && validationResult.warnings_count > 0;

  return (
    <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden space-y-6">
      {/* Top Academic Context Header */}
      <div className="p-6 bg-muted/30 border-b border-border">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <BookOpen className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
              <h3 className="text-lg font-semibold text-foreground">
                Extracted Curriculum Offerings Preview
              </h3>
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Parsed canonical course configurations, class sections, and instructor assignments
            </p>
          </div>

          {/* Academic Session Pills */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {summary.academic_session.year && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-background border border-border text-foreground">
                <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
                <span>
                  {summary.academic_session.year}{" "}
                  {summary.academic_session.term
                    ? `• ${summary.academic_session.term}`
                    : ""}
                </span>
              </span>
            )}

            {summary.department.name && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-background border border-border text-foreground">
                <Building className="h-3.5 w-3.5 text-muted-foreground" />
                <span>{summary.department.name}</span>
              </span>
            )}
          </div>
        </div>

        {/* Metrics Bar */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5">
          <div className="p-3.5 rounded-lg bg-card border border-border">
            <span className="text-xs text-muted-foreground">Total Courses</span>
            <p className="text-2xl font-bold text-foreground mt-0.5">
              {summary.total_courses}
            </p>
          </div>
          <div className="p-3.5 rounded-lg bg-card border border-border">
            <span className="text-xs text-muted-foreground">Configurations</span>
            <p className="text-2xl font-bold text-foreground mt-0.5">
              {summary.total_configurations}
            </p>
          </div>
          <div className="p-3.5 rounded-lg bg-card border border-border">
            <span className="text-xs text-muted-foreground">Class Sections</span>
            <p className="text-2xl font-bold text-foreground mt-0.5">
              {summary.total_classes}
            </p>
          </div>
          <div className="p-3.5 rounded-lg bg-card border border-border">
            <span className="text-xs text-muted-foreground">Constraints</span>
            <p className="text-2xl font-bold text-foreground mt-0.5">
              {summary.total_distribution_constraints}
            </p>
          </div>
        </div>
      </div>

      {/* Validation Result Banner */}
      {validationResult && (
        <div className="px-6">
          <div
            className={`p-4 rounded-xl border text-xs flex flex-col gap-2 ${
              validationResult.is_valid
                ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-900 dark:text-emerald-200"
                : "bg-rose-500/10 border-rose-500/20 text-rose-900 dark:text-rose-200"
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-medium">
                {validationResult.is_valid ? (
                  <CheckCircle className="h-4 w-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
                ) : (
                  <AlertCircle className="h-4 w-4 text-rose-600 dark:text-rose-400 shrink-0" />
                )}
                <span>
                  {validationResult.is_valid
                    ? "Schema & Semantic Validation Passed"
                    : `Validation Detected Issues (${validationResult.errors_count} error(s), ${validationResult.warnings_count} warning(s))`}
                </span>
              </div>

              {(hasValidationErrors || hasValidationWarnings) && (
                <button
                  type="button"
                  onClick={() => setShowAllErrors(!showAllErrors)}
                  className="underline hover:opacity-80 font-medium"
                >
                  {showAllErrors ? "Hide Details" : "View Details"}
                </button>
              )}
            </div>

            {showAllErrors && validationResult.errors && (
              <ul className="mt-2 space-y-1 list-disc list-inside font-mono text-[11px] text-rose-700 dark:text-rose-300">
                {validationResult.errors.map((err, i) => (
                  <li key={i}>
                    {err.path ? `[${err.path}] ` : ""}
                    {err.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {/* Search & Filter Bar */}
      <div className="px-6 flex items-center justify-between gap-4">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by code, title, or instructor..."
            className="w-full text-xs rounded-lg border border-input bg-background pl-9 pr-3 py-2 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <span className="text-xs text-muted-foreground">
          Showing {filteredCourses.length} of {summary.courses.length} courses
        </span>
      </div>

      {/* Offerings Table */}
      <div className="px-6 pb-6 overflow-x-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-muted-foreground">
              <th className="py-3 px-3 font-semibold">Course Code</th>
              <th className="py-3 px-3 font-semibold">Course Title</th>
              <th className="py-3 px-2 font-semibold">Credit</th>
              <th className="py-3 px-2 font-semibold">Instruction</th>
              <th className="py-3 px-2 font-semibold text-center">Configs</th>
              <th className="py-3 px-2 font-semibold text-center">Sections</th>
              <th className="py-3 px-3 font-semibold">Assigned Instructors</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60 font-normal">
            {filteredCourses.length === 0 ? (
              <tr>
                <td colSpan={7} className="py-8 text-center text-muted-foreground">
                  No matching courses found.
                </td>
              </tr>
            ) : (
              filteredCourses.map((course) => {
                const { sks, types } = getCourseMeta(course);
                return (
                  <tr
                    key={course.course_number}
                    className="hover:bg-muted/30 transition-colors"
                  >
                    <td className="py-3 px-3 font-mono font-semibold text-foreground whitespace-nowrap">
                      {course.course_number}
                    </td>
                    <td className="py-3 px-3 font-medium text-foreground">
                      {course.title || "—"}
                    </td>
                    <td className="py-3 px-2 text-muted-foreground whitespace-nowrap">
                      <span className="px-2 py-0.5 rounded bg-muted text-[11px] font-medium border border-border">
                        {sks}
                      </span>
                    </td>
                    <td className="py-3 px-2 whitespace-nowrap">
                      <div className="flex items-center gap-1">
                        {types.map((t) => (
                          <span
                            key={t}
                            className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="py-3 px-2 text-center text-foreground font-mono">
                      {course.configurations_count}
                    </td>
                    <td className="py-3 px-2 text-center text-foreground font-mono">
                      <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary font-bold text-[11px]">
                        {course.classes_count}
                      </span>
                    </td>
                    <td className="py-3 px-3">
                      {course.instructors.length > 0 ? (
                        <div className="flex flex-wrap gap-1 max-w-xs">
                          {course.instructors.map((ins, i) => (
                            <span
                              key={i}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-muted/60 text-[10px] text-foreground border border-border"
                            >
                              <Users className="h-2.5 w-2.5 text-muted-foreground" />
                              <span className="truncate max-w-[120px]">{ins}</span>
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-muted-foreground italic text-[11px]">
                          Unassigned
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
