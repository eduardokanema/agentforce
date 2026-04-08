import { useEffect, useState } from 'react';
import { wsClient } from '../lib/ws';

type WsConnectionState = 'connecting' | 'open' | 'closed';

export interface ConnectionBannerProps {
  connectionState?: WsConnectionState;
  className?: string;
}

function stateLabel(state: WsConnectionState): string {
  switch (state) {
    case 'open':
      return 'Connected';
    case 'connecting':
      return 'Connecting';
    case 'closed':
      return 'Reconnecting';
  }
}

export default function ConnectionBanner({ connectionState, className = '' }: ConnectionBannerProps) {
  const [liveState, setLiveState] = useState<WsConnectionState>(() => wsClient.connectionState);

  useEffect(() => {
    if (connectionState) {
      setLiveState(connectionState);
      return;
    }

    const handler = (state: WsConnectionState): void => {
      setLiveState(state);
    };

    wsClient.onConnectionState(handler);
    return () => {
      wsClient.offConnectionState(handler);
    };
  }, [connectionState]);

  const state = connectionState ?? liveState;
  const isOpen = state === 'open';
  const dotClassName = isOpen ? 'bg-green shadow-[0_0_0_3px_rgba(46,204,138,0.12)]' : 'bg-amber shadow-[0_0_0_3px_rgba(240,180,41,0.12)]';

  return (
    <div
      className={[
        'sticky top-0 z-20 flex h-12 items-center gap-2 border-b border-border bg-bg/90 px-7 backdrop-blur',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-full ${dotClassName}`} />
      <span className="text-[11px] uppercase tracking-[0.08em] text-dim">{stateLabel(state)}</span>
    </div>
  );
}
