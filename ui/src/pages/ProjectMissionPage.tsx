import { useEffect, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import ProjectShellHeader from '../components/ProjectShellHeader';
import { getProject } from '../lib/api';
import { PROJECTS_ROUTE, projectPlanRoute, type ProjectHarnessView } from '../lib/types';
import MissionDetailPage from './MissionDetailPage';

function LoadingState() {
  return (
    <div className="space-y-4">
      <div className="animate-pulse rounded-lg border border-border bg-card px-4 py-4">
        <div className="h-5 w-56 rounded bg-surface" />
        <div className="mt-3 h-4 w-72 rounded bg-surface" />
      </div>
    </div>
  );
}

export default function ProjectMissionPage() {
  const { id } = useParams<{ id?: string }>();
  const [project, setProject] = useState<ProjectHarnessView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) {
      setProject(null);
      setLoading(false);
      return;
    }

    let active = true;
    setLoading(true);
    getProject(id)
      .then((value) => {
        if (!active) {
          return;
        }
        setProject(value);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!active) {
          return;
        }
        setError(err instanceof Error ? err.message : 'Failed to load project');
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [id]);

  if (!id) {
    return <Navigate to={PROJECTS_ROUTE} replace />;
  }

  if (loading) {
    return <LoadingState />;
  }

  if (error || !project) {
    return (
      <section className="rounded-lg border border-red/30 bg-red-bg/20 px-4 py-5">
        <div className="text-sm font-semibold text-red">Unable to load project mission</div>
        <p className="mt-1 text-sm text-dim">{error ?? 'Project not found'}</p>
      </section>
    );
  }

  const missionId = project.summary.current_mission_id
    ?? project.summary.active_mission_id
    ?? project.active_cycle?.mission_id
    ?? null;

  return (
    <div className="grid gap-4">
      <ProjectShellHeader summary={project.summary} section="mission" />
      {missionId ? (
        <MissionDetailPage
          missionIdOverride={missionId}
          projectId={project.summary.project_id}
          projectName={project.summary.name}
          embedded
        />
      ) : (
        <section className="rounded-lg border border-border bg-card px-4 py-5">
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">Current Mission</div>
          <h2 className="mt-2 text-xl font-semibold text-text">No mission started yet</h2>
          <p className="mt-2 max-w-[64ch] text-sm text-dim">
            This project does not have an active mission. Finish the current plan and launch from the project plan section.
          </p>
          <div className="mt-4">
            <Link
              className="inline-flex items-center rounded-full border border-cyan/30 bg-cyan/10 px-3 py-1.5 text-[11px] font-semibold text-cyan transition-colors hover:bg-cyan/15 hover:no-underline"
              to={projectPlanRoute(project.summary.project_id)}
            >
              Open project plan
            </Link>
          </div>
        </section>
      )}
    </div>
  );
}
