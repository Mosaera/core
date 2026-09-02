/** The GitLab tanuki, inline. There is no logo asset set in this app (the Mosaera mark is
 *  typographic and every other icon comes from lucide), so a provider mark ships as an SVG
 *  component sized and coloured like a lucide icon — `size-4` by default, `currentColor` off. */
export function GitLabMark({ className = "size-4" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      role="img"
      aria-label="GitLab"
      className={className}
      fill="currentColor"
    >
      <path d="M23.955 13.587l-1.342-4.135-2.664-8.189a.455.455 0 0 0-.867 0L16.418 9.45H7.582L4.918 1.263a.455.455 0 0 0-.867 0L1.386 9.452.044 13.587a.924.924 0 0 0 .331 1.03L12 23.054l11.625-8.436a.92.92 0 0 0 .33-1.031" />
    </svg>
  );
}
