/**
 * UniTime AI Ingestion Gateway API Client.
 *
 * Production-ready typed client providing seamless integration with the FastAPI
 * ai-gateway backend (server.py) and UniTime server synchronization.
 */

// ============================================================================
// Types & Interfaces
// ============================================================================

export interface UniTimeStatus {
  connected: boolean;
  url: string;
  details?: Record<string, unknown> | null;
  error?: string | null;
}

export interface HealthResponse {
  status: string;
  provider: string;
  unitime: UniTimeStatus;
  timestamp: string;
}

export interface UploadOptions {
  provider?: "gemini" | "openai" | "openrouter" | "custom" | "mock" | string;
  model?: string;
  dryRun?: boolean;
  strict?: boolean;
  renderImages?: boolean;
  sync?: boolean;
}

export interface UploadResponse {
  job_id: string;
  filename: string;
  status: string;
  message: string;
}

export interface ProgressMetrics {
  stage: string;
  current_chunk: number;
  total_chunks: number;
  percent: number;
  message: string;
}

export interface CourseSummaryItem {
  course_number: string;
  title: string;
  subject_area: string;
  configurations_count: number;
  classes_count: number;
  instructors: string[];
}

export interface CourseSummary {
  academic_session: {
    year?: string;
    term?: string;
    campus?: string;
    [key: string]: unknown;
  };
  department: {
    code?: string;
    name?: string;
    [key: string]: unknown;
  };
  subject_area: {
    abbreviation?: string;
    title?: string;
    [key: string]: unknown;
  };
  total_courses: number;
  total_configurations: number;
  total_classes: number;
  total_distribution_constraints: number;
  courses: CourseSummaryItem[];
}

export interface AmbiguityItem {
  id: string;
  issue_signature?: string;
  type: string;
  question: string;
  options?: string[];
  suggested_resolution?: string;
  context?: Record<string, unknown>;
}

export interface ValidationErrorItem {
  path?: string;
  validator?: string;
  message: string;
}

export interface ValidationResult {
  is_valid: boolean;
  errors_count: number;
  warnings_count: number;
  errors?: ValidationErrorItem[];
  warnings?: string[];
}

export type JobState =
  | "queued"
  | "processing"
  | "waiting_disambiguation"
  | "completed"
  | "failed";

export interface JobStatusResponse {
  job_id: string;
  state: JobState;
  filename: string;
  progress: ProgressMetrics;
  ambiguities: AmbiguityItem[];
  course_summary?: CourseSummary | null;
  validation_result?: ValidationResult | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ResolveResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface SubmitRequest {
  unitime_url?: string;
}

export interface SubmitResponse {
  job_id: string;
  status: string;
  http_status_code: number;
  is_success: boolean;
  summary: string;
  details?: Record<string, unknown> | null;
}

export interface ReportItem {
  filename: string;
  size_bytes: number;
  created_at: string;
  modified_at: string;
}

export interface ReportDetailResponse {
  filename: string;
  content: string;
  size_bytes: number;
  modified_at: string;
}

// ============================================================================
// Custom Error Class
// ============================================================================

export class ApiError extends Error {
  statusCode: number;
  detail: string;

  constructor(statusCode: number, detail: string) {
    super(`API Error [${statusCode}]: ${detail}`);
    this.name = "ApiError";
    this.statusCode = statusCode;
    this.detail = detail;
  }
}

// ============================================================================
// Configuration & Base URL
// ============================================================================

export function getApiBaseUrl(): string {
  // Use environment variable if provided, with safe defaults
  if (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL.replace(/\/+$/, "");
  }

  // In browser development, if no env var, default to production endpoint or localhost
  if (typeof window !== "undefined") {
    if (
      window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1"
    ) {
      return "http://localhost:8005";
    }
  }

  return "https://tencent-vps.hanavy.online/unitime-api";
}

// Helper for unified fetch and JSON error handling
async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;

  const defaultHeaders: Record<string, string> = {};
  if (!(options.body instanceof FormData)) {
    defaultHeaders["Accept"] = "application/json";
    if (options.body && typeof options.body === "string") {
      defaultHeaders["Content-Type"] = "application/json";
    }
  }

