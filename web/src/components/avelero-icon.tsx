interface Props {
  size?: number;
  color?: string;
  className?: string;
}

export function AveleroIcon({
  size = 20,
  color = "currentColor",
  className = "",
}: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 256 256"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      style={{ color }}
      role="img"
      aria-label="Avelero"
    >
      <path
        d="M158.919 185.601H116.914L190.795 0H232.8L158.919 185.601Z"
        fill="currentColor"
      />
      <path
        d="M65.2031 256H23.1992L97.0791 70.4004H139.084L65.2031 256Z"
        fill="currentColor"
      />
    </svg>
  );
}
