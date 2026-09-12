import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/server-proxy";

export async function POST(request: NextRequest) {
  return proxyToGateway(request, "/api/ingest/upload");
}
