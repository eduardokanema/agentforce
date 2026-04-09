import type React from 'react';

export type AnsiSpan = { text: string; style: React.CSSProperties };

const ANSI_ESCAPE_RE = /\x1b\[([0-9;]*)m/g;

const COLOR_MAP: Record<number, string> = {
  30: '#090d18',
  31: '#ff6b6b',
  32: '#2ecc8a',
  33: '#f0b429',
  34: '#4d94ff',
  35: '#9b7dff',
  36: '#22d3ee',
  37: '#dde6f0',
  90: '#4d6070',
  91: '#ff6b6b',
  92: '#2ecc8a',
  93: '#f0b429',
  94: '#4d94ff',
  95: '#9b7dff',
  96: '#22d3ee',
  97: '#dde6f0',
};

function cloneStyle(style: React.CSSProperties): React.CSSProperties {
  return { ...style };
}

function stylesEqual(left: React.CSSProperties, right: React.CSSProperties): boolean {
  return left.color === right.color && left.fontWeight === right.fontWeight;
}

function pushSpan(spans: AnsiSpan[], text: string, style: React.CSSProperties): void {
  if (text.length === 0) {
    return;
  }

  const last = spans[spans.length - 1];
  if (last && stylesEqual(last.style, style)) {
    last.text += text;
    return;
  }

  spans.push({ text, style: cloneStyle(style) });
}

function applyCodes(codes: string[], currentStyle: React.CSSProperties): React.CSSProperties {
  if (codes.length === 0) {
    return currentStyle;
  }

  let nextStyle = cloneStyle(currentStyle);

  for (const code of codes) {
    if (code === '') {
      continue;
    }

    const value = Number(code);
    if (!Number.isFinite(value)) {
      continue;
    }

    if (value === 0) {
      nextStyle = {};
      continue;
    }

    if (value === 1) {
      nextStyle.fontWeight = 'bold';
      continue;
    }

    if (value >= 30 && value <= 37) {
      nextStyle.color = COLOR_MAP[value];
      continue;
    }

    if (value >= 90 && value <= 97) {
      nextStyle.color = COLOR_MAP[value];
    }
  }

  return nextStyle;
}

export function parseAnsi(line: string): AnsiSpan[] {
  if (!ANSI_ESCAPE_RE.test(line)) {
    return [{ text: line, style: {} }];
  }

  ANSI_ESCAPE_RE.lastIndex = 0;

  const spans: AnsiSpan[] = [];
  let currentStyle: React.CSSProperties = {};
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = ANSI_ESCAPE_RE.exec(line)) !== null) {
    const text = line.slice(lastIndex, match.index);
    pushSpan(spans, text, currentStyle);
    currentStyle = applyCodes(match[1].split(';'), currentStyle);
    lastIndex = ANSI_ESCAPE_RE.lastIndex;
  }

  pushSpan(spans, line.slice(lastIndex), currentStyle);

  return spans;
}
