import logoUrl from "../assets/logo.png";

type BrandLogoProps = {
  className?: string;
};

export function BrandLogo({ className }: BrandLogoProps) {
  const classes = className ? `brand-logo ${className}` : "brand-logo";
  return (
    <h1 className={classes}>
      <img src={logoUrl} alt="Tennis Oracle" />
    </h1>
  );
}
