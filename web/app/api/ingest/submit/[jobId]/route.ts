import { NextRequest } from "next/server";
import { proxyToGateway } from "@/lib/server-proxy";

export async function POST(
  request: NextRequest,
  { params }: { params: { jobId: string } }
) {
  return proxyToGateway(
    request,
    `/api/ingest/submit/${encodeURIComponent(params.jobId)}`
  );
}
