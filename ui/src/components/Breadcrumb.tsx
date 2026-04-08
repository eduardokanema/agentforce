import { Link } from 'react-router-dom';

export interface BreadcrumbProps {
  missionId: string;
  missionName: string;
  taskTitle?: string;
  className?: string;
}

export default function Breadcrumb({ missionId, missionName, taskTitle, className = '' }: BreadcrumbProps) {
  return (
    <nav className={['flex items-center gap-1.5 text-[11px] text-muted', className].filter(Boolean).join(' ')}>
      <Link className="text-dim hover:text-text hover:no-underline" to="/">
        Missions
      </Link>
      <span aria-hidden="true" className="text-muted">
        /
      </span>
      <Link className="text-dim hover:text-text hover:no-underline" to={`/mission/${missionId}`}>
        {missionName}
      </Link>
      {taskTitle ? (
        <>
          <span aria-hidden="true" className="text-muted">
            /
          </span>
          <span className="text-text">{taskTitle}</span>
        </>
      ) : null}
    </nav>
  );
}
