// SVG icons taken from tracex-workspace.html.

type IconProps = { size?: number; className?: string };

const stroke = (size: number, className?: string, width = 2) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: width,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  className,
  "aria-hidden": true,
});

/** The Tracex mark (docs/assets/tracex-mark.svg): callers → focus → traced callee. */
export function Logo() {
  return (
    <svg width="20" height="20" viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <path
        d="M16.2 16.2 27.6 27.6M47.8 16.2 36.4 27.6"
        stroke="rgb(var(--mint))"
        strokeOpacity=".7"
        strokeWidth="3.5"
        strokeLinecap="round"
      />
      <path d="M32 39.5v7.2" stroke="rgb(var(--trace))" strokeWidth="3.5" strokeLinecap="round" />
      <circle cx="12.5" cy="12.5" r="5.25" stroke="rgb(var(--sub))" strokeWidth="3.5" />
      <circle cx="51.5" cy="12.5" r="5.25" stroke="rgb(var(--sub))" strokeWidth="3.5" />
      <circle cx="32" cy="52.5" r="5.25" stroke="rgb(var(--trace))" strokeWidth="3.5" />
      <circle cx="32" cy="32" r="11" stroke="rgb(var(--mint))" strokeOpacity=".32" strokeWidth="2.5" />
      <circle cx="32" cy="32" r="6.5" fill="rgb(var(--mint))" />
    </svg>
  );
}

export const SearchIcon = ({ size = 14, className }: IconProps) => (
  <svg {...stroke(size, className)} stroke="rgb(var(--muted))">
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </svg>
);
export const FilterIcon = ({ size = 13, className }: IconProps) => (
  <svg {...stroke(size, className)}>
    <path d="M4 6h16M7 12h10M10 18h4" />
  </svg>
);
export const ChevronLeft = ({ size = 14, className }: IconProps) => (
  <svg {...stroke(size, className)}>
    <path d="m15 6-6 6 6 6" />
  </svg>
);
export const ChevronRight = ({ size = 14, className }: IconProps) => (
  <svg {...stroke(size, className)}>
    <path d="m9 6 6 6-6 6" />
  </svg>
);
export const MoonIcon = ({ size = 15, className }: IconProps) => (
  <svg {...stroke(size, className, 1.9)}>
    <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
  </svg>
);
export const SunIcon = ({ size = 15, className }: IconProps) => (
  <svg {...stroke(size, className, 1.9)}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
);
export const LinkIcon = ({ size = 12, className }: IconProps) => (
  <svg {...stroke(size, className)}>
    <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" />
    <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />
  </svg>
);
export const CallersIcon = ({ size = 12, className }: IconProps) => (
  <svg {...stroke(size, className)}>
    <circle cx="12" cy="18" r="2.5" />
    <circle cx="5" cy="5" r="2.5" />
    <circle cx="19" cy="5" r="2.5" />
    <path d="M6.5 7 11 15.5M17.5 7 13 15.5" />
  </svg>
);
export const GraphIcon = ({ size = 12, className }: IconProps) => (
  <svg {...stroke(size, className)}>
    <circle cx="6" cy="12" r="2.5" />
    <circle cx="18" cy="6" r="2.5" />
    <circle cx="18" cy="18" r="2.5" />
    <path d="M8.3 11 15.7 7M8.3 13l7.4 4" />
  </svg>
);
export const ArrowRight = ({ size = 12, className }: IconProps) => (
  <svg {...stroke(size, className)}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);
export const CloseIcon = ({ size = 13, className }: IconProps) => (
  <svg {...stroke(size, className)}>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);
