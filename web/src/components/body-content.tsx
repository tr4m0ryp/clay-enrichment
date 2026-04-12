/**
 * Shared component that renders body TEXT by splitting on "## " into
 * heading + paragraph sections. Used by company enrichment reports and
 * contact person research views.
 */

export function BodyContent({ text }: { text: string }) {
  if (!text) {
    return <p className="text-muted-foreground">No data</p>;
  }

  const sections = text.split(/^## /m).filter(Boolean);

  return (
    <div className="space-y-4">
      {sections.map((section, i) => {
        const [title, ...rest] = section.split("\n");
        return (
          <div key={i}>
            <h3 className="font-semibold text-sm mb-1">{title}</h3>
            <p className="text-sm text-muted-foreground whitespace-pre-line">
              {rest.join("\n").trim()}
            </p>
          </div>
        );
      })}
    </div>
  );
}
