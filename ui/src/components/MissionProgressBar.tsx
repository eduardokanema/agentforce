type ProgressClassKey =
  | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9
  | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19
  | 20 | 21 | 22 | 23 | 24 | 25 | 26 | 27 | 28 | 29
  | 30 | 31 | 32 | 33 | 34 | 35 | 36 | 37 | 38 | 39
  | 40 | 41 | 42 | 43 | 44 | 45 | 46 | 47 | 48 | 49
  | 50 | 51 | 52 | 53 | 54 | 55 | 56 | 57 | 58 | 59
  | 60 | 61 | 62 | 63 | 64 | 65 | 66 | 67 | 68 | 69
  | 70 | 71 | 72 | 73 | 74 | 75 | 76 | 77 | 78 | 79
  | 80 | 81 | 82 | 83 | 84 | 85 | 86 | 87 | 88 | 89
  | 90 | 91 | 92 | 93 | 94 | 95 | 96 | 97 | 98 | 99
  | 100;

export const PROGRESS_WIDTH_CLASSES = {
  0: '[--pct:0%]',
  1: '[--pct:1%]',
  2: '[--pct:2%]',
  3: '[--pct:3%]',
  4: '[--pct:4%]',
  5: '[--pct:5%]',
  6: '[--pct:6%]',
  7: '[--pct:7%]',
  8: '[--pct:8%]',
  9: '[--pct:9%]',
  10: '[--pct:10%]',
  11: '[--pct:11%]',
  12: '[--pct:12%]',
  13: '[--pct:13%]',
  14: '[--pct:14%]',
  15: '[--pct:15%]',
  16: '[--pct:16%]',
  17: '[--pct:17%]',
  18: '[--pct:18%]',
  19: '[--pct:19%]',
  20: '[--pct:20%]',
  21: '[--pct:21%]',
  22: '[--pct:22%]',
  23: '[--pct:23%]',
  24: '[--pct:24%]',
  25: '[--pct:25%]',
  26: '[--pct:26%]',
  27: '[--pct:27%]',
  28: '[--pct:28%]',
  29: '[--pct:29%]',
  30: '[--pct:30%]',
  31: '[--pct:31%]',
  32: '[--pct:32%]',
  33: '[--pct:33%]',
  34: '[--pct:34%]',
  35: '[--pct:35%]',
  36: '[--pct:36%]',
  37: '[--pct:37%]',
  38: '[--pct:38%]',
  39: '[--pct:39%]',
  40: '[--pct:40%]',
  41: '[--pct:41%]',
  42: '[--pct:42%]',
  43: '[--pct:43%]',
  44: '[--pct:44%]',
  45: '[--pct:45%]',
  46: '[--pct:46%]',
  47: '[--pct:47%]',
  48: '[--pct:48%]',
  49: '[--pct:49%]',
  50: '[--pct:50%]',
  51: '[--pct:51%]',
  52: '[--pct:52%]',
  53: '[--pct:53%]',
  54: '[--pct:54%]',
  55: '[--pct:55%]',
  56: '[--pct:56%]',
  57: '[--pct:57%]',
  58: '[--pct:58%]',
  59: '[--pct:59%]',
  60: '[--pct:60%]',
  61: '[--pct:61%]',
  62: '[--pct:62%]',
  63: '[--pct:63%]',
  64: '[--pct:64%]',
  65: '[--pct:65%]',
  66: '[--pct:66%]',
  67: '[--pct:67%]',
  68: '[--pct:68%]',
  69: '[--pct:69%]',
  70: '[--pct:70%]',
  71: '[--pct:71%]',
  72: '[--pct:72%]',
  73: '[--pct:73%]',
  74: '[--pct:74%]',
  75: '[--pct:75%]',
  76: '[--pct:76%]',
  77: '[--pct:77%]',
  78: '[--pct:78%]',
  79: '[--pct:79%]',
  80: '[--pct:80%]',
  81: '[--pct:81%]',
  82: '[--pct:82%]',
  83: '[--pct:83%]',
  84: '[--pct:84%]',
  85: '[--pct:85%]',
  86: '[--pct:86%]',
  87: '[--pct:87%]',
  88: '[--pct:88%]',
  89: '[--pct:89%]',
  90: '[--pct:90%]',
  91: '[--pct:91%]',
  92: '[--pct:92%]',
  93: '[--pct:93%]',
  94: '[--pct:94%]',
  95: '[--pct:95%]',
  96: '[--pct:96%]',
  97: '[--pct:97%]',
  98: '[--pct:98%]',
  99: '[--pct:99%]',
  100: '[--pct:100%]',
} satisfies Record<ProgressClassKey, string>;

function clampPct(pct: number): number {
  if (!Number.isFinite(pct)) {
    return 0;
  }

  return Math.max(0, Math.min(100, pct));
}

function progressKey(pct: number): ProgressClassKey {
  return Math.round(clampPct(pct)) as ProgressClassKey;
}

export interface MissionProgressBarProps {
  pct: number;
  className?: string;
}

export default function MissionProgressBar({ pct, className = '' }: MissionProgressBarProps) {
  const displayPct = Math.round(clampPct(pct));
  const pctClass = PROGRESS_WIDTH_CLASSES[progressKey(displayPct)];

  return (
    <div className={['space-y-1', className].filter(Boolean).join(' ')}>
      <div
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={displayPct}
        className="h-[3px] overflow-hidden rounded-[2px] bg-border"
        role="progressbar"
      >
        <div
          className={[
            'h-full w-[var(--pct)] bg-gradient-to-r from-blue to-teal transition-[width] duration-[400ms] [transition-timing-function:ease]',
            pctClass,
          ]
            .filter(Boolean)
            .join(' ')}
        />
      </div>
      <div className="text-[10px] text-dim">{displayPct}% complete</div>
    </div>
  );
}
