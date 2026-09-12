/**
 * Next.js Backend-For-Frontend (BFF) Server-Side Proxy.
 *
 * Securely proxies client requests from Vercel edge/serverless runtimes to the
 * backend AI Gateway (Tencent VPS) with:
 * 1. Automatic GATEWAY_API_KEY injection into request headers.
 * 2. Optional Admin Passcode protection via ADMIN_ACCESS_PASSWORD and HTTP-only cookies.
 * 3. Robust multipart/form-data streaming and JSON forwarding.
 */

import crypto from "crypto";
import { NextRequest, NextResponse } from "next/server";

export const ADMIN_COOKIE_NAME = "unitime_admin_session";

export interface ProxyOptions {
  checkAuth?: boolean;
  forwardQueryParams?: boolean;
}

/**
 * Determine whether administrative password authentication is required.
 */
export function isAdminAuthRequired(): boolean {
  const adminPass = process.env.ADMIN_ACCESS_PASSWORD;
  return Boolean(adminPass && adminPass.trim().length > 0);
}

/**
 * Derive the expected session token hash from ADMIN_ACCESS_PASSWORD.
 */
export function getExpectedSessionToken(): string | null {
  const adminPass = process.env.ADMIN_ACCESS_PASSWORD;
  if (!adminPass || !adminPass.trim()) {
    return null;
  }
  return crypto
    .createHash("sha256")
    .update(`unitime-bff-session-salt:${adminPass.trim()}`)
    .digest("hex");
}

/**
 * Constant-time comparison between user-provided password and ADMIN_ACCESS_PASSWORD.
 */
export function verifyAdminPassword(providedPassword: string): boolean {
  const expectedPassword = process.env.ADMIN_ACCESS_PASSWORD?.trim();
  if (!expectedPassword) {
    return true; // No password required
  }
  const bufA = Buffer.from(providedPassword.trim());
  const bufB = Buffer.from(expectedPassword);
  if (bufA.length !== bufB.length) {
    return false;
  }
  return crypto.timingSafeEqual(bufA, bufB);
}

/**
 * Validate incoming request session cookie against configured ADMIN_ACCESS_PASSWORD.
 */
export function isUserAuthenticated(request: NextRequest): boolean {
  if (!isAdminAuthRequired()) {
    return true;
  }
  const cookieValue = request.cookies.get(ADMIN_COOKIE_NAME)?.value;
  const expectedToken = getExpectedSessionToken();
  if (!cookieValue || !expectedToken) {
    return false;
  }
  const bufA = Buffer.from(cookieValue.trim());
  const bufB = Buffer.from(expectedToken);
  if (bufA.length !== bufB.length) {
    return false;
  }
  return crypto.timingSafeEqual(bufA, bufB);
}

/**
 * Forward request to backend AI Gateway with private credentials.
 */
export async function proxyToGateway(
  request: NextRequest,
  targetPath: string,
  options: ProxyOptions = {}
): Promise<NextResponse> {
  const { checkAuth = true, forwardQueryParams = true } = options;

  // Enforce session check if admin auth is enabled
  if (checkAuth && !isUserAuthenticated(request)) {
    return NextResponse.json(
      { detail: "Admin authentication required. Please log in." },
      { status: 401 }
    );
  }

  const rawBaseUrl =
    process.env.GATEWAY_API_URL || "https://tencent-vps.hanavy.online/unitime-api";
  const baseUrl = rawBaseUrl.replace(/\/+$/, "");
  const cleanPath = targetPath.startsWith("/") ? targetPath : `/${targetPath}`;
  const targetUrl = new URL(`${baseUrl}${cleanPath}`);

  // Forward URL search/query parameters
  if (forwardQueryParams) {
    request.nextUrl.searchParams.forEach((val, key) => {
      targetUrl.searchParams.set(key, val);
    });
  }

  // Build outbound headers with private server-side secret
  const headers: Record<string, string> = {};
  const gatewayApiKey = process.env.GATEWAY_API_KEY?.trim();
  if (gatewayApiKey) {
    headers["X-API-Key"] = gatewayApiKey;
  }

  const acceptHeader = request.headers.get("accept");
  if (acceptHeader) {
    headers["Accept"] = acceptHeader;
  }

  const method = request.method;
  let body: BodyInit | null = null;

  if (method !== "GET" && method !== "HEAD") {
    const contentType = request.headers.get("content-type") || "";
    if (contentType.includes("multipart/form-data")) {
      // Forward form data directly; fetch manages boundary automatically
      body = await request.formData();
    } else if (
      contentType.includes("application/json") ||
      contentType.includes("text/")
    ) {
      headers["Content-Type"] = contentType;
      body = await request.text();
    } else {
      const arrayBuf = await request.arrayBuffer();
      if (arrayBuf.byteLength > 0) {
        if (contentType) headers["Content-Type"] = contentType;
        body = arrayBuf;
      }
    }
  }

  try {
    const backendRes = await fetch(targetUrl.toString(), {
      method,
      headers,
      body,
      cache: "no-store",
    });

    const resContentType = backendRes.headers.get("content-type") || "";

    if (resContentType.includes("application/json")) {
      const data = await backendRes.json();
      return NextResponse.json(data, { status: backendRes.status });
    }

    const textPayload = await backendRes.text();
    return new NextResponse(textPayload, {
      status: backendRes.status,
      headers: {
        "content-type": resContentType || "text/plain; charset=utf-8",
      },
    });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    console.error(`BFF Proxy forward failure to ${targetUrl}:`, errMsg);
    return NextResponse.json(
      {
        detail: `Failed to connect to backend gateway at ${baseUrl}: ${errMsg}`,
      },
      { status: 502 }
    );
  }
}
