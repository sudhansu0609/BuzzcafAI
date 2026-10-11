import { useState } from 'react';
import { Film, Smartphone } from 'lucide-react';
import { useStudio } from '../state/studio';
import ShortsDesk from './ShortsDesk';
import LongformScheduler from '../components/LongformScheduler';

// Scheduler Desk: one place for both nightly schedulers. The Shorts tab is the
// Shorts Desk (find & score, daily batch, and the nightly wake / hibernate
// settings both schedulers share); the Long-form tab is the long-form
// scheduler that used to sit at the top of Projects.

type Kind = 'shorts' | 'long';
const KIND_KEY = 'scheduler_desk.kind';

// Projects reads this once on mount to open the project (and its Long-form /
// Shorts tab) that was clicked here.
const OPEN_PROJECT_KEY = 'projects.openOnLoad';

export default function SchedulerDesk() {
  const { navigate } = useStudio();
  const [kind, setKind] = useState<Kind>(() => {
    try {
      return localStorage.getItem(KIND_KEY) === 'long' ? 'long' : 'shorts';
    } catch {
      return 'shorts';
    }
  });
  const choose = (next: Kind) => {
    setKind(next);
    try {
      localStorage.setItem(KIND_KEY, next);
    } catch {
      // Private window: the tab just isn't remembered.
    }
  };

  const openProject = (id: string) => {
    try {
      localStorage.setItem('projects.kindTab', 'long');
      sessionStorage.setItem(OPEN_PROJECT_KEY, id);
    } catch {
      // Storage unavailable: Projects still opens, just not on this project.
    }
    navigate('projects');
  };

  return (
    <div>
      <div className="project-filter-tabs" style={{ marginBottom: 12 }}>
        <button type="button" className={`project-filter-tab ${kind === 'shorts' ? 'active' : ''}`} onClick={() => choose('shorts')}>
          <Smartphone size={14} />
          <span>Shorts</span>
        </button>
        <button type="button" className={`project-filter-tab ${kind === 'long' ? 'active' : ''}`} onClick={() => choose('long')}>
          <Film size={14} />
          <span>Long form</span>
        </button>
      </div>

      {kind === 'shorts' && <ShortsDesk />}
      {kind === 'long' && <LongformScheduler onOpenProject={openProject} />}
    </div>
  );
}
