// components/kpi-card.tsx
import { cn } from "@/lib/utils";

interface KPICardProps {
  title: string;
  value: string;
  subtitle?: string;
  status?: 'optimal' | 'favorable' | 'moderate' | 'critical';
  className?: string;
}

export function KPICard({ title, value, subtitle, status, className }: KPICardProps) {
  const statusConfig = {
    optimal: {
      color: 'bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300 border border-green-200 dark:border-green-800',
      label: 'Optimal'
    },
    favorable: {
      color: 'bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300 border border-neutral-200 dark:border-neutral-700',
      label: 'Favorable'
    },
    moderate: {
      color: 'bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-400 border border-neutral-200 dark:border-neutral-700',
      label: 'Moderate'
    },
    critical: {
      color: 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300 border border-red-200 dark:border-red-800',
      label: 'Critical'
    }
  };

  const currentStatus = status ? statusConfig[status] : null;

  return (
    <div className={cn(
      "bg-white dark:bg-neutral-900 rounded-lg border border-neutral-200 dark:border-neutral-800 p-4",
      "transition-all duration-300 hover:shadow-md hover:border-neutral-300 dark:hover:border-neutral-700",
      "min-w-0 sm:w-full mx-auto sm:mx-0 w-4/5 sm:opacity-100",
      className
    )}>
      <div className="flex flex-col space-y-2">
        <p className="text-xs font-medium text-neutral-600 dark:text-neutral-400 uppercase tracking-wide truncate">
          {title}
        </p>

        <div className="flex items-center justify-between min-w-0">
          <h3 className="text-xl lg:text-2xl font-semibold text-neutral-900 dark:text-white truncate min-w-0 mr-2">
            {value}
          </h3>

          {/* Status badge */}
          {currentStatus && (
            <span className={cn(
              "text-xs font-medium px-2 py-1 rounded-md shrink-0",
              currentStatus.color
            )}>
              {currentStatus.label}
            </span>
          )}
        </div>

        {/* Subtitle */}
        {subtitle && (
          <p className="text-xs text-neutral-500 dark:text-neutral-400 truncate">
            {subtitle}
          </p>
        )}
      </div>

      {/* Subtle hover effect line */}
      <div className={cn(
        "w-0 group-hover:w-full h-0.5 transition-all duration-300 mt-3",
        status === 'optimal' ? "bg-green-600 dark:bg-green-400" :
          status === 'critical' ? "bg-red-600 dark:bg-red-400" :
            "bg-neutral-900 dark:bg-white"
      )} />
    </div>
  );
}