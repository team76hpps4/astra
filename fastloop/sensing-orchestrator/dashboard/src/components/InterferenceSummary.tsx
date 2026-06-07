import { cn } from "@/lib/utils";

interface ChannelData {
  interference_power: number;
  noise_power: number;
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

interface InterferenceTypeSummaryProps {
  data: ChannelData[];
  className?: string;
}

export function InterferenceTypeSummary({ data, className }: InterferenceTypeSummaryProps) {
  // Calculate interference type statistics
  const calculateInterferenceStats = () => {
    const stats = {
      wifi: { count: 0, totalPower: 0, probability: 0 },
      bluetooth: { count: 0, totalPower: 0, probability: 0 },
      zigbee: { count: 0, totalPower: 0, probability: 0 },
      microwave: { count: 0, totalPower: 0, probability: 0 },
      empty: { count: 0, totalPower: 0, probability: 0 }
    };

    data.forEach(channel => {
      const inferences = channel.inference;
      const dominant = Object.entries(inferences).reduce((a, b) =>
        a[1] > b[1] ? a : b
      )[0] as keyof typeof stats;

      stats[dominant].count++;
      stats[dominant].totalPower += channel.interference_power;
      stats[dominant].probability += inferences[dominant];
    });

    // Calculate average probability
    Object.keys(stats).forEach(key => {
      const statKey = key as keyof typeof stats;
      if (stats[statKey].count > 0) {
        stats[statKey].probability = stats[statKey].probability / stats[statKey].count;
      }
    });

    return stats;
  };

  const stats = calculateInterferenceStats();
  const totalChannels = data.length;

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

  const sortedStats = Object.entries(stats)
    .filter(([tech]) => tech !== 'empty') // Optionally exclude empty channels
    .sort(([, a], [, b]) => b.count - a.count);

  return (
    <div className={cn(
      "bg-white dark:bg-neutral-950 rounded-lg border border-neutral-200 dark:border-neutral-800 p-6",
      "transition-all duration-300 hover:shadow-md",
      "hover:shadow-md hover:border-neutral-300 dark:hover:border-neutral-700",
      className
    )}>
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-xl font-semibold text-neutral-900 dark:text-white">
          Interference Sources
        </h3>
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Dominant by Channel
        </p>
      </div>

      <div className="space-y-4">
        {sortedStats.map(([tech, stat]) => (
          <div key={tech} className="flex items-center justify-between group">
            <div className="flex items-center space-x-3 flex-1 min-w-0">
              <div className={cn(
                "w-3 h-3 rounded-full shrink-0",
                getTechColor(tech)
              )} />
              <span className="text-sm font-medium text-neutral-700 dark:text-neutral-300 truncate">
                {getTechName(tech)}
              </span>
            </div>

            <div className="flex items-center space-x-4 shrink-0">
              <div className="text-right">
                <div className="text-sm font-semibold text-neutral-900 dark:text-white">
                  {stat.count}
                </div>
                <div className="text-xs text-neutral-500 dark:text-neutral-400">
                  channels
                </div>
              </div>

              <div className="w-20 bg-neutral-200 dark:bg-neutral-700 rounded-full h-2">
                <div
                  className={cn(
                    "h-2 rounded-full transition-all duration-500",
                    getTechColor(tech)
                  )}
                  style={{
                    width: `${(stat.count / totalChannels) * 100}%`
                  }}
                />
              </div>

              <div className="text-right w-16">
                <div className="text-sm font-medium text-neutral-600 dark:text-neutral-400">
                  {((stat.count / totalChannels) * 100).toFixed(0)}%
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Summary Footer */}
      <div className="border-t border-neutral-200 dark:border-neutral-800 mt-6 pt-4">
        <div className="flex justify-between text-sm">
          <span className="text-neutral-600 dark:text-neutral-400">
            Total Channels
          </span>
          <span className="font-semibold text-neutral-900 dark:text-white">
            {totalChannels}
          </span>
        </div>
      </div>
    </div>
  );
}