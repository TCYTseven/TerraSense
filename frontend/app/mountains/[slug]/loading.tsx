/**
 * Shown while the mountain page loads. Plain background, so the globe's fade-out flows
 * straight into the page's fade-in. It also lets the globe prefetch this route.
 */
export default function Loading() {
  return (
    <main aria-busy="true" className="fixed inset-0 h-svh overflow-hidden bg-background">
      <p className="sr-only">Loading mountain</p>
    </main>
  );
}
