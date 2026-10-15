import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: 'The $100 Agent — Verdict to Proof',
  description: 'An interactive business demonstration of bounded AI authority and independently verifiable evidence.',
  openGraph: {
    title: 'The $100 Agent — Verdict to Proof',
    description: 'Give AI authority. Not unlimited trust.',
    images: [{ url: '/og-the-100-agent.png', width: 1728, height: 909 }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'The $100 Agent — Verdict to Proof',
    description: 'Give AI authority. Not unlimited trust.',
    images: ['/og-the-100-agent.png'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
