import { describe, expect, it } from 'vitest';
import { renderMarkdown } from './markdown';

describe('renderMarkdown', () => {
  it('renders markdown to HTML', () => {
    expect(renderMarkdown('# Hello')).toContain('<h1');
  });

  it('sanitizes unsafe HTML', () => {
    expect(renderMarkdown('<script>alert(1)</script>')).not.toContain('<script');
  });
});
