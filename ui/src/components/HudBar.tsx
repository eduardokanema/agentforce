import { useEffect, useState } from 'react';
import LiveClock from './LiveClock';
import { useMissionList } from '../hooks/useMissionList';
import { wsClient } from '../lib/ws';
import type { MissionSummary } from '../lib/types';

type WsConnectionState = 'connecting' | 'open' | 'closed';

const APP_VERSION = 'v0.0.0';

type MissionLike = Partial<MissionSummary> & {
  task_states?: Record<string, { status?: string }>;
};

function getMissionCounts(
  missions: MissionLike[],
): { activeMissions: number; inProgressTasks: number; costUsd: number } {
  let activeMissions = 0;
  let inProgressTasks = 0;
  let costUsd = 0;

  for (const mission of missions) {
    costUsd += mission.cost_usd ?? 0;

    const status = String(mission.status);
    const isActive = status === 'active' || status === 'in_progress';
    if (!isActive) {
      continue;
    }

    activeMissions += 1;
    const taskStates = mission.task_states ?? {};
    const totalTasks = mission.total_tasks ?? Object.keys(taskStates).length;
    const doneTasks = mission.done_tasks ?? Object.values(taskStates).filter((task) => (
      task.status === 'completed' || task.status === 'review_approved'
    )).length;

    inProgressTasks += Math.max(0, totalTasks - doneTasks);
  }

  return { activeMissions, inProgressTasks, costUsd };
}

function stateDotClassName(state: WsConnectionState): string {
  if (state === 'open') {
    return 'w-2 h-2 rounded-full bg-green animate-[pulse-glow_2s_ease-in-out_infinite]';
  }

  return 'w-2 h-2 rounded-full bg-amber';
}

export default function HudBar() {
  const { missions } = useMissionList();
  const [connectionState, setConnectionState] = useState<WsConnectionState>(() => wsClient.connectionState);

  useEffect(() => {
    const handler = (state: WsConnectionState): void => {
      setConnectionState(state);
    };

    wsClient.onConnectionState(handler);
    return () => {
      wsClient.offConnectionState(handler);
    };
  }, []);

  const { activeMissions, inProgressTasks, costUsd } = getMissionCounts(missions);
  const dotClassName = stateDotClassName(connectionState);

  return (
    <div className="fixed top-0 inset-x-0 h-10 z-30 flex items-center px-4 gap-6 border-b border-border bg-surface/90 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        <span className="font-bold tracking-[0.15em] text-[13px] text-cyan">AGENTFORCE</span>
        <span className="rounded border border-border px-1.5 text-[10px] text-muted">{APP_VERSION}</span>
      </div>

      <div className="flex flex-1 justify-center gap-6 text-[11px] text-dim">
        <span>{activeMissions} ACTIVE | {inProgressTasks} TASKS | ${costUsd.toFixed(2)} TODAY</span>
      </div>

      <div className="flex items-center gap-3">
        <span aria-hidden="true" className={dotClassName} />
        <LiveClock />
      </div>
    </div>
  );
}
