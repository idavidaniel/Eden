import type { Metadata } from "next";
import { JetBrains_Mono, Public_Sans, Source_Serif_4 } from "next/font/google";
import "./globals.css";
import { Providers } from "@/lib/providers";

// Public Sans for the console, a serif for the documents the company produces,
// and a mono for the things that must be read character by character: hashes,
// keys, commands, money.
const ui = Public_Sans({
  variable: "--font-ui-loaded",
  subsets: ["latin"],
  display: "swap",
});
const doc = Source_Serif_4({
  variable: "--font-doc-loaded",
  subsets: ["latin"],
  display: "swap",
});
const mono = JetBrains_Mono({
  variable: "--font-mono-loaded",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Eden",
  description:
    "Companies of AI employees whose work is verified before it counts as done.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${ui.variable} ${doc.variable} ${mono.variable} h-full`}
    >
      <head>
        {/* Read before paint so the chosen theme does not flash the other one. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem("eden-theme");if(t==="dark"||t==="light")document.documentElement.dataset.theme=t}catch(e){}`,
          }}
        />
      </head>
      <body className="min-h-full">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
