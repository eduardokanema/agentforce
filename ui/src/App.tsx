import { useEffect, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom';
import HudBar from './components/HudBar';
import Sidebar from './components/Sidebar';
import { ToastProvider } from './components/Toast';
import { ThemeProvider } from './context/ThemeContext';
import { getConfig, selectLabsConfig } from './lib/api';
import {
  BLACK_HOLE_ROUTE,
  DEFAULT_LABS_CONFIG,
  isBlackHoleEnabled,
  MISSIONS_ROUTE,
  PLAN_ROUTE,
  PROJECTS_ROUTE,
  projectOverviewRoute,
  type LabsConfig,
} from './lib/types';
import ProjectsPageScreen from './pages/ProjectsPage';
import ProjectDetailPageScreen from './pages/ProjectDetailPage';
import MissionsPageScreen from './pages/MissionsPage';
import BlackHoleModePageScreen from './pages/BlackHoleModePage';
import ModelsPageScreen from './pages/ConnectorsPage';
import TelemetryPageScreen from './pages/TelemetryPage';
import TaskDetailPageScreen from './pages/TaskDetailPage';
import SettingsPageScreen from './pages/SettingsPage';
import GroundControlPageScreen from './pages/GroundControlPage';
import ProjectPlanPageScreen from './pages/ProjectPlanPage';
import ProjectMissionPageScreen from './pages/ProjectMissionPage';
import PlanRedirectPageScreen from './pages/PlanRedirectPage';
import MissionRedirectPageScreen from './pages/MissionRedirectPage';

const routeConfig = [
  { path: '/', element: <Navigate to={PROJECTS_ROUTE} replace /> },
  { path: PROJECTS_ROUTE, element: <ProjectsPageScreen /> },
  { path: '/projects/:id', element: <Navigate to={projectOverviewRoute(':id')} replace /> },
  { path: '/projects/:id/overview', element: <ProjectDetailPageScreen /> },
  { path: '/projects/:id/history', element: <ProjectDetailPageScreen /> },
  { path: '/projects/:id/settings', element: <ProjectDetailPageScreen /> },
  { path: '/projects/:id/plan', element: <ProjectPlanPageScreen /> },
  { path: '/projects/:id/mission', element: <ProjectMissionPageScreen /> },
  { path: '/missions', element: <MissionsPageScreen /> },
  { path: '/mission/:id', element: <MissionRedirectPageScreen /> },
  { path: '/mission/:mission_id/task/:task_id', element: <TaskDetailPageScreen /> },
  { path: PLAN_ROUTE, element: <PlanRedirectPageScreen /> },
  { path: '/plan/:id', element: <PlanRedirectPageScreen /> },
  { path: BLACK_HOLE_ROUTE, element: <BlackHoleModePageScreen /> },
  { path: '/black-hole/:id', element: <BlackHoleModePageScreen /> },
  { path: '/ground-control', element: <GroundControlPageScreen /> },
  { path: '/models', element: <ModelsPageScreen /> },
  { path: '/telemetry', element: <TelemetryPageScreen /> },
  { path: '/settings', element: <SettingsPageScreen /> },
] as const;

type Expect<T extends true> = T;
type RoutePath = (typeof routeConfig)[number]['path'];
type _projectsRouteExists = Expect<typeof PROJECTS_ROUTE extends RoutePath ? true : false>;
type _projectOverviewRouteExists = Expect<'/projects/:id/overview' extends RoutePath ? true : false>;
type _projectPlanRouteExists = Expect<'/projects/:id/plan' extends RoutePath ? true : false>;
type _projectMissionRouteExists = Expect<'/projects/:id/mission' extends RoutePath ? true : false>;
type _taskRouteExists = Expect<'/mission/:mission_id/task/:task_id' extends RoutePath ? true : false>;
type _planRouteExists = Expect<'/plan' extends RoutePath ? true : false>;
type _planIdRouteExists = Expect<'/plan/:id' extends RoutePath ? true : false>;
type _blackHoleRouteExists = Expect<'/black-hole' extends RoutePath ? true : false>;
type _blackHoleIdRouteExists = Expect<'/black-hole/:id' extends RoutePath ? true : false>;
type _modelsRouteExists = Expect<'/models' extends RoutePath ? true : false>;
type _telemetryRouteExists = Expect<'/telemetry' extends RoutePath ? true : false>;

function App() {
  const [labs, setLabs] = useState<LabsConfig | null>(null);

  useEffect(() => {
    let active = true;

    void getConfig()
      .then((config) => {
        if (active) {
          setLabs(selectLabsConfig(config));
        }
      })
      .catch(() => {
        if (active) {
          setLabs(DEFAULT_LABS_CONFIG);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  const resolvedLabs = labs ?? DEFAULT_LABS_CONFIG;
  const blackHoleRouteElement = labs === null
    ? null
    : isBlackHoleEnabled(resolvedLabs)
      ? <BlackHoleModePageScreen labs={resolvedLabs} />
      : <Navigate to={PROJECTS_ROUTE} replace />;

  return (
    <ThemeProvider>
    <ToastProvider>
      <BrowserRouter>
        <div className="flex h-screen overflow-hidden bg-bg">
          <Sidebar labs={resolvedLabs} />
          <div className="flex-1 min-w-0 flex flex-col">
            <HudBar />
            <main className="flex-1 overflow-y-auto pt-10">
              <div className="site-main">
                <Routes>
                  <Route path="/" element={<Navigate to={PROJECTS_ROUTE} replace />} />
                  <Route path={PROJECTS_ROUTE} element={<ProjectsPageScreen />} />
                  <Route
                    path="/projects/:id"
                    element={<ProjectDetailRouteRedirect />}
                  />
                  <Route path="/projects/:id/overview" element={<ProjectDetailPageScreen />} />
                  <Route path="/projects/:id/history" element={<ProjectDetailPageScreen />} />
                  <Route path="/projects/:id/settings" element={<ProjectDetailPageScreen />} />
                  <Route path="/projects/:id/plan" element={<ProjectPlanPageScreen labs={resolvedLabs} />} />
                  <Route path="/projects/:id/mission" element={<ProjectMissionPageScreen />} />
                  <Route path={MISSIONS_ROUTE} element={<MissionsPageScreen labs={resolvedLabs} />} />
                  <Route path="/mission/:id" element={<MissionRedirectPageScreen />} />
                  <Route path="/mission/:mission_id/task/:task_id" element={<TaskDetailPageScreen />} />
                  <Route path={PLAN_ROUTE} element={<PlanRedirectPageScreen />} />
                  <Route path="/plan/:id" element={<PlanRedirectPageScreen />} />
                  <Route path={BLACK_HOLE_ROUTE} element={blackHoleRouteElement} />
                  <Route path="/black-hole/:id" element={blackHoleRouteElement} />
                  <Route path="/ground-control" element={<GroundControlPageScreen />} />
                  <Route path="/models" element={<ModelsPageScreen />} />
                  <Route path="/telemetry" element={<TelemetryPageScreen />} />
                  <Route path="/settings" element={<SettingsPageScreen labs={resolvedLabs} onLabsChange={setLabs} />} />
                  <Route path="*" element={<Navigate to={PROJECTS_ROUTE} replace />} />
                </Routes>
              </div>
            </main>
          </div>
        </div>
      </BrowserRouter>
    </ToastProvider>
    </ThemeProvider>
  );
}

function ProjectDetailRouteRedirect() {
  const { id } = useParams<{ id?: string }>();
  const projectId = id ?? '';
  return <Navigate to={projectOverviewRoute(projectId)} replace />;
}

export default App;
