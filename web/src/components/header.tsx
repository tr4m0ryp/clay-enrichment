export function Header() {
  return (
    <header
      className="sticky top-0 z-30 flex items-center border-b border-border px-6"
      style={{ height: 56, backgroundColor: "rgba(254, 254, 254, 0.5)", backdropFilter: "blur(80px) saturate(2)", WebkitBackdropFilter: "blur(80px) saturate(2)" }}
    />
  );
}
