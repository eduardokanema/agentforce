import { useEffect, useState } from 'react';
import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom';
import { lookupProjectByDraft } from '../lib/api';
import { PROJECTS_ROUTE, projectPlanRoute } from '../lib/types';

const LAST_PROJECT_KEY = 'agentforce-last-project-id';

export default function PlanRedirectPage() {
  const { id } = useParams<{ id?: string }>();
  const [searchParams] = useSearchParams();
  const [target, setTarget] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const draftId = id ?? searchParams.get('draft') ?? null;
    if (!draftId) {
      const lastProjectId = window.localStorage.getItem(LAST_PROJECT_KEY);
      setTarget(lastProjectId ? projectPlanRoute(lastProjectId) : PROJECTS_ROUTE);
      return;
    }

    let active = true;
    lookupProjectByDraft(draftId)
      .then((result) => {
        if (!active) {
          return;
        }
        setTarget(`${projectPlanRoute(result.project_id)}?draft=${encodeURIComponent(draftId)}`);
      })
      .catch((err: unknown) => {
        if (!active) {
          return;
        }
        setError(err instanceof Error ? err.message : 'Unable to find the owning project for this plan');
      });

    return () => {
      active = false;
    };
  }, [id, searchParams]);

  if (target) {
    return <Navigate to={target} replace />;
  }

  if (error) {
    return (
      <section className="rounded-lg border border-amber/30 bg-amber/10 px-4 py-5 text-sm text-amber">
        <div className="font-semibold text-text">This plan could not be matched to a project.</div>
        <p className="mt-1 text-dim">{error}</p>
        <Link className="mt-3 inline-flex text-cyan hover:no-underline" to={PROJECTS_ROUTE}>
          Open Projects
        </Link>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-border bg-card px-4 py-5 text-sm text-dim">
      Finding the owning project for this plan...
    </section>
  );
}
