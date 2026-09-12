import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/server-proxy";

export async function GET(
  request: NextRequest,
  { params }: { params: { filename: string } }
) {
  return proxyToGateway(
    request,
    `/api/reports/${encodeURIComponent(params.filename)}`
  );
}
