import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import HudBar from './components/HudBar';
import Sidebar from './components/Sidebar';
import { ToastProvider } from './components/Toast';
import MissionsPageScreen from './pages/MissionsPage';
import MissionDetailPageScreen from './pages/MissionDetailPage';
import PlanModePageScreen from './pages/PlanModePage';
import ConnectorsPageScreen from './pages/ConnectorsPage';
import TelemetryPageScreen from './pages/TelemetryPage';
import TaskDetailPageScreen from './pages/TaskDetailPage';

const routeConfig = [
  { path: '/', element: <MissionsPageScreen /> },
  { path: '/mission/:id', element: <MissionDetailPageScreen /> },
  { path: '/mission/:mission_id/task/:task_id', element: <TaskDetailPageScreen /> },
  { path: '/plan', element: <PlanModePageScreen /> },
  { path: '/connectors', element: <ConnectorsPageScreen /> },
  { path: '/telemetry', element: <TelemetryPageScreen /> },
] as const;

type Expect<T extends true> = T;
type RoutePath = (typeof routeConfig)[number]['path'];
type _taskRouteExists = Expect<'/mission/:mission_id/task/:task_id' extends RoutePath ? true : false>;
type _planRouteExists = Expect<'/plan' extends RoutePath ? true : false>;
type _connectorsRouteExists = Expect<'/connectors' extends RoutePath ? true : false>;
type _telemetryRouteExists = Expect<'/telemetry' extends RoutePath ? true : false>;

function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <div className="flex h-screen overflow-hidden bg-bg">
          <Sidebar />
          <div className="flex-1 min-w-0 flex flex-col">
            <HudBar />
            <main className="flex-1 overflow-y-auto pt-10">
              <div className="site-main">
                <Routes>
                  {routeConfig.map(({ path, element }) => (
                    <Route key={path} path={path} element={element} />
                  ))}
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </div>
            </main>
          </div>
        </div>
      </BrowserRouter>
    </ToastProvider>
  );
}

export default App;
