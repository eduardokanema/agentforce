import { useEffect, useState } from 'react';
import { Navigate, useParams, useSearchParams } from 'react-router-dom';
import ProjectShellHeader from '../components/ProjectShellHeader';
import { getProject } from '../lib/api';
import { PROJECTS_ROUTE, type LabsConfig, type ProjectHarnessView } from '../lib/types';
import PlanModePage from './PlanModePage';

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

export default function ProjectPlanPage({
  labs,
}: {
  labs?: LabsConfig;
}) {
  const { id } = useParams<{ id?: string }>();
  const [searchParams] = useSearchParams();
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
        <div className="text-sm font-semibold text-red">Unable to load project plan</div>
        <p className="mt-1 text-sm text-dim">{error ?? 'Project not found'}</p>
      </section>
    );
  }

  const draftIdOverride = searchParams.get('draft')
    ?? project.summary.current_plan_id
    ?? project.active_cycle?.draft_id
    ?? null;
  const initialWorkspaces = project.context.working_directories.length > 0
    ? project.context.working_directories
    : [project.summary.repo_root];

  return (
    <div className="grid gap-4">
      <ProjectShellHeader summary={project.summary} section="plan" />
      <PlanModePage
        labs={labs}
        projectId={project.summary.project_id}
        projectName={project.summary.name}
        draftIdOverride={draftIdOverride}
        initialWorkspaces={initialWorkspaces}
      />
    </div>
  );
}
