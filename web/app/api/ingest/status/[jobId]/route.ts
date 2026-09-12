import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/server-proxy";

export async function GET(
  request: NextRequest,
  { params }: { params: { jobId: string } }
) {
  return proxyToGateway(
    request,
    `/api/ingest/status/${encodeURIComponent(params.jobId)}`
  );
}
