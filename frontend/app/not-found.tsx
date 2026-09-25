import Link from "next/link";

/** Site-wide 404, dark like the rest of the app. The default 404 follows the OS theme. */
export default function NotFound() {
  return (
    <main className="grid h-dvh place-items-center bg-background px-6">
      <div className="max-w-sm text-center">
        <h1 className="text-lg font-semibold">Page not found</h1>
        <Link href="/" className="mt-6 inline-block text-sm text-primary underline decoration-1 underline-offset-3">
          Back to globe
        </Link>
      </div>
    </main>
  );
}
