import { NextRequest, NextResponse } from "next/server";
import {
  ADMIN_COOKIE_NAME,
  getExpectedSessionToken,
  isAdminAuthRequired,
  isUserAuthenticated,
  verifyAdminPassword,
} from "@/lib/server-proxy";

/**
 * Check admin authentication status and whether password protection is active.
 */
export async function GET(request: NextRequest) {
  const required = isAdminAuthRequired();
  const authenticated = isUserAuthenticated(request);

  return NextResponse.json({
    required,
    authenticated,
  });
}

/**
 * Process administrator login or logout.
 */
export async function POST(request: NextRequest) {
  let body: Record<string, any> = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }

  const action = body.action || "login";

  // Logout action: clear session cookie
  if (action === "logout") {
    const response = NextResponse.json({
      success: true,
      message: "Logged out successfully.",
    });
    response.cookies.delete(ADMIN_COOKIE_NAME);
    return response;
  }

  // If password protection is not configured in env, automatically approve
  if (!isAdminAuthRequired()) {
    return NextResponse.json({
      success: true,
      message: "Admin password protection is not enabled.",
    });
  }

  const password = body.password;
  if (!password || typeof password !== "string") {
    return NextResponse.json(
      { detail: "Password is required for admin login." },
      { status: 400 }
    );
  }

  if (!verifyAdminPassword(password)) {
    return NextResponse.json(
      { detail: "Invalid admin password. Access denied." },
      { status: 401 }
    );
  }

  const token = getExpectedSessionToken();
  if (!token) {
    return NextResponse.json(
      { detail: "Server authentication error." },
      { status: 500 }
    );
  }

  const response = NextResponse.json({
    success: true,
    message: "Admin authentication successful.",
  });

  response.cookies.set(ADMIN_COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 7, // 7 days
  });

  return response;
}
