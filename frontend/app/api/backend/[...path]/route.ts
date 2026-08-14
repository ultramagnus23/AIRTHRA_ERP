// Catch-all proxy: /api/backend/<anything> -> FastAPI's /<anything>.
//
// Every REST call lib/api.ts makes goes through here so the browser
// only ever needs the same-origin httpOnly cookie (sent automatically)
// rather than the raw JWT. This route reads that cookie server-side,
// attaches it as `Authorization: Bearer <token>` to the upstream
// FastAPI request, and streams the response back unchanged (status,
// JSON body). Any other route group (admin/ERP/driver) built on this
// scaffold should reuse this same proxy rather than adding a new one.
import { NextRequest, NextResponse } from "next/server";
import { getRawToken } from "@/lib/session";

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";

async function proxy(req: NextRequest, path: string[]) {
  const token = await getRawToken();
  if (!token) {
    return NextResponse.json({ detail: "not authenticated" }, { status: 401 });
  }

  const upstreamUrl = `${API_BASE}/${path.join("/")}${req.nextUrl.search}`;
  const init: RequestInit = {
    method: req.method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": req.headers.get("content-type") ?? "application/json",
    },
    cache: "no-store",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    const body = await req.text();
    if (body) init.body = body;
  }

  const upstream = await fetch(upstreamUrl, init);
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
  });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
export async function PUT(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
export async function PATCH(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
export async function DELETE(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
