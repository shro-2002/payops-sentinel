import { ConsoleHeader } from "@/components/ConsoleHeader";
import { HomeConsole } from "@/components/HomeConsole";

export default function Home() {
  return (
    <>
      <ConsoleHeader />
      <main id="main" className="mx-auto max-w-[1400px] px-4 py-6">
        <HomeConsole />
      </main>
    </>
  );
}
