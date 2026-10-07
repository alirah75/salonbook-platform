import { EditorialPanel } from "@/components/shell";
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="container auth-grid">
      <section className="auth-card">{children}</section>
      <EditorialPanel compact />
    </div>
  );
}
