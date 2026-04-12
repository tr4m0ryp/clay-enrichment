export function Header() {
  return (
    <header
      className="sticky top-0 z-30 flex items-center justify-between border-b border-border bg-background/80 px-6 backdrop-blur"
      style={{ height: 56 }}
    >
      <div className="text-sm font-medium text-foreground" />
      <div className="flex items-center gap-4">
        <span className="text-xs text-muted-foreground">Avelero</span>
      </div>
    </header>
  );
}
