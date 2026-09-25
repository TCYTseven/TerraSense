import Link from "next/link";

export default function MountainNotFound() {
  return (
    <main className="grid h-dvh place-items-center bg-background px-6">
      <div className="max-w-sm text-center">
        <h1 className="text-lg font-semibold">No mountain here</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          TerraSense covers Mount Rainier, plus two markers on the globe.
        </p>
        <Link href="/" className="mt-6 inline-block text-sm text-primary underline decoration-1 underline-offset-3">
          Back to globe
        </Link>
      </div>
    </main>
  );
}
