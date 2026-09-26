import Image from "next/image";

/**
 * TerraSense mark from `public/terrasenselogo.png` (favicon and home header use the same asset).
 */
export default function BrandLogo({
  size = 48,
  className,
  priority = false,
}: {
  size?: number;
  className?: string;
  priority?: boolean;
}) {
  return (
    <Image
      src="/terrasenselogo.png"
      alt="TerraSense"
      width={size}
      height={size}
      priority={priority}
      className={className}
    />
  );
}
