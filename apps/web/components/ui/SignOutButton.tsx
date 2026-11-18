"use client";

import Button from "@mui/material/Button";

import { useRouter } from "@/i18n/navigation";

export function SignOutButton({ label }: { label: string }) {
  const router = useRouter();
  return (
    <Button
      color="inherit"
      variant="outlined"
      onClick={async () => {
        await fetch("/api/session", { method: "DELETE" });
        router.push("/login");
      }}
    >
      {label}
    </Button>
  );
}
