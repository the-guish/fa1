// Reviews on the rail: its name, its title, its icon, and the loader of its root component,
// which runs the first time the icon is chosen.
import type { ShellApp } from "@oneberth/ui";

export const reviews: ShellApp = {
  name: "reviews",
  title: "Reviews",
  icon: <ReviewsIcon />,
  load: () => import("./ReviewsApp"),
};

/** A sheet with a check mark, in the current colour. */
function ReviewsIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  );
}
