import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/server-proxy";

export async function GET(request: NextRequest) {
  return proxyToGateway(request, "/api/reports");
}
