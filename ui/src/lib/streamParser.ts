export type LineType = 'command' | 'pass' | 'fail' | 'warn' | 'inject' | 'path' | 'default';

const PATH_RE = /\/[a-zA-Z0-9_./-]+\.[a-z]{1,5}/;

export function parseStreamLine(line: string): { type: LineType; raw: string } {
  if (line.startsWith('[USER INSTRUCTION]')) {
    return { type: 'inject', raw: line };
  }

  if (line.startsWith('$ ') || line.startsWith('❯ ') || line.startsWith('> ')) {
    return { type: 'command', raw: line };
  }

  if (/PASS(ED)?|✓|✔/i.test(line) || line.toLowerCase().endsWith(' ok')) {
    return { type: 'pass', raw: line };
  }

  if (/FAIL(ED)?|ERROR|✗|✘/i.test(line)) {
    return { type: 'fail', raw: line };
  }

  if (/WARN(ING)?|⚠/i.test(line)) {
    return { type: 'warn', raw: line };
  }

  if (PATH_RE.test(line)) {
    return { type: 'path', raw: line };
  }

  return { type: 'default', raw: line };
}

export const LINE_CLASSES: Record<LineType, string> = {
  inject: 'bg-amber/10 border-l-2 border-amber text-amber',
  command: 'text-cyan opacity-90',
  pass: 'text-green',
  fail: 'text-red',
  warn: 'text-amber',
  path: 'text-dim',
  default: '',
};
