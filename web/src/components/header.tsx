"use client";

import { useEffect, useState } from "react";

export function Header() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 0);
    window.addEventListener("scroll", handler, { passive: true });
    return () => window.removeEventListener("scroll", handler);
  }, []);

  return (
    <header
      className={`sticky top-0 z-30 flex items-center border-b px-6 transition-colors duration-200 ${
        scrolled
          ? "border-border bg-background/70 backdrop-blur-xl"
          : "border-transparent bg-transparent"
      }`}
      style={{ height: 56 }}
    />
  );
}