  const response = await fetch(url, {
    ...options,
    headers: {
      ...defaultHeaders,
      ...options.headers,
    },
  });

  if (!response.ok) {
    let errorDetail = `Request failed with status ${response.status}`;
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || errJson.message || JSON.stringify(errJson);
    } catch {
      const text = await response.text().catch(() => "");
      if (text) errorDetail = text;
    }
    throw new ApiError(response.status, errorDetail);
  }

  // Handle empty responses
  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}

// ============================================================================
// API Client Functions
// ============================================================================

/**
 * Check gateway health and connectivity to the UniTime server.
 */
export async function checkHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health", {
    method: "GET",
    cache: "no-store",
  });
}

/**
 * Upload a document (PDF, Excel, CSV, JSON, TXT) and trigger ingestion pipeline.
 */
export async function uploadFile(
  file: File,
  options: UploadOptions = {}
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file, file.name);

  if (options.provider) {
    formData.append("provider", options.provider);
  }
  if (options.model) {
    formData.append("model", options.model);
  }
  if (options.dryRun !== undefined) {
    formData.append("dry_run", String(options.dryRun));
  }
  if (options.strict !== undefined) {
    formData.append("strict", String(options.strict));
  }
  if (options.renderImages !== undefined) {
    formData.append("render_images", String(options.renderImages));
  }

  const queryParams = new URLSearchParams();
  if (options.sync) {
    queryParams.set("sync", "true");
  }
  const queryString = queryParams.toString();
  const endpoint = `/api/ingest/upload${queryString ? `?${queryString}` : ""}`;

  return request<UploadResponse>(endpoint, {
    method: "POST",
    body: formData,
  });
}

/**
 * Fetch real-time job state, execution progress, ambiguities, and curriculum summary.
 */
export async function getStatus(jobId: string): Promise<JobStatusResponse> {
  if (!jobId || !jobId.trim()) {
    throw new ApiError(400, "jobId is required");
  }
  return request<JobStatusResponse>(`/api/ingest/status/${encodeURIComponent(jobId)}`, {
    method: "GET",
    cache: "no-store",
  });
}

/**
 * Provide administrative resolution for pending scheduling/capacity ambiguities.
 */
export async function resolveDisambiguation(
  jobId: string,
  resolutions: Record<string, string> | string,
  sync = false
): Promise<ResolveResponse> {
  if (!jobId || !jobId.trim()) {
    throw new ApiError(400, "jobId is required");
  }

  const body =
    typeof resolutions === "string"
      ? { resolution: resolutions }
      : { resolutions };

  const query = sync ? "?sync=true" : "";
  return request<ResolveResponse>(
    `/api/ingest/resolve/${encodeURIComponent(jobId)}${query}`,
    {
      method: "POST",
      body: JSON.stringify(body),
    }
  );
}

/**
 * Submit the extracted canonical timetable payload directly to the UniTime REST API.
 */
export async function submitToUniTime(
  jobId: string,
  options?: SubmitRequest
): Promise<SubmitResponse> {
  if (!jobId || !jobId.trim()) {
    throw new ApiError(400, "jobId is required");
  }

  return request<SubmitResponse>(
    `/api/ingest/submit/${encodeURIComponent(jobId)}`,
    {
      method: "POST",
      body: JSON.stringify(options || {}),
    }
  );
}

/**
 * List all generated executive markdown audit reports.
 */
export async function getReports(): Promise<ReportItem[]> {
  return request<ReportItem[]>("/api/reports", {
    method: "GET",
    cache: "no-store",
  });
}

/**
 * Retrieve raw markdown content for an audit report.
 */
export async function getReportContent(filename: string): Promise<string> {
  if (!filename || !filename.trim()) {
    throw new ApiError(400, "filename is required");
  }

  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/reports/${encodeURIComponent(filename)}?raw=true`;

  const response = await fetch(url, {
    method: "GET",
    headers: {
      Accept: "text/markdown, text/plain, */*",
    },
    cache: "no-store",
  });

  if (!response.ok) {
    let errorDetail = `Failed to fetch report content (${response.status})`;
    try {
      const err = await response.json();
      errorDetail = err.detail || errorDetail;
    } catch {
      // ignore
    }
    throw new ApiError(response.status, errorDetail);
  }

  return response.text();
}
