export type User = {
  id: string;
  tenant_id: string;
  phone: string | null;
  phone_verified: boolean;
  display_name: string;
  roles: string[];
};
export type Session = { user: User; csrf_token: string; expires_at: string };
export type AuthState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "authenticated"; session: Session }
  | { status: "error"; message: string };
