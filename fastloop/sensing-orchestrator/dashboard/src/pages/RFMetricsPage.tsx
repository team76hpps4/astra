import { Header } from "@/components/Header"
import { ModeToggle } from "@/components/ToggleTheme"
import { KPICard } from "@/components/KPICard"
import { useRfData } from "@/contexts/rf-data"
import { SpectrumOccupancyMap } from "@/components/OccupancyMap"
import { useMemo, useState } from "react"
import { InterferenceTypeSummary } from "@/components/InterferenceSummary"
import { ChannelDetailPanel } from "@/components/ChannelDetail"


export default function RFMetricsPage() {
  const { data } = useRfData();
  const [selectedChannel, setSelectedChannel] = useState<number | null>(null);

  const selectedData = useMemo(() => {
    if (!selectedChannel) return null;

    const find = data.find(d => d.channel === selectedChannel);
    if (find) return find;
    return null
  }, [data, selectedChannel])

  return (
    <>
      <Header fixed>
        <h1 className="text-2xl font-semibold w-full text-center">Spectrum Overview</h1>
        <div className='ms-auto flex items-center space-x-4'>
          <ModeToggle />
        </div>
      </Header>

      <main className="min-h-screen bg-gray-50 dark:bg-black pt-12 pb-12">
        <div className="container mx-auto px-6">

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 w-full max-w-7xl mx-auto">
            {/* <div className="flex flex-wrap justify-center gap-4 w-full"> */}
            <KPICard title="Maximum Loaded Channel" value="CH13" subtitle="13mW interference" status="critical" />
            <KPICard title="Recommonded Channel" value="CH12" subtitle="1mW interference" status="optimal" />
            <KPICard title="Maximum Noise Channel" value="CH10" subtitle="1mW noise" status="critical" />
            <KPICard title="Minimum Noise Channel" value="CH8" subtitle="1mW noise" status="optimal" />
          </div>

          <div className="max-w-6xl mt-5 mx-auto w-full">
            <SpectrumOccupancyMap data={data} onChannelSelect={setSelectedChannel} />
          </div>

          <div className="max-w-6xl mx-auto w-full px-2 sm:px-0 mt-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <InterferenceTypeSummary data={data} />

              <ChannelDetailPanel channel={selectedData} />
            </div>
          </div>

          <div className="mt-12 text-center">
            <p className="text-gray-500 dark:text-gray-400 text-sm">
              Last updated: {new Date().toLocaleTimeString()}
            </p>
          </div>
        </div>
      </main>
    </>
  )
}