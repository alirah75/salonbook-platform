import { notFound } from "next/navigation";
import { AppointmentPage } from "@/components/booking/appointments";
import { uuidPattern } from "@/lib/booking";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!new RegExp(`^${uuidPattern}$`).test(id)) notFound();
  return <AppointmentPage id={id} />;
}
