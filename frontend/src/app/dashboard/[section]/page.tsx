import { notFound } from "next/navigation";
import { WorkOverview } from "@/components/dashboard/overview";
import { CatalogPanel } from "@/components/dashboard/catalog";
import { TeamPanel } from "@/components/dashboard/team";
import { SchedulePanel } from "@/components/dashboard/schedule";
import { FinancePanel } from "@/components/dashboard/finance";
import {
  UsersPanel,
  RolesPanel,
  SettingsPanel,
} from "@/components/dashboard/management";
const pages = {
  appointments: WorkOverview,
  catalog: CatalogPanel,
  team: TeamPanel,
  schedule: SchedulePanel,
  finance: FinancePanel,
  users: UsersPanel,
  roles: RolesPanel,
  settings: SettingsPanel,
};
export default async function Page({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  if (!Object.hasOwn(pages, section)) notFound();
  const Component = pages[section as keyof typeof pages];
  return <Component />;
}
