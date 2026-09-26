/** Three to five short things to do before the weather turns. */
export default function PreventativeMeasures({ items }: { items: string[] }) {
  return (
    <section aria-labelledby="preventative-heading" className="border-t border-border px-5 py-4">
      <h2 id="preventative-heading" className="text-sm text-muted-foreground">
        Preventative measures
      </h2>
      <ul className="mt-2 list-disc space-y-2 pl-5 text-base marker:text-muted-foreground">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
