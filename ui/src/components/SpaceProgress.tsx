import { useMemo } from 'react';

interface SpaceProgressProps {
  pct: number;
  isRunning?: boolean;
  className?: string;
  variant?: 'default' | 'compact';
}

export default function SpaceProgress({ pct, isRunning, className = '', variant = 'default' }: SpaceProgressProps) {
  const displayPct = Math.max(0, Math.min(100, pct));
  const isCompact = variant === 'compact';
  
  // Generate some random stars for the background
  const stars = useMemo(() => {
    return Array.from({ length: isCompact ? 10 : 20 }).map((_, i) => ({
      id: i,
      left: `${Math.random() * 100}%`,
      top: `${Math.random() * 100}%`,
      size: Math.random() * 2 + 1,
      duration: Math.random() * 3 + 2,
      delay: Math.random() * 5,
    }));
  }, [isCompact]);

  return (
    <div className={['relative flex flex-col gap-2', className].filter(Boolean).join(' ')}>
      {!isCompact && (
        <div className="flex items-center justify-between text-[11px] font-medium text-dim">
          <span className="uppercase tracking-wider">Mission Progress</span>
          <span className="font-mono">{Math.round(displayPct)}%</span>
        </div>
      )}

      <div className={`relative ${isCompact ? 'h-6' : 'h-12'} w-full overflow-hidden rounded-xl border border-cyan/20 bg-bg shadow-[inset_0_0_20px_rgba(34,211,238,0.05)]`}>
        {/* Starfield background */}
        {isRunning && (
          <div className="absolute inset-0 opacity-40">
            {stars.map((star) => (
              <div
                key={star.id}
                className="absolute rounded-full bg-white animate-[star-move_linear_infinite]"
                style={{
                  left: star.left,
                  top: star.top,
                  width: `${isCompact ? star.size / 2 : star.size}px`,
                  height: `${isCompact ? star.size / 2 : star.size}px`,
                  animationDuration: `${star.duration}s`,
                  animationDelay: `-${star.delay}s`,
                }}
              />
            ))}
          </div>
        )}

        {/* Progress Fill */}
        <div 
          className="absolute inset-y-0 left-0 bg-gradient-to-r from-blue/20 via-cyan/20 to-teal/20 transition-[width] duration-700 ease-out"
          style={{ width: `${displayPct}%` }}
        />

        {/* Rocket Container */}
        <div 
          className="absolute inset-y-0 left-0 flex items-center transition-[width] duration-700 ease-out"
          style={{ width: `${displayPct}%` }}
        >
          {/* The Rocket */}
          <div 
            className={[
              "absolute z-10 flex flex-col items-center justify-center",
              isCompact ? "right-[-12px]" : "right-[-24px]",
              isRunning ? "animate-[rocket-float_3s_ease-in-out_infinite]" : ""
            ].join(' ')}
          >
            {/* Rocket SVG */}
            <svg 
              width={isCompact ? "16" : "32"} 
              height={isCompact ? "16" : "32"} 
              viewBox="0 0 24 24" 
              fill="none" 
              xmlns="http://www.w3.org/2000/svg"
              className="rotate-90 drop-shadow-[0_0_8px_rgba(34,211,238,0.6)]"
            >
              <path 
                d="M12 2C12 2 15 5 15 11C15 17 12 22 12 22C12 22 9 17 9 11C9 5 12 2 12 2Z" 
                fill="#22d3ee" 
              />
              <path 
                d="M12 2C12 2 14 5 14 11C14 17 12 22 12 22" 
                stroke="#ffffff" 
                strokeOpacity="0.5"
                strokeWidth="0.5" 
              />
              {/* Fins */}
              <path 
                d="M9 14L6 18V20L9 18V14Z" 
                fill="#0891b2" 
              />
              <path 
                d="M15 14L18 18V20L15 18V14Z" 
                fill="#0891b2" 
              />
              {/* Window */}
              <circle cx="12" cy="11" r="2" fill="#0d1525" />
            </svg>

            {/* Rocket Flame */}
            {isRunning && (
              <div className={`absolute ${isCompact ? 'right-[14px]' : 'right-[28px]'} top-1/2 -translate-y-1/2 flex gap-0.5`}>
                <div className={`${isCompact ? 'h-0.5 w-3' : 'h-1.5 w-6'} rounded-full bg-gradient-to-l from-orange-500 via-yellow-400 to-transparent animate-[flame-pulse_0.2s_ease-in-out_infinite]`} />
                <div className={`${isCompact ? 'h-0.5 w-2' : 'h-1 w-4'} rounded-full bg-gradient-to-l from-red-500 via-orange-400 to-transparent animate-[flame-pulse_0.2s_ease-in-out_infinite_0.1s]`} />
              </div>
            )}
          </div>
        </div>
      </div>

      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes star-move {
          0% { transform: translateX(100vw); opacity: 0; }
          10% { opacity: 1; }
          90% { opacity: 1; }
          100% { transform: translateX(-100px); opacity: 0; }
        }
        @keyframes rocket-float {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-4px); }
        }
        @keyframes flame-pulse {
          0%, 100% { transform: scaleX(1); opacity: 0.8; }
          50% { transform: scaleX(1.5); opacity: 1; }
        }
      `}} />
    </div>
  );
}
