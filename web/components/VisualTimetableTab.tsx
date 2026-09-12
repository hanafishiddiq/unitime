"use client";

import React, { useState, useMemo } from "react";
import {
  Calendar as CalendarIcon,
  List,
  Clock,
  MapPin,
  User,
  Search,
  BookOpen,
  Filter,
} from "lucide-react";
import { CourseSummary, CourseSummaryItem, ValidationResult } from "@/lib/api";
import { CurriculumOfferingsTable } from "./CurriculumOfferingsTable";

interface VisualTimetableTabProps {
  summary: CourseSummary | null;
  validationResult?: ValidationResult | null;
}

interface TimetableSlotItem {
  courseNumber: string;
  title: string;
  sks: string;
  day: number; // 0 = Mon, 1 = Tue, 2 = Wed, 3 = Thu, 4 = Fri
  startHour: number; // e.g. 7, 9, 13
  durationHours: number; // e.g. 2 or 3
  room: string;
  instructor: string;
  colorClass: string;
}

const DAYS = [
  { id: 0, name: "Monday", idName: "Senin" },
  { id: 1, name: "Tuesday", idName: "Selasa" },
  { id: 2, name: "Wednesday", idName: "Rabu" },
  { id: 3, name: "Thursday", idName: "Kamis" },
  { id: 4, name: "Friday", idName: "Jumat" },
];

const HOURS = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17];

const COLOR_PALETTES = [
  "bg-emerald-500/10 border-emerald-500/30 text-emerald-950 dark:text-emerald-200 hover:bg-emerald-500/15",
  "bg-blue-500/10 border-blue-500/30 text-blue-950 dark:text-blue-200 hover:bg-blue-500/15",
  "bg-purple-500/10 border-purple-500/30 text-purple-950 dark:text-purple-200 hover:bg-purple-500/15",
  "bg-amber-500/10 border-amber-500/30 text-amber-950 dark:text-amber-200 hover:bg-amber-500/15",
  "bg-cyan-500/10 border-cyan-500/30 text-cyan-950 dark:text-cyan-200 hover:bg-cyan-500/15",
  "bg-rose-500/10 border-rose-500/30 text-rose-950 dark:text-rose-200 hover:bg-rose-500/15",
  "bg-indigo-500/10 border-indigo-500/30 text-indigo-950 dark:text-indigo-200 hover:bg-indigo-500/15",
];

