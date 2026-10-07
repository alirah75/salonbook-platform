import type { Metadata } from "next";
import { MyAppointments } from "@/components/booking/appointments";
export const metadata: Metadata = { title: "نوبت‌های من" };
export default function Page() {
  return <MyAppointments />;
}
