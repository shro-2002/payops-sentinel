import { notFound } from "next/navigation";

import { ConsoleHeader } from "@/components/ConsoleHeader";
import { IncidentWorkspace } from "@/components/IncidentWorkspace";

export default async function IncidentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(id)) notFound();
  return (
    <>
      <ConsoleHeader />
      <main id="main" className="mx-auto max-w-[1400px] px-4 py-6">
        <IncidentWorkspace id={id} />
      </main>
    </>
  );
}
