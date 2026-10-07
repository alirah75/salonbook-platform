import type { Metadata } from "next";
import { BookingWizard } from "@/components/booking/wizard";
export const metadata: Metadata = { title: "رزرو نوبت" };
export default function Page() {
  return <BookingWizard />;
}
