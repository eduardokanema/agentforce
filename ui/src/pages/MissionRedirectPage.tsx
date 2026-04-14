import { useEffect, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { lookupProjectByMission } from '../lib/api';
import { PROJECTS_ROUTE, projectMissionRoute } from '../lib/types';

export default function MissionRedirectPage() {
  const { id } = useParams<{ id?: string }>();
  const [target, setTarget] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) {
      setTarget(PROJECTS_ROUTE);
      return;
    }

    let active = true;
    lookupProjectByMission(id)
      .then((result) => {
        if (!active) {
          return;
        }
        setTarget(projectMissionRoute(result.project_id));
      })
      .catch((err: unknown) => {
        if (!active) {
          return;
        }
        setError(err instanceof Error ? err.message : 'Unable to find the owning project for this mission');
      });

    return () => {
      active = false;
    };
  }, [id]);

  if (target) {
    return <Navigate to={target} replace />;
  }

  if (error) {
    return (
      <section className="rounded-lg border border-amber/30 bg-amber/10 px-4 py-5 text-sm text-amber">
        <div className="font-semibold text-text">This mission could not be matched to a project.</div>
        <p className="mt-1 text-dim">{error}</p>
        <Link className="mt-3 inline-flex text-cyan hover:no-underline" to={PROJECTS_ROUTE}>
          Open Projects
        </Link>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-border bg-card px-4 py-5 text-sm text-dim">
      Finding the owning project for this mission...
    </section>
  );
}
