import { useEffect, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import HudBar from './components/HudBar';
import Sidebar from './components/Sidebar';
import { ToastProvider } from './components/Toast';
import { ThemeProvider } from './context/ThemeContext';
import { getConfig, selectLabsConfig } from './lib/api';
import {
  BLACK_HOLE_ROUTE,
  DEFAULT_LABS_CONFIG,
  isBlackHoleEnabled,
  type LabsConfig,
  MISSIONS_ROUTE,
  PLAN_ROUTE,
} from './lib/types';
import MissionsPageScreen from './pages/MissionsPage';
import MissionDetailPageScreen from './pages/MissionDetailPage';
import PlanModePageScreen from './pages/PlanModePage';
import BlackHoleModePageScreen from './pages/BlackHoleModePage';
import ModelsPageScreen from './pages/ConnectorsPage';
import TelemetryPageScreen from './pages/TelemetryPage';
import TaskDetailPageScreen from './pages/TaskDetailPage';
import SettingsPageScreen from './pages/SettingsPage';
import GroundControlPageScreen from './pages/GroundControlPage';

const routeConfig = [
  { path: '/', element: <MissionsPageScreen /> },
  { path: '/missions', element: <MissionsPageScreen /> },
  { path: '/mission/:id', element: <MissionDetailPageScreen /> },
  { path: '/mission/:mission_id/task/:task_id', element: <TaskDetailPageScreen /> },
  { path: PLAN_ROUTE, element: <PlanModePageScreen /> },
  { path: '/plan/:id', element: <PlanModePageScreen /> },
  { path: BLACK_HOLE_ROUTE, element: <BlackHoleModePageScreen /> },
  { path: '/black-hole/:id', element: <BlackHoleModePageScreen /> },
  { path: '/ground-control', element: <GroundControlPageScreen /> },
  { path: '/models', element: <ModelsPageScreen /> },
  { path: '/telemetry', element: <TelemetryPageScreen /> },
  { path: '/settings', element: <SettingsPageScreen /> },
] as const;

type Expect<T extends true> = T;
type RoutePath = (typeof routeConfig)[number]['path'];
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
      : <Navigate to={MISSIONS_ROUTE} replace />;

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
                  <Route path="/" element={<MissionsPageScreen labs={resolvedLabs} />} />
                  <Route path={MISSIONS_ROUTE} element={<MissionsPageScreen labs={resolvedLabs} />} />
                  <Route path="/mission/:id" element={<MissionDetailPageScreen />} />
                  <Route path="/mission/:mission_id/task/:task_id" element={<TaskDetailPageScreen />} />
                  <Route path={PLAN_ROUTE} element={<PlanModePageScreen labs={resolvedLabs} />} />
                  <Route path="/plan/:id" element={<PlanModePageScreen labs={resolvedLabs} />} />
                  <Route path={BLACK_HOLE_ROUTE} element={blackHoleRouteElement} />
                  <Route path="/black-hole/:id" element={blackHoleRouteElement} />
                  <Route path="/ground-control" element={<GroundControlPageScreen />} />
                  <Route path="/models" element={<ModelsPageScreen />} />
                  <Route path="/telemetry" element={<TelemetryPageScreen />} />
                  <Route path="/settings" element={<SettingsPageScreen labs={resolvedLabs} onLabsChange={setLabs} />} />
                  <Route path="*" element={<Navigate to={MISSIONS_ROUTE} replace />} />
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

export default App;
