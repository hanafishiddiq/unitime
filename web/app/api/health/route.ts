import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/server-proxy";

export async function GET(request: NextRequest) {
  // Public health check endpoint for monitoring without admin auth requirement
  return proxyToGateway(request, "/api/health", { checkAuth: false });
}
