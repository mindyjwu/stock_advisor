"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearToken } from "@/lib/api";

const LINKS: [string, string][] = [
  ["/", "Feed"],
  ["/discuss", "Discuss"],
  ["/lists", "Shared Lists"],
  ["/profile", "Profile"],
];

export default function Nav() {
  const path = usePathname();
  const router = useRouter();

  function logout() {
    clearToken();
    router.push("/login");
  }

  return (
    <div className="topbar">
      <span className="row" style={{ gap: "1.25rem", flexWrap: "wrap" }}>
        <span className="brand">📈 Stock Advisor</span>
        {LINKS.map(([href, label]) => (
          <Link key={href} href={href} className={`navlink ${path === href ? "active" : ""}`}>
            {label}
          </Link>
        ))}
      </span>
      <button onClick={logout}>Sign out</button>
    </div>
  );
}
