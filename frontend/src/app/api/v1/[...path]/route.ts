import { devProxy } from "@/lib/dev-proxy";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ path: string[] }> };
async function proxy(request: Request, context: Context) {
  return devProxy(request, (await context.params).path);
}
export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
};
