import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Snapshot } from "../types";

export function WinProbabilityChart({ data }: { data: Snapshot["winProbabilitySeries"] }) {
  return (
    <section className="panel p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="panel-title">Win Probability</h3>
        <span className="text-sm text-muted">Live recalculated leverage curve</span>
      </div>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <defs>
              <linearGradient id="homeFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#6ee7ff" stopOpacity={0.6} />
                <stop offset="95%" stopColor="#6ee7ff" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
            <XAxis dataKey="minute" stroke="#89a3ba" />
            <YAxis stroke="#89a3ba" domain={[0, 1]} tickFormatter={(value) => `${Math.round(value * 100)}%`} />
            <Tooltip
              contentStyle={{
                background: "#0d1c2b",
                borderRadius: 16,
                border: "1px solid rgba(255,255,255,0.08)",
              }}
              formatter={(value: number) => `${Math.round(value * 100)}%`}
            />
            <Area type="monotone" dataKey="home" stroke="#6ee7ff" fill="url(#homeFill)" strokeWidth={3} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

