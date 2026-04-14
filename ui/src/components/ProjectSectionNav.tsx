import { NavLink } from 'react-router-dom';
import {
  projectHistoryRoute,
  projectMissionRoute,
  projectOverviewRoute,
  projectPlanRoute,
  projectSettingsRoute,
  type ProjectSection,
} from '../lib/types';

const SECTION_ITEMS: Array<{ section: ProjectSection; label: string; description: string }> = [
  { section: 'overview', label: 'Overview', description: 'Project status, context, and next action.' },
  { section: 'plan', label: 'Plan', description: 'Current brief, spec, tasks, and launch readiness.' },
  { section: 'mission', label: 'Mission', description: 'Execution progress and intervention controls.' },
  { section: 'history', label: 'History', description: 'Earlier plans, missions, and readjustments.' },
  { section: 'settings', label: 'Settings', description: 'Project metadata, archive, and lifecycle controls.' },
];

function projectSectionHref(projectId: string, section: ProjectSection): string {
  switch (section) {
    case 'overview':
      return projectOverviewRoute(projectId);
    case 'plan':
      return projectPlanRoute(projectId);
    case 'mission':
      return projectMissionRoute(projectId);
    case 'history':
      return projectHistoryRoute(projectId);
    case 'settings':
      return projectSettingsRoute(projectId);
  }
}

export default function ProjectSectionNav({
  projectId,
  currentSection,
}: {
  projectId: string;
  currentSection: ProjectSection;
}) {
  return (
    <nav aria-label="Project sections" className="rounded-lg border border-border bg-card px-3 py-3">
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-5">
        {SECTION_ITEMS.map((item) => {
          const selected = item.section === currentSection;
          return (
            <NavLink
              key={item.section}
              to={projectSectionHref(projectId, item.section)}
              className={[
                'rounded-lg border px-3 py-3 transition-colors hover:no-underline',
                selected
                  ? 'border-cyan/30 bg-cyan/10 text-cyan'
                  : 'border-border bg-surface text-text hover:border-border-lit hover:bg-card',
              ].join(' ')}
            >
              <div className="text-[12px] font-semibold">{item.label}</div>
              <div className="mt-1 text-[11px] leading-5 text-dim">{item.description}</div>
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}
