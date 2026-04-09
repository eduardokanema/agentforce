import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import TokenMeter from './TokenMeter';

describe('TokenMeter', () => {
  it('renders token and cost chips with formatted values', () => {
    const markup = renderToStaticMarkup(
      <TokenMeter tokensIn={1234} tokensOut={56} costUsd={1.2345} label="mission tokens" />,
    );

    expect(markup).toContain('↓ 1,234 in');
    expect(markup).toContain('↑ 56 out');
    expect(markup).toContain('$1.2345');
    expect(markup).toContain('bg-surface border border-border rounded-full px-3 py-0.5 font-mono text-[11px]');
    expect(markup).toContain('text-green');
  });
});
