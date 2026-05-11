import type { TeamProjection } from "../types";

type Props = {
  homeTeam: TeamProjection;
  awayTeam: TeamProjection;
};

export function QuarterProjectionTable({ homeTeam, awayTeam }: Props) {
  return (
    <section className="panel p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="panel-title">Quarter Projections</h3>
        <span className="text-sm text-muted">Updated by pace, pressure, and rotation context</span>
      </div>
      <div className="overflow-hidden rounded-2xl border border-white/6">
        <table className="w-full text-left text-sm">
          <thead className="bg-black/25 text-muted">
            <tr>
              <th className="px-4 py-3">Team</th>
              <th className="px-4 py-3">Q1</th>
              <th className="px-4 py-3">Q2</th>
              <th className="px-4 py-3">Q3</th>
              <th className="px-4 py-3">Q4</th>
              <th className="px-4 py-3">Final</th>
            </tr>
          </thead>
          <tbody>
            {[awayTeam, homeTeam].map((team) => (
              <tr key={team.teamId} className="border-t border-white/6 bg-white/[0.02]">
                <td className="px-4 py-4 font-medium text-white">{team.teamName}</td>
                {team.projectedScore.map((score, index) => (
                  <td key={`${team.teamId}-${index}`} className="px-4 py-4 text-ink">
                    {score}
                  </td>
                ))}
                <td className="px-4 py-4 font-semibold text-electric">{team.finalScoreMean}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

