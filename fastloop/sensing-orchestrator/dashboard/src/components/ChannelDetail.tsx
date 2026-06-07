// components/channel-detail-panel.tsx
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

interface ChannelDetailPanelProps {
  channel: ChannelData | null;
  className?: string;
}

export function ChannelDetailPanel({ channel, className }: ChannelDetailPanelProps) {
  if (!channel) {
    return (
      <div className={cn(
        "bg-white dark:bg-neutral-950 rounded-lg border border-neutral-200 dark:border-neutral-800 p-8",
        "flex flex-col items-center justify-center min-h-[400px] text-center",
        "hover:shadow-md hover:border-neutral-300 dark:hover:border-neutral-700",
        className
      )}>
        <div className="text-neutral-400 dark:text-neutral-600 mb-4">
          <svg className="w-16 h-16 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <h3 className="text-lg font-semibold text-neutral-600 dark:text-neutral-400 mb-2">
          No Channel Selected
        </h3>
        <p className="text-sm text-neutral-500 dark:text-neutral-400 max-w-sm">
          Click on any channel in the Spectrum Power Map to view detailed analysis, power distribution, and technology inference data.
        </p>
      </div>
    );
  }

  const totalPower = channel.interference_power + channel.noise_power + channel.wifi_power;

  const getTechColor = (tech: string) => {
    const colors = {
      wifi: 'bg-red-500',
      bluetooth: 'bg-blue-500',
      zigbee: 'bg-green-500',
      microwave: 'bg-yellow-500',
      empty: 'bg-neutral-300 dark:bg-neutral-700'
    };
    return colors[tech as keyof typeof colors] || 'bg-neutral-400';
  };

  const getTechName = (tech: string) => {
    const names = {
      wifi: 'Wi-Fi',
      bluetooth: 'Bluetooth',
      zigbee: 'Zigbee',
      microwave: 'Microwave',
      empty: 'Empty'
    };
    return names[tech as keyof typeof names] || tech;
  };

  const inferenceEntries = Object.entries(channel.inference)
    .sort(([, a], [, b]) => b - a)
    .filter(([tech]) => tech !== 'empty' || channel.inference.empty > 0.01);

  return (
    <div className={cn(
      "bg-white dark:bg-neutral-950 rounded-lg border border-neutral-200 dark:border-neutral-800 p-6",
      "transition-all duration-300 hover:shadow-md",
      "hover:shadow-md hover:border-neutral-300 dark:hover:border-neutral-700",
      className
    )}>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-xl font-semibold text-neutral-900 dark:text-white">
            Channel {channel.channel} Analysis
          </h3>
          <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
            Detailed spectrum analysis
          </p>
        </div>
        <div className={cn(
          "px-3 py-1 rounded-full text-xs font-medium",
          channel.cusum_flag === 1
            ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200 border border-yellow-200 dark:border-yellow-800"
            : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200 border border-green-200 dark:border-green-800"
        )}>
          {channel.cusum_flag === 1 ? 'Anomaly Detected' : 'Normal'}
        </div>
      </div>

      {/* Power Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="text-center p-4 bg-green-50 dark:bg-green-950 rounded-lg">
          <div className="text-2xl font-bold text-green-700 dark:text-green-300">
            {(channel.wifi_power * 1000).toFixed(2)}
          </div>
          <div className="text-sm text-green-700 dark:text-green-300 mt-1">
            Wifi Power (mW)
          </div>
        </div>
        <div className="text-center p-4 bg-orange-50 dark:bg-orange-950 rounded-lg">
          <div className="text-2xl font-bold text-orange-700 dark:text-orange-300">
            {(channel.interference_power * 1000).toFixed(2)}
          </div>
          <div className="text-sm text-orange-600 dark:text-orange-400 mt-1">
            Interference (mW)
          </div>
        </div>
        <div className="text-center p-4 bg-blue-50 dark:bg-blue-950 rounded-lg">
          <div className="text-2xl font-bold text-blue-700 dark:text-blue-300">
            {(channel.noise_power * 1000).toFixed(2)}
          </div>
          <div className="text-sm text-blue-600 dark:text-blue-400 mt-1">
            Noise (mW)
          </div>
        </div>
      </div>

      {/* Power Distribution Bar */}
      <div className="mb-6">
        <div className="flex justify-between text-sm text-neutral-60 dark:text-neutral-400 mb-2">
          <span>Power Distribution</span>
          <span>Total: {(totalPower * 1000).toFixed(2)} mW</span>
        </div>
        <div className="w-full h-4 flex items-center bg-neutral-200 dark:bg-neutral-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-400"
            style={{ width: `${(channel.noise_power / totalPower) * 100}%` }}
          />
          <div
            className="h-full bg-green-400"
            style={{ width: `${(channel.wifi_power / totalPower) * 100}%` }}
          />
          <div
            className="h-full bg-orange-500"
            style={{ width: `${(channel.interference_power / totalPower) * 100}%` }}
          />
        </div>
        <div className="flex justify-between text-xs text-neutral-500 dark:text-neutral-400 mt-2">
          <div className="flex items-center">
            <div className="w-2 h-2 bg-blue-400 rounded mr-1"></div>
            <span>Noise: {((channel.noise_power / totalPower) * 100).toFixed(1)}%</span>
          </div>
          <div className="flex items-center">
            <div className="w-2 h-2 bg-green-400 rounded mr-1"></div>
            <span>Wifi: {((channel.wifi_power / totalPower) * 100).toFixed(1)}%</span>
          </div>
          <div className="flex items-center">
            <div className="w-2 h-2 bg-orange-500 rounded mr-1"></div>
            <span>Interference: {((channel.interference_power / totalPower) * 100).toFixed(1)}%</span>
          </div>
        </div>
      </div>

      {/* Inference Probabilities */}
      <div>
        <h4 className="text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-3">
          Technology Inference
        </h4>
        <div className="space-y-2">
          {inferenceEntries.map(([tech, probability]) => (
            <div key={tech} className="flex items-center justify-between group">
              <div className="flex items-center space-x-3 flex-1">
                <div className={cn(
                  "w-3 h-3 rounded-full shrink-0",
                  getTechColor(tech)
                )} />
                <span className="text-sm text-neutral-600 dark:text-neutral-400">
                  {getTechName(tech)}
                </span>
              </div>

              <div className="flex items-center space-x-3">
                <div className="w-24 bg-neutral-200 dark:bg-neutral-700 rounded-full h-2">
                  <div
                    className={cn(
                      "h-2 rounded-full transition-all duration-500",
                      getTechColor(tech)
                    )}
                    style={{ width: `${probability * 100}%` }}
                  />
                </div>
                <span className="text-sm font-medium text-neutral-900 dark:text-white w-12 text-right">
                  {(probability * 100).toFixed(1)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}