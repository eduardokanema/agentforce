import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import MissionsPageScreen from './pages/MissionsPage';
import MissionDetailPageScreen from './pages/MissionDetailPage';
import TaskDetailPageScreen from './pages/TaskDetailPage';

const routeConfig = [
  { path: '/', element: <MissionsPageScreen /> },
  { path: '/mission/:id', element: <MissionDetailPageScreen /> },
  { path: '/mission/:mission_id/task/:task_id', element: <TaskDetailPageScreen /> },
] as const;

type Expect<T extends true> = T;
type RoutePath = (typeof routeConfig)[number]['path'];
type _taskRouteExists = Expect<'/mission/:mission_id/task/:task_id' extends RoutePath ? true : false>;

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {routeConfig.map(({ path, element }) => (
          <Route key={path} path={path} element={element} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
