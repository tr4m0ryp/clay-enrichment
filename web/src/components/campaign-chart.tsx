"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

const COLORS = [
  "hsl(221, 83%, 53%)",
  "hsl(262, 83%, 58%)",
  "hsl(160, 60%, 45%)",
  "hsl(30, 90%, 55%)",
  "hsl(350, 80%, 55%)",
  "hsl(190, 70%, 50%)",
  "hsl(45, 90%, 50%)",
  "hsl(300, 60%, 50%)",
];

interface TimelineRow {
  campaign_id: string;
  campaign_name: string;
  day: string;
  cumulative: number;
}

interface CampaignChartProps {
  data: TimelineRow[];
}

export function CampaignChart({ data }: CampaignChartProps) {
  if (data.length === 0) {
    return (
      <div className="flex h-[300px] items-center justify-center rounded-md border border-border text-sm text-muted-foreground">
        No email data yet.
      </div>
    );
  }

  const campaigns = [...new Map(data.map((r) => [r.campaign_id, r.campaign_name])).entries()];

  const dayMap = new Map<string, Record<string, number>>();
  for (const row of data) {
    const dayStr = new Date(row.day).toISOString().slice(0, 10);
    if (!dayMap.has(dayStr)) dayMap.set(dayStr, {});
    dayMap.get(dayStr)![row.campaign_id] = row.cumulative;
  }

  const sortedDays = [...dayMap.keys()].sort();

  const chartData = sortedDays.map((day) => {
    const entry: Record<string, string | number> = { day };
    const values = dayMap.get(day)!;
    for (const [id] of campaigns) {
      entry[id] = values[id] ?? 0;
    }
    return entry;
  });

  // Forward-fill: ensure cumulative values carry forward across days
  for (let i = 1; i < chartData.length; i++) {
    for (const [id] of campaigns) {
      if (chartData[i][id] === 0 && chartData[i - 1][id] !== undefined) {
        chartData[i][id] = chartData[i - 1][id];
      }
    }
  }

  return (
    <div className="h-[300px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
          <XAxis
            dataKey="day"
            tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
            tickFormatter={(v: string) => {
              const d = new Date(v);
              return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
            }}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
            allowDecimals={false}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "hsl(var(--background))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 6,
              fontSize: 12,
            }}
            labelFormatter={(v) => {
              const d = new Date(String(v));
              return d.toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
              });
            }}
          />
          <Legend
            wrapperStyle={{ fontSize: 12 }}
          />
          {campaigns.map(([id, name], i) => (
            <Line
              key={id}
              type="monotone"
              dataKey={id}
              name={name}
              stroke={COLORS[i % COLORS.length]}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
