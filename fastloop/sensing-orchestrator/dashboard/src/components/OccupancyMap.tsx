import { cn } from "@/lib/utils";

interface ChannelData {
  interference_power: number;
  noise_power: number;
  wifi_power: number;
  inference: {
    bluetooth: number;
    empty: number;
    wifi: number;
    zigbee: number;
    microwave: number;
  };
  cusum_flag: number;
  channel: number;
}

interface SpectrumOccupancyMapProps {
  data: ChannelData[];
  className?: string;
  onChannelSelect?: (channel: number) => void
}

export function SpectrumOccupancyMap({
  data,
  className,
  onChannelSelect
}: SpectrumOccupancyMapProps) {

  const sortedData = [...data].sort((a, b) => a.channel - b.channel);

  const getTotalPower = (channel: ChannelData) => {
    return channel.interference_power + channel.noise_power + channel.wifi_power;
  };

  const channelWidth = "w-12";

  return (
    <div className={cn(
      "bg-white dark:bg-neutral-900 rounded-lg border border-neutral-200 dark:border-neutral-800 p-6",
      "transition-all duration-300 hover:shadow-md",
      "hover:shadow-md hover:border-neutral-300 dark:hover:border-neutral-700",
      className
    )}>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-xl font-semibold text-neutral-900 dark:text-white">
            Spectrum Power Map
          </h3>
          <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
            2.4 GHz Band - Channels 1 to {sortedData.length}
          </p>
        </div>
      </div>

      <div className="mb-8">
        <div className="flex justify-between mb-2 px-2">
          {sortedData.map((channel) => {
            return (
              <div
                key={channel.channel}
                className={cn(
                  "text-center text-xs font-medium text-neutral-600 dark:text-neutral-400",
                  channelWidth
                )}
              >
                {channel.channel}
              </div>
            )
          })}
        </div>

        <div className="flex items-end justify-between px-2 h-32">
          {sortedData.map((channel) => {
            const totalPower = getTotalPower(channel);
            const interferencePower = channel.interference_power;
            const noisePower = channel.noise_power;
            const wifiPower = channel.wifi_power;

            return (
              <div
                key={channel.channel}
                className="flex flex-col items-center justify-end group relative h-full"
                onClick={() => onChannelSelect ? onChannelSelect(channel.channel) : null}
              >
                <div
                  className={cn(
                    "w-10 rounded-t transition-all duration-500 ease-out",
                    "group-hover:brightness-110 group-hover:shadow-lg",
                    "bg-green-400 dark:bg-green-600"
                  )}
                  style={{ height: `${(wifiPower / totalPower) * 128}px` }}
                />
                <div
                  className={cn(
                    "w-10 rounded-t transition-all duration-500 ease-out",
                    "group-hover:brightness-110 group-hover:shadow-lg",
                    "bg-blue-400 dark:bg-blue-600"
                  )}
                  style={{ height: `${(noisePower / totalPower) * 128}px` }}
                />
                <div
                  className={cn(
                    "w-10 rounded-b transition-all duration-500 ease-out",
                    "group-hover:brightness-110 group-hover:shadow-lg",
                    "bg-orange-400 dark:bg-orange-600"
                  )}
                  style={{ height: `${(interferencePower / totalPower) * 128}px` }}
                />

                <div className="absolute bottom-full mb-2 hidden group-hover:block z-10">
                  <div className="bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 text-xs rounded px-3 py-2 whitespace-nowrap shadow-lg">
                    <div className="font-semibold text-center">Channel {channel.channel}</div>
                    <div className="border-t border-neutral-700 dark:border-neutral-300 my-1"></div>
                    <div>Total: {(totalPower * 1000).toFixed(3)} mW</div>
                    <div>Wifi: {(wifiPower * 1000).toFixed(3)} mW</div>
                    <div>Interference: {(interferencePower * 1000).toFixed(3)} mW</div>
                    <div>Noise: {(noisePower * 1000).toFixed(3)} mW</div>
                  </div>
                  <div className="w-2 h-2 bg-neutral-900 dark:bg-white rotate-45 absolute -bottom-1 left-1/2 -translate-x-1/2"></div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="w-full h-0.5 bg-neutral-300 dark:bg-neutral-700 mt-4"></div>
      </div>

      <div className="border-t border-neutral-200 dark:border-neutral-800 pt-4">
        <h4 className="text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-3">
          Power Level Legend
        </h4>
        <div className="flex flex-wrap gap-4 items-center">
          <div className="flex items-center space-x-2">
            <div className="w-3 h-3 bg-green-400 dark:bg-green-600 rounded" />
            <span className="text-xs text-neutral-600 dark:text-neutral-400">Wifi Power</span>
          </div>
          <div className="flex items-center space-x-2">
            <div className="w-3 h-3 bg-orange-400 dark:bg-orange-600 rounded" />
            <span className="text-xs text-neutral-600 dark:text-neutral-400">Interference Power</span>
          </div>
          <div className="flex items-center space-x-2">
            <div className="w-3 h-3 bg-blue-400 dark:bg-blue-600 rounded" />
            <span className="text-xs text-neutral-600 dark:text-neutral-400">Noise Power</span>
          </div>
        </div>
        <div className="mt-3 p-2 bg-blue-50 dark:bg-blue-900/20 rounded border border-blue-200 dark:border-blue-800">
          <p className="text-xs text-blue-700 dark:text-blue-300 text-center">
            💡 Click on any channel bar to view detailed analysis
          </p>
        </div>
      </div>
    </div>
  );
}