import React, { useEffect, useState } from 'react';

function formatTime(date: Date): string {
  return [
    String(date.getHours()).padStart(2, '0'),
    String(date.getMinutes()).padStart(2, '0'),
    String(date.getSeconds()).padStart(2, '0'),
  ].join(':');
}

export default React.memo(function LiveClock() {
  const [time, setTime] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => {
      setTime((current) => new Date(current.getTime() + 1000));
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, []);

  return <span className="font-mono text-[11px] text-dim tabular-nums">{formatTime(time)}</span>;
});
