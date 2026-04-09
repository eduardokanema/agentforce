import { describe, expect, it } from 'vitest';
import { parseAnsi } from './ansi';

describe('parseAnsi', () => {
  it('parses ANSI colors and reset codes', () => {
    expect(parseAnsi('\x1b[32mhello\x1b[0m')).toEqual([
      { text: 'hello', style: { color: '#2ecc8a' } },
    ]);
  });

  it('returns plain text unchanged when there are no ANSI codes', () => {
    expect(parseAnsi('plain')).toEqual([{ text: 'plain', style: {} }]);
  });

  it('applies multiple style codes in one escape sequence', () => {
    expect(parseAnsi('\x1b[1;32mhi\x1b[0m')).toEqual([
      { text: 'hi', style: { fontWeight: 'bold', color: '#2ecc8a' } },
    ]);
  });
});
