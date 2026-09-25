"use client";

import Link from "next/link";

/** The API failed while loading a mountain. retry() refetches the server data. */
export default function MountainError({
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <main className="grid h-dvh place-items-center bg-background px-6">
      <div role="alert" className="max-w-sm text-center">
        <h1 className="text-lg font-semibold">Could not load this mountain</h1>
        <p className="mt-2 text-sm text-muted">The TerraSense API did not answer. Try again in a moment.</p>
        <div className="mt-6 flex items-center justify-center gap-4 text-sm">
          <button
            type="button"
            onClick={() => retry()}
            className="rounded-md bg-accent px-4 py-2 font-semibold text-background"
          >
            Try again
          </button>
          <Link href="/" className="text-accent hover:underline">
            Back to globe
          </Link>
        </div>
      </div>
    </main>
  );
}
