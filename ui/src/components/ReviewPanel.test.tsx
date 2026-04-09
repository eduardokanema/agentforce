import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import ReviewPanel from './ReviewPanel';

describe('ReviewPanel', () => {
  it('renders markdown feedback and score-specific styling', () => {
    const markup = renderToStaticMarkup(
      <ReviewPanel
        feedback={'# Heading\n\n- item **one**\n\n`code`'}
        score={9}
        criteriaResults={{ security: 'met', docs: 'needs work' }}
        blockingIssues={['Missing tests']}
        suggestions={['Consider splitting the helper into smaller functions.']}
      />,
    );

    expect(markup).toContain('prose-like');
    expect(markup).toContain('<h1>Heading</h1>');
    expect(markup).toContain('<strong>one</strong>');
    expect(markup).toContain('<code>code</code>');
    expect(markup).toContain('bg-green/10');
    expect(markup).toContain('text-green');
    expect(markup).toContain('animate-[pulse-glow_3s_ease_infinite]');
    expect(markup).toContain('Blocking Issues');
    expect(markup).toContain('Missing tests');
    expect(markup).toContain('Suggestions (1)');
    expect(markup).toContain('security');
    expect(markup).toContain('✓');
    expect(markup).toContain('docs');
    expect(markup).toContain('~');
  });

  it('uses amber and red tones for mid and low scores', () => {
    const amberMarkup = renderToStaticMarkup(<ReviewPanel feedback="ok" score={6} />);
    const redMarkup = renderToStaticMarkup(<ReviewPanel feedback="bad" score={3} />);

    expect(amberMarkup).toContain('bg-amber/10');
    expect(amberMarkup).toContain('text-amber');
    expect(redMarkup).toContain('bg-red/10');
    expect(redMarkup).toContain('text-red');
  });
});
