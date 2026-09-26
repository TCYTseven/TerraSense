/**
 * Shown while the hill page loads. Plain background, so the globe's fade-out flows
 * straight into the page's fade-in. It also lets the globe prefetch this route.
 */
export default function Loading() {
  return (
    <main aria-busy="true" className="h-dvh bg-background">
      <p className="sr-only">Loading hill</p>
    </main>
  );
}
