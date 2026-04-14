import { Navigate, useParams, useSearchParams } from 'react-router-dom';
import { PROJECTS_ROUTE, projectPlanRoute } from '../lib/types';

export default function ProjectMissionPage() {
  const { id } = useParams<{ id?: string }>();
  const [searchParams] = useSearchParams();

  if (!id) {
    return <Navigate to={PROJECTS_ROUTE} replace />;
  }

  const planId = searchParams.get('plan');
  const target = planId
    ? `${projectPlanRoute(id)}?plan=${encodeURIComponent(planId)}`
    : projectPlanRoute(id);

  return <Navigate to={target} replace />;
}