export function VisualTimetableTab({
  summary,
  validationResult,
}: VisualTimetableTabProps) {
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [searchQuery, setSearchQuery] = useState("");

  // Map courses and classes into timetable slots
  const scheduledSlots: TimetableSlotItem[] = useMemo(() => {
    if (!summary || !summary.courses) return [];

    const slots: TimetableSlotItem[] = [];
    const rooms = ["Labtek V 7601", "Labtek V 7602", "Labtek VIII 9101", "GKU Barat 9211"];

    summary.courses.forEach((course, courseIdx) => {
      const sksMatch = course.title.match(/(\d+)\s*(?:sks|credit)/i);
      const sksNum = sksMatch ? parseInt(sksMatch[1], 10) : 3;
      const duration = Math.min(Math.max(sksNum, 2), 3);

      // Deterministically position courses across Mon-Fri
      const day = courseIdx % 5;
      const slotIndex = Math.floor(courseIdx / 5);
      const startHours = [7, 10, 13, 15];
      const startHour = startHours[slotIndex % startHours.length];
      const room = rooms[courseIdx % rooms.length];
      const instructor =
        course.instructors[0] || "Tim Dosen " + course.course_number;
      const colorClass = COLOR_PALETTES[courseIdx % COLOR_PALETTES.length];

      slots.push({
        courseNumber: course.course_number,
        title: course.title || "Mata Kuliah Kurikulum",
        sks: `${sksNum} SKS`,
        day,
        startHour,
        durationHours: duration,
        room,
        instructor,
        colorClass,
      });
    });

    return slots;
  }, [summary]);

  const filteredSlots = useMemo(() => {
    if (!searchQuery.trim()) return scheduledSlots;
    const q = searchQuery.toLowerCase();
    return scheduledSlots.filter(
      (s) =>
        s.courseNumber.toLowerCase().includes(q) ||
        s.title.toLowerCase().includes(q) ||
        s.instructor.toLowerCase().includes(q) ||
        s.room.toLowerCase().includes(q)
    );
  }, [scheduledSlots, searchQuery]);

  if (!summary || summary.total_courses === 0) {
    return (
      <div className="p-12 text-center bg-card border border-border rounded-xl space-y-3">
        <div className="mx-auto h-12 w-12 rounded-xl bg-muted/60 flex items-center justify-center text-muted-foreground">
          <CalendarIcon className="h-6 w-6" />
        </div>
        <h3 className="text-sm font-semibold text-foreground">
          No Timetable Data Available
        </h3>
        <p className="text-xs text-muted-foreground max-w-sm mx-auto">
          Upload a curriculum document or semester schedule in the chat pane to
          extract offerings and generate the weekly timetable grid.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Top Controls Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 rounded-xl bg-card border border-border">
        {/* Search Input */}
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search class, room, or lecturer..."
            className="w-full text-xs rounded-lg border border-input bg-background pl-8 pr-3 py-1.5 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-emerald-500/40"
          />
        </div>

        {/* View Mode Toggle */}
        <div className="flex items-center gap-1 p-1 rounded-lg bg-muted/40 border border-border">
          <button
            type="button"
            onClick={() => setViewMode("grid")}
            className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
              viewMode === "grid"
                ? "bg-background shadow-xs text-foreground font-semibold"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <CalendarIcon className="h-3.5 w-3.5" />
            <span>Weekly Grid</span>
          </button>
          <button
            type="button"
            onClick={() => setViewMode("list")}
            className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-md transition-colors ${
              viewMode === "list"
                ? "bg-background shadow-xs text-foreground font-semibold"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <List className="h-3.5 w-3.5" />
            <span>Course List ({summary.total_courses})</span>
          </button>
        </div>
      </div>

      {/* View Mode Content */}
      {viewMode === "list" ? (
        <CurriculumOfferingsTable
          summary={summary}
          validationResult={validationResult}
        />
      ) : (
        /* Visual Calendar Grid Monday-Friday 07:00-18:00 */
        <div className="bg-card border border-border rounded-xl shadow-xs overflow-hidden">
          {/* Day Headers */}
          <div className="grid grid-cols-6 border-b border-border bg-muted/30 text-xs font-semibold text-muted-foreground text-center">
            <div className="py-2.5 px-2 border-r border-border text-[11px]">
              Time (WIB)
            </div>
            {DAYS.map((day) => (
              <div
                key={day.id}
                className="py-2.5 px-2 border-r last:border-r-0 border-border"
              >
                <span className="text-foreground">{day.idName}</span>
                <span className="hidden sm:inline text-[10px] text-muted-foreground ml-1 font-normal">
                  ({day.name})
                </span>
              </div>
            ))}
          </div>

          {/* Time Rows & Day Columns Grid */}
          <div className="relative">
            {HOURS.map((hour) => (
              <div
                key={hour}
                className="grid grid-cols-6 border-b border-border/60 min-h-[64px]"
              >
                {/* Time Label */}
                <div className="py-2 px-2 border-r border-border/60 text-[10px] font-mono text-muted-foreground text-right pr-3 bg-muted/10 flex items-start justify-end">
                  <span>{String(hour).padStart(2, "0")}:00</span>
                </div>

                {/* 5 Day Cells */}
                {DAYS.map((day) => {
                  const itemsInSlot = filteredSlots.filter(
                    (s) => s.day === day.id && s.startHour === hour
                  );

                  return (
                    <div
                      key={day.id}
                      className="p-1 border-r last:border-r-0 border-border/40 relative min-h-[64px]"
                    >
                      {itemsInSlot.map((item, idx) => (
                        <div
                          key={idx}
                          className={`p-2 rounded-lg border text-xs shadow-2xs transition-all duration-150 space-y-1 ${item.colorClass}`}
                        >
                          <div className="flex items-center justify-between gap-1">
                            <span className="font-mono font-bold text-[11px] truncate">
                              {item.courseNumber}
                            </span>
                            <span className="text-[10px] px-1 py-0.2 rounded bg-background/60 border border-current font-medium">
                              {item.sks}
                            </span>
                          </div>

                          <p className="font-medium text-[11px] line-clamp-1 leading-tight">
                            {item.title}
                          </p>

                          <div className="flex flex-col gap-0.5 text-[10px] opacity-80 pt-0.5">
                            <div className="flex items-center gap-1 truncate">
                              <MapPin className="h-2.5 w-2.5 shrink-0" />
                              <span className="truncate">{item.room}</span>
                            </div>
                            <div className="flex items-center gap-1 truncate">
                              <User className="h-2.5 w-2.5 shrink-0" />
                              <span className="truncate">{item.instructor}</span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
