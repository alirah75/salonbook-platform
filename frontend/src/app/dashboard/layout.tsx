import { WorkspaceShell } from "@/components/dashboard/workspace";
export default function Layout({ children }: { children: React.ReactNode }) {
  return <WorkspaceShell>{children}</WorkspaceShell>;
}
